# comfyui-video-demo Justfile

set dotenv-load

# List available recipes
default:
    @just --list

# Configure ComfyUI server URL in .env
config:
    #!/usr/bin/env bash
    current=""
    if [ -f .env ]; then
        current=$(grep -oP '(?<=^COMFYUI_URL=).*' .env 2>/dev/null || true)
    fi
    if [ -n "$current" ]; then
        echo "Current COMFYUI_URL=$current"
    fi
    read -rp "ComfyUI URL [${current:-http://127.0.0.1:8188}]: " url
    url="${url:-${current:-http://127.0.0.1:8188}}"
    if [ -f .env ]; then
        if grep -q '^COMFYUI_URL=' .env; then
            sed -i "s|^COMFYUI_URL=.*|COMFYUI_URL=${url}|" .env
        else
            echo "COMFYUI_URL=${url}" >> .env
        fi
    else
        echo "COMFYUI_URL=${url}" > .env
    fi
    echo "Saved COMFYUI_URL=${url} to .env"

# Run chained image-to-video generation
chain *ARGS:
    python3 chain.py {{ARGS}}

# Concatenate all segment videos in output/ into final.mp4
concat DIR="output":
    #!/usr/bin/env bash
    set -euo pipefail
    shopt -s nullglob
    files=("{{DIR}}"/segment_*.mp4)
    if [ ${#files[@]} -eq 0 ]; then
        echo "No segment videos found in {{DIR}}/"
        exit 1
    fi
    list=$(mktemp)
    for f in "${files[@]}"; do
        echo "file '$(realpath "$f")'" >> "$list"
    done
    out="{{DIR}}/final.mp4"
    ffmpeg -y -f concat -safe 0 -i "$list" -c copy "$out"
    rm "$list"
    echo "Concatenated ${#files[@]} segments -> $out"

# Extract last frame from a video as PNG
last-frame VIDEO OUT:
    ffmpeg -y -sseof -0.1 -i "{{VIDEO}}" -frames:v 1 "{{OUT}}"

# Clean output directory
[confirm("Remove output/ directory?")]
clean:
    rm -rf output/ __pycache__/
    @echo "Cleaned"
