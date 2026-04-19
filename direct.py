"""Interactive director mode TUI for ComfyUI video generation.

Full TUI for reviewing and directing video generation clip by clip.
Navigate between scenes, refine prompts and voiceover, and build
your movie interactively.

Usage:
    python3 direct.py --seed 42 --style story-arc --theme "A librarian turns into books"

See --help for all options.
"""

import argparse
import curses
import json
import os
import random
import readline
import shutil
import subprocess
import sys
import textwrap
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
    upload_file,
    upload_image,
)
from mux import get_duration, pad_audio_centered
from render_voiceover import TTS_DEMO_DIR, render_segment_tts
from run_dir import make_run_dir
from styles import DEFAULT_STYLE, load_style
from transition import (
    AUDIO_WORKFLOW,
    T2I_WORKFLOW,
    TRANSITION_WORKFLOW,
    patch_audio_workflow,
    patch_t2i_workflow,
    patch_transition_workflow,
)
from write_script import _build_prompts, _build_transition_prompts, call_llm

LLM_URL = os.environ.get("LLM_URL", "http://127.0.0.1:8000")
LLM_MODEL = os.environ.get("LLM_MODEL", "default")
V2V_WORKFLOW = os.path.join(os.path.dirname(__file__), "workflow", "wan_v2v.json")


def extract_first_frame(video_path, output_png):
    """Extract the first frame of a video to a PNG using ffmpeg."""
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", video_path, "-frames:v", "1", output_png],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg first-frame extraction failed: "
            f"{result.stderr.decode(errors='replace')}"
        )
    return output_png

# Color pair IDs
C_APPROVED = 1
C_RENDERED = 2
C_PENDING = 3
C_DRAFT = 4
C_DIM = 5
C_KEY = 6


# ── Scene data ──────────────────────────────────────────────────────

class Scene:
    def __init__(self, index, suffix, voiceover_text="", length=None):
        self.index = index
        self.suffix = suffix
        self.voiceover_text = voiceover_text
        self.length = length  # per-scene frame count, None = use default
        self.status = "pending"  # pending | rendered | approved
        self._backup_suffix = None
        self._backup_voiceover = None
        self.has_draft = False

    @property
    def num(self):
        return self.index + 1

    @property
    def label(self):
        return f"segment_{self.num:02d}"

    def video_path(self, d):
        return os.path.join(d, f"{self.label}.mp4")

    def frame_path(self, d):
        return os.path.join(d, f"{self.label}_last.png")

    def vo_path(self, d):
        return os.path.join(d, f"voiceover_{self.num:02d}.wav")

    def preview_path(self, d):
        return os.path.join(d, f"preview_{self.num:02d}.mp4")

    def has_video(self, d):
        return os.path.exists(self.video_path(d))

    def save_draft_backup(self):
        if not self.has_draft:
            self._backup_suffix = self.suffix
            self._backup_voiceover = self.voiceover_text
            self.has_draft = True

    def cancel_draft(self):
        if self.has_draft:
            self.suffix = self._backup_suffix
            self.voiceover_text = self._backup_voiceover
            self._backup_suffix = None
            self._backup_voiceover = None
            self.has_draft = False

    def commit_draft(self):
        self._backup_suffix = None
        self._backup_voiceover = None
        self.has_draft = False


# ── Transition mode data ────────────────────────────────────────────

class Keyframe:
    def __init__(self, index, description):
        self.index = index
        self.description = description
        self.status = "pending"  # pending | generated | approved

    @property
    def num(self):
        return self.index + 1

    def image_path(self, d):
        return os.path.join(d, f"keyframe_{self.num:02d}.png")

    def has_image(self, d):
        return os.path.exists(self.image_path(d))


class TransitionClip:
    def __init__(self, index, description, voiceover_text=""):
        self.index = index
        self.description = description
        self.voiceover_text = voiceover_text
        self.status = "pending"  # pending | rendered | approved

    @property
    def num(self):
        return self.index + 1

    def video_path(self, d):
        return os.path.join(d, f"transition_{self.num:02d}.mp4")

    def has_video(self, d):
        return os.path.exists(self.video_path(d))

    def vo_path(self, d):
        return os.path.join(d, f"voiceover_{self.num:02d}.wav")


# ── File backup helpers ──────────────────────────────────────────────

def _backup(path):
    bak = path + ".bak"
    if os.path.exists(path):
        if os.path.exists(bak):
            os.unlink(bak)
        os.rename(path, bak)

def _restore(path):
    bak = path + ".bak"
    if os.path.exists(bak):
        if os.path.exists(path):
            os.unlink(path)
        os.rename(bak, path)

def _delete_bak(path):
    bak = path + ".bak"
    if os.path.exists(bak):
        os.unlink(bak)

def _delete_if_exists(path):
    if os.path.exists(path):
        os.unlink(path)


# ── TUI ──────────────────────────────────────────────────────────────

