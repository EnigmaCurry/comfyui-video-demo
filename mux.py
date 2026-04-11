"""Mux voiceover audio into concatenated video, centering each clip in its segment.

Each voiceover WAV is padded with silence so it sits centered within its
corresponding video segment, then all padded clips are concatenated and
mixed with the original video audio.

Usage:
    python3 mux.py --seed 42
"""

import argparse
import glob
import os
import subprocess
import sys
import tempfile


def get_duration(path):
    """Get media duration in seconds via ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return float(result.stdout.strip())
    return None


def pad_audio_centered(wav_path, target_duration, output_path):
    """Pad a WAV with silence so it's centered within target_duration."""
    dur = get_duration(wav_path)
    if dur is None:
        raise RuntimeError(f"Could not get duration of {wav_path}")

    if dur >= target_duration:
        # Voiceover is longer than segment — just copy it
        subprocess.run(
            ["ffmpeg", "-y", "-i", wav_path, "-c:a", "pcm_s16le", output_path],
            capture_output=True,
        )
        return dur

    pad_total = target_duration - dur
    pad_before = pad_total / 2
    pad_after = pad_total - pad_before

    # Use adelay for front padding and apad+atrim for back padding
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", wav_path,
         "-af", f"adelay={int(pad_before * 1000)}|{int(pad_before * 1000)},"
                f"apad=pad_dur={pad_after}",
         "-c:a", "pcm_s16le", output_path],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg pad failed: {result.stderr.decode(errors='replace')}")
    return dur


def main():
    parser = argparse.ArgumentParser(
        description="Mux voiceover into final video with centered audio"
    )
    parser.add_argument("--seed", type=int, required=True,
                        help="Run ID seed")
    parser.add_argument("--output-dir", default="output",
                        help="Base output directory (default: output)")
    parser.add_argument("--video-volume", type=float, default=0.3,
                        help="Original video audio volume (default: 0.3)")
    parser.add_argument("--voice-volume", type=float, default=1.0,
                        help="Voiceover volume (default: 1.0)")

    args = parser.parse_args()

    run_dir = os.path.join(args.output_dir, str(args.seed))

    # Find segment videos and voiceover files
    seg_videos = sorted(glob.glob(os.path.join(run_dir, "segment_*.mp4")))
    vo_files = sorted(glob.glob(os.path.join(run_dir, "voiceover_*.wav")))

    if not seg_videos:
        print(f"Error: no segment videos in {run_dir}/", file=sys.stderr)
        sys.exit(1)

    final_path = os.path.join(run_dir, "final.mp4")

    # Check if up to date
    if os.path.exists(final_path):
        final_mtime = os.path.getmtime(final_path)
        stale = False
        for f in seg_videos + vo_files:
            if os.path.getmtime(f) > final_mtime:
                stale = True
                break
        if not stale:
            print(f"final.mp4 is already up to date ({len(seg_videos)} segments)")
            return

    tmpdir = tempfile.mkdtemp(prefix="mux-")

    try:
        # Concat video segments
        vlist = os.path.join(tmpdir, "videos.txt")
        with open(vlist, "w") as f:
            for v in seg_videos:
                f.write(f"file '{os.path.abspath(v)}'\n")

        tmp_video = os.path.join(tmpdir, "concat.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", vlist, "-c", "copy", tmp_video],
            capture_output=True, check=True,
        )

        if vo_files and len(vo_files) == len(seg_videos):
            print(f"Mixing {len(vo_files)} voiceover clips (centered) with "
                  f"{len(seg_videos)} video segments...")

            # Get each video segment duration and pad voiceover to match
            padded_files = []
            for i, (seg_vid, vo_wav) in enumerate(zip(seg_videos, vo_files)):
                seg_dur = get_duration(seg_vid)
                if seg_dur is None:
                    print(f"  warning: could not get duration of {seg_vid}, "
                          f"using 24s", file=sys.stderr)
                    seg_dur = 24.0

                padded_path = os.path.join(tmpdir, f"padded_{i:02d}.wav")
                vo_dur = pad_audio_centered(vo_wav, seg_dur, padded_path)

                pad_before = max(0, (seg_dur - vo_dur) / 2)
                print(f"  segment {i+1}: video={seg_dur:.1f}s, "
                      f"voice={vo_dur:.1f}s, "
                      f"offset={pad_before:.1f}s")
                padded_files.append(padded_path)

            # Concat padded voiceover
            vo_list = os.path.join(tmpdir, "voiceover.txt")
            with open(vo_list, "w") as f:
                for p in padded_files:
                    f.write(f"file '{os.path.abspath(p)}'\n")

            tmp_vo = os.path.join(tmpdir, "voiceover.wav")
            subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                 "-i", vo_list, "-c:a", "pcm_s16le", tmp_vo],
                capture_output=True, check=True,
            )

            # Mix video audio + voiceover
            vv = args.video_volume
            vov = args.voice_volume
            subprocess.run(
                ["ffmpeg", "-y", "-i", tmp_video, "-i", tmp_vo,
                 "-filter_complex",
                 f"[0:a]volume={vv}[orig];"
                 f"[1:a]volume={vov}[vo];"
                 f"[orig][vo]amix=inputs=2:duration=longest[aout]",
                 "-map", "0:v", "-map", "[aout]",
                 "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                 final_path],
                capture_output=True, check=True,
            )
        else:
            if vo_files and len(vo_files) != len(seg_videos):
                print(f"Warning: {len(vo_files)} voiceover files but "
                      f"{len(seg_videos)} segments, skipping voiceover mix")
            # No voiceover — just copy concat
            subprocess.run(
                ["ffmpeg", "-y", "-i", tmp_video, "-c", "copy", final_path],
                capture_output=True, check=True,
            )

        print(f"Saved: {final_path}")

    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
