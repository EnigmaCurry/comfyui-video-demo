"""Generate a video chain script using an OpenAI-compatible LLM API.

Produces per-segment visual prompts and voiceover monologue that can be fed
to chain.py and render_voiceover.py.

Usage:
    python3 write_script.py --theme "surreal dream journey" --segments 16 --seed 42

See --help for all options.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

LLM_URL = os.environ.get("LLM_URL", "http://127.0.0.1:8000")
LLM_MODEL = os.environ.get("LLM_MODEL", "default")

VISUAL_SYSTEM_PROMPT = """\
You are a visual director writing a shot list for a surreal experimental video.

The video is made of sequential segments, each about 24 seconds long.
Each segment is generated from a text-to-video AI model.
Each segment begins from the last frame of the previous segment.

Your job is to write a vivid, concrete visual description for each segment.
These are NOT story beats or dialogue — they are visual directions for an AI video model.

Rules:
- Each description should be 1-3 sentences of pure visual language.
- Describe what is SEEN: colors, textures, shapes, movement, lighting, composition.
- Each segment should feel like a sudden visual shift — a metamorphosis, not a fade.
- Maintain some thread of continuity (a color, a shape, a motif) between adjacent segments.
- Vary the visual style across segments: some abstract, some figurative, some architectural, etc.
- Do NOT use character names, dialogue, narrative, or plot.
- Do NOT use meta-language like "the scene transitions to" or "we see".
- Just describe the visual content directly.

Respond with a JSON array of strings, one per segment. No other text.\
"""

VOICEOVER_SYSTEM_PROMPT = """\
You are a poet and narrator writing a voiceover monologue for a surreal experimental video.

The video is made of sequential segments, each about 24 seconds long.
You will be given the visual descriptions for each segment.
Your job is to write spoken monologue text that accompanies each segment.

Rules:
- Each segment's voiceover should be about 40-60 words (to fill ~24 seconds of speech).
- The voiceover should be poetic, contemplative, or stream-of-consciousness.
- It should COMPLEMENT the visuals, not describe them literally.
- Think of it like a waking dream narration — the speaker is experiencing these visions.
- The voice should have a consistent personality across all segments.
- Vary the tone: sometimes questioning, sometimes declarative, sometimes whispering urgency.
- Do NOT describe what is being seen on screen directly.
- Instead, speak about ideas, feelings, memories, or questions evoked by the imagery.
- The monologue should feel like one continuous thought that evolves across segments.

Respond with a JSON array of strings, one per segment. No other text.\
"""


def _salvage_json_array(text):
    """Try to recover complete items from a truncated JSON array."""
    import re
    # Find all complete quoted strings in the array
    matches = re.findall(r'"((?:[^"\\]|\\.)*)"', text)
    if not matches:
        return None
    # Filter to just the array items (skip any that look like keys)
    # The pattern in our case is simple: array of strings
    # Try progressively shorter lists until one parses
    for i in range(len(matches), 0, -1):
        attempt = json.dumps(matches[:i])
        try:
            return json.loads(attempt)
        except json.JSONDecodeError:
            continue
    return None


def call_llm(base_url, model, system_prompt, user_msg, temperature=0.9, api_key=None):
    """Call the LLM with streaming and return parsed JSON array."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        "temperature": temperature,
        "max_tokens": 16384,
        "stream": True,
    }

    url = f"{base_url}/v1/chat/completions"
    data = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    try:
        resp = urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"Error: HTTP {e.code}: {body}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Error: could not connect to {base_url}: {e.reason}", file=sys.stderr)
        sys.exit(1)

    # Read SSE stream with a waiting spinner for time-to-first-token
    import threading
    content = ""
    token_count = 0
    finish_reason = None
    first_token = threading.Event()

    def wait_spinner():
        """Show elapsed seconds while waiting for first token."""
        import itertools
        elapsed = 0
        for _ in itertools.count():
            if first_token.wait(timeout=1):
                return
            elapsed += 1
            sys.stdout.write(f"\r  streaming: (thinking {elapsed}s...)")
            sys.stdout.flush()

    spinner = threading.Thread(target=wait_spinner, daemon=True)
    spinner.start()

    try:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line or not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
                choice = chunk["choices"][0]
                delta = choice.get("delta", {})
                text_chunk = delta.get("content", "")
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]
                if text_chunk:
                    if not first_token.is_set():
                        first_token.set()
                        spinner.join()
                        sys.stdout.write(f"\r  streaming: ")
                        sys.stdout.flush()
                    content += text_chunk
                    token_count += 1
                    if token_count % 20 == 0:
                        sys.stdout.write(".")
                        sys.stdout.flush()
            except (json.JSONDecodeError, KeyError, IndexError):
                continue
    finally:
        first_token.set()
        resp.close()

    status = f"{token_count} tokens"
    if finish_reason and finish_reason != "stop":
        status += f", finish_reason={finish_reason}"
    print(f" ({status})")

    # Parse JSON from the response (handle markdown code blocks)
    text = content.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        items = json.loads(text)
    except json.JSONDecodeError:
        # Try to salvage truncated JSON array
        items = _salvage_json_array(text)
        if items is None:
            print(f"Error: LLM response was not valid JSON:\n{content}", file=sys.stderr)
            sys.exit(1)
        print(f"  warning: response was truncated, salvaged {len(items)} complete segments")

    if not isinstance(items, list):
        print(f"Error: expected JSON array, got {type(items).__name__}", file=sys.stderr)
        sys.exit(1)

    return items


