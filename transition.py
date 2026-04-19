"""Workflow patching for transition mode pipelines.

Provides patching functions for:
- HiDream T2I workflow (keyframe image generation)
- LTX 2.3 transition workflow (two-frame video transitions)
- AceStep 1.5 audio generation (soundtrack)
"""

import copy
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

# ── AceStep audio node IDs ───────────────────────────────────────────
AUDIO_PROMPT_NODE = "94"
AUDIO_SEED_NODE = "3"
AUDIO_SEED_FIELD = "seed"
AUDIO_DURATION_NODE = "98"
AUDIO_DURATION_FIELD = "seconds"
AUDIO_OUTPUT_NODE = "107"
AUDIO_OUTPUT_FIELD = "filename_prefix"

# ── Default workflow paths ───────────────────────────────────────────
T2I_WORKFLOW = os.path.join(os.path.dirname(__file__), "workflow", "hidream_t2i.json")
TRANSITION_WORKFLOW = os.path.join(os.path.dirname(__file__), "workflow", "ltx_transition.json")
AUDIO_WORKFLOW = os.path.join(os.path.dirname(__file__), "workflow", "acestep_audio.json")


def patch_t2i_workflow(workflow, *, prompt_text, negative_prompt_text="",
                       seed_value, width=1920, height=1088, output_prefix="ComfyUI"):
    """Patch HiDream T2I workflow for keyframe image generation."""
    wf = copy.deepcopy(workflow)

    wf[T2I_PROMPT_NODE]["inputs"][T2I_PROMPT_FIELD] = prompt_text
    wf[T2I_NEG_PROMPT_NODE]["inputs"][T2I_NEG_PROMPT_FIELD] = negative_prompt_text
    wf[T2I_SEED_NODE]["inputs"][T2I_SEED_FIELD] = seed_value
    wf[T2I_WIDTH_NODE]["inputs"]["width"] = width
    wf[T2I_HEIGHT_NODE]["inputs"]["height"] = height
    wf[T2I_OUTPUT_NODE]["inputs"][T2I_OUTPUT_FIELD] = output_prefix

    return wf


def patch_transition_workflow(workflow, *, first_image_name, last_image_name,
                               prompt_text, negative_prompt_text="",
                               seed_value, width=640, height=480,
                               frame_rate=25, duration_seconds=10,
                               output_prefix="video/transition"):
    """Patch LTX transition workflow for two-frame video transition.

    Note: the workflow's math expression computes frame count as
    ``duration_seconds * frame_rate + 1``, so duration_seconds is in seconds.
    """
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


def patch_audio_workflow(workflow, *, prompt_text, seed_value,
                          duration_seconds=120, bpm=120, keyscale="C major",
                          output_prefix="audio/soundtrack"):
    """Patch AceStep 1.5 audio workflow for soundtrack generation.

    The prompt node has many fields; we patch tags, seed, duration, bpm, keyscale.
    The latent node's seconds must match the prompt node's duration.
    """
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