class DirectorTUI:
    def __init__(self, *, scenes, run_dir, workflow_template, base_url,
                 base_prompt, length, strip_audio, voice, tts_dir, tts_seed,
                 seed, args, timeout, script_path, voiceover_json_path,
                 has_voiceover, style_name, llm_url, llm_model, llm_api_key):
        self.scenes = scenes
        self.run_dir = run_dir
        self.workflow_template = workflow_template
        self.base_url = base_url
        self.base_prompt = base_prompt
        self.length = length
        self.style_name = style_name
        self.llm_url = llm_url
        self.llm_model = llm_model
        self.llm_api_key = llm_api_key
        self.strip_audio = strip_audio
        self.voice = voice
        self.tts_dir = tts_dir
        self.tts_seed = tts_seed
        self.seed = seed
        self.args = args
        self.timeout = timeout
        self.script_path = script_path
        self.voiceover_json_path = voiceover_json_path
        self.has_voiceover = has_voiceover
        self.current = 0
        self.frontier = -1
        self.stdscr = None
        self.status_msg = ""
        self.should_quit = False

    def run(self):
        # Try to restore a previous session
        if self._load_session():
            print(f"Resumed session: scene {self.current + 1}, "
                  f"{self.frontier + 1} rendered")
        else:
            # First run — render scene 1
            if not self.scenes[0].has_video(self.run_dir):
                self._render_scene_terminal(0)
            else:
                self.scenes[0].status = "rendered"
            self.frontier = 0
            self._save_session()
        curses.wrapper(self._main)
        self._post_tui()

    # ── curses lifecycle ─────────────────────────────────────────────

    def _main(self, stdscr):
        self.stdscr = stdscr
        curses.curs_set(0)
        curses.use_default_colors()
        if curses.has_colors():
            curses.init_pair(C_APPROVED, curses.COLOR_GREEN, -1)
            curses.init_pair(C_RENDERED, curses.COLOR_CYAN, -1)
            curses.init_pair(C_PENDING, curses.COLOR_YELLOW, -1)
            curses.init_pair(C_DRAFT, curses.COLOR_MAGENTA, -1)
            curses.init_pair(C_DIM, curses.COLOR_WHITE, -1)
            curses.init_pair(C_KEY, curses.COLOR_CYAN, -1)

        while not self.should_quit:
            self._draw()
            key = stdscr.getch()
            self._handle_key(key)

        # Don't call endwin() here — curses.wrapper handles that.
        self._save_session()

    def _post_tui(self):
        """Called after curses.wrapper returns and terminal is restored."""
        print(f"Session saved. Resume with the same --seed {self.seed}")

    def _leave_curses(self):
        curses.endwin()

    def _resume_curses(self):
        self.stdscr.clear()
        self.stdscr.refresh()

    # ── drawing ──────────────────────────────────────────────────────

    def _safe(self, y, x, text, attr=0):
        h, w = self.stdscr.getmaxyx()
        if 0 <= y < h and 0 <= x < w:
            try:
                self.stdscr.addnstr(y, x, text, w - x, attr)
            except curses.error:
                pass

    def _hline(self, y, left, mid, right, w):
        self._safe(y, 0, left + mid * (w - 2) + right)

    def _row(self, y, text, w, attr=0):
        padded = " " + text[:w - 4]
        self._safe(y, 0, "│" + padded.ljust(w - 2) + "│", attr)

    def _draw(self):
        self.stdscr.clear()
        h, w = self.stdscr.getmaxyx()
        scene = self.scenes[self.current]
        bw = min(w, 80)  # box width
        y = 0

        # ── top border + title ───────────────────────────────────────
        self._hline(y, "┌", "─", "┐", bw); y += 1

        title = "DIRECTOR"
        info = f"Scene {scene.num} / {len(self.scenes)}"
        gap = bw - 4 - len(title) - len(info)
        self._safe(y, 0, "│ " + title + " " * max(1, gap) + info + " │",
                   curses.A_BOLD)
        y += 1

        # ── status line ──────────────────────────────────────────────
        st, sc = self._status_label(scene)
        tag = f" (modified)" if scene.has_draft else ""
        scene_len = scene.length if scene.length is not None else self.length
        dur_str = f"{scene_len / 25.0:.0f}s"
        if scene.length is not None:
            dur_str += " (custom)"
        self._row(y, f"Status: {st}{tag}    Duration: {dur_str}", bw, sc); y += 1

        # ── scene strip ──────────────────────────────────────────────
        self._hline(y, "├", "─", "┤", bw); y += 1
        strip = self._scene_strip(bw - 4)
        self._row(y, strip, bw); y += 1

        # ── visual prompt ────────────────────────────────────────────
        self._hline(y, "├", "─", "┤", bw); y += 1
        self._row(y, "Visual:", bw, curses.A_BOLD); y += 1
        for line in textwrap.wrap(scene.suffix, width=bw - 8)[:5]:
            self._row(y, f"  {line}", bw); y += 1
        if len(textwrap.wrap(scene.suffix, width=bw - 8)) > 5:
            self._row(y, "  ...", bw); y += 1

        # ── voiceover ────────────────────────────────────────────────
        self._row(y, "", bw); y += 1
        self._row(y, "Voiceover:", bw, curses.A_BOLD); y += 1
        vo = scene.voiceover_text or "(none)"
        for line in textwrap.wrap(vo, width=bw - 8)[:3]:
            self._row(y, f"  {line}", bw); y += 1
        if len(textwrap.wrap(vo, width=bw - 8)) > 3:
            self._row(y, "  ...", bw); y += 1

        # ── navigation ───────────────────────────────────────────────
        self._hline(y, "├", "─", "┤", bw); y += 1
        self._row(y, "", bw); y += 1
        self._row(y, "[Space] Play  [p] Play prev+current  [Left/Right/Home/End]",
                  bw); y += 1
        self._row(y, "", bw); y += 1

        # ── actions ──────────────────────────────────────────────────
        half = (bw - 4) // 2
        actions = self._available_actions(scene)
        for left, right in actions:
            combined = left.ljust(half) + right
            self._row(y, combined, bw); y += 1

        # ── status message ───────────────────────────────────────────
        self._row(y, "", bw); y += 1
        if self.status_msg:
            self._row(y, self.status_msg, bw, curses.A_DIM); y += 1

        self._hline(y, "└", "─", "┘", bw)
        self.stdscr.refresh()

    def _status_label(self, scene):
        if scene.status == "approved":
            return "APPROVED", curses.color_pair(C_APPROVED) | curses.A_BOLD
        elif scene.status == "rendered":
            return "RENDERED", curses.color_pair(C_RENDERED) | curses.A_BOLD
        return "PENDING", curses.color_pair(C_PENDING)

    def _scene_strip(self, width):
        """Build a film-strip indicator of scene progress."""
        parts = []
        for i, sc in enumerate(self.scenes):
            if i == self.current:
                if sc.status == "approved":
                    parts.append(f"[{sc.num}]")
                elif sc.status == "rendered":
                    parts.append(f"({sc.num})")
                else:
                    parts.append(f"<{sc.num}>")
            else:
                if sc.status == "approved":
                    parts.append(f" {sc.num} ")
                elif sc.status == "rendered":
                    parts.append(f" {sc.num} ")
                else:
                    parts.append(f" . ")
            # Truncate if too wide
            test = " ".join(parts)
            if len(test) > width - 4:
                parts[-1] = "..."
                break
        return " ".join(parts)

    def _available_actions(self, scene):
        """Return pairs of (left_col, right_col) action labels."""
        rows = []
        is_frontier = (self.current == self.frontier)
        has_video = scene.status in ("rendered", "approved")

        if is_frontier and has_video:
            rows.append(("[a] Approve & render next", "[Enter] Re-render (new seed)"))
            rows.append(("[v] Refine visual", ""))
        elif has_video:
            rows.append(("[Enter] Re-render (new seed)", "[v] Refine visual"))

        vo_label = "[o] Refine voiceover" if self.has_voiceover and has_video else ""
        rows.append((vo_label, "[d] Set duration"))

        if has_video:
            rows.append(("[t] Transform (V2V)", ""))

        cancel_label = "[c] Cancel changes" if scene.has_draft else ""
        if cancel_label:
            rows.append((cancel_label, ""))

        rows.append(("[r] Render movie", "[q] Quit"))
        return rows

    # ── key handling ─────────────────────────────────────────────────

    def _handle_key(self, key):
        scene = self.scenes[self.current]

        if key == ord("\n") or key == curses.KEY_ENTER:
            self._rerender()
        elif key == ord(" "):
            self._play_current()
        elif key == curses.KEY_LEFT or key == ord("h"):
            if self.current > 0:
                self.current -= 1
                self.status_msg = ""
        elif key == curses.KEY_RIGHT or key == ord("l"):
            if self.current < self.frontier:
                self.current += 1
                self.status_msg = ""
        elif key == curses.KEY_HOME:
            self.current = 0
            self.status_msg = ""
        elif key == curses.KEY_END:
            self.current = self.frontier
            self.status_msg = ""
        elif key == ord("a"):
            self._approve()
        elif key == ord("v"):
            self._refine_visual()
        elif key == ord("o"):
            self._refine_voiceover()
        elif key == ord("c"):
            self._cancel_changes()
        elif key == ord("d"):
            self._set_duration()
        elif key == ord("t"):
            self._transform()
        elif key == ord("p"):
            self._play_sequence()
        elif key == ord("r"):
            self._render_movie()
        elif key == ord("q"):
            self.status_msg = "Press Q again to quit"
            self._draw()
            confirm = self.stdscr.getch()
            if confirm == ord("q") or confirm == ord("Q"):
                self.should_quit = True
            else:
                self.status_msg = ""

    # ── playback ─────────────────────────────────────────────────────

    def _play_current(self):
        scene = self.scenes[self.current]
        if not scene.has_video(self.run_dir):
            self.status_msg = "No video to play"
            return
        preview = self._make_preview(scene)
        if not shutil.which("mpv"):
            self.status_msg = "mpv not found — install mpv to play videos"
            return
        self._leave_curses()
        subprocess.run(["mpv", "--really-quiet", preview],
                       check=False)
        self._resume_curses()

    def _play_sequence(self):
        """Play the previous scene and current scene back-to-back."""
        scene = self.scenes[self.current]
        if not scene.has_video(self.run_dir):
            self.status_msg = "No video to play"
            return
        if self.current == 0:
            # Only one scene, just play it
            self._play_current()
            return

        prev = self.scenes[self.current - 1]
        if not prev.has_video(self.run_dir):
            self._play_current()
            return

        # Build previews for both scenes
        prev_preview = self._make_preview(prev)
        curr_preview = self._make_preview(scene)

        # Concat into a temp file
        import tempfile
        seq_path = os.path.join(self.run_dir, "_sequence.mp4")
        list_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False)
        try:
            list_file.write(f"file '{os.path.abspath(prev_preview)}'\n")
            list_file.write(f"file '{os.path.abspath(curr_preview)}'\n")
            list_file.close()
            result = subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                 "-i", list_file.name, "-c", "copy", seq_path],
                capture_output=True,
            )
        finally:
            os.unlink(list_file.name)

        if result.returncode != 0:
            self.status_msg = "Failed to concat sequence"
            return

        if not shutil.which("mpv"):
            self.status_msg = "mpv not found — install mpv to play videos"
            return
        self._leave_curses()
        subprocess.run(["mpv", "--really-quiet", seq_path], check=False)
        self._resume_curses()
        _delete_if_exists(seq_path)

    def _rerender(self):
        """Re-render the current scene with a new random seed (same prompt)."""
        scene = self.scenes[self.current]
        if scene.status == "pending":
            self.status_msg = "Scene not yet rendered"
            return

        scene.save_draft_backup()

        # Invalidate scenes after this one
        if self.current < self.frontier:
            self._invalidate_after(self.current)

        # Back up current files
        for f in [scene.video_path(self.run_dir),
                  scene.frame_path(self.run_dir)]:
            _backup(f)
        _delete_if_exists(scene.preview_path(self.run_dir))

        self._leave_curses()
        self._render_scene_terminal(self.current)
        self.frontier = self.current
        self._save_script()
        self._resume_curses()

    def _set_duration(self):
        """Set custom duration for the current scene."""
        scene = self.scenes[self.current]
        current_len = scene.length if scene.length is not None else self.length
        current_secs = current_len / 25.0

        raw = self._input_text(
            f"Current duration: {current_secs:.0f}s ({current_len} frames)\n"
            f"Default duration: {self.length / 25.0:.0f}s\n\n"
            f"Enter new duration in seconds (or Enter to keep, 0 to reset to default):\n",
        )
        if not raw:
            self.status_msg = "No changes"
            return
        try:
            secs = int(raw)
        except ValueError:
            self.status_msg = f"Invalid number: {raw}"
            return

        if secs == 0:
            scene.length = None
            self.status_msg = f"Scene {scene.num} reset to default ({self.length / 25.0:.0f}s)"
        else:
            scene.length = secs * 25
            self.status_msg = f"Scene {scene.num} set to {secs}s ({scene.length} frames)"
        self._save_script()

    def _transform(self):
        """Transform the current scene using Wan 2.1 VACE video-to-video."""
        scene = self.scenes[self.current]
        if not scene.has_video(self.run_dir):
            self.status_msg = "No video to transform"
            return

        if not os.path.exists(V2V_WORKFLOW):
            self.status_msg = f"V2V workflow not found: {V2V_WORKFLOW}"
            return

        change_request = self._input_text(
            "What do you want to change about this scene?\n"
            "  (e.g. 'change the lighting to red alert with a space battle outside')\n"
        )
        if not change_request:
            self.status_msg = "Transform cancelled"
            return

        # Use LLM to rewrite the change request as a full scene description
        self._leave_curses()
        print(f"\n  Rewriting prompt via LLM...")
        sys.stdout.write("  streaming: ")
        sys.stdout.flush()
        v2v_sys = (
            "You are a visual scene description writer for a video-to-video AI model. "
            "You will be given an original scene description and a change request. "
            "Write a single complete scene description that incorporates the requested "
            "changes while preserving elements not mentioned in the change request. "
            "Be vivid and specific. Write it as a continuous description, not a list. "
            "Respond with a JSON array containing one string: your scene description."
        )
        v2v_user = (
            f"Original scene:\n{scene.suffix}\n\n"
            f"Requested changes:\n{change_request}\n\n"
            f"Respond with a JSON array of one string: the complete modified scene description."
        )
        try:
            result = call_llm(self.llm_url, self.llm_model, v2v_sys, v2v_user,
                              temperature=0.7, api_key=self.llm_api_key)
            prompt = result[0] if isinstance(result, list) and result else change_request
            print(f"  V2V prompt: {prompt[:100]}...")
        except Exception as e:
            print(f"  LLM failed: {e}")
            print(f"  Using change request as-is.")
            prompt = change_request
        self._resume_curses()

        raw_str = self._input_text(
            "Control strength (how much the original video guides the output):\n"
            "  1.0 = very faithful to original (subtle changes)\n"
            "  0.5 = balanced (moderate changes)\n"
            "  0.2 = loose (major restyling, may lose structure)\n",
            prefill="0.5",
        )
        try:
            strength = float(raw_str) if raw_str else 0.5
            strength = max(0.0, min(1.0, strength))
        except ValueError:
            strength = 0.5

        scene.save_draft_backup()

        # Back up current video
        _backup(scene.video_path(self.run_dir))
        _backup(scene.frame_path(self.run_dir))
        _delete_if_exists(scene.preview_path(self.run_dir))

        self._leave_curses()
        self._run_v2v(scene, prompt, strength)
        self._save_script()
        self._resume_curses()

    def _run_v2v(self, scene, prompt, strength=0.5):
        """Run Wan 2.1 VACE V2V workflow on a scene."""
        import copy

        # Use the backed-up original video as input
        input_video = scene.video_path(self.run_dir) + ".bak"
        if not os.path.exists(input_video):
            input_video = scene.video_path(self.run_dir)

        output_video = scene.video_path(self.run_dir)
        ref_image = os.path.join(self.run_dir, f"_v2v_ref_{scene.num:02d}.png")

        # Extract first frame as reference image
        print(f"\n{'='*60}")
        print(f"  V2V Transform — Scene {scene.num}")
        print(f"  Prompt: {prompt[:70]}...")
        print(f"  Input:  {input_video}")
        print(f"{'='*60}")

        extract_first_frame(input_video, ref_image)

        # Get input video resolution
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0:s=x", input_video],
            capture_output=True, text=True,
        )
        if probe.returncode == 0 and "x" in probe.stdout.strip():
            vid_w, vid_h = [int(x) for x in probe.stdout.strip().split("x")]
        else:
            vid_w, vid_h = 720, 720

        # Get input video info for frame count
        vid_dur = get_duration(input_video)
        # Wan VACE runs at 16fps, compute frame count (must be 4n+1)
        if vid_dur:
            raw_frames = int(vid_dur * 16)
            wan_frames = ((raw_frames - 1) // 4) * 4 + 1
            wan_frames = max(wan_frames, 5)
        else:
            wan_frames = 81

        # Upload video and reference image
        print(f"  Uploading video...")
        uploaded_video = upload_file(self.base_url, input_video)
        print(f"  Uploading reference image...")
        uploaded_ref = upload_image(self.base_url, ref_image)

        # Load and patch workflow
        with open(V2V_WORKFLOW) as f:
            wf = json.load(f)

        wf = copy.deepcopy(wf)
        noise_seed = random.randint(0, 2**53)

        # Patch nodes
        wf["145"]["inputs"]["file"] = uploaded_video          # LoadVideo
        wf["134"]["inputs"]["image"] = uploaded_ref           # LoadImage (reference)
        wf["6"]["inputs"]["text"] = prompt                    # positive prompt
        wf["3"]["inputs"]["seed"] = noise_seed                # KSampler seed
        wf["49"]["inputs"]["width"] = vid_w                   # match input resolution
        wf["49"]["inputs"]["height"] = vid_h
        wf["49"]["inputs"]["length"] = wan_frames             # frame count
        wf["49"]["inputs"]["strength"] = strength             # control video influence
        wf["114"]["inputs"]["filename_prefix"] = (            # output
            f"{self.seed}/v2v_{scene.label}")

        print(f"  Resolution: {vid_w}x{vid_h}")
        print(f"  Strength:   {strength} (lower = more prompt influence)")
        print(f"  Frames:     {wan_frames} ({wan_frames/16:.1f}s at 16fps)")
        print(f"  Seed:       {noise_seed}")
        print(f"  Submitting V2V workflow...")

        start = time.time()
        try:
            history = run_workflow(self.base_url, wf, timeout=self.timeout)
            download_output(self.base_url, history, output_video,
                            strip_audio=self.strip_audio)
            extract_last_frame(output_video, scene.frame_path(self.run_dir))
            elapsed = time.time() - start
            actual_dur = get_duration(output_video)
            print(f"  Transformed in {fmt_duration(elapsed)}")
            if actual_dur:
                print(f"  Output duration: {actual_dur:.1f}s")
            scene.status = "rendered"
        except Exception as e:
            print(f"  V2V failed: {e}")
            # Restore backup
            _restore(scene.video_path(self.run_dir))
            _restore(scene.frame_path(self.run_dir))

        # Clean up temp reference
        _delete_if_exists(ref_image)

    def _make_preview(self, scene):
        """Mux voiceover into video for preview, or return plain video."""
        video = scene.video_path(self.run_dir)
        vo_wav = scene.vo_path(self.run_dir)
        preview = scene.preview_path(self.run_dir)

        if not os.path.exists(vo_wav):
            return video

        # Check if preview is up to date
        if os.path.exists(preview):
            ptime = os.path.getmtime(preview)
            if (ptime > os.path.getmtime(video) and
                    ptime > os.path.getmtime(vo_wav)):
                return preview

        vid_dur = get_duration(video)
        if vid_dur is None:
            return video

        padded = os.path.join(self.run_dir, f"_pad_{scene.num:02d}.wav")
        try:
            pad_audio_centered(vo_wav, vid_dur, padded)
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", video, "-i", padded,
                 "-map", "0:v", "-map", "1:a",
                 "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                 "-shortest", preview],
                capture_output=True,
            )
            if os.path.exists(padded):
                os.unlink(padded)
            if result.returncode == 0:
                return preview
        except Exception:
            pass
        return video

    # ── approve ──────────────────────────────────────────────────────

    def _approve(self):
        scene = self.scenes[self.current]
        if scene.status == "pending":
            self.status_msg = "Scene not yet rendered"
            return
        if self.current != self.frontier:
            self.status_msg = "Navigate to latest scene first (End key)"
            return

        scene.status = "approved"
        scene.commit_draft()
        # Delete file backups
        for f in [scene.video_path(self.run_dir),
                  scene.frame_path(self.run_dir),
                  scene.vo_path(self.run_dir)]:
            _delete_bak(f)
        self._save_script()

        next_idx = self.current + 1
        if next_idx < len(self.scenes):
            # Next scene exists in script
            self._leave_curses()
            self._render_scene_terminal(next_idx)
            self.frontier = next_idx
            self.current = next_idx
            self._resume_curses()
        else:
            # Beyond script — ask for a new scene prompt
            new_prompt = self._input_text(
                "Beyond the script. Enter a visual prompt for the next scene,\n"
                "or press Enter to end the movie:\n"
            )
            if new_prompt:
                new_vo = ""
                if self.has_voiceover:
                    new_vo = self._input_text(
                        "Enter voiceover text (or Enter to skip):\n"
                    )
                self.scenes.append(Scene(next_idx, new_prompt, new_vo))
                self._save_script()
                self._leave_curses()
                self._render_scene_terminal(next_idx)
                self.frontier = next_idx
                self.current = next_idx
                self._resume_curses()
            else:
                self.status_msg = "No prompt entered. Press q to quit."

    # ── refine visual ────────────────────────────────────────────────

    def _refine_visual(self):
        scene = self.scenes[self.current]
        if scene.status == "pending":
            self.status_msg = "Scene not yet rendered"
            return

        new_prompt = self._input_text(
            f"Current visual prompt:\n  {scene.suffix}\n\n"
            "Enter new prompt (or Enter to cancel):\n",
            prefill=scene.suffix,
        )
        if not new_prompt or new_prompt == scene.suffix:
            self.status_msg = "No changes"
            return

        scene.save_draft_backup()
        scene.suffix = new_prompt

        # Invalidate scenes after this one
        if self.current < self.frontier:
            self._invalidate_after(self.current)

        # Back up current files, then re-render
        for f in [scene.video_path(self.run_dir),
                  scene.frame_path(self.run_dir)]:
            _backup(f)
        _delete_if_exists(scene.preview_path(self.run_dir))

        self._leave_curses()
        self._render_scene_terminal(self.current)
        self.frontier = self.current
        self._save_script()
        self._resume_curses()

    # ── refine voiceover ─────────────────────────────────────────────

    def _refine_voiceover(self):
        scene = self.scenes[self.current]
        if not self.has_voiceover:
            self.status_msg = "Voiceover disabled"
            return
        if scene.status == "pending":
            self.status_msg = "Scene not yet rendered"
            return

        new_vo = self._input_text(
            f"Current voiceover:\n  {scene.voiceover_text}\n\n"
            "Enter new voiceover (or Enter to cancel):\n",
            prefill=scene.voiceover_text,
        )
        if not new_vo or new_vo == scene.voiceover_text:
            self.status_msg = "No changes"
            return

        scene.save_draft_backup()
        scene.voiceover_text = new_vo

        _backup(scene.vo_path(self.run_dir))
        _delete_if_exists(scene.preview_path(self.run_dir))

        # Re-render voiceover WAV
        if self.tts_dir:
            self._leave_curses()
            vo_path = scene.vo_path(self.run_dir)
            print(f"\nRendering voiceover for scene {scene.num}...")
            try:
                render_segment_tts(
                    self.tts_dir, self.base_url,
                    scene.voiceover_text, self.voice, vo_path,
                    seed=self.tts_seed + scene.index,
                )
                print(f"  Saved: {vo_path}")
            except Exception as e:
                print(f"  Failed: {e}")
            self._resume_curses()

        self._save_script()
        self.status_msg = "Voiceover updated"

    # ── cancel changes ───────────────────────────────────────────────

    def _cancel_changes(self):
        scene = self.scenes[self.current]
        if not scene.has_draft:
            self.status_msg = "No changes to cancel"
            return

        scene.cancel_draft()

        # Restore any backed-up files (visual, frame, voiceover)
        for f in [scene.video_path(self.run_dir),
                  scene.frame_path(self.run_dir)]:
            if os.path.exists(f + ".bak"):
                _delete_if_exists(f)
                _restore(f)

        if os.path.exists(scene.vo_path(self.run_dir) + ".bak"):
            _delete_if_exists(scene.vo_path(self.run_dir))
            _restore(scene.vo_path(self.run_dir))

        _delete_if_exists(scene.preview_path(self.run_dir))
        self._save_script()
        self.status_msg = "Reverted to approved version"

    # ── render movie ─────────────────────────────────────────────────

    def _render_movie(self):
        """Mux all rendered segments into final video and play it."""
        self._save_script()
        self._leave_curses()

        # Clean up preview/backup files before muxing
        for s in self.scenes:
            _delete_if_exists(s.preview_path(self.run_dir))
            for f in [s.video_path(self.run_dir),
                      s.frame_path(self.run_dir),
                      s.vo_path(self.run_dir)]:
                _delete_bak(f)

        print()
        print("=" * 60)
        usable = [s for s in self.scenes if s.has_video(self.run_dir)]
        print(f"  RENDERING MOVIE  ({len(usable)} segments)")
        print("=" * 60)

        try:
            subprocess.run(
                ["python3", "mux.py", "--seed", str(self.seed)],
                check=True,
            )
            dir_name = os.path.basename(self.run_dir)
            final_path = os.path.join(self.run_dir, f"{dir_name}.mp4")
            if os.path.exists(final_path):
                if shutil.which("mpv"):
                    print(f"\nPlaying: {final_path}")
                    subprocess.run(
                        ["mpv", "--really-quiet", final_path],
                        check=False,
                    )
                else:
                    print(f"\nSaved: {final_path} (install mpv to auto-play)")
        except subprocess.CalledProcessError as e:
            print(f"  Mux failed: {e}")

        self._resume_curses()

    # ── rendering ────────────────────────────────────────────────────

    def _render_scene_terminal(self, idx):
        """Render voiceover + video for a scene (runs outside curses)."""
        scene = self.scenes[idx]

        # Voiceover first (faster)
        if self.has_voiceover and scene.voiceover_text and self.tts_dir:
            vo_path = scene.vo_path(self.run_dir)
            if not os.path.exists(vo_path):
                print(f"\n{'='*60}")
                print(f"  Rendering voiceover {scene.num}...")
                print(f"  Text: {scene.voiceover_text[:70]}")
                print(f"{'='*60}")
                try:
                    render_segment_tts(
                        self.tts_dir, self.base_url,
                        scene.voiceover_text, self.voice, vo_path,
                        seed=self.tts_seed + idx,
                    )
                    print(f"  Saved: {vo_path}")
                except Exception as e:
                    print(f"  Voiceover failed: {e} (continuing)")

        # Video
        prompt_text = build_prompt_text(self.base_prompt, scene.suffix, idx)
        is_t2v = idx == 0

        current_image = None
        if not is_t2v and idx > 0:
            current_image = self.scenes[idx - 1].frame_path(self.run_dir)
            if not os.path.exists(current_image):
                print(f"  Error: previous frame missing: {current_image}")
                return

        noise_seed = random.randint(0, 2**53)
        seg_video = scene.video_path(self.run_dir)
        seg_frame = scene.frame_path(self.run_dir)

        scene_length = scene.length if scene.length is not None else self.length
        expected_dur = scene_length / 25.0

        print(f"\n{'='*60}")
        print(f"  Rendering scene {scene.num}")
        if is_t2v:
            print(f"  Mode:     text-to-video")
        print(f"  Prompt:   {prompt_text[:70]}...")
        print(f"  Seed:     {noise_seed}")
        dur_note = "" if scene.length is None else " (custom)"
        print(f"  Duration: {expected_dur:.0f}s ({scene_length} frames){dur_note}")
        print(f"{'='*60}")

        if is_t2v:
            placeholder = _create_placeholder_image(self.run_dir)
            uploaded_name = upload_image(self.base_url, placeholder)
        else:
            uploaded_name = upload_image(self.base_url, current_image)

        wf = patch_workflow(
            self.workflow_template,
            image_name=uploaded_name,
            prompt_text=prompt_text,
            image_node=self.args.image_node,
            image_field=self.args.image_field,
            prompt_node=self.args.prompt_node,
            prompt_field=self.args.prompt_field,
            output_node=self.args.output_node,
            output_field=self.args.output_field,
            output_prefix=f"{self.seed}/{scene.label}",
            seed_node=self.args.seed_node,
            seed_field=self.args.seed_field,
            seed_value=noise_seed,
            negative_prompt_node=self.args.negative_prompt_node,
            negative_prompt_field=self.args.negative_prompt_field,
            negative_prompt_text=self.args.negative_prompt,
            t2v_switch_node=self.args.t2v_switch_node,
            t2v_switch_field=self.args.t2v_switch_field,
            t2v_enabled=is_t2v,
            length_node=self.args.length_node,
            length_field=self.args.length_field,
            length_value=scene_length,
        )

        start = time.time()
        try:
            history = run_workflow(self.base_url, wf, timeout=self.timeout)
            download_output(self.base_url, history, seg_video,
                            strip_audio=self.strip_audio)
            extract_last_frame(seg_video, seg_frame)
            elapsed = time.time() - start
            actual_dur = get_duration(seg_video)
            if actual_dur is not None:
                print(f"  Rendered in {fmt_duration(elapsed)}, "
                      f"clip duration: {actual_dur:.1f}s")
                if abs(actual_dur - expected_dur) > 1.0:
                    print(f"  WARNING: expected {expected_dur:.0f}s "
                          f"but got {actual_dur:.1f}s")
            else:
                print(f"  Rendered in {fmt_duration(elapsed)}")
            scene.status = "rendered"
        except Exception as e:
            print(f"  Render failed: {e}")

    def _invalidate_after(self, idx):
        """Delete rendered files for all scenes after idx."""
        for i in range(idx + 1, len(self.scenes)):
            sc = self.scenes[i]
            for f in [sc.video_path(self.run_dir),
                      sc.frame_path(self.run_dir),
                      sc.vo_path(self.run_dir),
                      sc.preview_path(self.run_dir)]:
                _delete_if_exists(f)
                _delete_bak(f)
            sc.status = "pending"
            sc.has_draft = False

    # ── text input ───────────────────────────────────────────────────

    def _input_text(self, message, prefill=""):
        """Prompt for text input (exits curses temporarily)."""
        self._leave_curses()
        print()
        print(message)

        if prefill:
            def hook():
                readline.insert_text(prefill)
                readline.redisplay()
            readline.set_pre_input_hook(hook)

        try:
            result = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            result = ""
        finally:
            readline.set_pre_input_hook()

        self._resume_curses()
        return result

    # ── persistence ──────────────────────────────────────────────────

    def _session_path(self):
        return os.path.join(self.run_dir, "session.json")

    def _save_session(self):
        """Save full session state so it can be resumed later."""
        session = {
            "current": self.current,
            "frontier": self.frontier,
            "style": self.style_name,
            "default_length": self.length,
            "scenes": [
                {
                    "status": s.status,
                    "suffix": s.suffix,
                    "voiceover_text": s.voiceover_text,
                    "length": s.length,
                    "has_draft": s.has_draft,
                    "_backup_suffix": s._backup_suffix,
                    "_backup_voiceover": s._backup_voiceover,
                }
                for s in self.scenes
            ],
        }
        with open(self._session_path(), "w") as f:
            json.dump(session, f, indent=2)
            f.write("\n")

    def _load_session(self):
        """Restore session state from disk. Returns True if restored."""
        path = self._session_path()
        if not os.path.exists(path):
            return False
        try:
            with open(path) as f:
                session = json.load(f)
        except (json.JSONDecodeError, KeyError):
            return False

        # Restore style and default length from session
        if session.get("style"):
            self.style_name = session["style"]
        if session.get("default_length"):
            self.length = session["default_length"]

        saved_scenes = session.get("scenes", [])

        # Extend self.scenes if the saved session had more (extended scenes)
        for i in range(len(self.scenes), len(saved_scenes)):
            ss = saved_scenes[i]
            self.scenes.append(Scene(i, ss["suffix"], ss.get("voiceover_text", "")))

        # Restore per-scene state
        for i, ss in enumerate(saved_scenes):
            if i >= len(self.scenes):
                break
            s = self.scenes[i]
            s.suffix = ss["suffix"]
            s.voiceover_text = ss.get("voiceover_text", "")
            s.length = ss.get("length")
            s.has_draft = ss.get("has_draft", False)
            s._backup_suffix = ss.get("_backup_suffix")
            s._backup_voiceover = ss.get("_backup_voiceover")
            # Only trust the saved status if the files still exist
            if ss["status"] in ("rendered", "approved") and s.has_video(self.run_dir):
                s.status = ss["status"]
            elif s.has_video(self.run_dir):
                s.status = "rendered"
            else:
                s.status = "pending"

        # Restore position — clamp to valid range
        self.frontier = -1
        for i, s in enumerate(self.scenes):
            if s.status in ("rendered", "approved"):
                self.frontier = i
        self.current = min(session.get("current", 0), max(self.frontier, 0))
        return self.frontier >= 0

    def _save_script(self):
        suffixes = [s.suffix for s in self.scenes]
        with open(self.script_path, "w") as f:
            json.dump(suffixes, f, indent=2)
            f.write("\n")
        voiceover = [s.voiceover_text for s in self.scenes]
        if any(voiceover):
            with open(self.voiceover_json_path, "w") as f:
                json.dump(voiceover, f, indent=2)
                f.write("\n")
        self._save_session()


