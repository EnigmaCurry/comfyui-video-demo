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
