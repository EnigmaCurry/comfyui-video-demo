"""Interactive director mode for ComfyUI video generation.

Renders clips one at a time, previews each in mpv, and lets you
accept, refine, or redirect the movie as you go.

Usage:
    python3 direct.py --seed 42 --style story-arc --theme "A librarian turns into books"

See --help for all options.
"""

import argparse
import copy
import json
import os
import random
import readline
import subprocess
import sys
import time

from chain import (
    DEFAULT_IMAGE_FIELD,
    DEFAULT_IMAGE_NODE,
    DEFAULT_LENGTH,
    DEFAULT_LENGTH_FIELD,
    DEFAULT_LENGTH_NODE,
    DEFAULT_OUTPUT_FIELD,
    DEFAULT_OUTPUT_NODE,
    DEFAULT_PROMPT_FIELD,
    DEFAULT_PROMPT_NODE,
    DEFAULT_SEED_FIELD,
    DEFAULT_SEED_NODE,
    DEFAULT_T2V_SWITCH_FIELD,
    DEFAULT_T2V_SWITCH_NODE,
    _create_placeholder_image,
    build_prompt_text,
    extract_last_frame,
    fmt_duration,
    load_workflow,
    patch_workflow,
)
from comfyui_video import (
    COMFYUI_URL,
    download_output,
    run_workflow,
    upload_image,
)
from run_dir import get_run_dir, make_run_dir
from styles import DEFAULT_STYLE, list_styles, load_style
from write_script import _build_prompts, call_llm

LLM_URL = os.environ.get("LLM_URL", "http://127.0.0.1:8000")
LLM_MODEL = os.environ.get("LLM_MODEL", "default")


def preview_clip(video_path):
    """Play a clip in mpv and wait for it to finish."""
    try:
        subprocess.run(
            ["mpv", "--loop=inf", "--really-quiet", video_path],
            check=False,
        )
    except FileNotFoundError:
        print("  warning: mpv not found, skipping preview")


