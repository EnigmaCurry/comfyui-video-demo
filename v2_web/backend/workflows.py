"""Workflow patching for T2I keyframe and LTX transition generation.

Adapted from v1_tui/transition.py.
"""

import copy
import json
import os

# ── HiDream T2I node IDs ────────────────────────────────────────────
T2I_PROMPT_NODE = "85"
T2I_PROMPT_FIELD = "text"
T2I_NEG_PROMPT_NODE = "90"
T2I_NEG_PROMPT_FIELD = "text"
T2I_SEED_NODE = "94"
T2I_SEED_FIELD = "seed"
T2I_WIDTH_NODE = "84"
T2I_HEIGHT_NODE = "84"
T2I_OUTPUT_NODE = "88"
T2I_OUTPUT_FIELD = "filename_prefix"

T2I_WORKFLOW_PATH = os.path.join(os.path.dirname(__file__), "workflow", "hidream_t2i.json")

# ── LTX transition node IDs ─────────────────────────────────────────
TRANS_FIRST_IMAGE_NODE = "146"
TRANS_LAST_IMAGE_NODE = "147"
TRANS_PROMPT_NODE = "139:128"
TRANS_PROMPT_FIELD = "text"
TRANS_NEG_PROMPT_NODE = "139:112"
TRANS_NEG_PROMPT_FIELD = "text"
TRANS_SEED_NODE = "139:100"
TRANS_SEED_FIELD = "noise_seed"
TRANS_WIDTH_NODE = "139:113"
TRANS_HEIGHT_NODE = "139:98"
TRANS_FRAMERATE_NODE = "139:114"
TRANS_DURATION_NODE = "139:143"
TRANS_OUTPUT_NODE = "68"
TRANS_OUTPUT_FIELD = "filename_prefix"

TRANSITION_WORKFLOW_PATH = os.path.join(os.path.dirname(__file__), "workflow", "ltx_transition.json")


def load_workflow(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def patch_t2i_workflow(workflow: dict, *, prompt_text: str,
                       negative_prompt_text: str = "",
                       seed_value: int, width: int = 1920,
                       height: int = 1088,
                       output_prefix: str = "ComfyUI") -> dict:
    """Patch HiDream T2I workflow for keyframe image generation."""
    wf = copy.deepcopy(workflow)
    wf[T2I_PROMPT_NODE]["inputs"][T2I_PROMPT_FIELD] = prompt_text
    wf[T2I_NEG_PROMPT_NODE]["inputs"][T2I_NEG_PROMPT_FIELD] = negative_prompt_text
    wf[T2I_SEED_NODE]["inputs"][T2I_SEED_FIELD] = seed_value
    wf[T2I_WIDTH_NODE]["inputs"]["width"] = width
    wf[T2I_HEIGHT_NODE]["inputs"]["height"] = height
    wf[T2I_OUTPUT_NODE]["inputs"][T2I_OUTPUT_FIELD] = output_prefix
    return wf


def patch_transition_workflow(workflow: dict, *, first_image_name: str,
                               last_image_name: str, prompt_text: str,
                               negative_prompt_text: str = "",
                               seed_value: int, width: int = 640,
                               height: int = 480, frame_rate: int = 25,
                               duration_seconds: int = 10,
                               output_prefix: str = "video/transition") -> dict:
    """Patch LTX transition workflow for two-frame video transition."""
    wf = copy.deepcopy(workflow)
    wf[TRANS_FIRST_IMAGE_NODE]["inputs"]["image"] = first_image_name
    wf[TRANS_LAST_IMAGE_NODE]["inputs"]["image"] = last_image_name
    wf[TRANS_PROMPT_NODE]["inputs"][TRANS_PROMPT_FIELD] = prompt_text
    wf[TRANS_NEG_PROMPT_NODE]["inputs"][TRANS_NEG_PROMPT_FIELD] = negative_prompt_text
    wf[TRANS_SEED_NODE]["inputs"][TRANS_SEED_FIELD] = seed_value
    wf[TRANS_WIDTH_NODE]["inputs"]["value"] = width
    wf[TRANS_HEIGHT_NODE]["inputs"]["value"] = height
    wf[TRANS_FRAMERATE_NODE]["inputs"]["value"] = frame_rate
    wf[TRANS_DURATION_NODE]["inputs"]["value"] = duration_seconds
    wf[TRANS_OUTPUT_NODE]["inputs"][TRANS_OUTPUT_FIELD] = output_prefix
    return wf


# ── AceStep audio node IDs ──────────────────────────────────────────
AUDIO_PROMPT_NODE = "94"
AUDIO_SEED_NODE = "3"
AUDIO_SEED_FIELD = "seed"
AUDIO_DURATION_NODE = "98"
AUDIO_DURATION_FIELD = "seconds"
AUDIO_OUTPUT_NODE = "107"
AUDIO_OUTPUT_FIELD = "filename_prefix"

AUDIO_WORKFLOW_PATH = os.path.join(os.path.dirname(__file__), "workflow", "acestep_audio.json")


def patch_audio_workflow(workflow: dict, *, prompt_text: str, seed_value: int,
                          duration_seconds: int = 120, bpm: int = 120,
                          keyscale: str = "C major",
                          output_prefix: str = "audio/soundtrack") -> dict:
    """Patch AceStep 1.5 audio workflow for soundtrack generation."""
    wf = copy.deepcopy(workflow)
    wf[AUDIO_PROMPT_NODE]["inputs"]["tags"] = prompt_text
    wf[AUDIO_PROMPT_NODE]["inputs"]["seed"] = seed_value
    wf[AUDIO_PROMPT_NODE]["inputs"]["duration"] = duration_seconds
    wf[AUDIO_PROMPT_NODE]["inputs"]["bpm"] = bpm
    wf[AUDIO_PROMPT_NODE]["inputs"]["keyscale"] = keyscale
    wf[AUDIO_SEED_NODE]["inputs"][AUDIO_SEED_FIELD] = seed_value
    wf[AUDIO_DURATION_NODE]["inputs"][AUDIO_DURATION_FIELD] = duration_seconds
    wf[AUDIO_OUTPUT_NODE]["inputs"][AUDIO_OUTPUT_FIELD] = output_prefix
    return wf
