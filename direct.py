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
    upload_image,
)
from mux import get_duration, pad_audio_centered
from render_voiceover import TTS_DEMO_DIR, render_segment_tts
from run_dir import make_run_dir
from styles import DEFAULT_STYLE, load_style
from write_script import _build_prompts, call_llm

LLM_URL = os.environ.get("LLM_URL", "http://127.0.0.1:8000")
LLM_MODEL = os.environ.get("LLM_MODEL", "default")

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
                 has_voiceover):
        self.scenes = scenes
        self.run_dir = run_dir
        self.workflow_template = workflow_template
        self.base_url = base_url
        self.base_prompt = base_prompt
        self.length = length
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
        self._row(y, "[Space] Play  [Left/Right] Navigate  [Home/End] Jump",
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
        self._leave_curses()
        subprocess.run(["mpv", "--really-quiet", preview],
                       check=False)
        self._resume_curses()

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

        old_suffix = scene.suffix
        old_vo = scene.voiceover_text
        scene.cancel_draft()

        # Restore backed-up files
        if old_suffix != scene.suffix:
            # Visual was changed — restore video
            _delete_if_exists(scene.video_path(self.run_dir))
            _delete_if_exists(scene.frame_path(self.run_dir))
            _restore(scene.video_path(self.run_dir))
            _restore(scene.frame_path(self.run_dir))

        if old_vo != scene.voiceover_text:
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
                print(f"\nPlaying: {final_path}")
                subprocess.run(
                    ["mpv", "--really-quiet", final_path],
                    check=False,
                )
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
        args.theme = _ask("Theme")
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

    if args.segments is None:
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


# ── main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Interactive director mode TUI for video generation"
    )
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--theme", nargs="+", default=None)
    parser.add_argument("--style", default=None)
    parser.add_argument("--segments", type=int, default=None)
    parser.add_argument("--duration", type=int, default=None)
    parser.add_argument("--workflow", default="workflow/ltx_i2v.json")
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
            # Resume existing session — load theme from saved files
            resuming = True
            theme_file = os.path.join(existing, "theme.txt")
            if os.path.exists(theme_file):
                with open(theme_file) as f:
                    args.theme = f.read().strip()
            # Load style from session if not overridden
            session_path = os.path.join(existing, "session.json")
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
    )
    tui.run()


if __name__ == "__main__":
    main()
