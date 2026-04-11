"""Chained ComfyUI LTX image-to-video generation.

Generates a sequence of short video segments where each segment starts
from the last frame of the previous one. Prompts drift across segments
to create surreal, mutating continuity.

Usage:
    python3 chain.py --image start.png --workflow workflow/ltx_i2v.json

See --help for all options.
"""

import argparse
import copy
import json
import os
import subprocess
import sys

from comfyui_video import (
    COMFYUI_URL,
    download_output,
    run_workflow,
    upload_image,
)

# ── Default prompt config ─────────────────────────────────────────────

BASE_PROMPT = (
    "The video behaves like a chain of surreal revelations constantly "
    "interrupting each other. Each new image should feel like a sudden "
    "unexpected jump in thought. Transitions should be active "
    "metamorphoses, not crossfades. Begin from the input image, preserve "
    "some colors and shapes from it, but quickly mutate into new imagery."
)

DEFAULT_SUFFIXES = [
    "introduce chrome glamour, rainbow hair, twin phones, lacquered surfaces",
    "introduce desert masks, eyes, heat shimmer, sacred symbols",
    "introduce insects, jewels, stained-glass fragmentation",
    "introduce black liquid, iridescent membranes, abstract biological geometry",
    "introduce crystalline frost, shattered mirrors, prismatic light beams",
    "introduce molten gold rivers, floating stones, volcanic glass",
    "introduce deep ocean bioluminescence, tentacles, coral architecture",
    "introduce circuit boards, neon glyphs, holographic overlays",
]

# ── Workflow patching ─────────────────────────────────────────────────
# These are the node IDs and field paths to patch in the exported
# ComfyUI API workflow JSON. Configure these to match your workflow.

# Defaults assume a typical LTX 2.3 image-to-video workflow.
# Override with --image-node, --prompt-node, --output-node if needed.

DEFAULT_IMAGE_NODE = "269"         # LoadImage node ID
DEFAULT_IMAGE_FIELD = "image"      # field name within inputs

DEFAULT_PROMPT_NODE = "267:266"    # PrimitiveStringMultiline prompt node
DEFAULT_PROMPT_FIELD = "value"     # field name within inputs

DEFAULT_OUTPUT_NODE = "75"         # SaveVideo node ID
DEFAULT_OUTPUT_FIELD = "filename_prefix"

DEFAULT_SEED_NODE = "267:237"      # RandomNoise node for main sampler
DEFAULT_SEED_FIELD = "noise_seed"

DEFAULT_T2V_SWITCH_NODE = "267:201"  # PrimitiveBoolean: "Switch to Text to Video?"
DEFAULT_T2V_SWITCH_FIELD = "value"


def load_workflow(path):
    """Load a ComfyUI API-format workflow JSON."""
    with open(path) as f:
        return json.load(f)


def patch_workflow(workflow, *, image_name, prompt_text,
                   image_node, image_field,
                   prompt_node, prompt_field,
                   output_node, output_field, output_prefix,
                   seed_node, seed_field, seed_value,
                   negative_prompt_node=None, negative_prompt_field=None,
                   negative_prompt_text=None,
                   t2v_switch_node=None, t2v_switch_field=None,
                   t2v_enabled=False):
    """Patch a workflow dict with new image, prompt, and output settings."""
    wf = copy.deepcopy(workflow)

    # Patch text-to-video switch
    if t2v_switch_node and t2v_switch_node in wf:
        wf[t2v_switch_node]["inputs"][t2v_switch_field] = t2v_enabled

    # Patch image input (skip if in t2v mode — no image needed)
    if image_node and image_node in wf and not t2v_enabled:
        wf[image_node]["inputs"][image_field] = image_name

    # Patch prompt
    if prompt_node and prompt_node in wf:
        wf[prompt_node]["inputs"][prompt_field] = prompt_text

    # Patch output filename prefix
    if output_node and output_node in wf and output_prefix:
        wf[output_node]["inputs"][output_field] = output_prefix

    # Patch seed
    if seed_node and seed_node in wf and seed_value is not None:
        wf[seed_node]["inputs"][seed_field] = seed_value

    # Patch negative prompt
    if (negative_prompt_node and negative_prompt_node in wf
            and negative_prompt_text is not None):
        wf[negative_prompt_node]["inputs"][negative_prompt_field] = negative_prompt_text

    return wf