def print_script_overview(suffixes, voiceover=None):
    """Print the planned script so the director can see what's ahead."""
    print("\n╔══════════════════════════════════════════════════════════════╗")
    print("║  SCRIPT OVERVIEW                                           ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    for i, s in enumerate(suffixes):
        label = f"  [{i+1:2d}] "
        # Wrap long lines
        text = s[:100] + "..." if len(s) > 100 else s
        print(f"{label}{text}")
        if voiceover and i < len(voiceover):
            vo = voiceover[i]
            vo_text = vo[:80] + "..." if len(vo) > 80 else vo
            print(f"       VO: {vo_text}")
    print()


def director_prompt(seg_num, total, suffix):
    """Show the interactive director prompt. Returns (action, extra).

    Actions:
        accept  - keep this clip, move on
        refine  - re-render with modifications (extra = amended prompt or "")
        extend  - add a new scene beyond the script (extra = new prompt)
        end     - stop here, mux what we have
        quit    - abort without muxing
    """
    print()
    print("─" * 60)
    print(f"  Segment {seg_num}/{total}")
    print(f"  Prompt: {suffix[:90]}{'...' if len(suffix) > 90 else ''}")
    print("─" * 60)
    print("  Commands:")
    print("    [Enter]        Accept this clip, continue")
    print("    r [prompt]     Refine: re-render (optionally amend the prompt)")
    print("    e [prompt]     Extend: add a new scene after current script")
    print("    end            Finish movie here, mux what we have")
    print("    quit           Abort without muxing")
    print("    skip           Skip to next segment without re-rendering")
    print("    show           Replay the current clip")
    print()

    while True:
        try:
            response = input("  director> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return "quit", ""

        if response == "" or response.lower() == "y":
            return "accept", ""
        elif response.lower() == "end":
            return "end", ""
        elif response.lower() == "quit":
            return "quit", ""
        elif response.lower() == "skip":
            return "skip", ""
        elif response.lower() == "show":
            return "show", ""
        elif response.lower().startswith("r"):
            extra = response[1:].strip()
            return "refine", extra
        elif response.lower().startswith("e"):
            extra = response[1:].strip()
            if not extra:
                try:
                    extra = input("  new scene prompt> ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    continue
            return "extend", extra
        else:
            print(f"  Unknown command: {response}")


def render_segment(*, workflow_template, base_url, run_dir, seg_num, seed,
                   prompt_text, current_image, is_t2v, length, strip_audio,
                   args, timeout):
    """Render a single segment. Returns (video_path, last_frame_path)."""
    seg_label = f"segment_{seg_num:02d}"
    seg_video = os.path.join(run_dir, f"{seg_label}.mp4")
    seg_frame = os.path.join(run_dir, f"{seg_label}_last.png")

    noise_seed = random.randint(0, 2**53)

    print(f"\n{'='*60}")
    print(f"  Rendering segment {seg_num}")
    if is_t2v:
        print(f"  mode:   text-to-video")
    print(f"  prompt: {prompt_text[:80]}...")
    print(f"  noise:  {noise_seed}")
    print(f"{'='*60}")

    # Upload image
    if is_t2v:
        placeholder = _create_placeholder_image(run_dir)
        uploaded_name = upload_image(base_url, placeholder)
    else:
        uploaded_name = upload_image(base_url, current_image)

    wf = patch_workflow(
        workflow_template,
        image_name=uploaded_name,
        prompt_text=prompt_text,
        image_node=args.image_node,
        image_field=args.image_field,
        prompt_node=args.prompt_node,
        prompt_field=args.prompt_field,
        output_node=args.output_node,
        output_field=args.output_field,
        output_prefix=f"{seed}/{seg_label}",
        seed_node=args.seed_node,
        seed_field=args.seed_field,
        seed_value=noise_seed,
        negative_prompt_node=args.negative_prompt_node,
        negative_prompt_field=args.negative_prompt_field,
        negative_prompt_text=args.negative_prompt,
        t2v_switch_node=args.t2v_switch_node,
        t2v_switch_field=args.t2v_switch_field,
        t2v_enabled=is_t2v,
        length_node=args.length_node,
        length_field=args.length_field,
        length_value=length,
    )

    start = time.time()
    history = run_workflow(base_url, wf, timeout=timeout)

    download_output(base_url, history, seg_video, strip_audio=strip_audio)
    extract_last_frame(seg_video, seg_frame)

    elapsed = time.time() - start
    print(f"  rendered in {fmt_duration(elapsed)}")

    return seg_video, seg_frame


def main():
    parser = argparse.ArgumentParser(
        description="Interactive director mode for video generation"
    )
    parser.add_argument("--seed", type=int, required=True,
                        help="Run ID seed")
    parser.add_argument("--theme", nargs="+", required=True,
                        help="Theme or concept for the video")
    parser.add_argument("--style", default=DEFAULT_STYLE,
                        help=f"Prompt style (default: {DEFAULT_STYLE})")
    parser.add_argument("--segments", type=int, default=16,
                        help="Number of planned segments (default: 16)")
    parser.add_argument("--duration", type=int, default=None,
                        help="Segment duration in seconds (default: from style)")
    parser.add_argument("--workflow", default="workflow/ltx_i2v.json",
                        help="ComfyUI workflow JSON")
    parser.add_argument("--url", default=None,
                        help=f"ComfyUI server URL (default: {COMFYUI_URL})")
    parser.add_argument("--timeout", type=int, default=600,
                        help="Per-segment timeout in seconds (default: 600)")
    parser.add_argument("--base-prompt", default=None,
                        help="Override base prompt (default: from style)")
    parser.add_argument("--negative-prompt", default=None,
                        help="Override negative prompt text")
    parser.add_argument("--no-voiceover", action="store_true",
                        help="Skip voiceover generation")
    parser.add_argument("--length", type=int, default=None,
                        help="Video length in frames (overrides --duration)")
    parser.add_argument("--skip-script", action="store_true",
                        help="Skip script generation, use existing script.json")

    # Workflow node configuration (same defaults as chain.py)
    parser.add_argument("--image-node", default=DEFAULT_IMAGE_NODE)
    parser.add_argument("--image-field", default=DEFAULT_IMAGE_FIELD)
    parser.add_argument("--prompt-node", default=DEFAULT_PROMPT_NODE)
    parser.add_argument("--prompt-field", default=DEFAULT_PROMPT_FIELD)
    parser.add_argument("--output-node", default=DEFAULT_OUTPUT_NODE)
    parser.add_argument("--output-field", default=DEFAULT_OUTPUT_FIELD)
    parser.add_argument("--seed-node", default=DEFAULT_SEED_NODE)
    parser.add_argument("--seed-field", default=DEFAULT_SEED_FIELD)
    parser.add_argument("--negative-prompt-node", default="267:247")
    parser.add_argument("--negative-prompt-field", default="text")
    parser.add_argument("--t2v-switch-node", default=DEFAULT_T2V_SWITCH_NODE)
    parser.add_argument("--t2v-switch-field", default=DEFAULT_T2V_SWITCH_FIELD)
    parser.add_argument("--length-node", default=DEFAULT_LENGTH_NODE)
    parser.add_argument("--length-field", default=DEFAULT_LENGTH_FIELD)

    # LLM configuration
    parser.add_argument("--llm-url", default=None,
                        help=f"LLM API URL (default: {LLM_URL})")
    parser.add_argument("--llm-model", default=None,
                        help=f"LLM model name (default: {LLM_MODEL})")
    parser.add_argument("--llm-api-key", default=None,
                        help="LLM API key")

    args = parser.parse_args()
    args.theme = " ".join(args.theme)

    base_url = args.url or COMFYUI_URL
    llm_url = args.llm_url or LLM_URL
    llm_model = args.llm_model or LLM_MODEL
    llm_api_key = args.llm_api_key or os.environ.get("LLM_API_KEY", "")

    # Resolve style and duration
    style = load_style(args.style)
    strip_audio = style.get("strip_audio", False)
    if args.duration is None:
        args.duration = style.get("default_duration", 24)
    if args.length is not None:
        length = args.length
    else:
        length = args.duration * 25

    if args.base_prompt is None:
        args.base_prompt = style.get("base_prompt", "")

    # Create run directory
    run_dir = make_run_dir("output", args.seed, theme=args.theme)
    theme_path = os.path.join(run_dir, "theme.txt")
    if not os.path.exists(theme_path):
        with open(theme_path, "w") as f:
            f.write(args.theme)

    # Load workflow
    workflow_template = load_workflow(args.workflow)

    script_path = os.path.join(run_dir, "script.json")
    voiceover_path = os.path.join(run_dir, "voiceover.json")

    # ── Step 1: Generate or load script ─────────────────────────────
    if args.skip_script and os.path.exists(script_path):
        print(f"Loading existing script: {script_path}")
        with open(script_path) as f:
            suffixes = json.load(f)
        voiceover = None
        if os.path.exists(voiceover_path):
            with open(voiceover_path) as f:
                voiceover = json.load(f)
    else:
        print("╔══════════════════════════════════════════════════════════════╗")
        print("║  GENERATING SCRIPT                                         ║")
        print("╚══════════════════════════════════════════════════════════════╝")

        visual_sys, voiceover_sys, _ = _build_prompts(args.style, args.duration)

        # Generate visual descriptions
        if os.path.exists(script_path):
            print(f"  Script exists: {script_path} (loading)")
            with open(script_path) as f:
                suffixes = json.load(f)
        else:
            print(f"  Generating {args.segments}-segment visual script...")
            user_msg = f"Theme: {args.theme}\nNumber of segments: {args.segments}"
            if args.base_prompt:
                user_msg += (f"\n\nThe following base prompt will be prepended to each "
                             f"of your descriptions, so do not repeat its content:\n"
                             f"{args.base_prompt}")
            sys.stdout.write("  streaming: ")
            sys.stdout.flush()
            suffixes = call_llm(llm_url, llm_model, visual_sys, user_msg,
                                api_key=llm_api_key)
            if len(suffixes) > args.segments:
                suffixes = suffixes[:args.segments]
            with open(script_path, "w") as f:
                json.dump(suffixes, f, indent=2)
                f.write("\n")
            print(f"  saved: {script_path}")

        # Generate voiceover
        voiceover = None
        if not args.no_voiceover:
            if os.path.exists(voiceover_path):
                print(f"  Voiceover exists: {voiceover_path} (loading)")
                with open(voiceover_path) as f:
                    voiceover = json.load(f)
            else:
                print(f"\n  Generating voiceover text...")
                visual_list = "\n".join(
                    f"  Segment {i+1}: {v}" for i, v in enumerate(suffixes))
                vo_user_msg = (f"Theme: {args.theme}\n"
                               f"Number of segments: {len(suffixes)}\n\n"
                               f"Visual descriptions:\n{visual_list}")
                sys.stdout.write("  streaming: ")
                sys.stdout.flush()
                voiceover = call_llm(llm_url, llm_model, voiceover_sys,
                                     vo_user_msg, api_key=llm_api_key)
                if len(voiceover) > len(suffixes):
                    voiceover = voiceover[:len(suffixes)]
                with open(voiceover_path, "w") as f:
                    json.dump(voiceover, f, indent=2)
                    f.write("\n")
                print(f"  saved: {voiceover_path}")

    # Show the script
    print_script_overview(suffixes, voiceover)

    # ── Step 2: Interactive render loop ──────────────────────────────
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  DIRECTOR MODE — rendering begins                          ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    current_image = None
    completed_segments = []
    seg_num = 0
    total = len(suffixes)

    while seg_num < len(suffixes):
        suffix = suffixes[seg_num]
        prompt_text = build_prompt_text(args.base_prompt, suffix, seg_num)
        is_t2v = seg_num == 0

        seg_label = f"segment_{seg_num + 1:02d}"
        seg_video = os.path.join(run_dir, f"{seg_label}.mp4")
        seg_frame = os.path.join(run_dir, f"{seg_label}_last.png")

        # Check if already rendered
        if os.path.exists(seg_video) and os.path.exists(seg_frame):
            print(f"\n  Segment {seg_num + 1} already rendered, previewing...")
            preview_clip(seg_video)
            action, extra = director_prompt(seg_num + 1, total, suffix)
        else:
            # Render the segment
            seg_video, seg_frame = render_segment(
                workflow_template=workflow_template,
                base_url=base_url,
                run_dir=run_dir,
                seg_num=seg_num + 1,
                seed=args.seed,
                prompt_text=prompt_text,
                current_image=current_image,
                is_t2v=is_t2v,
                length=length,
                strip_audio=strip_audio,
                args=args,
                timeout=args.timeout,
            )

            # Preview
            preview_clip(seg_video)
            action, extra = director_prompt(seg_num + 1, total, suffix)

        # Handle the director's decision
        if action == "accept":
            completed_segments.append(seg_video)
            current_image = seg_frame
            seg_num += 1
            # Save progress
            _save_progress(run_dir, completed_segments, suffixes[:seg_num])

        elif action == "skip":
            if os.path.exists(seg_video) and os.path.exists(seg_frame):
                completed_segments.append(seg_video)
                current_image = seg_frame
            seg_num += 1
            _save_progress(run_dir, completed_segments, suffixes[:seg_num])

        elif action == "show":
            preview_clip(seg_video)
            continue  # re-prompt

        elif action == "refine":
            # Delete current renders
            for f in (seg_video, seg_frame):
                if os.path.exists(f):
                    os.unlink(f)

            # Amend the prompt if extra text provided
            if extra:
                suffixes[seg_num] = extra
                # Update script on disk
                with open(script_path, "w") as f:
                    json.dump(suffixes, f, indent=2)
                    f.write("\n")
                print(f"  Updated prompt for segment {seg_num + 1}")
            # Loop back to re-render (same seg_num)
            continue

        elif action == "extend":
            # Add a new scene beyond the current script
            suffixes.append(extra)
            total = len(suffixes)
            # Update script on disk
            with open(script_path, "w") as f:
                json.dump(suffixes, f, indent=2)
                f.write("\n")
            print(f"  Added segment {total}: {extra[:60]}...")
            # Accept current segment first
            completed_segments.append(seg_video)
            current_image = seg_frame
            seg_num += 1
            _save_progress(run_dir, completed_segments, suffixes[:seg_num])

        elif action == "end":
            completed_segments.append(seg_video)
            current_image = seg_frame
            print(f"\n  Ending movie with {len(completed_segments)} segments.")
            break

        elif action == "quit":
            print("\n  Aborted. Segments rendered so far are in:")
            print(f"    {run_dir}/")
            sys.exit(0)

    # ── Step 3: Mux final video ──────────────────────────────────────
    if not completed_segments:
        print("No segments to mux.")
        sys.exit(0)

    _save_progress(run_dir, completed_segments, suffixes[:len(completed_segments)])

    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  MUXING FINAL VIDEO                                        ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    # Run mux.py
    subprocess.run(
        ["python3", "mux.py", "--seed", str(args.seed)],
        check=True,
    )

    # Find and play the final video
    dir_name = os.path.basename(run_dir)
    final_path = os.path.join(run_dir, f"{dir_name}.mp4")
    if os.path.exists(final_path):
        print(f"\nFinal video: {final_path}")
        print("Playing final video...")
        preview_clip(final_path)
    else:
        print(f"\nSegments saved in: {run_dir}/")


def _save_progress(run_dir, completed_segments, used_suffixes):
    """Save a progress file so interrupted sessions can be reviewed."""
    progress = {
        "completed": len(completed_segments),
        "segments": [os.path.basename(s) for s in completed_segments],
        "prompts": used_suffixes,
    }
    with open(os.path.join(run_dir, "progress.json"), "w") as f:
        json.dump(progress, f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
