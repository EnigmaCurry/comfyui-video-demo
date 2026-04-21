# Film Director

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

# Install all dependencies
install:
    uv venv
    uv pip install -r backend/requirements.txt
    cd frontend && npm install

# Run backend API server
backend *ARGS:
    #!/usr/bin/env bash
    source .venv/bin/activate
    cd backend && uvicorn main:app --reload --host 0.0.0.0 --port 8000 {{ARGS}}

# Run frontend dev server
frontend:
    cd frontend && npm run dev -- --host 0.0.0.0

# Run both backend and frontend for development
dev:
    #!/usr/bin/env bash
    trap 'kill 0' EXIT
    just backend &
    just frontend &
    wait

# Build frontend for production
build:
    cd frontend && npm run build

# Clean output and build artifacts
[confirm("Remove output/ and frontend/dist/?")]
clean:
    rm -rf backend/projects/ backend/output/ frontend/dist/ backend/__pycache__/
    @echo "Cleaned"