def extract_last_frame(video_path, output_png):
    """Extract the last frame of a video to a PNG using ffmpeg."""
    result = subprocess.run(
        ["ffmpeg", "-y", "-sseof", "-0.1", "-i", video_path,
         "-frames:v", "1", output_png],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg last-frame extraction failed: "
            f"{result.stderr.decode(errors='replace')}"
        )
    return output_png


def concat_videos(video_paths, output_path):
    """Concatenate videos using ffmpeg concat demuxer."""
    import tempfile
    list_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False
    )
    try:
        for p in video_paths:
            list_file.write(f"file '{os.path.abspath(p)}'\n")
        list_file.close()
        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", list_file.name, "-c", "copy", output_path],
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg concat failed: "
                f"{result.stderr.decode(errors='replace')}"
            )
    finally:
        os.unlink(list_file.name)
    return output_path


def build_prompt_text(base, suffix, segment_index):
    """Combine base prompt with per-segment suffix."""
    parts = [base.strip()]
    if suffix:
        parts.append(suffix.strip())
    return " ".join(parts)


def main():
    parser = argparse.ArgumentParser(
        description="Chained LTX image-to-video generation via ComfyUI"
    )
    parser.add_argument(
        "--image", default=None,
        help="Path to initial input image (optional if --text-to-video is used)",
    )
    parser.add_argument(
        "--workflow", required=True,
        help="Path to ComfyUI API-format workflow JSON",
    )
    parser.add_argument(
        "--output-dir", default="output",
        help="Directory for output files (default: output)",
    )
    parser.add_argument(
        "--segments", type=int, default=4,
        help="Number of video segments to generate (default: 4)",
    )
    parser.add_argument(
        "--base-prompt", default=BASE_PROMPT,
        help="Shared base prompt for all segments",
    )
    parser.add_argument(
        "--suffixes", nargs="*", default=None,
        help="Per-segment prompt suffixes (cycles if fewer than segments)",
    )
    parser.add_argument(
        "--suffixes-file", default=None,
        help="JSON file with list of prompt suffixes",
    )
    parser.add_argument(
        "--url", default=None,
        help=f"ComfyUI server URL (default: {COMFYUI_URL})",
    )

    # Workflow node configuration
    parser.add_argument("--image-node", default=DEFAULT_IMAGE_NODE,
                        help=f"LoadImage node ID (default: {DEFAULT_IMAGE_NODE})")
    parser.add_argument("--image-field", default=DEFAULT_IMAGE_FIELD,
                        help=f"Image input field name (default: {DEFAULT_IMAGE_FIELD})")
    parser.add_argument("--prompt-node", default=DEFAULT_PROMPT_NODE,
                        help=f"Prompt node ID (default: {DEFAULT_PROMPT_NODE})")
    parser.add_argument("--prompt-field", default=DEFAULT_PROMPT_FIELD,
                        help=f"Prompt text field name (default: {DEFAULT_PROMPT_FIELD})")
    parser.add_argument("--output-node", default=DEFAULT_OUTPUT_NODE,
                        help="Output node ID for filename prefix (default: auto)")
    parser.add_argument("--output-field", default=DEFAULT_OUTPUT_FIELD,
                        help=f"Output filename field (default: {DEFAULT_OUTPUT_FIELD})")
    parser.add_argument("--seed-node", default=DEFAULT_SEED_NODE,
                        help="Sampler node ID for seed patching (default: none)")
    parser.add_argument("--seed-field", default=DEFAULT_SEED_FIELD,
                        help=f"Seed field name (default: {DEFAULT_SEED_FIELD})")
    parser.add_argument("--seed", type=int, default=None,
                        help="Base seed value (increments per segment; default: random)")
    parser.add_argument("--negative-prompt-node", default="267:247",
                        help="Negative prompt node ID (default: 267:247)")
    parser.add_argument("--negative-prompt-field", default="text",
                        help="Negative prompt field name (default: text)")
    parser.add_argument("--negative-prompt", default=None,
                        help="Override negative prompt text")
    parser.add_argument("--text-to-video", action="store_true",
                        help="Use text-to-video mode for the first segment (no input image needed)")
    parser.add_argument("--t2v-switch-node", default=DEFAULT_T2V_SWITCH_NODE,
                        help=f"T2V switch node ID (default: {DEFAULT_T2V_SWITCH_NODE})")
    parser.add_argument("--t2v-switch-field", default=DEFAULT_T2V_SWITCH_FIELD,
                        help=f"T2V switch field name (default: {DEFAULT_T2V_SWITCH_FIELD})")

    parser.add_argument("--concat", action="store_true",
                        help="Concatenate all segments into final.mp4")
    parser.add_argument("--timeout", type=int, default=600,
                        help="Per-segment timeout in seconds (default: 600)")
    parser.add_argument("--start-segment", type=int, default=1,
                        help="Starting segment number (for resuming, default: 1)")
    parser.add_argument("--start-frame", default=None,
                        help="Override: use this PNG as input for the first segment "
                             "instead of --image (for resuming)")

    args = parser.parse_args()

    base_url = args.url or COMFYUI_URL

    # Load workflow
    workflow_template = load_workflow(args.workflow)

    # Resolve suffixes
    if args.suffixes_file:
        with open(args.suffixes_file) as f:
            suffixes = json.load(f)
    elif args.suffixes:
        suffixes = args.suffixes
    else:
        suffixes = DEFAULT_SUFFIXES

    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)

    # Initial image
    current_image = args.start_frame or args.image
    if current_image and not os.path.exists(current_image):
        print(f"Error: image not found: {current_image}", file=sys.stderr)
        sys.exit(1)
    if not current_image and not args.text_to_video:
        print("Error: --image is required unless --text-to-video is used", file=sys.stderr)
        sys.exit(1)

    segment_videos = []

    for i in range(args.segments):
        seg_num = args.start_segment + i
        seg_label = f"segment_{seg_num:02d}"
        seg_video = os.path.join(args.output_dir, f"{seg_label}.mp4")
        seg_frame = os.path.join(args.output_dir, f"{seg_label}_last.png")

        suffix_idx = i % len(suffixes)
        suffix = suffixes[suffix_idx]
        prompt_text = build_prompt_text(args.base_prompt, suffix, i)

        # Compute seed for this segment
        if args.seed is not None:
            seed_value = args.seed + i
        else:
            import random
            seed_value = random.randint(0, 2**53)

        # First segment can be text-to-video (no image input)
        is_t2v = args.text_to_video and i == 0 and not args.start_frame

        print(f"\n{'='*60}")
        print(f"Segment {seg_num}/{args.start_segment + args.segments - 1}")
        if is_t2v:
            print(f"  mode:   text-to-video")
        print(f"  suffix: {suffix}")
        print(f"  seed:   {seed_value}")
        if not is_t2v:
            print(f"  image:  {current_image}")
        print(f"  output: {seg_video}")
        print(f"{'='*60}")

        # Upload current image to ComfyUI (skip for t2v)
        uploaded_name = None
        if not is_t2v:
            print(f"  uploading image...")
            uploaded_name = upload_image(base_url, current_image)
            print(f"  uploaded as: {uploaded_name}")

        # Patch workflow
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
            output_prefix=seg_label,
            seed_node=args.seed_node,
            seed_field=args.seed_field,
            seed_value=seed_value,
            negative_prompt_node=args.negative_prompt_node,
            negative_prompt_field=args.negative_prompt_field,
            negative_prompt_text=args.negative_prompt,
            t2v_switch_node=args.t2v_switch_node,
            t2v_switch_field=args.t2v_switch_field,
            t2v_enabled=is_t2v,
        )

        # Submit and wait
        print(f"  submitting workflow...")
        history = run_workflow(base_url, wf, timeout=args.timeout)

        # Download output video
        print(f"  downloading video...")
        download_output(base_url, history, seg_video)
        print(f"  saved: {seg_video}")

        # Extract last frame
        print(f"  extracting last frame...")
        extract_last_frame(seg_video, seg_frame)
        print(f"  saved: {seg_frame}")

        segment_videos.append(seg_video)
        current_image = seg_frame

    # Concatenate if requested
    if args.concat and len(segment_videos) > 1:
        final_path = os.path.join(args.output_dir, "final.mp4")
        print(f"\nConcatenating {len(segment_videos)} segments...")
        concat_videos(segment_videos, final_path)
        print(f"Final video: {final_path}")

    print(f"\nDone. Generated {len(segment_videos)} segments in {args.output_dir}/")


if __name__ == "__main__":
    main()
