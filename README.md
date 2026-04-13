# comfyui-video-demo

Chained LTX image-to-video generation via ComfyUI. Generates long surreal
videos as a sequence of short segments, where each segment starts from the
last frame of the previous one. Prompts drift across segments to create
mutating visual continuity.

Optional LLM-generated scripts and TTS voiceover narration.

## Prerequisites

- Python 3
- [ComfyUI](https://github.com/comfyanonymous/ComfyUI) with LTX 2.3 model and custom nodes
- ffmpeg
- [just](https://github.com/casey/just) (task runner)

### Optional

- [tts-demo](https://github.com/EnigmaCurry/tts-demo) for voiceover
  narration (clone it as a sibling directory: `../tts-demo`)
- An OpenAI-compatible LLM API (vllm, ollama, etc.) for script generation
- Wan 2.1 VACE model in ComfyUI for V2V scene transforms
- mpv for video preview playback

## Setup

```bash
just config   # configure ComfyUI URL, LLM endpoint, and API keys
```

Export your LTX image-to-video workflow from ComfyUI in **API format**
(Save API Format) and save it to `workflow/ltx_i2v.json`.

### .env variables

| Variable | Description | Default |
|----------|-------------|---------|
| `COMFYUI_URL` | ComfyUI server URL | `http://127.0.0.1:8188` |
| `COMFYUI_TOKEN` | Bearer token for ComfyUI auth | (none) |
| `LLM_URL` | OpenAI-compatible LLM API URL | `http://127.0.0.1:8000` |
| `LLM_MODEL` | LLM model name | `default` |
| `LLM_API_KEY` | Bearer token for LLM API | (none) |

## Director mode (interactive)

The director mode is a TUI for building videos clip-by-clip with full
creative control. Run it with no arguments for interactive setup:

```bash
just direct
```

Or pass options directly:

```bash
just direct --seed 123 --style story-arc --theme A librarian slowly turns into her own books
```

This generates a script and voiceover text via LLM, then enters a curses
TUI where you render, review, and refine each scene one at a time.

### TUI controls

| Key | Action |
|-----|--------|
| Space | Play current scene in mpv |
| p | Play previous + current scene back-to-back |
| Left/Right | Navigate between rendered scenes |
| Home/End | Jump to first/last scene |
| Enter | Re-render current scene with a new seed |
| a | Approve scene and render the next one |
| v | Refine visual prompt (edit and re-render) |
| o | Refine voiceover text (edit and re-render audio) |
| d | Set custom duration for this scene |
| t | Transform scene with V2V (Wan 2.1 VACE) |
| c | Cancel changes (revert to approved version) |
| r | Render final movie (mux all segments and play) |
| q q | Quit (double-tap; session is saved) |

### Session persistence

Sessions are saved automatically. Quit anytime and resume by running
`just direct --seed <same-seed>`. All scene statuses, prompts, voiceover
text, custom durations, and your current position are restored.

### V2V transform

Press `t` to restyle a rendered scene using the Wan 2.1 VACE
video-to-video model. This keeps the motion/composition of the original
clip but regenerates the visuals from a new prompt.

Tips:
- Describe the full destination scene, not what to change
- Use lower strength (0.2-0.4) for major restyling
- Use higher strength (0.6-0.8) for subtle changes
- Requires `workflow/wan_v2v.json` and the Wan 2.1 VACE model in ComfyUI

### Extending beyond the script

When you approve the last scripted scene, the TUI prompts for a new scene
description. Enter a prompt to keep going, or press Enter to stop. Extended
scenes are saved to the script and session.

## Batch mode

Run the full pipeline in one command:

```bash
just workflow --theme "waking life alien dreamscape" --seed 42 --segments 16
```

This runs all four steps in sequence:
1. Generate visual script + voiceover monologue from the LLM
2. Render voiceover audio via tts-demo
3. Render chained video segments via ComfyUI
4. Concatenate segments into `final.mp4` with centered voiceover

Every step skips existing files, so the command is fully resumable. If it
gets interrupted, just run it again.

### Additional workflow options

```bash
# Custom voice for narration
just workflow --theme "gothic cathedral dreams" --seed 99 --segments 8 --voice narrator.wav

# Shorter segments (121 frames ~= 4 seconds)
just workflow --theme "ocean depths" --seed 77 --segments 32 --length 121
```

Extra flags are passed through to `chain.py` (e.g. `--length`, `--base-prompt`,
`--negative-prompt`).

## Running steps individually

Each step can also be run separately:

```bash
# 1. Generate visual script + voiceover monologue
just script --theme "waking life alien dreamscape" --seed 42 --segments 16

# 2. Review and edit the generated files
cat output/42/script.json      # visual prompts per segment
cat output/42/voiceover.json   # voiceover monologue per segment

# 3. Render voiceover audio (requires ComfyUI + ChatterboxTTS)
just voiceover --seed 42 --voice narrator.wav

# 4. Render video segments (requires ComfyUI + LTX)
just chain --text-to-video --workflow workflow/ltx_i2v.json \
  --seed 42 --segments 16 --suffixes-file output/42/script.json

# 5. Concatenate with centered voiceover
just concat 42
```

### Manual script generation

If you prefer to use your own LLM (e.g. ChatGPT, Claude), use the manual
mode which prints prompts for copy-paste:

```bash
just script-manual --theme "waking life alien dreamscape" --seed 42 --segments 16
```

## Iterating

The `--seed` is a run ID — all outputs go to `output/{seed}/`. Existing
files are skipped automatically.

```bash
# Don't like segment 5? Delete it and re-run (gets a new random noise seed)
rm output/42/segment_05.mp4 output/42/segment_05_last.png
just workflow --theme "waking life alien dreamscape" --seed 42 --segments 16

# Extend from 16 to 32 segments (keeps the first 16, generates 17-32)
just workflow --theme "waking life alien dreamscape" --seed 42 --segments 32

# Regenerate the LLM script from scratch
just script --theme "new direction" --seed 42 --segments 16 --force

# Re-concat after changes
just concat 42

# Concat all seed directories
just concat
```

## Recipes

| Recipe | Description |
|--------|-------------|
| `just direct` | Interactive director mode TUI |
| `just workflow` | Run full batch pipeline: script, voiceover, video, concat |
| `just clip` | Render a single test clip and play it |
| `just config` | Configure `.env` settings |
| `just script` | Generate visual + voiceover script from LLM |
| `just script-manual` | Generate script via copy-paste prompts |
| `just voiceover` | Render voiceover audio via tts-demo |
| `just chain` | Run chained video generation |
| `just concat` | Concatenate segments into `final.mp4` |
| `just concat 42` | Concat a specific seed run |
| `just last-frame VIDEO OUT` | Extract last frame from a video |
| `just clean` | Remove output directory |

## Output structure

```
output/
└── 42/                        # seed/run ID
    ├── script.json            # visual prompts (from LLM)
    ├── voiceover.json         # voiceover text (from LLM)
    ├── segment_01.mp4         # video segments
    ├── segment_01_last.png    # last frame (input for next segment)
    ├── segment_02.mp4
    ├── segment_02_last.png
    ├── ...
    ├── voiceover_01.wav       # voiceover audio per segment
    ├── voiceover_02.wav
    ├── ...
    └── final.mp4              # concatenated final video with voiceover
```

## chain.py options

| Flag | Description | Default |
|------|-------------|---------|
| `--seed` | Run ID (required) | -- |
| `--workflow` | ComfyUI API workflow JSON (required) | -- |
| `--image` | Initial input image | -- |
| `--text-to-video` | Text-to-video mode for first segment | off |
| `--segments` | Number of segments | 4 |
| `--length` | Video length in frames | 600 (~24s) |
| `--base-prompt` | Shared base prompt | surreal metamorphosis |
| `--suffixes-file` | JSON file of per-segment suffixes | built-in |
| `--concat` | Concatenate after generation | off |
| `--timeout` | Per-segment timeout (seconds) | 600 |
| `--negative-prompt` | Override negative prompt | -- |

Workflow node IDs are configurable via `--image-node`, `--prompt-node`,
`--seed-node`, `--output-node`, etc. See `python3 chain.py --help`.
