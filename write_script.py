"""Generate a video chain script using an OpenAI-compatible LLM API.

Produces a JSON file of per-segment visual prompts that can be fed
to chain.py via --suffixes-file.

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

SYSTEM_PROMPT = """\
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


def generate_script(base_url, model, theme, segments, base_prompt=None,
                    temperature=0.9, api_key=None):
    """Call the LLM to generate per-segment visual descriptions."""
    user_msg = f"Theme: {theme}\nNumber of segments: {segments}"
    if base_prompt:
        user_msg += f"\n\nThe following base prompt will be prepended to each of your descriptions, so do not repeat its content:\n{base_prompt}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "temperature": temperature,
        "max_tokens": 4096,
    }

    url = f"{base_url}/v1/chat/completions"
    data = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"Error: HTTP {e.code}: {body}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Error: could not connect to {base_url}: {e.reason}", file=sys.stderr)
        sys.exit(1)

    content = result["choices"][0]["message"]["content"]

    # Parse JSON from the response (handle markdown code blocks)
    text = content.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Strip first and last lines (```json and ```)
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        suffixes = json.loads(text)
    except json.JSONDecodeError:
        print(f"Error: LLM response was not valid JSON:\n{content}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(suffixes, list):
        print(f"Error: expected JSON array, got {type(suffixes).__name__}", file=sys.stderr)
        sys.exit(1)

    return suffixes


def main():
    parser = argparse.ArgumentParser(
        description="Generate video chain script from an LLM"
    )
    parser.add_argument("--theme", required=True,
                        help="High-level theme or concept for the video")
    parser.add_argument("--segments", type=int, default=16,
                        help="Number of segments to generate (default: 16)")
    parser.add_argument("--seed", type=int, required=True,
                        help="Run ID seed (output goes to output/{seed}/script.json)")
    parser.add_argument("--base-prompt", default=None,
                        help="Base prompt that will be prepended (so LLM avoids repeating it)")
    parser.add_argument("--output", default=None,
                        help="Output path (default: output/{seed}/script.json)")
    parser.add_argument("--url", default=None,
                        help=f"LLM API base URL (default: {LLM_URL})")
    parser.add_argument("--model", default=None,
                        help=f"Model name (default: {LLM_MODEL})")
    parser.add_argument("--api-key", default=None,
                        help="API key (default: LLM_API_KEY env var)")
    parser.add_argument("--temperature", type=float, default=0.9,
                        help="Sampling temperature (default: 0.9)")
    parser.add_argument("--print", action="store_true", dest="print_only",
                        help="Print to stdout instead of saving to file")

    args = parser.parse_args()

    base_url = args.url or LLM_URL
    model = args.model or LLM_MODEL
    api_key = args.api_key or os.environ.get("LLM_API_KEY", "")

    print(f"Generating {args.segments}-segment script for theme: {args.theme}")
    print(f"  LLM: {base_url} ({model})")

    suffixes = generate_script(
        base_url, model, args.theme, args.segments,
        base_prompt=args.base_prompt,
        temperature=args.temperature,
        api_key=api_key,
    )

    # Pad or trim to requested count
    if len(suffixes) < args.segments:
        print(f"  warning: LLM returned {len(suffixes)} segments, "
              f"requested {args.segments} — will cycle", file=sys.stderr)
    elif len(suffixes) > args.segments:
        suffixes = suffixes[:args.segments]

    if args.print_only:
        print(json.dumps(suffixes, indent=2))
        return

    out_path = args.output
    if not out_path:
        run_dir = os.path.join("output", str(args.seed))
        os.makedirs(run_dir, exist_ok=True)
        out_path = os.path.join(run_dir, "script.json")

    with open(out_path, "w") as f:
        json.dump(suffixes, f, indent=2)
        f.write("\n")

    print(f"\nSaved {len(suffixes)} segments to {out_path}")
    print(f"\nUse with:")
    print(f"  just chain --text-to-video --workflow workflow/ltx_i2v.json "
          f"--seed {args.seed} --segments {len(suffixes)} "
          f"--suffixes-file {out_path}")


if __name__ == "__main__":
    main()
