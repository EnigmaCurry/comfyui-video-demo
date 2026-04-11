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

# Generate a video script from an LLM
script *ARGS:
    python3 write_script.py {{ARGS}}

# Render voiceover audio from voiceover.json using tts-demo
voiceover *ARGS:
    python3 render_voiceover.py {{ARGS}}

# Run chained image-to-video generation
chain *ARGS:
    python3 chain.py {{ARGS}}

# Concatenate segment videos into final.mp4, mixing in voiceover if available
concat *SEED:
    #!/usr/bin/env bash
    set -euo pipefail
    concat_dir() {
        local dir="$1"
        shopt -s nullglob
        local files=("$dir"/segment_*.mp4)
        if [ ${#files[@]} -eq 0 ]; then
            return
        fi
        local out="$dir/final.mp4"
        # Check if final.mp4 is already up to date
        if [ -f "$out" ]; then
            local stale=false
            for f in "${files[@]}"; do
                if [ "$f" -nt "$out" ]; then
                    stale=true
                    break
                fi
            done
            # Also check voiceover files
            local vo_files=("$dir"/voiceover_*.wav)
            for f in "${vo_files[@]}"; do
                if [ "$f" -nt "$out" ]; then
                    stale=true
                    break
                fi
            done
            if [ "$stale" = false ]; then
                echo "$dir: final.mp4 is already up to date (${#files[@]} segments)"
                return
            fi
        fi
        # Concat video segments
        local vlist
        vlist=$(mktemp)
        for f in "${files[@]}"; do
            echo "file '$(realpath "$f")'" >> "$vlist"
        done
        # Check if voiceover files exist
        local vo_files=("$dir"/voiceover_*.wav)
        if [ ${#vo_files[@]} -gt 0 ] && [ ${#vo_files[@]} -eq ${#files[@]} ]; then
            echo "$dir: mixing voiceover with video audio..."
            # Concat video without final output first
            local tmp_video
            tmp_video=$(mktemp --suffix=.mp4)
            ffmpeg -y -f concat -safe 0 -i "$vlist" -c copy "$tmp_video" 2>/dev/null
            # Concat voiceover wavs
            local vo_list
            vo_list=$(mktemp)
            for f in "${vo_files[@]}"; do
                echo "file '$(realpath "$f")'" >> "$vo_list"
            done
            local tmp_vo
            tmp_vo=$(mktemp --suffix=.wav)
            ffmpeg -y -f concat -safe 0 -i "$vo_list" -c:a pcm_s16le "$tmp_vo" 2>/dev/null
            # Mix: keep original video audio, add voiceover on top
            # Original audio at reduced volume, voiceover at full volume
            ffmpeg -y -i "$tmp_video" -i "$tmp_vo" \
                -filter_complex "[0:a]volume=0.3[orig];[1:a]volume=1.0[vo];[orig][vo]amix=inputs=2:duration=longest[aout]" \
                -map 0:v -map "[aout]" -c:v copy -c:a aac -b:a 192k "$out" 2>/dev/null
            rm "$tmp_video" "$vo_list" "$tmp_vo"
        else
            if [ ${#vo_files[@]} -gt 0 ] && [ ${#vo_files[@]} -ne ${#files[@]} ]; then
                echo "$dir: warning: ${#vo_files[@]} voiceover files but ${#files[@]} segments, skipping mix"
            fi
            ffmpeg -y -f concat -safe 0 -i "$vlist" -c copy "$out" 2>/dev/null
        fi
        rm "$vlist"
        echo "$dir: concatenated ${#files[@]} segments -> final.mp4"
    }
    if [ -n "{{SEED}}" ]; then
        concat_dir "output/{{SEED}}"
    else
        for dir in output/*/; do
            [ -d "$dir" ] && concat_dir "$dir"
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