def main():
    parser = argparse.ArgumentParser(
        description="Generate video chain script from an LLM"
    )
    parser.add_argument("--theme", required=True, nargs="+",
                        help="High-level theme or concept for the video")
    parser.add_argument("--segments", type=int, default=16,
                        help="Number of segments to generate (default: 16)")
    parser.add_argument("--seed", type=int, required=True,
                        help="Run ID seed (output goes to output/{seed}/)")
    parser.add_argument("--base-prompt", default=None,
                        help="Base prompt that will be prepended (so LLM avoids repeating it)")
    parser.add_argument("--url", default=None,
                        help=f"LLM API base URL (default: {LLM_URL})")
    parser.add_argument("--model", default=None,
                        help=f"Model name (default: {LLM_MODEL})")
    parser.add_argument("--api-key", default=None,
                        help="API key (default: LLM_API_KEY env var)")
    parser.add_argument("--temperature", type=float, default=0.9,
                        help="Sampling temperature (default: 0.9)")
    parser.add_argument("--visual-only", action="store_true",
                        help="Only generate visual descriptions, skip voiceover")
    parser.add_argument("--voiceover-only", action="store_true",
                        help="Only generate voiceover (requires existing script.json)")
    parser.add_argument("--force", action="store_true",
                        help="Regenerate even if files already exist")
    parser.add_argument("--print", action="store_true", dest="print_only",
                        help="Print to stdout instead of saving to file")

    args = parser.parse_args()

    args.theme = " ".join(args.theme)
    base_url = args.url or LLM_URL
    model = args.model or LLM_MODEL
    api_key = args.api_key or os.environ.get("LLM_API_KEY", "")

    run_dir = os.path.join("output", str(args.seed))
    os.makedirs(run_dir, exist_ok=True)

    script_path = os.path.join(run_dir, "script.json")
    voiceover_path = os.path.join(run_dir, "voiceover.json")

    # ── Visual descriptions ───────────────────────────────────────────
    if not args.voiceover_only:
        if os.path.exists(script_path) and not args.force:
            print(f"Visual script exists: {script_path} (use --force to regenerate)")
            with open(script_path) as f:
                visuals = json.load(f)
        else:
            print(f"Generating {args.segments}-segment visual script...")
            print(f"  theme: {args.theme}")
            print(f"  LLM:   {base_url} ({model})")
            sys.stdout.write("  streaming: ")
            sys.stdout.flush()

            user_msg = f"Theme: {args.theme}\nNumber of segments: {args.segments}"
            if args.base_prompt:
                user_msg += (f"\n\nThe following base prompt will be prepended to each "
                             f"of your descriptions, so do not repeat its content:\n"
                             f"{args.base_prompt}")

            visuals = call_llm(base_url, model, VISUAL_SYSTEM_PROMPT, user_msg,
                               temperature=args.temperature, api_key=api_key)

            if len(visuals) < args.segments:
                print(f"  warning: LLM returned {len(visuals)} segments, "
                      f"requested {args.segments} — will cycle", file=sys.stderr)
            elif len(visuals) > args.segments:
                visuals = visuals[:args.segments]

            if args.print_only:
                print("\n=== Visual descriptions ===")
                print(json.dumps(visuals, indent=2))
            else:
                with open(script_path, "w") as f:
                    json.dump(visuals, f, indent=2)
                    f.write("\n")
                print(f"  saved: {script_path}")
    else:
        if not os.path.exists(script_path):
            print(f"Error: {script_path} not found (needed for --voiceover-only)",
                  file=sys.stderr)
            sys.exit(1)
        with open(script_path) as f:
            visuals = json.load(f)

    # ── Voiceover monologue ───────────────────────────────────────────
    if not args.visual_only:
        if os.path.exists(voiceover_path) and not args.force:
            print(f"\nVoiceover exists: {voiceover_path} (use --force to regenerate)")
        else:
            print(f"\nGenerating voiceover monologue...")
            sys.stdout.write("  streaming: ")
            sys.stdout.flush()

            visual_list = "\n".join(f"  Segment {i+1}: {v}" for i, v in enumerate(visuals))
            vo_user_msg = (f"Theme: {args.theme}\n"
                           f"Number of segments: {len(visuals)}\n\n"
                           f"Visual descriptions for each segment:\n{visual_list}")

            voiceover = call_llm(base_url, model, VOICEOVER_SYSTEM_PROMPT, vo_user_msg,
                                 temperature=args.temperature, api_key=api_key)

            if len(voiceover) < len(visuals):
                print(f"  warning: LLM returned {len(voiceover)} voiceover segments, "
                      f"expected {len(visuals)} — will cycle", file=sys.stderr)
            elif len(voiceover) > len(visuals):
                voiceover = voiceover[:len(visuals)]

            if args.print_only:
                print("\n=== Voiceover monologue ===")
                print(json.dumps(voiceover, indent=2))
            else:
                with open(voiceover_path, "w") as f:
                    json.dump(voiceover, f, indent=2)
                    f.write("\n")
                print(f"  saved: {voiceover_path}")

    # ── Usage hint ────────────────────────────────────────────────────
    if not args.print_only:
        print(f"\nNext steps:")
        print(f"  1. Review/edit: {script_path}")
        if not args.visual_only:
            print(f"     Review/edit: {voiceover_path}")
            print(f"  2. Render voiceover (with ChatterboxTTS running):")
            print(f"     just voiceover --seed {args.seed}")
        step = 3 if not args.visual_only else 2
        print(f"  {step}. Render video (with LTX running):")
        print(f"     just chain --text-to-video --workflow workflow/ltx_i2v.json "
              f"--seed {args.seed} --segments {len(visuals)} "
              f"--suffixes-file {script_path}")


if __name__ == "__main__":
    main()
