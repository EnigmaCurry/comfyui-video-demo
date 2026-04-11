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
    seed="" segments="16" theme="" voice="despotism-doc.wav" voice_delay="0.0" extra_args=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --seed) seed="$2"; shift 2 ;;
            --segments) segments="$2"; shift 2 ;;
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
    if [ -z "$seed" ]; then
        echo "Error: --seed is required" >&2; exit 1
    fi
    if [ -z "$theme" ]; then
        echo "Error: --theme is required" >&2; exit 1
    fi
    echo "══════════════════════════════════════════════════════════════"
    echo "  Step 1/4: Generate script + voiceover text"
    echo "══════════════════════════════════════════════════════════════"
    python3 write_script.py --theme $theme --seed "$seed" --segments "$segments"
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
        --seed "$seed" --segments "$segments" \
        --suffixes-file "$script_path" "${extra_args[@]}"
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

# Clean output directory
[confirm("Remove output/ directory?")]
clean:
    rm -rf output/ __pycache__/
    @echo "Cleaned"
