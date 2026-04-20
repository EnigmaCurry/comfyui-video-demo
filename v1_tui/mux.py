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
        # Voiceover is longer than segment — trim to fit
        subprocess.run(
            ["ffmpeg", "-y", "-i", wav_path,
             "-af", f"atrim=0:{target_duration},afade=t=out:st={max(0, target_duration - 0.15)}:d=0.15",
             "-c:a", "pcm_s16le", output_path],
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
    parser.add_argument("--voice-delay", type=float, default=0.0,
                        help="Extra delay in seconds added after centering (default: 0.0)")
    parser.add_argument("--pattern", default="segment",
                        help="Video file pattern prefix (default: segment, also: transition)")

    args = parser.parse_args()

    from run_dir import get_run_dir
    run_dir = get_run_dir(args.output_dir, args.seed)

    # Find segment videos and voiceover files
    seg_videos = sorted(glob.glob(os.path.join(run_dir, f"{args.pattern}_*.mp4")))
    vo_files = sorted(glob.glob(os.path.join(run_dir, "voiceover_*.wav")))

    if not seg_videos:
        print(f"Error: no segment videos in {run_dir}/", file=sys.stderr)
        sys.exit(1)

    # Name the final video after the directory
    dir_name = os.path.basename(run_dir)
    final_path = os.path.join(run_dir, f"{dir_name}.mp4")

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
        # Check if all segments share the same frame rate
        def get_fps(path):
            r = subprocess.run(
                ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
                 "-show_entries", "stream=r_frame_rate",
                 "-of", "csv=p=0", path],
                capture_output=True, text=True,
            )
            return r.stdout.strip() if r.returncode == 0 else None

        fps_set = set(get_fps(v) for v in seg_videos)
        mixed_fps = len(fps_set) > 1

        if mixed_fps:
            # Pick the most common fps as target
            from collections import Counter
            fps_counts = Counter(get_fps(v) for v in seg_videos)
            target_fps_str = fps_counts.most_common(1)[0][0]
            # Evaluate fractional fps like "25/1" to a number string
            if "/" in target_fps_str:
                num, den = target_fps_str.split("/")
                target_fps = str(int(num) // int(den))
            else:
                target_fps = target_fps_str
            print(f"  Mixed frame rates detected: {fps_set}")
            print(f"  Normalizing to {target_fps} fps")

        # Normalize mismatched segments before concat
        normalized_videos = []
        if mixed_fps:
            for i, v in enumerate(seg_videos):
                if get_fps(v) != target_fps_str:
                    norm_path = os.path.join(tmpdir, f"norm_{i:02d}.mp4")
                    print(f"  re-encoding {os.path.basename(v)} "
                          f"({get_fps(v)} -> {target_fps}fps)")
                    result = subprocess.run(
                        ["ffmpeg", "-y", "-i", v,
                         "-r", target_fps,
                         "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                         "-an", norm_path],
                        capture_output=True,
                    )
                    if result.returncode != 0:
                        print(f"  warning: re-encode failed: "
                              f"{result.stderr.decode(errors='replace')[:200]}",
                              file=sys.stderr)
                        normalized_videos.append(v)
                    else:
                        normalized_videos.append(norm_path)
                else:
                    normalized_videos.append(v)
        else:
            normalized_videos = seg_videos

        # Concat video segments
        vlist = os.path.join(tmpdir, "videos.txt")
        with open(vlist, "w") as f:
            for v in normalized_videos:
                f.write(f"file '{os.path.abspath(v)}'\n")

        tmp_video = os.path.join(tmpdir, "concat.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", vlist, "-c", "copy", tmp_video],
            capture_output=True, check=True,
        )

        # Build a mapping from segment index to voiceover file
        vo_by_index = {}
        for vo in vo_files:
            # Extract index from voiceover_NN.wav
            base = os.path.splitext(os.path.basename(vo))[0]
            try:
                idx = int(base.split("_")[1]) - 1  # 1-based to 0-based
                vo_by_index[idx] = vo
            except (IndexError, ValueError):
                pass

        if vo_by_index:
            print(f"Mixing {len(vo_by_index)} voiceover clips (centered) with "
                  f"{len(seg_videos)} video segments...")

            # Get each video segment duration and pad voiceover to match
            padded_files = []
            for i, seg_vid in enumerate(seg_videos):
                seg_dur = get_duration(seg_vid)
                if seg_dur is None:
                    print(f"  warning: could not get duration of {seg_vid}, "
                          f"using 24s", file=sys.stderr)
                    seg_dur = 24.0

                padded_path = os.path.join(tmpdir, f"padded_{i:02d}.wav")
                vo_wav = vo_by_index.get(i)

                if vo_wav is None:
                    # Generate silence for this segment
                    subprocess.run(
                        ["ffmpeg", "-y", "-f", "lavfi",
                         "-i", f"anullsrc=r=24000:cl=mono",
                         "-t", str(seg_dur),
                         "-c:a", "pcm_s16le", padded_path],
                        capture_output=True, check=True,
                    )
                    print(f"  segment {i+1}: video={seg_dur:.1f}s, "
                          f"(silence)")
                else:
                    vo_dur = pad_audio_centered(vo_wav, seg_dur, padded_path)

                    if vo_dur > seg_dur:
                        print(f"  segment {i+1}: video={seg_dur:.1f}s, "
                              f"voice={vo_dur:.1f}s, trimmed to {seg_dur:.1f}s")
                    else:
                        pad_before = (seg_dur - vo_dur) / 2
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

            # Warn if total voiceover and video durations differ
            video_dur = get_duration(tmp_video)
            vo_dur_total = get_duration(tmp_vo)
            if video_dur and vo_dur_total:
                diff = abs(video_dur - vo_dur_total)
                if diff > 1.0:
                    print(f"  WARNING: total video={video_dur:.1f}s, "
                          f"voiceover={vo_dur_total:.1f}s "
                          f"(diff={diff:.1f}s)")

            # Apply master offset delay to the full voiceover track
            if args.voice_delay > 0:
                delay_ms = int(args.voice_delay * 1000)
                tmp_vo_delayed = os.path.join(tmpdir, "voiceover_delayed.wav")
                subprocess.run(
                    ["ffmpeg", "-y", "-i", tmp_vo,
                     "-af", f"adelay={delay_ms}|{delay_ms}",
                     "-c:a", "pcm_s16le", tmp_vo_delayed],
                    capture_output=True, check=True,
                )
                tmp_vo = tmp_vo_delayed
                print(f"  master delay: {args.voice_delay}s")

            # Check if video has an audio stream
            probe = subprocess.run(
                ["ffprobe", "-v", "quiet", "-select_streams", "a",
                 "-show_entries", "stream=index", "-of", "csv=p=0",
                 tmp_video],
                capture_output=True, text=True,
            )
            has_audio = bool(probe.stdout.strip())

            # Mix video audio + voiceover, or just add voiceover
            vv = args.video_volume
            vov = args.voice_volume
            if has_audio:
                result = subprocess.run(
                    ["ffmpeg", "-y", "-i", tmp_video, "-i", tmp_vo,
                     "-filter_complex",
                     f"[0:a]volume={vv}[orig];"
                     f"[1:a]volume={vov}[vo];"
                     f"[orig][vo]amix=inputs=2:duration=first[aout]",
                     "-map", "0:v", "-map", "[aout]",
                     "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                     final_path],
                    capture_output=True,
                )
            else:
                print("  (video has no audio track, using voiceover only)")
                result = subprocess.run(
                    ["ffmpeg", "-y", "-i", tmp_video, "-i", tmp_vo,
                     "-map", "0:v", "-map", "1:a",
                     "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                     "-shortest", final_path],
                    capture_output=True,
                )
            if result.returncode != 0:
                print(f"  ffmpeg error: {result.stderr.decode(errors='replace')}",
                      file=sys.stderr)
                raise subprocess.CalledProcessError(result.returncode, "ffmpeg")
        else:
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
