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
