"""Workflow patching for T2I keyframe generation.

Adapted from v1_tui/transition.py — only the HiDream T2I patch is included
for the initial keyframe-grid scope.
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