# ── Transition Director TUI ──────────────────────────────────────────

class TransitionDirectorTUI:
    """Interactive TUI for transition mode: keyframes → transitions → movie."""

    PHASE_KEYFRAMES = "keyframes"
    PHASE_TRANSITIONS = "transitions"

    def __init__(self, *, keyframes, transitions, run_dir, t2i_template,
                 transition_template, audio_template, base_url, base_prompt,
                 negative_prompt, duration_seconds, width, height, frame_rate,
                 strip_audio, voice, tts_dir, tts_seed, seed, timeout,
                 has_voiceover, style_name, llm_url, llm_model, llm_api_key):
        self.keyframes = keyframes
        self.transitions = transitions
        self.run_dir = run_dir
        self.t2i_template = t2i_template
        self.transition_template = transition_template
        self.audio_template = audio_template
        self.base_url = base_url
        self.base_prompt = base_prompt
        self.negative_prompt = negative_prompt
        self.duration_seconds = duration_seconds
        self.width = width
        self.height = height
        self.frame_rate = frame_rate
        self.strip_audio = strip_audio
        self.voice = voice
        self.tts_dir = tts_dir
        self.tts_seed = tts_seed
        self.seed = seed
        self.timeout = timeout
        self.has_voiceover = has_voiceover
        self.style_name = style_name
        self.llm_url = llm_url
        self.llm_model = llm_model
        self.llm_api_key = llm_api_key
        self.current = 0
        self.phase = self.PHASE_KEYFRAMES
        self.stdscr = None
        self.status_msg = ""
        self.should_quit = False
        self.auto_mode = False

    def run(self, auto=False):
        self.auto_mode = auto
        if self._load_session():
            print(f"Resumed session: {self.phase} phase, position {self.current + 1}")
        else:
            if self.auto_mode:
                # Auto mode — render and approve everything
                self._auto_approve_keyframes()
                self._auto_approve_transitions()
                self._render_movie()
                print(f"Session saved. Resume with the same --seed {self.seed}")
                return
            # First run — render keyframe 1
            if not self.keyframes[0].has_image(self.run_dir):
                self._render_keyframe_terminal(0)
            else:
                self.keyframes[0].status = "generated"
            self._save_session()

        if self.auto_mode:
            # Resume auto mode from wherever we left off
            if self.phase == self.PHASE_KEYFRAMES:
                if not all(k.status == "approved" for k in self.keyframes):
                    self._auto_approve_keyframes()
                self._auto_approve_transitions()
            elif not all(t.status == "approved" for t in self.transitions):
                self._auto_approve_transitions()
            self._render_movie()
            print(f"Session saved. Resume with the same --seed {self.seed}")
            return

        curses.wrapper(self._main)
        print(f"Session saved. Resume with the same --seed {self.seed}")

    def _main(self, stdscr):
        self.stdscr = stdscr
        curses.curs_set(0)
        curses.use_default_colors()
        if curses.has_colors():
            curses.init_pair(C_APPROVED, curses.COLOR_GREEN, -1)
            curses.init_pair(C_RENDERED, curses.COLOR_CYAN, -1)
            curses.init_pair(C_PENDING, curses.COLOR_YELLOW, -1)
            curses.init_pair(C_DRAFT, curses.COLOR_MAGENTA, -1)
            curses.init_pair(C_DIM, curses.COLOR_WHITE, -1)
            curses.init_pair(C_KEY, curses.COLOR_CYAN, -1)

        while not self.should_quit:
            self._draw()
            key = stdscr.getch()
            self._handle_key(key)
        self._save_session()

    def _leave_curses(self):
        if self.stdscr is not None:
            curses.endwin()

    def _resume_curses(self):
        if self.stdscr is not None:
            self.stdscr.clear()
            self.stdscr.refresh()

    def _safe(self, y, x, text, attr=0):
        h, w = self.stdscr.getmaxyx()
        if 0 <= y < h and 0 <= x < w:
            try:
                self.stdscr.addnstr(y, x, text, w - x, attr)
            except curses.error:
                pass

    def _hline(self, y, left, mid, right, w):
        self._safe(y, 0, left + mid * (w - 2) + right)

    def _row(self, y, text, w, attr=0):
        padded = " " + text[:w - 4]
        self._safe(y, 0, "│" + padded.ljust(w - 2) + "│", attr)

    def _input_text(self, message, prefill=""):
        self._leave_curses()
        print()
        print(message)
        if prefill:
            def hook():
                readline.insert_text(prefill)
                readline.redisplay()
            readline.set_pre_input_hook(hook)
        try:
            result = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            result = ""
        finally:
            readline.set_pre_input_hook()
        self._resume_curses()
        return result

    # ── drawing ──────────────────────────────────────────────────────

    def _draw(self):
        self.stdscr.clear()
        h, w = self.stdscr.getmaxyx()
        bw = min(w, 80)
        y = 0

        self._hline(y, "┌", "─", "┐", bw); y += 1

        if self.phase == self.PHASE_KEYFRAMES:
            self._draw_keyframe_phase(y, bw)
        else:
            self._draw_transition_phase(y, bw)

    def _draw_keyframe_phase(self, y, bw):
        kf = self.keyframes[self.current]

        title = "TRANSITION DIRECTOR — Keyframes"
        info = f"Keyframe {kf.num} / {len(self.keyframes)}"
        gap = bw - 4 - len(title) - len(info)
        self._safe(y, 0, "│ " + title + " " * max(1, gap) + info + " │",
                   curses.A_BOLD)
        y += 1

        # Status
        st, sc = self._kf_status_label(kf)
        self._row(y, f"Status: {st}", bw, sc); y += 1

        # Strip
        self._hline(y, "├", "─", "┤", bw); y += 1
        strip = self._kf_strip(bw - 4)
        self._row(y, strip, bw); y += 1

        # Description
        self._hline(y, "├", "─", "┤", bw); y += 1
        self._row(y, "Description:", bw, curses.A_BOLD); y += 1
        for line in textwrap.wrap(kf.description, width=bw - 8)[:5]:
            self._row(y, f"  {line}", bw); y += 1

        # Actions
        self._hline(y, "├", "─", "┤", bw); y += 1
        self._row(y, "", bw); y += 1
        self._row(y, "[Space] View keyframe  [Left/Right] Navigate", bw); y += 1
        self._row(y, "", bw); y += 1

        has_img = kf.has_image(self.run_dir)
        if has_img and kf.status == "generated":
            self._row(y, "[a] Approve    [Enter] Regenerate (new seed)", bw); y += 1
        elif has_img and kf.status == "approved":
            self._row(y, "[Enter] Regenerate    (already approved)", bw); y += 1
        else:
            self._row(y, "[Enter] Generate keyframe image", bw); y += 1

        self._row(y, "[v] Edit description   [A] Auto-approve all", bw); y += 1
        self._row(y, "[r] Render movie       [q] Quit", bw); y += 1

        all_approved = all(k.status == "approved" for k in self.keyframes)
        if all_approved:
            self._row(y, "", bw); y += 1
            self._row(y, "All keyframes approved! Press [g] to enter transition phase",
                      bw, curses.color_pair(C_APPROVED) | curses.A_BOLD); y += 1

        self._row(y, "", bw); y += 1
        if self.status_msg:
            self._row(y, self.status_msg, bw, curses.A_DIM); y += 1

        self._hline(y, "└", "─", "┘", bw)
        self.stdscr.refresh()

    def _draw_transition_phase(self, y, bw):
        tr = self.transitions[self.current]
        kf_from = self.keyframes[tr.index]
        kf_to = self.keyframes[tr.index + 1]

        title = "TRANSITION DIRECTOR — Transitions"
        info = f"Transition {tr.num} / {len(self.transitions)}"
        gap = bw - 4 - len(title) - len(info)
        self._safe(y, 0, "│ " + title + " " * max(1, gap) + info + " │",
                   curses.A_BOLD)
        y += 1

        st, sc = self._tr_status_label(tr)
        dur_str = f"{self.duration_seconds}s"
        self._row(y, f"Status: {st}    Duration: {dur_str}", bw, sc); y += 1

        # Strip
        self._hline(y, "├", "─", "┤", bw); y += 1
        strip = self._tr_strip(bw - 4)
        self._row(y, strip, bw); y += 1

        # From/To keyframes
        self._hline(y, "├", "─", "┤", bw); y += 1
        self._row(y, f"From keyframe {kf_from.num}:", bw, curses.A_BOLD); y += 1
        for line in textwrap.wrap(kf_from.description, width=bw - 8)[:2]:
            self._row(y, f"  {line}", bw); y += 1

        self._row(y, f"To keyframe {kf_to.num}:", bw, curses.A_BOLD); y += 1
        for line in textwrap.wrap(kf_to.description, width=bw - 8)[:2]:
            self._row(y, f"  {line}", bw); y += 1

        # Transition prompt
        self._row(y, "", bw); y += 1
        self._row(y, "Transition:", bw, curses.A_BOLD); y += 1
        for line in textwrap.wrap(tr.description, width=bw - 8)[:3]:
            self._row(y, f"  {line}", bw); y += 1

        # Voiceover
        if self.has_voiceover:
            self._row(y, "", bw); y += 1
            self._row(y, "Voiceover:", bw, curses.A_BOLD); y += 1
            vo = tr.voiceover_text or "(none)"
            for line in textwrap.wrap(vo, width=bw - 8)[:2]:
                self._row(y, f"  {line}", bw); y += 1

        # Actions
        self._hline(y, "├", "─", "┤", bw); y += 1
        self._row(y, "", bw); y += 1
        self._row(y, "[Space] Play  [Left/Right] Navigate", bw); y += 1
        self._row(y, "", bw); y += 1

        has_vid = tr.has_video(self.run_dir)
        if has_vid:
            self._row(y, "[a] Approve    [Enter] Regenerate (new seed)", bw); y += 1
            self._row(y, "[e] Edit transition prompt    [o] Edit voiceover",
                      bw); y += 1
        else:
            self._row(y, "[Enter] Render transition", bw); y += 1
            self._row(y, "[e] Edit transition prompt", bw); y += 1

        self._row(y, "[A] Auto-approve all   [b] Back to keyframes",
                  bw); y += 1
        self._row(y, "[r] Render movie       [s] Soundtrack", bw); y += 1
        self._row(y, "[q] Quit", bw); y += 1

        self._row(y, "", bw); y += 1
        if self.status_msg:
            self._row(y, self.status_msg, bw, curses.A_DIM); y += 1

        self._hline(y, "└", "─", "┘", bw)
        self.stdscr.refresh()

    def _kf_status_label(self, kf):
        if kf.status == "approved":
            return "APPROVED", curses.color_pair(C_APPROVED) | curses.A_BOLD
        elif kf.status == "generated":
            return "GENERATED", curses.color_pair(C_RENDERED) | curses.A_BOLD
        return "PENDING", curses.color_pair(C_PENDING)

    def _tr_status_label(self, tr):
        if tr.status == "approved":
            return "APPROVED", curses.color_pair(C_APPROVED) | curses.A_BOLD
        elif tr.status == "rendered":
            return "RENDERED", curses.color_pair(C_RENDERED) | curses.A_BOLD
        return "PENDING", curses.color_pair(C_PENDING)

    def _kf_strip(self, width):
        parts = []
        for i, kf in enumerate(self.keyframes):
            if i == self.current:
                if kf.status == "approved":
                    parts.append(f"[{kf.num}]")
                elif kf.status == "generated":
                    parts.append(f"({kf.num})")
                else:
                    parts.append(f"<{kf.num}>")
            else:
                if kf.status == "approved":
                    parts.append(f" {kf.num} ")
                elif kf.status == "generated":
                    parts.append(f" {kf.num} ")
                else:
                    parts.append(f" . ")
            test = " ".join(parts)
            if len(test) > width - 4:
                parts[-1] = "..."
                break
        return " ".join(parts)

    def _tr_strip(self, width):
        parts = []
        for i, tr in enumerate(self.transitions):
            if i == self.current:
                if tr.status == "approved":
                    parts.append(f"[{tr.num}]")
                elif tr.status == "rendered":
                    parts.append(f"({tr.num})")
                else:
                    parts.append(f"<{tr.num}>")
            else:
                if tr.status == "approved":
                    parts.append(f" {tr.num} ")
                elif tr.status == "rendered":
                    parts.append(f" {tr.num} ")
                else:
                    parts.append(f" . ")
            test = " ".join(parts)
            if len(test) > width - 4:
                parts[-1] = "..."
                break
        return " ".join(parts)

    # ── key handling ─────────────────────────────────────────────────

    def _handle_key(self, key):
        if self.phase == self.PHASE_KEYFRAMES:
            self._handle_key_keyframes(key)
        else:
            self._handle_key_transitions(key)

    def _handle_key_keyframes(self, key):
        if key == ord("\n") or key == curses.KEY_ENTER:
            self._generate_keyframe()
        elif key == ord(" "):
            self._view_keyframe()
        elif key == curses.KEY_LEFT or key == ord("h"):
            if self.current > 0:
                self.current -= 1
                self.status_msg = ""
        elif key == curses.KEY_RIGHT or key == ord("l"):
            max_nav = len(self.keyframes) - 1
            # Allow navigating to any keyframe that's generated or earlier
            for i, kf in enumerate(self.keyframes):
                if kf.status == "pending" and i > 0:
                    max_nav = i
                    break
            if self.current < max_nav:
                self.current += 1
                self.status_msg = ""
        elif key == curses.KEY_HOME:
            self.current = 0
            self.status_msg = ""
        elif key == curses.KEY_END:
            # Go to last generated keyframe
            last = 0
            for i, kf in enumerate(self.keyframes):
                if kf.status != "pending":
                    last = i
            self.current = last
            self.status_msg = ""
        elif key == ord("a"):
            self._approve_keyframe()
        elif key == ord("v"):
            self._edit_keyframe_description()
        elif key == ord("A"):
            self._auto_approve_keyframes()
        elif key == ord("g"):
            all_approved = all(k.status == "approved" for k in self.keyframes)
            if all_approved:
                self.phase = self.PHASE_TRANSITIONS
                self.current = 0
                self.status_msg = "Entered transition phase"
            else:
                self.status_msg = "Approve all keyframes first"
        elif key == ord("r"):
            self._render_movie()
        elif key == ord("q"):
            self._quit_confirm()

    def _handle_key_transitions(self, key):
        if key == ord("\n") or key == curses.KEY_ENTER:
            self._render_transition()
        elif key == ord(" "):
            self._play_transition()
        elif key == curses.KEY_LEFT or key == ord("h"):
            if self.current > 0:
                self.current -= 1
                self.status_msg = ""
        elif key == curses.KEY_RIGHT or key == ord("l"):
            if self.current < len(self.transitions) - 1:
                self.current += 1
                self.status_msg = ""
        elif key == curses.KEY_HOME:
            self.current = 0
            self.status_msg = ""
        elif key == curses.KEY_END:
            self.current = len(self.transitions) - 1
            self.status_msg = ""
        elif key == ord("a"):
            self._approve_transition()
        elif key == ord("A"):
            self._auto_approve_transitions()
        elif key == ord("e"):
            self._edit_transition_prompt()
        elif key == ord("o"):
            self._edit_transition_voiceover()
        elif key == ord("b"):
            self.phase = self.PHASE_KEYFRAMES
            self.current = 0
            self.status_msg = "Back to keyframes"
        elif key == ord("r"):
            self._render_movie()
        elif key == ord("s"):
            self._soundtrack_director()
        elif key == ord("q"):
            self._quit_confirm()

    def _quit_confirm(self):
        self.status_msg = "Press Q again to quit"
        self._draw()
        confirm = self.stdscr.getch()
        if confirm == ord("q") or confirm == ord("Q"):
            self.should_quit = True
        else:
            self.status_msg = ""

    # ── keyframe actions ─────────────────────────────────────────────

    def _view_keyframe(self):
        kf = self.keyframes[self.current]
        if not kf.has_image(self.run_dir):
            self.status_msg = "No image to view"
            return
        if not shutil.which("mpv"):
            self.status_msg = "mpv not found"
            return
        self._leave_curses()
        subprocess.run(["mpv", "--really-quiet", kf.image_path(self.run_dir)],
                       check=False)
        self._resume_curses()

    def _generate_keyframe(self):
        kf = self.keyframes[self.current]
        self._leave_curses()
        self._render_keyframe_terminal(self.current)
        self._save_session()
        self._resume_curses()

    def _render_keyframe_terminal(self, idx):
        kf = self.keyframes[idx]
        prompt = kf.description
        if self.base_prompt:
            prompt = self.base_prompt + " " + prompt

        noise_seed = random.randint(0, 2**53)
        output_png = kf.image_path(self.run_dir)

        print(f"\n{'='*60}")
        print(f"  Generating keyframe {kf.num}")
        print(f"  Prompt: {prompt[:70]}...")
        print(f"  Seed:   {noise_seed}")
        print(f"{'='*60}")

        wf = patch_t2i_workflow(
            self.t2i_template,
            prompt_text=prompt,
            negative_prompt_text=self.negative_prompt,
            seed_value=noise_seed,
            output_prefix=f"{self.seed}/keyframe_{kf.num:02d}",
        )

        start = time.time()
        try:
            history = run_workflow(self.base_url, wf, timeout=self.timeout)
            download_output(self.base_url, history, output_png,
                            output_type="images")
            elapsed = time.time() - start
            print(f"  Generated in {fmt_duration(elapsed)}")
            kf.status = "generated"
        except Exception as e:
            print(f"  Generation failed: {e}")

    def _approve_keyframe(self):
        kf = self.keyframes[self.current]
        if kf.status == "pending":
            self.status_msg = "Keyframe not yet generated"
            return
        kf.status = "approved"
        self._save_session()

        # Auto-advance to next ungenerated keyframe
        next_idx = None
        for i in range(len(self.keyframes)):
            if self.keyframes[i].status == "pending":
                next_idx = i
                break

        if next_idx is not None:
            self._leave_curses()
            self._render_keyframe_terminal(next_idx)
            self.current = next_idx
            self._save_session()
            self._resume_curses()
        else:
            all_approved = all(k.status == "approved" for k in self.keyframes)
            if all_approved:
                self.status_msg = "All keyframes approved! Press [g] for transitions"
            else:
                # Find next non-approved
                for i, k in enumerate(self.keyframes):
                    if k.status != "approved":
                        self.current = i
                        break
                self.status_msg = f"Keyframe {kf.num} approved"

    def _edit_keyframe_description(self):
        kf = self.keyframes[self.current]
        new_desc = self._input_text(
            f"Current description:\n  {kf.description}\n\n"
            "Enter new description (or Enter to cancel):\n",
            prefill=kf.description,
        )
        if not new_desc or new_desc == kf.description:
            self.status_msg = "No changes"
            return
        kf.description = new_desc
        # Re-generate with new description
        self._leave_curses()
        self._render_keyframe_terminal(self.current)
        self._save_session()
        self._resume_curses()

    # ── auto-approve ─────────────────────────────────────────────────

    def _auto_approve_keyframes(self):
        """Generate and approve all remaining keyframes without interaction."""
        self._leave_curses()
        print(f"\n{'='*60}")
        print(f"  AUTO-APPROVE: generating all remaining keyframes")
        print(f"{'='*60}")

        for i, kf in enumerate(self.keyframes):
            if kf.status == "approved":
                continue
            if not kf.has_image(self.run_dir):
                self._render_keyframe_terminal(i)
            if kf.has_image(self.run_dir):
                kf.status = "approved"
                print(f"  Keyframe {kf.num} approved")
            self.current = i
            self._save_session()

        print(f"\n  All keyframes approved. Entering transition phase.")
        self.phase = self.PHASE_TRANSITIONS
        self.current = 0
        self._save_session()
        self._resume_curses()

    def _auto_approve_transitions(self):
        """Render and approve all remaining transitions without interaction."""
        self._leave_curses()
        print(f"\n{'='*60}")
        print(f"  AUTO-APPROVE: rendering all remaining transitions")
        print(f"{'='*60}")

        for i, tr in enumerate(self.transitions):
            if tr.status == "approved":
                continue
            if not tr.has_video(self.run_dir):
                self._render_transition_terminal(i)
            if tr.has_video(self.run_dir):
                tr.status = "approved"
                print(f"  Transition {tr.num} approved")
            self.current = i
            self._save_session()

        print(f"\n  All transitions approved. Press [r] to render movie.")
        self._resume_curses()
        self.status_msg = "All transitions approved! Press [r] to render movie"

    # ── transition actions ───────────────────────────────────────────

    def _render_transition(self):
        tr = self.transitions[self.current]
        self._leave_curses()
        self._render_transition_terminal(self.current)
        self._save_session()
        self._resume_curses()

    def _render_transition_terminal(self, idx):
        tr = self.transitions[idx]
        kf_from = self.keyframes[idx]
        kf_to = self.keyframes[idx + 1]

        first_img = kf_from.image_path(self.run_dir)
        last_img = kf_to.image_path(self.run_dir)

        if not os.path.exists(first_img):
            print(f"  Error: keyframe {kf_from.num} image missing")
            return
        if not os.path.exists(last_img):
            print(f"  Error: keyframe {kf_to.num} image missing")
            return

        # Voiceover first
        if self.has_voiceover and tr.voiceover_text and self.tts_dir:
            vo_path = tr.vo_path(self.run_dir)
            if not os.path.exists(vo_path):
                print(f"\n{'='*60}")
                print(f"  Rendering voiceover {tr.num}...")
                print(f"  Text: {tr.voiceover_text[:70]}")
                print(f"{'='*60}")
                try:
                    render_segment_tts(
                        self.tts_dir, self.base_url,
                        tr.voiceover_text, self.voice, vo_path,
                        seed=self.tts_seed + idx,
                    )
                    print(f"  Saved: {vo_path}")
                except Exception as e:
                    print(f"  Voiceover failed: {e} (continuing)")

        noise_seed = random.randint(0, 2**53)
        output_video = tr.video_path(self.run_dir)

        print(f"\n{'='*60}")
        print(f"  Rendering transition {tr.num}")
        print(f"  From:     keyframe {kf_from.num}")
        print(f"  To:       keyframe {kf_to.num}")
        print(f"  Prompt:   {tr.description[:70]}...")
        print(f"  Seed:     {noise_seed}")
        total_frames = self.duration_seconds * self.frame_rate + 1
        print(f"  Duration: {self.duration_seconds}s "
              f"({total_frames} frames)")
        print(f"{'='*60}")

        uploaded_first = upload_image(self.base_url, first_img)
        uploaded_last = upload_image(self.base_url, last_img)

        wf = patch_transition_workflow(
            self.transition_template,
            first_image_name=uploaded_first,
            last_image_name=uploaded_last,
            prompt_text=tr.description,
            negative_prompt_text=self.negative_prompt,
            seed_value=noise_seed,
            width=self.width,
            height=self.height,
            frame_rate=self.frame_rate,
            duration_seconds=self.duration_seconds,
            output_prefix=f"{self.seed}/transition_{tr.num:02d}",
        )

        start = time.time()
        try:
            history = run_workflow(self.base_url, wf, timeout=self.timeout)
            download_output(self.base_url, history, output_video,
                            strip_audio=self.strip_audio)
            elapsed = time.time() - start
            actual_dur = get_duration(output_video)
            if actual_dur is not None:
                print(f"  Rendered in {fmt_duration(elapsed)}, "
                      f"clip duration: {actual_dur:.1f}s")
            else:
                print(f"  Rendered in {fmt_duration(elapsed)}")
            tr.status = "rendered"
        except Exception as e:
            print(f"  Render failed: {e}")

    def _play_transition(self):
        tr = self.transitions[self.current]
        if not tr.has_video(self.run_dir):
            self.status_msg = "No video to play"
            return
        if not shutil.which("mpv"):
            self.status_msg = "mpv not found"
            return
        preview = self._make_transition_preview(tr)
        self._leave_curses()
        subprocess.run(["mpv", "--really-quiet", preview], check=False)
        self._resume_curses()

    def _make_transition_preview(self, tr):
        """Mux voiceover into transition video for preview, or return plain video."""
        video = tr.video_path(self.run_dir)
        vo_wav = tr.vo_path(self.run_dir)
        preview = os.path.join(self.run_dir, f"preview_{tr.num:02d}.mp4")

        if not os.path.exists(vo_wav):
            return video

        # Check if preview is up to date
        if os.path.exists(preview):
            ptime = os.path.getmtime(preview)
            if (ptime > os.path.getmtime(video) and
                    ptime > os.path.getmtime(vo_wav)):
                return preview

        vid_dur = get_duration(video)
        if vid_dur is None:
            return video

        padded = os.path.join(self.run_dir, f"_pad_{tr.num:02d}.wav")
        try:
            pad_audio_centered(vo_wav, vid_dur, padded)
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", video, "-i", padded,
                 "-map", "0:v", "-map", "1:a",
                 "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                 "-shortest", preview],
                capture_output=True,
            )
            if os.path.exists(padded):
                os.unlink(padded)
            if result.returncode == 0:
                return preview
        except Exception:
            pass
        return video

    def _approve_transition(self):
        tr = self.transitions[self.current]
        if tr.status == "pending":
            self.status_msg = "Transition not yet rendered"
            return
        tr.status = "approved"
        self._save_session()

        # Auto-advance and render next transition
        next_idx = self.current + 1
        if next_idx < len(self.transitions):
            tr_next = self.transitions[next_idx]
            if tr_next.status == "pending":
                self._leave_curses()
                self._render_transition_terminal(next_idx)
                self.current = next_idx
                self._save_session()
                self._resume_curses()
            else:
                self.current = next_idx
                self.status_msg = ""
        else:
            self.status_msg = "All transitions done! Press [r] to render movie"

    def _edit_transition_prompt(self):
        tr = self.transitions[self.current]
        new_desc = self._input_text(
            f"Current transition prompt:\n  {tr.description}\n\n"
            "Enter new prompt (or Enter to cancel):\n",
            prefill=tr.description,
        )
        if not new_desc or new_desc == tr.description:
            self.status_msg = "No changes"
            return
        tr.description = new_desc
        self._save_session()
        self.status_msg = "Prompt updated. Press Enter to re-render."

    def _edit_transition_voiceover(self):
        if not self.has_voiceover:
            self.status_msg = "Voiceover disabled"
            return
        tr = self.transitions[self.current]
        new_vo = self._input_text(
            f"Current voiceover:\n  {tr.voiceover_text}\n\n"
            "Enter new voiceover (or Enter to cancel):\n",
            prefill=tr.voiceover_text,
        )
        if not new_vo or new_vo == tr.voiceover_text:
            self.status_msg = "No changes"
            return
        tr.voiceover_text = new_vo
        # Re-render voiceover WAV
        if self.tts_dir:
            vo_path = tr.vo_path(self.run_dir)
            _delete_if_exists(vo_path)
            self._leave_curses()
            print(f"\nRendering voiceover for transition {tr.num}...")
            try:
                render_segment_tts(
                    self.tts_dir, self.base_url,
                    tr.voiceover_text, self.voice, vo_path,
                    seed=self.tts_seed + tr.index,
                )
                print(f"  Saved: {vo_path}")
            except Exception as e:
                print(f"  Failed: {e}")
            self._resume_curses()
        self._save_session()
        self.status_msg = "Voiceover updated"

    # ── soundtrack director ─────────────────────────────────────────

    def _soundtrack_director(self):
        """Interactive soundtrack director: divide video into sections, prompt each, render audio."""
        # Check if final movie exists
        dir_name = os.path.basename(self.run_dir)
        final_path = os.path.join(self.run_dir, f"{dir_name}.mp4")
        if not os.path.exists(final_path):
            self.status_msg = "Render movie first with [r]"
            return

        total_dur = get_duration(final_path)
        if total_dur is None:
            self.status_msg = "Could not get movie duration"
            return

        self._leave_curses()
        print(f"\n{'='*60}")
        print(f"  SOUNDTRACK DIRECTOR")
        print(f"  Movie: {final_path}")
        print(f"  Duration: {total_dur:.1f}s")
        print(f"{'='*60}")

        # Ask how many sections
        raw = input(f"\nHow many soundtrack sections? [1]: ").strip()
        try:
            n_sections = int(raw) if raw else 1
            n_sections = max(1, n_sections)
        except ValueError:
            n_sections = 1

        section_dur = total_dur / n_sections
        print(f"\n  {n_sections} sections, ~{section_dur:.1f}s each")

        # Collect prompts for each section
        sections = []
        for i in range(n_sections):
            start = section_dur * i
            end = section_dur * (i + 1)
            print(f"\n  Section {i+1}/{n_sections} ({start:.0f}s - {end:.0f}s)")
            print(f"  Enter music description (paste text, Ctrl-D to finish):")
            lines = []
            try:
                first = input("  > ")
                lines.append(first)
                while True:
                    lines.append(input())
            except EOFError:
                pass
            prompt = " ".join("\n".join(lines).split()).strip()
            if not prompt:
                prompt = "cinematic orchestral soundtrack"
            sections.append({
                "prompt": prompt,
                "duration": int(round(section_dur)),
                "start": start,
            })
            print(f"  Prompt: {prompt[:80]}...")

        # Ask for musical parameters
        print()
        bpm_raw = input("BPM [120]: ").strip()
        bpm = int(bpm_raw) if bpm_raw else 120

        keyscale_raw = input("Key/scale [C minor]: ").strip()
        keyscale = keyscale_raw if keyscale_raw else "C minor"

        # Render each section
        print(f"\n{'='*60}")
        print(f"  Rendering {n_sections} soundtrack sections...")
        print(f"{'='*60}")

        soundtrack_files = []
        for i, sec in enumerate(sections):
            output_mp3 = os.path.join(self.run_dir, f"soundtrack_{i+1:02d}.mp3")

            # Skip if already exists
            if os.path.exists(output_mp3):
                print(f"\n  Section {i+1} exists: {output_mp3}")
                soundtrack_files.append(output_mp3)
                continue

            noise_seed = random.randint(0, 2**53)
            print(f"\n  Section {i+1}/{n_sections}")
            print(f"  Duration: {sec['duration']}s")
            print(f"  Prompt:   {sec['prompt'][:70]}...")
            print(f"  BPM:      {bpm}")
            print(f"  Key:      {keyscale}")
            print(f"  Seed:     {noise_seed}")

            wf = patch_audio_workflow(
                self.audio_template,
                prompt_text=sec["prompt"],
                seed_value=noise_seed,
                duration_seconds=sec["duration"],
                bpm=bpm,
                keyscale=keyscale,
                output_prefix=f"{self.seed}/soundtrack_{i+1:02d}",
            )

            start = time.time()
            try:
                history = run_workflow(self.base_url, wf, timeout=self.timeout)
                download_output(self.base_url, history, output_mp3,
                                output_type="audio")
                elapsed = time.time() - start
                print(f"  Rendered in {fmt_duration(elapsed)}")
                soundtrack_files.append(output_mp3)
            except Exception as e:
                print(f"  Render failed: {e}")

        if not soundtrack_files:
            print("\n  No soundtrack files rendered.")
            self._resume_curses()
            return

        # Concatenate soundtrack sections
        print(f"\n{'='*60}")
        print(f"  Muxing soundtrack into movie...")
        print(f"{'='*60}")

        import tempfile
        tmpdir = tempfile.mkdtemp(prefix="soundtrack-")
        try:
            # Concat all soundtrack sections into one file
            if len(soundtrack_files) == 1:
                full_soundtrack = soundtrack_files[0]
            else:
                slist = os.path.join(tmpdir, "soundtrack.txt")
                with open(slist, "w") as f:
                    for sf in soundtrack_files:
                        f.write(f"file '{os.path.abspath(sf)}'\n")
                full_soundtrack = os.path.join(tmpdir, "soundtrack_full.mp3")
                subprocess.run(
                    ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                     "-i", slist, "-c", "copy", full_soundtrack],
                    capture_output=True, check=True,
                )

            # Mux soundtrack into the video
            scored_path = os.path.join(self.run_dir, f"{dir_name}_scored.mp4")

            # Check if video already has audio
            probe = subprocess.run(
                ["ffprobe", "-v", "quiet", "-select_streams", "a",
                 "-show_entries", "stream=index", "-of", "csv=p=0",
                 final_path],
                capture_output=True, text=True,
            )
            has_audio = bool(probe.stdout.strip())

            if has_audio:
                # Mix existing audio with soundtrack
                result = subprocess.run(
                    ["ffmpeg", "-y", "-i", final_path, "-i", full_soundtrack,
                     "-filter_complex",
                     "[0:a]volume=1.0[orig];"
                     "[1:a]volume=0.5[music];"
                     "[orig][music]amix=inputs=2:duration=first[aout]",
                     "-map", "0:v", "-map", "[aout]",
                     "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                     scored_path],
                    capture_output=True,
                )
            else:
                # Just add soundtrack
                result = subprocess.run(
                    ["ffmpeg", "-y", "-i", final_path, "-i", full_soundtrack,
                     "-map", "0:v", "-map", "1:a",
                     "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                     "-shortest", scored_path],
                    capture_output=True,
                )

            if result.returncode != 0:
                print(f"  Mux failed: {result.stderr.decode(errors='replace')[:200]}")
            elif os.path.exists(scored_path):
                print(f"\n  Saved: {scored_path}")
                if shutil.which("mpv"):
                    print(f"  Playing...")
                    subprocess.run(["mpv", "--really-quiet", scored_path],
                                   check=False)
        finally:
            import shutil as shutil_mod
            shutil_mod.rmtree(tmpdir, ignore_errors=True)

        self._resume_curses()

    # ── render movie ─────────────────────────────────────────────────

    def _render_movie(self):
        self._save_session()
        self._leave_curses()
        print()
        print("=" * 60)
        usable = [tr for tr in self.transitions if tr.has_video(self.run_dir)]
        print(f"  RENDERING MOVIE  ({len(usable)} transitions)")
        print("=" * 60)

        try:
            cmd = ["python3", "mux.py", "--seed", str(self.seed),
                   "--pattern", "transition"]
            subprocess.run(cmd, check=True)
            dir_name = os.path.basename(self.run_dir)
            final_path = os.path.join(self.run_dir, f"{dir_name}.mp4")
            if os.path.exists(final_path):
                if shutil.which("mpv"):
                    print(f"\nPlaying: {final_path}")
                    subprocess.run(["mpv", "--really-quiet", final_path],
                                   check=False)
                else:
                    print(f"\nSaved: {final_path} (install mpv to auto-play)")
        except subprocess.CalledProcessError as e:
            print(f"  Mux failed: {e}")

        self._resume_curses()

    # ── persistence ──────────────────────────────────────────────────

    def _session_path(self):
        return os.path.join(self.run_dir, "session.json")

    def _save_session(self):
        session = {
            "mode": "transition",
            "phase": self.phase,
            "current": self.current,
            "style": self.style_name,
            "duration_seconds": self.duration_seconds,
            "width": self.width,
            "height": self.height,
            "frame_rate": self.frame_rate,
            "keyframes": [
                {"description": kf.description, "status": kf.status}
                for kf in self.keyframes
            ],
            "transitions": [
                {
                    "description": tr.description,
                    "voiceover_text": tr.voiceover_text,
                    "status": tr.status,
                }
                for tr in self.transitions
            ],
        }
        with open(self._session_path(), "w") as f:
            json.dump(session, f, indent=2)
            f.write("\n")

    def _load_session(self):
        path = self._session_path()
        if not os.path.exists(path):
            return False
        try:
            with open(path) as f:
                session = json.load(f)
        except (json.JSONDecodeError, KeyError):
            return False

        if session.get("mode") != "transition":
            return False

        self.phase = session.get("phase", self.PHASE_KEYFRAMES)
        self.current = session.get("current", 0)
        if session.get("duration_seconds"):
            self.duration_seconds = session["duration_seconds"]
        if session.get("width"):
            self.width = session["width"]
        if session.get("height"):
            self.height = session["height"]
        if session.get("frame_rate"):
            self.frame_rate = session["frame_rate"]

        saved_kf = session.get("keyframes", [])
        for i, skf in enumerate(saved_kf):
            if i >= len(self.keyframes):
                break
            kf = self.keyframes[i]
            kf.description = skf["description"]
            if skf["status"] in ("generated", "approved") and kf.has_image(self.run_dir):
                kf.status = skf["status"]
            elif kf.has_image(self.run_dir):
                kf.status = "generated"
            else:
                kf.status = "pending"

        saved_tr = session.get("transitions", [])
        for i, str_ in enumerate(saved_tr):
            if i >= len(self.transitions):
                break
            tr = self.transitions[i]
            tr.description = str_["description"]
            tr.voiceover_text = str_.get("voiceover_text", "")
            if str_["status"] in ("rendered", "approved") and tr.has_video(self.run_dir):
                tr.status = str_["status"]
            elif tr.has_video(self.run_dir):
                tr.status = "rendered"
            else:
                tr.status = "pending"

        # Clamp current position
        if self.phase == self.PHASE_KEYFRAMES:
            self.current = min(self.current, len(self.keyframes) - 1)
        else:
            self.current = min(self.current, len(self.transitions) - 1)

        has_any = any(kf.status != "pending" for kf in self.keyframes)
        return has_any


# ── interactive setup ────────────────────────────────────────────────

def _ask(prompt, default=None):
    """Prompt the user for input with an optional default."""
    if default is not None:
        display = f"{prompt} [{default}]: "
    else:
        display = f"{prompt}: "
    try:
        value = input(display).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    return value if value else (str(default) if default is not None else "")


def _ask_multiline(prompt):
    """Read free-form multiline input terminated by Ctrl-D (EOF) or a single Enter on a short input."""
    print(f"{prompt}:")
    lines = []
    try:
        first = input("> ")
        lines.append(first)
        # If the first line looks complete (non-empty, no trailing indication of more),
        # check if there's more input coming by reading until EOF
        print("  (continue pasting, then press Ctrl-D on an empty line to finish)")
        while True:
            lines.append(input())
    except EOFError:
        pass
    except KeyboardInterrupt:
        print()
        sys.exit(0)
    text = "\n".join(lines).strip()
    # Collapse to single line for use as theme (newlines → spaces)
    return " ".join(text.split())


def _ask_choice(prompt, choices, default=None):
    """Prompt the user to pick from a list of choices."""
    for i, c in enumerate(choices):
        marker = " *" if c == default else ""
        print(f"  {i + 1}) {c}{marker}")
    while True:
        raw = _ask(prompt, default)
        # Accept the value directly if it matches a choice
        if raw in choices:
            return raw
        # Accept a number
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(choices):
                return choices[idx]
        except ValueError:
            pass
        print(f"  Please enter a number 1-{len(choices)} or a name from the list.")


def interactive_setup(args):
    """Prompt for any missing required values."""
    from styles import list_styles
    styles = list_styles()

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  DIRECTOR MODE — Setup                                       ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()

    if not args.theme:
        args.theme = _ask_multiline("Theme (paste text, then Ctrl-D to finish)")
        if not args.theme:
            print("Error: theme is required")
            sys.exit(1)

    if args.seed is None:
        raw = _ask("Seed (run ID)", default=random.randint(1, 9999))
        try:
            args.seed = int(raw)
        except ValueError:
            print(f"Error: seed must be a number, got: {raw}")
            sys.exit(1)

    if args.style is None:
        args.style = _ask_choice("Style", styles, default=DEFAULT_STYLE)

    if args.mode != "freeform" and args.segments is None:
        raw = _ask("Segments", default=16)
        try:
            args.segments = int(raw)
        except ValueError:
            args.segments = 16

    if args.duration is None:
        style_data = load_style(args.style)
        style_default = style_data.get("default_duration", 24)
        raw = _ask("Duration per segment (seconds)", default=style_default)
        try:
            args.duration = int(raw)
        except ValueError:
            args.duration = style_default

    print()


# ── Freeform Director TUI ────────────────────────────────────────────

FREEFORM_SCENE_SYS = """\
You are a visual director helping to plan a single scene in an improvised video.

Given a user's scene idea, generate THREE things:
1. "end_keyframe": A vivid 1-3 sentence description of a STILL IMAGE showing \
what the scene ends on. Concrete, specific, visual — no abstract language.
2. "transition": A 1-3 sentence description of the MOTION and TRANSFORMATION \
from the previous keyframe to the ending keyframe. Use active verbs: drifts, \
sweeps, dissolves, pulls back, rushes forward.
3. "voiceover": Spoken narration text for this scene, exactly {word_lo}-{word_hi} \
words. Poetic, contemplative, or dramatic — complements the visuals without \
describing them literally.

Respond with a JSON array containing one object with keys "end_keyframe", \
"transition", "voiceover". Example: [{{"end_keyframe": "...", "transition": \
"...", "voiceover": "..."}}]. No other text.\
"""


class FreeformDirectorTUI:
    """Interactive TUI for freeform improvised video creation."""

    def __init__(self, *, run_dir, t2i_template, transition_template,
                 audio_template, base_url, negative_prompt,
                 default_duration, width, height, frame_rate, strip_audio,
                 voice, tts_dir, tts_seed, seed, timeout, has_voiceover,
                 llm_url, llm_model, llm_api_key):
        self.keyframes = []       # list of Keyframe
        self.transitions = []     # list of TransitionClip
        self.run_dir = run_dir
        self.t2i_template = t2i_template
        self.transition_template = transition_template
        self.audio_template = audio_template
        self.base_url = base_url
        self.negative_prompt = negative_prompt
        self.default_duration = default_duration
        self.width = width
        self.height = height
        self.frame_rate = frame_rate
        self.strip_audio = strip_audio
        self.voice = voice
        self.tts_dir = tts_dir
        self.tts_seed = tts_seed
        self.seed = seed
        self.timeout = timeout
        self.has_voiceover = has_voiceover
        self.llm_url = llm_url
        self.llm_model = llm_model
        self.llm_api_key = llm_api_key
        self.current = 0  # index into transitions (scenes)
        self.stdscr = None
        self.status_msg = ""
        self.should_quit = False

    def run(self):
        if self._load_session():
            print(f"Resumed session: {len(self.transitions)} scenes")
        else:
            # First run — need initial keyframe
            self._create_first_keyframe()
            self._save_session()

        curses.wrapper(self._main)
        print(f"Session saved. Resume with the same --seed {self.seed}")

    def _create_first_keyframe(self):
        """Prompt for and generate the initial keyframe."""
        print(f"\n{'='*60}")
        print(f"  FREEFORM DIRECTOR — First Keyframe")
        print(f"{'='*60}")
        print(f"\nDescribe the opening image (paste text, Ctrl-D to finish):")
        lines = []
        try:
            first = input("> ")
            lines.append(first)
            print("  (continue pasting, then Ctrl-D on empty line to finish)")
            while True:
                lines.append(input())
        except EOFError:
            pass
        description = " ".join("\n".join(lines).split()).strip()
        if not description:
            description = "A cinematic establishing shot"

        kf = Keyframe(0, description)
        self.keyframes.append(kf)
        self._render_keyframe_terminal(0)

    def _main(self, stdscr):
        self.stdscr = stdscr
        curses.curs_set(0)
        curses.use_default_colors()
        if curses.has_colors():
            curses.init_pair(C_APPROVED, curses.COLOR_GREEN, -1)
            curses.init_pair(C_RENDERED, curses.COLOR_CYAN, -1)
            curses.init_pair(C_PENDING, curses.COLOR_YELLOW, -1)
            curses.init_pair(C_DRAFT, curses.COLOR_MAGENTA, -1)
            curses.init_pair(C_DIM, curses.COLOR_WHITE, -1)
            curses.init_pair(C_KEY, curses.COLOR_CYAN, -1)

        while not self.should_quit:
            self._draw()
            key = stdscr.getch()
            self._handle_key(key)
        self._save_session()

    def _leave_curses(self):
        if self.stdscr is not None:
            curses.endwin()

    def _resume_curses(self):
        if self.stdscr is not None:
            self.stdscr.clear()
            self.stdscr.refresh()

    def _safe(self, y, x, text, attr=0):
        h, w = self.stdscr.getmaxyx()
        if 0 <= y < h and 0 <= x < w:
            try:
                self.stdscr.addnstr(y, x, text, w - x, attr)
            except curses.error:
                pass

    def _hline(self, y, left, mid, right, w):
        self._safe(y, 0, left + mid * (w - 2) + right)

    def _row(self, y, text, w, attr=0):
        padded = " " + text[:w - 4]
        self._safe(y, 0, "│" + padded.ljust(w - 2) + "│", attr)

    def _input_text(self, message, prefill=""):
        self._leave_curses()
        print()
        print(message)
        if prefill:
            def hook():
                readline.insert_text(prefill)
                readline.redisplay()
            readline.set_pre_input_hook(hook)
        try:
            result = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            result = ""
        finally:
            readline.set_pre_input_hook()
        self._resume_curses()
        return result

    def _input_multiline(self, message):
        self._leave_curses()
        print()
        print(message)
        lines = []
        try:
            first = input("> ")
            lines.append(first)
            print("  (continue pasting, then Ctrl-D on empty line to finish)")
            while True:
                lines.append(input())
        except EOFError:
            pass
        self._resume_curses()
        return " ".join("\n".join(lines).split()).strip()

    # ── drawing ──────────────────────────────────────────────────────

    def _draw(self):
        self.stdscr.clear()
        h, w = self.stdscr.getmaxyx()
        bw = min(w, 80)
        y = 0

        self._hline(y, "┌", "─", "┐", bw); y += 1

        n_scenes = len(self.transitions)
        title = "FREEFORM DIRECTOR"
        if n_scenes == 0:
            info = "No scenes yet"
        else:
            info = f"Scene {self.current + 1} / {n_scenes}"
        gap = bw - 4 - len(title) - len(info)
        self._safe(y, 0, "│ " + title + " " * max(1, gap) + info + " │",
                   curses.A_BOLD)
        y += 1

        if n_scenes == 0:
            # No scenes yet — just show the first keyframe
            kf = self.keyframes[0] if self.keyframes else None
            if kf:
                self._row(y, f"Opening keyframe:", bw, curses.A_BOLD); y += 1
                for line in textwrap.wrap(kf.description, width=bw - 8)[:3]:
                    self._row(y, f"  {line}", bw); y += 1

            self._hline(y, "├", "─", "┤", bw); y += 1
            self._row(y, "", bw); y += 1
            self._row(y, "[Space] View keyframe   [n] Add new scene", bw); y += 1
            self._row(y, "[r] Render movie        [q] Quit", bw); y += 1
        else:
            tr = self.transitions[self.current]
            kf_from = self.keyframes[tr.index]
            kf_to = self.keyframes[tr.index + 1]

            # Status
            st, sc = ("RENDERED", curses.color_pair(C_RENDERED) | curses.A_BOLD) \
                if tr.has_video(self.run_dir) else \
                ("PENDING", curses.color_pair(C_PENDING))
            self._row(y, f"Status: {st}", bw, sc); y += 1

            # Strip
            self._hline(y, "├", "─", "┤", bw); y += 1
            parts = []
            for i, t in enumerate(self.transitions):
                marker = f"[{i+1}]" if i == self.current else f" {i+1} "
                parts.append(marker)
            self._row(y, " ".join(parts), bw); y += 1

            # Keyframes
            self._hline(y, "├", "─", "┤", bw); y += 1
            self._row(y, f"From keyframe {kf_from.num}:", bw, curses.A_BOLD); y += 1
            for line in textwrap.wrap(kf_from.description, width=bw - 8)[:2]:
                self._row(y, f"  {line}", bw); y += 1

            self._row(y, f"To keyframe {kf_to.num}:", bw, curses.A_BOLD); y += 1
            for line in textwrap.wrap(kf_to.description, width=bw - 8)[:2]:
                self._row(y, f"  {line}", bw); y += 1

            # Transition
            self._row(y, "", bw); y += 1
            self._row(y, "Transition:", bw, curses.A_BOLD); y += 1
            for line in textwrap.wrap(tr.description, width=bw - 8)[:3]:
                self._row(y, f"  {line}", bw); y += 1

            # Voiceover
            if self.has_voiceover and tr.voiceover_text:
                self._row(y, "", bw); y += 1
                self._row(y, "Voiceover:", bw, curses.A_BOLD); y += 1
                for line in textwrap.wrap(tr.voiceover_text, width=bw - 8)[:2]:
                    self._row(y, f"  {line}", bw); y += 1

            # Actions
            self._hline(y, "├", "─", "┤", bw); y += 1
            self._row(y, "", bw); y += 1
            self._row(y, "[Space] Play  [Left/Right] Navigate", bw); y += 1
            self._row(y, "", bw); y += 1
            self._row(y, "[n] Add new scene       [Enter] Re-render", bw); y += 1
            self._row(y, "[e] Edit transition     [v] Edit end keyframe", bw); y += 1
            self._row(y, "[o] Edit voiceover      [s] Soundtrack", bw); y += 1
            self._row(y, "[r] Render movie        [q] Quit", bw); y += 1

        self._row(y, "", bw); y += 1
        if self.status_msg:
            self._row(y, self.status_msg, bw, curses.A_DIM); y += 1

        self._hline(y, "└", "─", "┘", bw)
        self.stdscr.refresh()

    # ── key handling ─────────────────────────────────────────────────

    def _handle_key(self, key):
        n_scenes = len(self.transitions)

        if key == ord("n"):
            self._add_scene()
        elif key == ord(" "):
            self._play_current()
        elif key == ord("\n") or key == curses.KEY_ENTER:
            if n_scenes > 0:
                self._rerender_current()
        elif key == curses.KEY_LEFT or key == ord("h"):
            if self.current > 0:
                self.current -= 1
                self.status_msg = ""
        elif key == curses.KEY_RIGHT or key == ord("l"):
            if self.current < n_scenes - 1:
                self.current += 1
                self.status_msg = ""
        elif key == curses.KEY_HOME:
            self.current = 0
            self.status_msg = ""
        elif key == curses.KEY_END:
            if n_scenes > 0:
                self.current = n_scenes - 1
                self.status_msg = ""
        elif key == ord("e") and n_scenes > 0:
            self._edit_transition()
        elif key == ord("v") and n_scenes > 0:
            self._edit_end_keyframe()
        elif key == ord("o") and n_scenes > 0:
            self._edit_voiceover()
        elif key == ord("s"):
            self._soundtrack_director()
        elif key == ord("r"):
            self._render_movie()
        elif key == ord("q"):
            self.status_msg = "Press Q again to quit"
            self._draw()
            confirm = self.stdscr.getch()
            if confirm == ord("q") or confirm == ord("Q"):
                self.should_quit = True
            else:
                self.status_msg = ""

    # ── add scene ────────────────────────────────────────────────────

    def _add_scene(self):
        """Add a new scene: get prompt, LLM extrapolates, generate keyframe + transition."""
        self._leave_curses()

        # Duration
        raw = input(f"\nScene duration in seconds [{self.default_duration}]: ").strip()
        try:
            duration = int(raw) if raw else self.default_duration
        except ValueError:
            duration = self.default_duration

        # Scene prompt
        print(f"\nDescribe what happens in this scene (paste text, Ctrl-D to finish):")
        lines = []
        try:
            first = input("> ")
            lines.append(first)
            print("  (continue pasting, then Ctrl-D on empty line to finish)")
            while True:
                lines.append(input())
        except EOFError:
            pass
        scene_prompt = " ".join("\n".join(lines).split()).strip()
        if not scene_prompt:
            print("  Cancelled.")
            self._resume_curses()
            return

        # LLM extrapolation
        from write_script import _voiceover_word_range
        wlo, whi = _voiceover_word_range(duration)
        sys_prompt = FREEFORM_SCENE_SYS.format(word_lo=wlo, word_hi=whi)

        prev_kf = self.keyframes[-1]
        user_msg = (f"Previous keyframe (what we're starting from):\n"
                    f"  {prev_kf.description}\n\n"
                    f"Scene duration: {duration} seconds\n\n"
                    f"Scene idea:\n  {scene_prompt}")

        print(f"\n  Generating scene details via LLM...")
        sys.stdout.write("  streaming: ")
        sys.stdout.flush()
        try:
            result = call_llm(self.llm_url, self.llm_model, sys_prompt,
                              user_msg, temperature=0.8, api_key=self.llm_api_key)
            # call_llm returns a list; we expect [{"end_keyframe":..., ...}]
            item = result[0]
            if isinstance(item, str):
                scene_data = json.loads(item)
            else:
                scene_data = item
        except (SystemExit, Exception) as e:
            print(f"  LLM failed: {e}")
            print(f"  Using scene prompt directly.")
            scene_data = {
                "end_keyframe": scene_prompt,
                "transition": scene_prompt,
                "voiceover": "",
            }

        end_kf_desc = scene_data.get("end_keyframe", scene_prompt)
        transition_desc = scene_data.get("transition", scene_prompt)
        voiceover_text = scene_data.get("voiceover", "")

        print(f"\n  End keyframe: {end_kf_desc[:80]}...")
        print(f"  Transition:   {transition_desc[:80]}...")
        if voiceover_text:
            print(f"  Voiceover:    {voiceover_text[:80]}...")

        # Create the new keyframe and transition
        new_kf_idx = len(self.keyframes)
        new_kf = Keyframe(new_kf_idx, end_kf_desc)
        self.keyframes.append(new_kf)

        tr_idx = len(self.transitions)
        new_tr = TransitionClip(tr_idx, transition_desc, voiceover_text)
        self.transitions.append(new_tr)

        # Generate end keyframe image
        self._render_keyframe_terminal(new_kf_idx)

        # Render voiceover
        if self.has_voiceover and voiceover_text and self.tts_dir:
            vo_path = new_tr.vo_path(self.run_dir)
            if not os.path.exists(vo_path):
                print(f"\n  Rendering voiceover...")
                try:
                    render_segment_tts(
                        self.tts_dir, self.base_url,
                        voiceover_text, self.voice, vo_path,
                        seed=self.tts_seed + tr_idx,
                    )
                    print(f"  Saved: {vo_path}")
                except Exception as e:
                    print(f"  Voiceover failed: {e}")

        # Render transition
        self._render_transition_terminal(tr_idx, duration)

        self.current = tr_idx
        self._save_session()
        self._resume_curses()

    # ── rendering ────────────────────────────────────────────────────

    def _render_keyframe_terminal(self, idx):
        kf = self.keyframes[idx]
        noise_seed = random.randint(0, 2**53)
        output_png = kf.image_path(self.run_dir)

        print(f"\n{'='*60}")
        print(f"  Generating keyframe {kf.num}")
        print(f"  Prompt: {kf.description[:70]}...")
        print(f"  Seed:   {noise_seed}")
        print(f"{'='*60}")

        wf = patch_t2i_workflow(
            self.t2i_template,
            prompt_text=kf.description,
            negative_prompt_text=self.negative_prompt,
            seed_value=noise_seed,
            output_prefix=f"{self.seed}/keyframe_{kf.num:02d}",
        )

        start = time.time()
        try:
            history = run_workflow(self.base_url, wf, timeout=self.timeout)
            download_output(self.base_url, history, output_png,
                            output_type="images")
            elapsed = time.time() - start
            print(f"  Generated in {fmt_duration(elapsed)}")
            kf.status = "approved"
        except Exception as e:
            print(f"  Generation failed: {e}")

    def _render_transition_terminal(self, idx, duration_seconds=None):
        tr = self.transitions[idx]
        kf_from = self.keyframes[idx]
        kf_to = self.keyframes[idx + 1]

        if duration_seconds is None:
            duration_seconds = self.default_duration

        first_img = kf_from.image_path(self.run_dir)
        last_img = kf_to.image_path(self.run_dir)

        if not os.path.exists(first_img) or not os.path.exists(last_img):
            print(f"  Error: keyframe images missing")
            return

        noise_seed = random.randint(0, 2**53)
        output_video = tr.video_path(self.run_dir)

        total_frames = duration_seconds * self.frame_rate + 1
        print(f"\n{'='*60}")
        print(f"  Rendering scene {tr.num}")
        print(f"  From:     keyframe {kf_from.num}")
        print(f"  To:       keyframe {kf_to.num}")
        print(f"  Prompt:   {tr.description[:70]}...")
        print(f"  Seed:     {noise_seed}")
        print(f"  Duration: {duration_seconds}s ({total_frames} frames)")
        print(f"{'='*60}")

        uploaded_first = upload_image(self.base_url, first_img)
        uploaded_last = upload_image(self.base_url, last_img)

        wf = patch_transition_workflow(
            self.transition_template,
            first_image_name=uploaded_first,
            last_image_name=uploaded_last,
            prompt_text=tr.description,
            negative_prompt_text=self.negative_prompt,
            seed_value=noise_seed,
            width=self.width,
            height=self.height,
            frame_rate=self.frame_rate,
            duration_seconds=duration_seconds,
            output_prefix=f"{self.seed}/transition_{tr.num:02d}",
        )

        start = time.time()
        try:
            history = run_workflow(self.base_url, wf, timeout=self.timeout)
            download_output(self.base_url, history, output_video,
                            strip_audio=self.strip_audio)
            elapsed = time.time() - start
            actual_dur = get_duration(output_video)
            if actual_dur is not None:
                print(f"  Rendered in {fmt_duration(elapsed)}, "
                      f"clip duration: {actual_dur:.1f}s")
            else:
                print(f"  Rendered in {fmt_duration(elapsed)}")
            tr.status = "rendered"
        except Exception as e:
            print(f"  Render failed: {e}")

    # ── playback ─────────────────────────────────────────────────────

    def _play_current(self):
        if not self.transitions:
            # Play the opening keyframe
            if self.keyframes and self.keyframes[0].has_image(self.run_dir):
                if not shutil.which("mpv"):
                    self.status_msg = "mpv not found"
                    return
                self._leave_curses()
                subprocess.run(["mpv", "--really-quiet",
                               self.keyframes[0].image_path(self.run_dir)],
                               check=False)
                self._resume_curses()
            return

        tr = self.transitions[self.current]
        if not tr.has_video(self.run_dir):
            self.status_msg = "No video to play"
            return
        if not shutil.which("mpv"):
            self.status_msg = "mpv not found"
            return

        # Mux voiceover for preview
        preview = self._make_preview(tr)
        self._leave_curses()
        subprocess.run(["mpv", "--really-quiet", preview], check=False)
        self._resume_curses()

    def _make_preview(self, tr):
        video = tr.video_path(self.run_dir)
        vo_wav = tr.vo_path(self.run_dir)
        preview = os.path.join(self.run_dir, f"preview_{tr.num:02d}.mp4")

        if not os.path.exists(vo_wav):
            return video

        if os.path.exists(preview):
            ptime = os.path.getmtime(preview)
            if (ptime > os.path.getmtime(video) and
                    ptime > os.path.getmtime(vo_wav)):
                return preview

        vid_dur = get_duration(video)
        if vid_dur is None:
            return video

        padded = os.path.join(self.run_dir, f"_pad_{tr.num:02d}.wav")
        try:
            pad_audio_centered(vo_wav, vid_dur, padded)
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", video, "-i", padded,
                 "-map", "0:v", "-map", "1:a",
                 "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                 "-shortest", preview],
                capture_output=True,
            )
            if os.path.exists(padded):
                os.unlink(padded)
            if result.returncode == 0:
                return preview
        except Exception:
            pass
        return video

    # ── editing ──────────────────────────────────────────────────────

    def _rerender_current(self):
        if not self.transitions:
            return
        tr = self.transitions[self.current]
        _delete_if_exists(tr.video_path(self.run_dir))
        _delete_if_exists(os.path.join(self.run_dir, f"preview_{tr.num:02d}.mp4"))
        self._leave_curses()
        self._render_transition_terminal(self.current)
        self._save_session()
        self._resume_curses()

    def _edit_transition(self):
        tr = self.transitions[self.current]
        new_desc = self._input_text(
            f"Current transition prompt:\n  {tr.description}\n\n"
            "Enter new prompt (or Enter to cancel):\n",
            prefill=tr.description,
        )
        if not new_desc or new_desc == tr.description:
            self.status_msg = "No changes"
            return
        tr.description = new_desc
        _delete_if_exists(tr.video_path(self.run_dir))
        _delete_if_exists(os.path.join(self.run_dir, f"preview_{tr.num:02d}.mp4"))
        self._leave_curses()
        self._render_transition_terminal(self.current)
        self._save_session()
        self._resume_curses()

    def _edit_end_keyframe(self):
        tr = self.transitions[self.current]
        kf = self.keyframes[tr.index + 1]
        new_desc = self._input_text(
            f"Current end keyframe description:\n  {kf.description}\n\n"
            "Enter new description (or Enter to cancel):\n",
            prefill=kf.description,
        )
        if not new_desc or new_desc == kf.description:
            self.status_msg = "No changes"
            return
        kf.description = new_desc
        self._leave_curses()
        self._render_keyframe_terminal(kf.index)
        # Re-render this transition and invalidate later ones
        _delete_if_exists(tr.video_path(self.run_dir))
        _delete_if_exists(os.path.join(self.run_dir, f"preview_{tr.num:02d}.mp4"))
        self._render_transition_terminal(self.current)
        # Invalidate transitions after this one (they depend on this keyframe)
        for i in range(self.current + 1, len(self.transitions)):
            later = self.transitions[i]
            _delete_if_exists(later.video_path(self.run_dir))
            _delete_if_exists(os.path.join(self.run_dir, f"preview_{later.num:02d}.mp4"))
            later.status = "pending"
        self._save_session()
        self._resume_curses()

    def _edit_voiceover(self):
        if not self.has_voiceover:
            self.status_msg = "Voiceover disabled"
            return
        tr = self.transitions[self.current]
        new_vo = self._input_text(
            f"Current voiceover:\n  {tr.voiceover_text}\n\n"
            "Enter new voiceover (or Enter to cancel):\n",
            prefill=tr.voiceover_text,
        )
        if not new_vo or new_vo == tr.voiceover_text:
            self.status_msg = "No changes"
            return
        tr.voiceover_text = new_vo
        if self.tts_dir:
            vo_path = tr.vo_path(self.run_dir)
            _delete_if_exists(vo_path)
            _delete_if_exists(os.path.join(self.run_dir, f"preview_{tr.num:02d}.mp4"))
            self._leave_curses()
            print(f"\nRendering voiceover for scene {tr.num}...")
            try:
                render_segment_tts(
                    self.tts_dir, self.base_url,
                    tr.voiceover_text, self.voice, vo_path,
                    seed=self.tts_seed + tr.index,
                )
                print(f"  Saved: {vo_path}")
            except Exception as e:
                print(f"  Failed: {e}")
            self._resume_curses()
        self._save_session()
        self.status_msg = "Voiceover updated"

    # ── soundtrack (reuse from TransitionDirectorTUI) ────────────────

    def _soundtrack_director(self):
        dir_name = os.path.basename(self.run_dir)
        final_path = os.path.join(self.run_dir, f"{dir_name}.mp4")
        if not os.path.exists(final_path):
            self.status_msg = "Render movie first with [r]"
            return

        total_dur = get_duration(final_path)
        if total_dur is None:
            self.status_msg = "Could not get movie duration"
            return

        self._leave_curses()
        print(f"\n{'='*60}")
        print(f"  SOUNDTRACK DIRECTOR")
        print(f"  Movie: {final_path}")
        print(f"  Duration: {total_dur:.1f}s")
        print(f"{'='*60}")

        raw = input(f"\nHow many soundtrack sections? [1]: ").strip()
        try:
            n_sections = int(raw) if raw else 1
            n_sections = max(1, n_sections)
        except ValueError:
            n_sections = 1

        section_dur = total_dur / n_sections
        sections = []
        for i in range(n_sections):
            start = section_dur * i
            end = section_dur * (i + 1)
            print(f"\n  Section {i+1}/{n_sections} ({start:.0f}s - {end:.0f}s)")
            print(f"  Enter music description (paste text, Ctrl-D to finish):")
            lines = []
            try:
                first = input("  > ")
                lines.append(first)
                while True:
                    lines.append(input())
            except EOFError:
                pass
            prompt = " ".join("\n".join(lines).split()).strip()
            if not prompt:
                prompt = "cinematic orchestral soundtrack"
            sections.append({"prompt": prompt, "duration": int(round(section_dur))})

        bpm = int(input("\nBPM [120]: ").strip() or "120")
        keyscale = input("Key/scale [C minor]: ").strip() or "C minor"

        print(f"\n{'='*60}")
        print(f"  Rendering {n_sections} soundtrack sections...")
        print(f"{'='*60}")

        soundtrack_files = []
        for i, sec in enumerate(sections):
            output_mp3 = os.path.join(self.run_dir, f"soundtrack_{i+1:02d}.mp3")
            if os.path.exists(output_mp3):
                print(f"\n  Section {i+1} exists: {output_mp3}")
                soundtrack_files.append(output_mp3)
                continue

            noise_seed = random.randint(0, 2**53)
            wf = patch_audio_workflow(
                self.audio_template,
                prompt_text=sec["prompt"],
                seed_value=noise_seed,
                duration_seconds=sec["duration"],
                bpm=bpm, keyscale=keyscale,
                output_prefix=f"{self.seed}/soundtrack_{i+1:02d}",
            )
            try:
                history = run_workflow(self.base_url, wf, timeout=self.timeout)
                download_output(self.base_url, history, output_mp3,
                                output_type="audio")
                soundtrack_files.append(output_mp3)
            except Exception as e:
                print(f"  Render failed: {e}")

        if not soundtrack_files:
            self._resume_curses()
            return

        import tempfile
        tmpdir = tempfile.mkdtemp(prefix="soundtrack-")
        try:
            if len(soundtrack_files) == 1:
                full_st = soundtrack_files[0]
            else:
                slist = os.path.join(tmpdir, "st.txt")
                with open(slist, "w") as f:
                    for sf in soundtrack_files:
                        f.write(f"file '{os.path.abspath(sf)}'\n")
                full_st = os.path.join(tmpdir, "full.mp3")
                subprocess.run(
                    ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                     "-i", slist, "-c", "copy", full_st],
                    capture_output=True, check=True)

            scored_path = os.path.join(self.run_dir, f"{dir_name}_scored.mp4")
            probe = subprocess.run(
                ["ffprobe", "-v", "quiet", "-select_streams", "a",
                 "-show_entries", "stream=index", "-of", "csv=p=0", final_path],
                capture_output=True, text=True)
            has_audio = bool(probe.stdout.strip())

            if has_audio:
                result = subprocess.run(
                    ["ffmpeg", "-y", "-i", final_path, "-i", full_st,
                     "-filter_complex",
                     "[0:a]volume=1.0[orig];[1:a]volume=0.5[music];"
                     "[orig][music]amix=inputs=2:duration=first[aout]",
                     "-map", "0:v", "-map", "[aout]",
                     "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                     scored_path], capture_output=True)
            else:
                result = subprocess.run(
                    ["ffmpeg", "-y", "-i", final_path, "-i", full_st,
                     "-map", "0:v", "-map", "1:a",
                     "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                     "-shortest", scored_path], capture_output=True)

            if result.returncode == 0 and os.path.exists(scored_path):
                print(f"\n  Saved: {scored_path}")
                if shutil.which("mpv"):
                    subprocess.run(["mpv", "--really-quiet", scored_path], check=False)
        finally:
            import shutil as shutil_mod
            shutil_mod.rmtree(tmpdir, ignore_errors=True)

        self._resume_curses()

    # ── render movie ─────────────────────────────────────────────────

    def _render_movie(self):
        if not self.transitions:
            self.status_msg = "No scenes to render"
            return
        self._save_session()
        self._leave_curses()
        print()
        print("=" * 60)
        usable = [tr for tr in self.transitions if tr.has_video(self.run_dir)]
        print(f"  RENDERING MOVIE  ({len(usable)} scenes)")
        print("=" * 60)

        try:
            cmd = ["python3", "mux.py", "--seed", str(self.seed),
                   "--pattern", "transition"]
            subprocess.run(cmd, check=True)
            dir_name = os.path.basename(self.run_dir)
            final_path = os.path.join(self.run_dir, f"{dir_name}.mp4")
            if os.path.exists(final_path):
                if shutil.which("mpv"):
                    print(f"\nPlaying: {final_path}")
                    subprocess.run(["mpv", "--really-quiet", final_path],
                                   check=False)
                else:
                    print(f"\nSaved: {final_path} (install mpv to auto-play)")
        except subprocess.CalledProcessError as e:
            print(f"  Mux failed: {e}")

        self._resume_curses()

    # ── persistence ──────────────────────────────────────────────────

    def _session_path(self):
        return os.path.join(self.run_dir, "session.json")

    def _save_session(self):
        session = {
            "mode": "freeform",
            "current": self.current,
            "default_duration": self.default_duration,
            "width": self.width,
            "height": self.height,
            "frame_rate": self.frame_rate,
            "keyframes": [
                {"description": kf.description, "status": kf.status}
                for kf in self.keyframes
            ],
            "transitions": [
                {
                    "description": tr.description,
                    "voiceover_text": tr.voiceover_text,
                    "status": tr.status,
                }
                for tr in self.transitions
            ],
        }
        with open(self._session_path(), "w") as f:
            json.dump(session, f, indent=2)
            f.write("\n")

    def _load_session(self):
        path = self._session_path()
        if not os.path.exists(path):
            return False
        try:
            with open(path) as f:
                session = json.load(f)
        except (json.JSONDecodeError, KeyError):
            return False

        if session.get("mode") != "freeform":
            return False

        self.current = session.get("current", 0)
        if session.get("default_duration"):
            self.default_duration = session["default_duration"]
        if session.get("width"):
            self.width = session["width"]
        if session.get("height"):
            self.height = session["height"]
        if session.get("frame_rate"):
            self.frame_rate = session["frame_rate"]

        self.keyframes = []
        for i, skf in enumerate(session.get("keyframes", [])):
            kf = Keyframe(i, skf["description"])
            if skf["status"] in ("generated", "approved") and kf.has_image(self.run_dir):
                kf.status = skf["status"]
            elif kf.has_image(self.run_dir):
                kf.status = "generated"
            self.keyframes.append(kf)

        self.transitions = []
        for i, str_ in enumerate(session.get("transitions", [])):
            tr = TransitionClip(i, str_["description"], str_.get("voiceover_text", ""))
            if str_["status"] in ("rendered", "approved") and tr.has_video(self.run_dir):
                tr.status = str_["status"]
            elif tr.has_video(self.run_dir):
                tr.status = "rendered"
            self.transitions.append(tr)

        self.current = min(self.current, max(0, len(self.transitions) - 1))
        return bool(self.keyframes)


def _run_freeform_mode(args, run_dir, base_url, llm_url, llm_model,
                       llm_api_key, style, strip_audio):
    """Run the freeform director TUI."""
    negative_prompt = args.negative_prompt or style.get("negative_prompt", "")
    has_voiceover = not args.no_voiceover
    default_duration = args.duration if args.duration else style.get("default_duration", 10)

    tts_dir = None
    if has_voiceover:
        tts_dir = TTS_DEMO_DIR
        if not os.path.isdir(tts_dir):
            print(f"Warning: tts-demo not found at {tts_dir}")
            print("  Voiceover audio will be disabled.")
            tts_dir = None

    t2i_template = load_workflow(args.t2i_workflow)
    transition_template = load_workflow(args.transition_workflow)
    audio_template = load_workflow(args.audio_workflow)

    tui = FreeformDirectorTUI(
        run_dir=run_dir,
        t2i_template=t2i_template,
        transition_template=transition_template,
        audio_template=audio_template,
        base_url=base_url,
        negative_prompt=negative_prompt,
        default_duration=default_duration,
        width=args.transition_width,
        height=args.transition_height,
        frame_rate=args.transition_fps,
        strip_audio=strip_audio,
        voice=args.voice,
        tts_dir=tts_dir,
        tts_seed=args.tts_seed,
        seed=args.seed,
        timeout=args.timeout,
        has_voiceover=has_voiceover,
        llm_url=llm_url,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
    )
    tui.run()


def _run_transition_mode(args, run_dir, base_url, llm_url, llm_model,
                         llm_api_key, style, strip_audio, length):
    """Run the transition director TUI."""
    negative_prompt = args.negative_prompt or style.get("negative_prompt", "")
    duration_seconds = args.duration
    has_voiceover = not args.no_voiceover

    keyframes_path = os.path.join(run_dir, "keyframes.json")
    transitions_path = os.path.join(run_dir, "transitions.json")
    voiceover_path = os.path.join(run_dir, "voiceover.json")

    # Generate or load keyframe descriptions
    if os.path.exists(keyframes_path):
        print(f"Loading keyframes: {keyframes_path}")
        with open(keyframes_path) as f:
            kf_descs = json.load(f)
    else:
        keyframe_sys, transition_sys, voiceover_sys, _, _ = \
            _build_transition_prompts(args.style, args.duration)

        print(f"Generating {args.segments} keyframe descriptions...")
        user_msg = f"Theme: {args.theme}\nNumber of keyframes: {args.segments}"
        sys.stdout.write("  streaming: ")
        sys.stdout.flush()
        kf_descs = call_llm(llm_url, llm_model, keyframe_sys, user_msg,
                            api_key=llm_api_key)
        if len(kf_descs) > args.segments:
            kf_descs = kf_descs[:args.segments]
        with open(keyframes_path, "w") as f:
            json.dump(kf_descs, f, indent=2)
            f.write("\n")
        print(f"  Saved: {keyframes_path}")

    # Generate or load transition descriptions
    if os.path.exists(transitions_path):
        print(f"Loading transitions: {transitions_path}")
        with open(transitions_path) as f:
            tr_descs = json.load(f)
    else:
        keyframe_sys, transition_sys, voiceover_sys, _, _ = \
            _build_transition_prompts(args.style, args.duration)

        n_transitions = len(kf_descs) - 1
        print(f"\nGenerating {n_transitions} transition descriptions...")
        kf_list = "\n".join(
            f"  Keyframe {i+1}: {k}" for i, k in enumerate(kf_descs))
        trans_user_msg = (f"Theme: {args.theme}\n"
                          f"Number of keyframes: {len(kf_descs)}\n\n"
                          f"Keyframe descriptions:\n{kf_list}")
        sys.stdout.write("  streaming: ")
        sys.stdout.flush()
        tr_descs = call_llm(llm_url, llm_model, transition_sys, trans_user_msg,
                            api_key=llm_api_key)
        if len(tr_descs) > n_transitions:
            tr_descs = tr_descs[:n_transitions]
        with open(transitions_path, "w") as f:
            json.dump(tr_descs, f, indent=2)
            f.write("\n")
        print(f"  Saved: {transitions_path}")

    # Generate or load voiceover
    voiceover = [""] * len(tr_descs)
    if has_voiceover:
        if os.path.exists(voiceover_path):
            print(f"Loading voiceover: {voiceover_path}")
            with open(voiceover_path) as f:
                voiceover = json.load(f)
        else:
            keyframe_sys, transition_sys, voiceover_sys, _, _ = \
                _build_transition_prompts(args.style, args.duration)

            print("Generating voiceover text...")
            kf_list = "\n".join(
                f"  Keyframe {i+1}: {k}" for i, k in enumerate(kf_descs))
            tr_list = "\n".join(
                f"  Transition {i+1}: {t}" for i, t in enumerate(tr_descs))
            vo_msg = (f"Theme: {args.theme}\n"
                      f"Number of transitions: {len(tr_descs)}\n\n"
                      f"Keyframe descriptions:\n{kf_list}\n\n"
                      f"Transition descriptions:\n{tr_list}")
            sys.stdout.write("  streaming: ")
            sys.stdout.flush()
            voiceover = call_llm(llm_url, llm_model, voiceover_sys, vo_msg,
                                 api_key=llm_api_key)
            if len(voiceover) > len(tr_descs):
                voiceover = voiceover[:len(tr_descs)]
            with open(voiceover_path, "w") as f:
                json.dump(voiceover, f, indent=2)
                f.write("\n")
            print(f"  Saved: {voiceover_path}")

    while len(voiceover) < len(tr_descs):
        voiceover.append("")

    # Print overview
    print(f"\nKeyframes: {len(kf_descs)}")
    for i, k in enumerate(kf_descs):
        text = k[:80] + "..." if len(k) > 80 else k
        print(f"  [KF {i+1:2d}] {text}")
    print(f"\nTransitions: {len(tr_descs)}")
    for i, t in enumerate(tr_descs):
        text = t[:80] + "..." if len(t) > 80 else t
        print(f"  [TR {i+1:2d}] {text}")
    print()

    # Resolve TTS
    tts_dir = None
    if has_voiceover:
        tts_dir = TTS_DEMO_DIR
        if not os.path.isdir(tts_dir):
            print(f"Warning: tts-demo not found at {tts_dir}")
            print("  Voiceover audio will be disabled.")
            tts_dir = None

    # Build data model
    keyframes = [Keyframe(i, kf_descs[i]) for i in range(len(kf_descs))]
    transitions = [TransitionClip(i, tr_descs[i], voiceover[i] or "")
                   for i in range(len(tr_descs))]

    # Load workflow templates
    t2i_template = load_workflow(args.t2i_workflow)
    transition_template = load_workflow(args.transition_workflow)
    audio_template = load_workflow(args.audio_workflow)

    tui = TransitionDirectorTUI(
        keyframes=keyframes,
        transitions=transitions,
        run_dir=run_dir,
        t2i_template=t2i_template,
        transition_template=transition_template,
        audio_template=audio_template,
        base_url=base_url,
        base_prompt=args.base_prompt or "",
        negative_prompt=negative_prompt,
        duration_seconds=duration_seconds,
        width=args.transition_width,
        height=args.transition_height,
        frame_rate=args.transition_fps,
        strip_audio=strip_audio,
        voice=args.voice,
        tts_dir=tts_dir,
        tts_seed=args.tts_seed,
        seed=args.seed,
        timeout=args.timeout,
        has_voiceover=has_voiceover,
        style_name=args.style,
        llm_url=llm_url,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
    )
    tui.run(auto=args.auto)


# ── main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Interactive director mode TUI for video generation"
    )
    parser.add_argument("--mode", default="chain",
                        choices=["chain", "transition", "freeform"],
                        help="Director mode: chain (sequential I2V), transition (keyframe pairs), freeform (improvised scenes)")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--theme", nargs="+", default=None)
    parser.add_argument("--style", default=None)
    parser.add_argument("--segments", type=int, default=None)
    parser.add_argument("--duration", type=int, default=None)
    parser.add_argument("--workflow", default="workflow/ltx_i2v.json")
    parser.add_argument("--t2i-workflow", default=T2I_WORKFLOW)
    parser.add_argument("--transition-workflow", default=TRANSITION_WORKFLOW)
    parser.add_argument("--transition-width", type=int, default=640)
    parser.add_argument("--transition-height", type=int, default=480)
    parser.add_argument("--transition-fps", type=int, default=25)
    parser.add_argument("--audio-workflow", default=AUDIO_WORKFLOW)
    parser.add_argument("--auto", action="store_true",
                        help="Auto-approve all keyframes and transitions without interactive review")
    parser.add_argument("--url", default=None)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--base-prompt", default=None)
    parser.add_argument("--negative-prompt", default=None)
    parser.add_argument("--no-voiceover", action="store_true")
    parser.add_argument("--length", type=int, default=None)
    parser.add_argument("--skip-script", action="store_true")
    parser.add_argument("--voice", default="despotism-doc.wav")
    parser.add_argument("--tts-seed", type=int, default=1)

    # Workflow nodes (same defaults as chain.py)
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

    # LLM
    parser.add_argument("--llm-url", default=None)
    parser.add_argument("--llm-model", default=None)
    parser.add_argument("--llm-api-key", default=None)

    args = parser.parse_args()

    # Join theme words if provided via CLI
    if args.theme:
        args.theme = " ".join(args.theme)

    # Check for an existing session before interactive setup
    resuming = False
    if args.seed is not None:
        from run_dir import find_run_dir
        existing = find_run_dir("output", args.seed)
        if existing and os.path.exists(os.path.join(existing, "session.json")):
            # Resume existing session — load theme and mode from saved files
            resuming = True
            theme_file = os.path.join(existing, "theme.txt")
            if os.path.exists(theme_file):
                with open(theme_file) as f:
                    args.theme = f.read().strip()
            # Detect mode from saved session
            session_path = os.path.join(existing, "session.json")
            try:
                with open(session_path) as f:
                    saved_session = json.load(f)
                if saved_session.get("mode") == "transition":
                    args.mode = "transition"
                elif saved_session.get("mode") == "freeform":
                    args.mode = "freeform"
                if saved_session.get("style"):
                    args.style = args.style or saved_session["style"]
            except (json.JSONDecodeError, KeyError):
                pass
            print(f"Resuming session from {existing}/")

    if not resuming:
        interactive_setup(args)

    base_url = args.url or COMFYUI_URL
    llm_url = args.llm_url or LLM_URL
    llm_model = args.llm_model or LLM_MODEL
    llm_api_key = args.llm_api_key or os.environ.get("LLM_API_KEY", "")

    # Default style if not set (resuming or CLI)
    if args.style is None:
        args.style = DEFAULT_STYLE

    style = load_style(args.style)
    strip_audio = style.get("strip_audio", False)
    if args.duration is None:
        args.duration = style.get("default_duration", 24)
    length = args.length if args.length else args.duration * 25

    if args.base_prompt is None:
        args.base_prompt = style.get("base_prompt", "")

    if resuming:
        run_dir = existing
    else:
        run_dir = make_run_dir("output", args.seed, theme=args.theme)
    theme_path = os.path.join(run_dir, "theme.txt")
    if not os.path.exists(theme_path):
        with open(theme_path, "w") as f:
            f.write(args.theme)

    # ── freeform mode ────────────────────────────────────────────────
    if args.mode == "freeform":
        _run_freeform_mode(args, run_dir, base_url, llm_url, llm_model,
                           llm_api_key, style, strip_audio)
        return

    # ── transition mode ─────────────────────────────────────────────
    is_transition = args.mode == "transition" or style.get("mode") == "transition"
    if is_transition:
        _run_transition_mode(args, run_dir, base_url, llm_url, llm_model,
                             llm_api_key, style, strip_audio, length)
        return

    workflow_template = load_workflow(args.workflow)
    script_path = os.path.join(run_dir, "script.json")
    voiceover_json_path = os.path.join(run_dir, "voiceover.json")
    visual_sys, voiceover_sys, _ = _build_prompts(args.style, args.duration)

    # ── generate or load script ──────────────────────────────────────
    if os.path.exists(script_path) and not (not args.skip_script and False):
        print(f"Loading script: {script_path}")
        with open(script_path) as f:
            suffixes = json.load(f)
    else:
        print(f"Generating {args.segments}-segment script...")
        user_msg = f"Theme: {args.theme}\nNumber of segments: {args.segments}"
        if args.base_prompt:
            user_msg += (f"\n\nBase prompt (prepended to each):\n{args.base_prompt}")
        sys.stdout.write("  streaming: ")
        sys.stdout.flush()
        suffixes = call_llm(llm_url, llm_model, visual_sys, user_msg,
                            api_key=llm_api_key)
        if len(suffixes) > args.segments:
            suffixes = suffixes[:args.segments]
        with open(script_path, "w") as f:
            json.dump(suffixes, f, indent=2)
            f.write("\n")
        print(f"  Saved: {script_path}")

    # ── generate or load voiceover text ──────────────────────────────
    voiceover = [""] * len(suffixes)
    has_voiceover = not args.no_voiceover
    if has_voiceover:
        if os.path.exists(voiceover_json_path):
            print(f"Loading voiceover: {voiceover_json_path}")
            with open(voiceover_json_path) as f:
                voiceover = json.load(f)
        else:
            print("Generating voiceover text...")
            visual_list = "\n".join(
                f"  Segment {i+1}: {v}" for i, v in enumerate(suffixes))
            vo_msg = (f"Theme: {args.theme}\n"
                      f"Number of segments: {len(suffixes)}\n\n"
                      f"Visual descriptions:\n{visual_list}")
            sys.stdout.write("  streaming: ")
            sys.stdout.flush()
            voiceover = call_llm(llm_url, llm_model, voiceover_sys, vo_msg,
                                 api_key=llm_api_key)
            if len(voiceover) > len(suffixes):
                voiceover = voiceover[:len(suffixes)]
            with open(voiceover_json_path, "w") as f:
                json.dump(voiceover, f, indent=2)
                f.write("\n")
            print(f"  Saved: {voiceover_json_path}")

    while len(voiceover) < len(suffixes):
        voiceover.append("")

    # ── print overview ───────────────────────────────────────────────
    print(f"\nScript: {len(suffixes)} scenes")
    for i, s in enumerate(suffixes):
        text = s[:80] + "..." if len(s) > 80 else s
        print(f"  [{i+1:2d}] {text}")
    print()

    # ── resolve TTS ──────────────────────────────────────────────────
    tts_dir = None
    if has_voiceover:
        tts_dir = TTS_DEMO_DIR
        if not os.path.isdir(tts_dir):
            print(f"Warning: tts-demo not found at {tts_dir}")
            print("  Voiceover audio will be disabled.")
            tts_dir = None

    # ── build scenes and launch TUI ──────────────────────────────────
    scenes = [Scene(i, suffixes[i], voiceover[i] or "")
              for i in range(len(suffixes))]

    tui = DirectorTUI(
        scenes=scenes,
        run_dir=run_dir,
        workflow_template=workflow_template,
        base_url=base_url,
        base_prompt=args.base_prompt,
        length=length,
        strip_audio=strip_audio,
        voice=args.voice,
        tts_dir=tts_dir,
        tts_seed=args.tts_seed,
        seed=args.seed,
        args=args,
        timeout=args.timeout,
        script_path=script_path,
        voiceover_json_path=voiceover_json_path,
        has_voiceover=has_voiceover,
        style_name=args.style,
        llm_url=llm_url,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
    )
    tui.run()


if __name__ == "__main__":
    main()
