# comfyui-video-demo Justfile

set dotenv-load

# List available recipes
default:
    @just --list

# Configure .env settings
config:
    #!/usr/bin/env bash
    touch .env
    set_var() {
        local key="$1" prompt="$2" default="$3" secret="$4"
        local current
        current=$(grep -oP "(?<=^${key}=).*" .env 2>/dev/null || true)
        local display_default="${current:-$default}"
        if [ "$secret" = "true" ] && [ -n "$current" ]; then
            display_default="****${current: -4}"
        fi
        if [ -n "$display_default" ]; then
            read -rp "${prompt} [${display_default}]: " value
        else
            read -rp "${prompt}: " value
        fi
        value="${value:-$current}"
        value="${value:-$default}"
        if [ -n "$value" ]; then
            if grep -q "^${key}=" .env; then
                sed -i "s|^${key}=.*|${key}=${value}|" .env
            else
                echo "${key}=${value}" >> .env
            fi
        fi
    }
    echo "=== ComfyUI ==="
    set_var COMFYUI_URL  "ComfyUI URL"    "http://127.0.0.1:8188"
    set_var COMFYUI_TOKEN "ComfyUI Bearer token (blank for none)" "" true
    echo ""
    echo "=== LLM (for script generation) ==="
    set_var LLM_URL   "LLM API URL"   "http://127.0.0.1:8000"
    set_var LLM_MODEL "LLM model name" "default"
    set_var LLM_API_KEY "LLM API key (blank for none)" "" true
    echo ""
    echo "Saved to .env"

# Run full pipeline: script → voiceover → video → concat
workflow *ARGS:
    #!/usr/bin/env bash
    set -euo pipefail
    set -- {{ARGS}}
    # Parse --seed, --segments, --theme, and passthrough args
    seed="" segments="16" duration="" theme="" style="absurd-realism" voice="despotism-doc.wav" voice_delay="0.0" extra_args=()
    # Check for --help before parsing
    for arg in "$@"; do
        if [[ "$arg" == "--help" || "$arg" == "-h" ]]; then
            echo "Usage: just workflow --seed SEED --theme THEME [OPTIONS]"
            echo ""
            echo "End-to-end pipeline: generate script → render voiceover → render video → mux"
            echo ""
            echo "Required arguments:"
            echo "  --seed SEED           Run ID seed (output goes to output/{seed}/)"
            echo "  --theme THEME         Theme or concept for the video (can be multiple words)"
            echo ""
            echo "Optional arguments:"
            echo "  --segments N          Number of segments (default: 16)"
            echo "  --duration SECS       Segment duration in seconds (default: from style)"
            echo "  --style NAME          Prompt style (default: absurd-realism)"
            echo "  --voice FILE          Voice sample WAV file (default: despotism-doc.wav)"
            echo "  --voice-delay SECS    Delay before voiceover starts (default: 0.0)"
            echo ""
            echo "Any additional arguments are passed through to chain.py."
            echo "Run 'python3 chain.py --help' for chain.py options."
            exit 0
        fi
    done
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --seed) seed="$2"; shift 2 ;;
            --segments) segments="$2"; shift 2 ;;
            --duration) duration="$2"; shift 2 ;;
            --style) style="$2"; shift 2 ;;
            --theme) shift; theme=""
                while [[ $# -gt 0 ]] && [[ "$1" != --* ]]; do
                    theme="$theme $1"; shift
                done
                theme="${theme# }" ;;
            --voice) voice="$2"; shift 2 ;;
            --voice-delay) voice_delay="$2"; shift 2 ;;
            *) extra_args+=("$1"); shift ;;
        esac
    done
    # Resolve duration from style if not explicitly set
    if [ -z "$duration" ]; then
        duration=$(python3 -c "from styles import load_style; print(load_style('$style').get('default_duration', 24))")
    fi
    # Convert duration (seconds) to frames (25 fps)
    length=$(( duration * 25 ))
    if [ -z "$seed" ]; then
        echo "Error: --seed is required" >&2; exit 1
    fi
    if [ -z "$theme" ]; then
        echo "Error: --theme is required" >&2; exit 1
    fi
    echo "══════════════════════════════════════════════════════════════"
    echo "  Step 1/4: Generate script + voiceover text"
    echo "══════════════════════════════════════════════════════════════"
    python3 write_script.py --theme $theme --seed "$seed" --segments "$segments" --duration "$duration" --style "$style"
    # Resolve the run directory (may include theme slug)
    run_dir=$(python3 -c "from run_dir import get_run_dir; print(get_run_dir('output', $seed))")
    script_path="${run_dir}/script.json"
    echo ""
    echo "══════════════════════════════════════════════════════════════"
    echo "  Step 2/4: Render voiceover audio"
    echo "══════════════════════════════════════════════════════════════"
    python3 render_voiceover.py --seed "$seed" --voice "$voice"
    echo ""
    echo "══════════════════════════════════════════════════════════════"
    echo "  Step 3/4: Render video segments"
    echo "══════════════════════════════════════════════════════════════"
    python3 chain.py --text-to-video --workflow workflow/ltx_i2v.json \
        --seed "$seed" --segments "$segments" --length "$length" \
        --style "$style" --suffixes-file "$script_path" "${extra_args[@]}"
    echo ""
    echo "══════════════════════════════════════════════════════════════"
    echo "  Step 4/4: Concatenate + mux voiceover"
    echo "══════════════════════════════════════════════════════════════"
    python3 mux.py --seed "$seed" --voice-delay "$voice_delay"

