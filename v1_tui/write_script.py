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

from styles import DEFAULT_STYLE, list_styles, load_style

LLM_URL = os.environ.get("LLM_URL", "http://127.0.0.1:8000")
LLM_MODEL = os.environ.get("LLM_MODEL", "default")

DEFAULT_DURATION = 24


def _voiceover_word_range(duration):
    """Estimate word count range for a given duration in seconds."""
    # ~1.7 words/sec speaking rate (scaled back 33% from 2.5)
    lo = max(1, int(duration * 1.0))
    hi = max(lo, int(duration * 1.7))
    return lo, hi


DEFAULT_VOICEOVER_SYSTEM_PROMPT_TEMPLATE = """\
You are a poet and narrator writing a voiceover monologue for a surreal experimental video.

The video is made of sequential segments, each about {duration} seconds long.
You will be given the visual descriptions for each segment.
Your job is to write spoken monologue text that accompanies each segment.

Rules:
- CRITICAL: Each segment's voiceover MUST be {word_lo}-{word_hi} words MAX (to fill ~{duration} seconds of speech). Count your words carefully. If the limit is 3-5 words, write a fragment, not a sentence.
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


def _build_prompts(style_name, duration):
    """Build visual and voiceover system prompts from a style + duration."""
    style = load_style(style_name)
    visual_sys = style["visual_system_prompt"].format(duration=duration)
    wlo, whi = _voiceover_word_range(duration)
    vo_template = style.get("voiceover_system_prompt") or DEFAULT_VOICEOVER_SYSTEM_PROMPT_TEMPLATE
    voiceover_sys = vo_template.format(duration=duration, word_lo=wlo, word_hi=whi)
    base_prompt = style.get("base_prompt")
    return visual_sys, voiceover_sys, base_prompt


def _build_transition_prompts(style_name, duration):
    """Build keyframe, transition, and voiceover prompts for transition mode."""
    style = load_style(style_name)
    keyframe_sys = style["keyframe_system_prompt"]
    transition_sys = style["transition_system_prompt"].format(duration=duration)
    wlo, whi = _voiceover_word_range(duration)
    vo_template = style.get("voiceover_system_prompt") or DEFAULT_VOICEOVER_SYSTEM_PROMPT_TEMPLATE
    voiceover_sys = vo_template.format(duration=duration, word_lo=wlo, word_hi=whi)
    base_prompt = style.get("base_prompt")
    negative_prompt = style.get("negative_prompt", "")
    return keyframe_sys, transition_sys, voiceover_sys, base_prompt, negative_prompt


# For backward compat with write_script_manual.py imports
_default_style = load_style(DEFAULT_STYLE)
VISUAL_SYSTEM_PROMPT_TEMPLATE = _default_style["visual_system_prompt"]
VISUAL_SYSTEM_PROMPT = VISUAL_SYSTEM_PROMPT_TEMPLATE.format(duration=DEFAULT_DURATION)
VOICEOVER_SYSTEM_PROMPT_TEMPLATE = DEFAULT_VOICEOVER_SYSTEM_PROMPT_TEMPLATE
_wlo, _whi = _voiceover_word_range(DEFAULT_DURATION)
VOICEOVER_SYSTEM_PROMPT = VOICEOVER_SYSTEM_PROMPT_TEMPLATE.format(
    duration=DEFAULT_DURATION, word_lo=_wlo, word_hi=_whi)


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


def _generate_transition_script(args, run_dir, base_url, model, api_key):
    """Generate keyframes.json, transitions.json, and voiceover.json for transition mode."""
    keyframe_sys, transition_sys, voiceover_sys, base_prompt, neg_prompt = \
        _build_transition_prompts(args.style, args.duration)

    keyframes_path = os.path.join(run_dir, "keyframes.json")
    transitions_path = os.path.join(run_dir, "transitions.json")
    voiceover_path = os.path.join(run_dir, "voiceover.json")

    # ── Keyframe descriptions ────────────────────────────────────────
    if not args.voiceover_only:
        if os.path.exists(keyframes_path) and not args.force:
            print(f"Keyframes exist: {keyframes_path} (use --force to regenerate)")
            with open(keyframes_path) as f:
                keyframes = json.load(f)
        else:
            print(f"Generating {args.segments} keyframe descriptions...")
            print(f"  theme: {args.theme}")
            print(f"  LLM:   {base_url} ({model})")
            sys.stdout.write("  streaming: ")
            sys.stdout.flush()

            user_msg = f"Theme: {args.theme}\nNumber of keyframes: {args.segments}"
            keyframes = call_llm(base_url, model, keyframe_sys, user_msg,
                                 temperature=args.temperature, api_key=api_key)

            if len(keyframes) > args.segments:
                keyframes = keyframes[:args.segments]

            if args.print_only:
                print("\n=== Keyframe descriptions ===")
                print(json.dumps(keyframes, indent=2))
            else:
                with open(keyframes_path, "w") as f:
                    json.dump(keyframes, f, indent=2)
                    f.write("\n")
                print(f"  saved: {keyframes_path}")

        # ── Transition descriptions ──────────────────────────────────
        if os.path.exists(transitions_path) and not args.force:
            print(f"Transitions exist: {transitions_path} (use --force to regenerate)")
        else:
            n_transitions = len(keyframes) - 1
            print(f"\nGenerating {n_transitions} transition descriptions...")
            sys.stdout.write("  streaming: ")
            sys.stdout.flush()

            kf_list = "\n".join(
                f"  Keyframe {i+1}: {k}" for i, k in enumerate(keyframes))
            trans_user_msg = (f"Theme: {args.theme}\n"
                              f"Number of keyframes: {len(keyframes)}\n\n"
                              f"Keyframe descriptions:\n{kf_list}")

            transitions = call_llm(base_url, model, transition_sys, trans_user_msg,
                                   temperature=args.temperature, api_key=api_key)

            if len(transitions) > n_transitions:
                transitions = transitions[:n_transitions]
            if len(transitions) < n_transitions:
                print(f"  warning: LLM returned {len(transitions)} transitions, "
                      f"expected {n_transitions} — will cycle", file=sys.stderr)

            if args.print_only:
                print("\n=== Transition descriptions ===")
                print(json.dumps(transitions, indent=2))
            else:
                with open(transitions_path, "w") as f:
                    json.dump(transitions, f, indent=2)
                    f.write("\n")
                print(f"  saved: {transitions_path}")
    else:
        if not os.path.exists(keyframes_path):
            print(f"Error: {keyframes_path} not found (needed for --voiceover-only)",
                  file=sys.stderr)
            sys.exit(1)
        with open(keyframes_path) as f:
            keyframes = json.load(f)

    # ── Voiceover ────────────────────────────────────────────────────
    if not args.visual_only:
        if os.path.exists(voiceover_path) and not args.force:
            print(f"\nVoiceover exists: {voiceover_path} (use --force to regenerate)")
        else:
            # Load transitions for context
            if os.path.exists(transitions_path):
                with open(transitions_path) as f:
                    transitions = json.load(f)
            else:
                print(f"Error: {transitions_path} not found (needed for voiceover)",
                      file=sys.stderr)
                sys.exit(1)

            print(f"\nGenerating voiceover for {len(transitions)} transitions...")
            sys.stdout.write("  streaming: ")
            sys.stdout.flush()

            kf_list = "\n".join(
                f"  Keyframe {i+1}: {k}" for i, k in enumerate(keyframes))
            tr_list = "\n".join(
                f"  Transition {i+1} (keyframe {i+1} → {i+2}): {t}"
                for i, t in enumerate(transitions))
            vo_msg = (f"Theme: {args.theme}\n"
                      f"Number of transitions: {len(transitions)}\n\n"
                      f"Keyframe descriptions:\n{kf_list}\n\n"
                      f"Transition descriptions:\n{tr_list}")

            voiceover = call_llm(base_url, model, voiceover_sys, vo_msg,
                                 temperature=args.temperature, api_key=api_key)

            if len(voiceover) > len(transitions):
                voiceover = voiceover[:len(transitions)]

            if args.print_only:
                print("\n=== Voiceover ===")
                print(json.dumps(voiceover, indent=2))
            else:
                with open(voiceover_path, "w") as f:
                    json.dump(voiceover, f, indent=2)
                    f.write("\n")
                print(f"  saved: {voiceover_path}")

    if not args.print_only:
        print(f"\nNext steps:")
        print(f"  1. Review/edit: {keyframes_path}")
        print(f"     Review/edit: {transitions_path}")
        print(f"  2. Run transition director:")
        print(f"     just transition --seed {args.seed}")


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
    parser.add_argument("--duration", type=int, default=None,
                        help="Segment duration in seconds (default: from style)")
    parser.add_argument("--style", default=DEFAULT_STYLE,
                        help=f"Prompt style (default: {DEFAULT_STYLE}; available: {', '.join(list_styles())})")
    parser.add_argument("--base-prompt", default=None,
                        help="Override base prompt (default: from style)")
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

    # Resolve duration from style if not explicitly set
    style_data = load_style(args.style)
    if args.duration is None:
        args.duration = style_data.get("default_duration", DEFAULT_DURATION)

    # Detect transition mode from style
    is_transition = style_data.get("mode") == "transition"

    from run_dir import make_run_dir
    run_dir = make_run_dir("output", args.seed, theme=args.theme)

    # Save theme for use by mux.py when naming the final video
    theme_path = os.path.join(run_dir, "theme.txt")
    if not os.path.exists(theme_path):
        with open(theme_path, "w") as f:
            f.write(args.theme)

    if is_transition:
        _generate_transition_script(args, run_dir, base_url, model, api_key)
        return

    # Build duration-aware prompts from style
    visual_sys, voiceover_sys, style_base_prompt = _build_prompts(args.style, args.duration)
    if args.base_prompt is None:
        args.base_prompt = style_base_prompt

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

            visuals = call_llm(base_url, model, visual_sys, user_msg,
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

            voiceover = call_llm(base_url, model, voiceover_sys, vo_user_msg,
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
