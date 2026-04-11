"""Manual script generation — prints prompts for you to paste into an LLM.

Outputs the system+user prompts for visual descriptions and voiceover,
then reads back the JSON response from stdin.

Usage:
    python3 write_script_manual.py --theme "surreal dream" --segments 16 --seed 42

See --help for all options.
"""

import argparse
import json
import os
import sys

# Import prompts from write_script
from write_script import VISUAL_SYSTEM_PROMPT, VOICEOVER_SYSTEM_PROMPT


def read_json_response(label):
    """Read a JSON array from stdin."""
    print(f"\nPaste the {label} JSON array below, then press Ctrl+D (EOF):")
    print("─" * 40)
    text = sys.stdin.read().strip()
    print("─" * 40)

    # Strip markdown code blocks
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        items = json.loads(text)
    except json.JSONDecodeError:
        print(f"Error: not valid JSON", file=sys.stderr)
        sys.exit(1)

    if not isinstance(items, list):
        print(f"Error: expected JSON array, got {type(items).__name__}", file=sys.stderr)
        sys.exit(1)

    return items


def print_prompt(system, user):
    """Print a formatted prompt for copy-pasting."""
    print("\n" + "=" * 60)
    print("SYSTEM PROMPT (paste as system message):")
    print("=" * 60)
    print(system)
    print("\n" + "=" * 60)
    print("USER MESSAGE (paste as user message):")
    print("=" * 60)
    print(user)
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Manual script generation — prints prompts for copy-paste"
    )
    parser.add_argument("--theme", required=True, nargs="+",
                        help="High-level theme or concept for the video")
    parser.add_argument("--segments", type=int, default=16,
                        help="Number of segments to generate (default: 16)")
    parser.add_argument("--seed", type=int, required=True,
                        help="Run ID seed (output goes to output/{seed}/)")
    parser.add_argument("--base-prompt", default=None,
                        help="Base prompt that will be prepended to visual descriptions")
    parser.add_argument("--visual-only", action="store_true",
                        help="Only do visual descriptions, skip voiceover")
    parser.add_argument("--voiceover-only", action="store_true",
                        help="Only do voiceover (requires existing script.json)")
    parser.add_argument("--force", action="store_true",
                        help="Regenerate even if files already exist")

    args = parser.parse_args()
    args.theme = " ".join(args.theme)

    run_dir = os.path.join("output", str(args.seed))
    os.makedirs(run_dir, exist_ok=True)

    theme_path = os.path.join(run_dir, "theme.txt")
    if not os.path.exists(theme_path):
        with open(theme_path, "w") as f:
            f.write(args.theme)

    script_path = os.path.join(run_dir, "script.json")
    voiceover_path = os.path.join(run_dir, "voiceover.json")

    # ── Visual descriptions ───────────────────────────────────────────
    if not args.voiceover_only:
        if os.path.exists(script_path) and not args.force:
            print(f"Visual script exists: {script_path} (use --force to regenerate)")
            with open(script_path) as f:
                visuals = json.load(f)
        else:
            user_msg = f"Theme: {args.theme}\nNumber of segments: {args.segments}"
            if args.base_prompt:
                user_msg += (f"\n\nThe following base prompt will be prepended to each "
                             f"of your descriptions, so do not repeat its content:\n"
                             f"{args.base_prompt}")

            print_prompt(VISUAL_SYSTEM_PROMPT, user_msg)
            visuals = read_json_response("visual descriptions")

            if len(visuals) > args.segments:
                visuals = visuals[:args.segments]

            with open(script_path, "w") as f:
                json.dump(visuals, f, indent=2)
                f.write("\n")
            print(f"\nSaved {len(visuals)} visual descriptions to {script_path}")
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
            visual_list = "\n".join(f"  Segment {i+1}: {v}" for i, v in enumerate(visuals))
            vo_user_msg = (f"Theme: {args.theme}\n"
                           f"Number of segments: {len(visuals)}\n\n"
                           f"Visual descriptions for each segment:\n{visual_list}")

            print_prompt(VOICEOVER_SYSTEM_PROMPT, vo_user_msg)
            voiceover = read_json_response("voiceover monologue")

            if len(voiceover) > len(visuals):
                voiceover = voiceover[:len(visuals)]

            with open(voiceover_path, "w") as f:
                json.dump(voiceover, f, indent=2)
                f.write("\n")
            print(f"\nSaved {len(voiceover)} voiceover segments to {voiceover_path}")

    # ── Usage hint ────────────────────────────────────────────────────
    print(f"\nNext steps:")
    print(f"  just chain --text-to-video --workflow workflow/ltx_i2v.json "
          f"--seed {args.seed} --segments {len(visuals)} "
          f"--suffixes-file {script_path}")


if __name__ == "__main__":
    main()
