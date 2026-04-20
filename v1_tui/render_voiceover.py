"""Render voiceover audio from voiceover.json using tts-demo.

Reads the voiceover monologue for each segment and renders it to WAV
files using the ChatterboxTTS model via ComfyUI (through ../tts-demo).

Usage:
    python3 render_voiceover.py --seed 42

See --help for all options.
"""

import argparse
import json
import os
import subprocess
import sys
import time

COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")


def get_wav_duration(path):
    """Get duration of a wav file in seconds using ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return float(result.stdout.strip())
    return None
TTS_DEMO_DIR = os.environ.get("TTS_DEMO_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tts-demo"))


def fmt_duration(seconds):
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m{s:02d}s"


def render_segment_tts(tts_dir, comfyui_url, text, voice, output_path, seed=1):
    """Render a single voiceover segment using tts-demo's tts.py."""
    cmd = [
        sys.executable,
        os.path.join(tts_dir, "tts.py"),
        "--url", comfyui_url,
        "--voice", voice,
        "--output", os.path.abspath(output_path),
        "--seed", str(seed),
        "--no-play",
        text,
    ]
    result = subprocess.run(cmd, cwd=tts_dir, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  tts.py stderr: {result.stderr}", file=sys.stderr)
        raise RuntimeError(f"tts.py failed with exit code {result.returncode}")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Render voiceover audio from voiceover.json using tts-demo"
    )
    parser.add_argument("--seed", type=int, required=True,
                        help="Run ID seed (reads from output/{seed}/voiceover.json)")
    parser.add_argument("--voice", default="despotism-doc.wav",
                        help="TTS voice reference file (default: despotism-doc.wav)")
    parser.add_argument("--tts-seed", type=int, default=1,
                        help="TTS RNG seed (default: 1)")
    parser.add_argument("--url", default=None,
                        help=f"ComfyUI URL for TTS (default: {COMFYUI_URL})")
    parser.add_argument("--tts-dir", default=None,
                        help=f"Path to tts-demo directory (default: {TTS_DEMO_DIR})")
    parser.add_argument("--duration", type=int, default=24,
                        help="Segment duration in seconds for warnings (default: 24)")

    args = parser.parse_args()

    comfyui_url = args.url or COMFYUI_URL
    tts_dir = args.tts_dir or TTS_DEMO_DIR

    if not os.path.isdir(tts_dir):
        print(f"Error: tts-demo not found at {tts_dir}", file=sys.stderr)
        print(f"Install it with: git clone <tts-demo-repo> ../tts-demo", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(os.path.join(tts_dir, "tts.py")):
        print(f"Error: tts.py not found in {tts_dir}", file=sys.stderr)
        sys.exit(1)

    from run_dir import get_run_dir
    run_dir = get_run_dir("output", args.seed)
    voiceover_path = os.path.join(run_dir, "voiceover.json")

    if not os.path.exists(voiceover_path):
        print(f"Error: {voiceover_path} not found", file=sys.stderr)
        print(f"Generate it first: just script --theme '...' --seed {args.seed}",
              file=sys.stderr)
        sys.exit(1)

    with open(voiceover_path) as f:
        voiceover = json.load(f)

    print(f"Rendering {len(voiceover)} voiceover segments")
    print(f"  voice: {args.voice}")
    print(f"  TTS:   {comfyui_url}")

    rendered = 0
    skipped = 0
    clip_times = []
    start = time.time()

    for i, text in enumerate(voiceover):
        seg_num = i + 1
        out_path = os.path.join(run_dir, f"voiceover_{seg_num:02d}.wav")

        if os.path.exists(out_path):
            print(f"\n  voiceover {seg_num}: exists, skipping")
            skipped += 1
            continue

        remaining = len(voiceover) - rendered - skipped
        seg_start = time.time()

        print(f"\n{'='*60}")
        print(f"Voiceover {seg_num}/{len(voiceover)} ({remaining} remaining)")
        print(f"  text: {text[:80]}{'...' if len(text) > 80 else ''}")
        print(f"  output: {out_path}")
        print(f"{'='*60}")

        render_segment_tts(
            tts_dir, comfyui_url, text, args.voice, out_path,
            seed=args.tts_seed + i,
        )
        print(f"  saved: {out_path}")

        # Check duration
        dur = get_wav_duration(out_path)
        if dur is not None:
            print(f"  duration: {dur:.1f}s", end="")
            if dur > args.duration:
                print(f"  WARNING: exceeds {args.duration}s segment length!")
            else:
                print()

        clip_time = time.time() - seg_start
        clip_times.append(clip_time)
        elapsed = time.time() - start
        avg_time = sum(clip_times) / len(clip_times)
        remaining_count = len(voiceover) - (rendered + skipped + 1)
        eta = avg_time * remaining_count

        print(f"  clip: {fmt_duration(clip_time)} | "
              f"avg: {fmt_duration(avg_time)} | "
              f"elapsed: {fmt_duration(elapsed)} | "
              f"eta: {fmt_duration(eta)} ({remaining_count} left)")

        rendered += 1

    total = time.time() - start
    print(f"\nDone. {rendered} rendered, {skipped} skipped ({fmt_duration(total)} total)")


if __name__ == "__main__":
    main()