# Generate a video script from an LLM
script *ARGS:
    python3 write_script.py {{ARGS}}

# Generate a video script manually (prints prompts for copy-paste)
script-manual *ARGS:
    python3 write_script_manual.py {{ARGS}}

# Render voiceover audio from voiceover.json using tts-demo
voiceover *ARGS:
    python3 render_voiceover.py {{ARGS}}

# Run chained image-to-video generation
chain *ARGS:
    python3 chain.py {{ARGS}}

# Concatenate segments into final.mp4, mixing centered voiceover if available
concat *SEED:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -n "{{SEED}}" ]; then
        python3 mux.py --seed "{{SEED}}"
    else
        for dir in output/*/; do
            [ -d "$dir" ] || continue
            seed=$(basename "$dir")
            python3 mux.py --seed "$seed"
        done
    fi

# Extract last frame from a video as PNG
last-frame VIDEO OUT:
    ffmpeg -y -sseof -0.1 -i "{{VIDEO}}" -frames:v 1 "{{OUT}}"

# Render a single test clip from a text prompt and play it in a loop
clip *ARGS:
    #!/usr/bin/env bash
    set -euo pipefail
    set -- {{ARGS}}
    style="absurd-realism" duration="" seed="" prompt_words=()
    # Parse --help
    for arg in "$@"; do
        if [[ "$arg" == "--help" || "$arg" == "-h" ]]; then
            echo "Usage: just clip [--style NAME] [--duration SECS] PROMPT..."
            echo ""
            echo "Render a single test clip from a text prompt and play it with mpv."
            echo ""
            echo "Options:"
            echo "  --seed SEED       Reproducible seed (default: random)"
            echo "  --style NAME      Prompt style (default: absurd-realism)"
            echo "  --duration SECS   Clip duration in seconds (default: from style)"
            echo ""
            echo "Example:"
            echo "  just clip a cat riding a bicycle through space"
            exit 0
        fi
    done
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --seed) seed="$2"; shift 2 ;;
            --style) style="$2"; shift 2 ;;
            --duration) duration="$2"; shift 2 ;;
            *) prompt_words+=("$1"); shift ;;
        esac
    done
    if [ ${#prompt_words[@]} -eq 0 ]; then
        echo "Error: prompt text is required" >&2; exit 1
    fi
    prompt="${prompt_words[*]}"
    # Derive filename slug from first 6 words
    slug=$(echo "${prompt_words[*]:0:6}" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]\+/-/g; s/^-//; s/-$//' | head -c 60)
    # Resolve duration from style if not set
    if [ -z "$duration" ]; then
        duration=$(python3 -c "from styles import load_style; print(load_style('$style').get('default_duration', 24))")
    fi
    length=$(( duration * 25 ))
    seed="${seed:-$RANDOM}"
    output_dir="output/clips"
    mkdir -p "$output_dir"
    output_file="${output_dir}/${slug}.mp4"
    echo "Prompt:   $prompt"
    echo "Style:    $style"
    echo "Duration: ${duration}s (${length} frames)"
    echo "Output:   $output_file"
    echo ""
    python3 chain.py --text-to-video --workflow workflow/ltx_i2v.json \
        --seed "$seed" --segments 1 --length "$length" \
        --style "$style" --suffixes "$prompt" \
        --output-dir "$output_dir"
    # Find the rendered segment
    run_dir=$(python3 -c "from run_dir import get_run_dir; print(get_run_dir('$output_dir', $seed))")
    rendered="${run_dir}/segment_01.mp4"
    if [ ! -f "$rendered" ]; then
        echo "Error: rendered video not found at $rendered" >&2; exit 1
    fi
    # Move to final location with slug name, strip audio
    mv "$rendered" "$output_file"
    ffmpeg -y -i "$output_file" -an -c:v copy "$output_file.tmp.mp4" && mv "$output_file.tmp.mp4" "$output_file"
    # Clean up the run directory
    rm -rf "$run_dir"
    echo ""
    echo "Playing: $output_file"
    mpv --loop "$output_file"

# Interactive director mode TUI: render clips one-by-one with review
direct *ARGS:
    #!/usr/bin/env bash
    set -euo pipefail
    set -- {{ARGS}}
    # Parse --theme with multi-word support, pass everything else through
    theme="" extra_args=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --theme) shift; theme=""
                while [[ $# -gt 0 ]] && [[ "$1" != --* ]]; do
                    theme="$theme $1"; shift
                done
                theme="${theme# }" ;;
            *) extra_args+=("$1"); shift ;;
        esac
    done
    theme_args=()
    if [ -n "$theme" ]; then
        theme_args+=(--theme $theme)
    fi
    python3 direct.py "${theme_args[@]}" "${extra_args[@]}"

# Clean output directory
[confirm("Remove output/ directory?")]
clean:
    rm -rf output/ __pycache__/
    @echo "Cleaned"
