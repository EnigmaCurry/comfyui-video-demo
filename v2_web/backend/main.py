"""FastAPI application for the v2_web film director."""

import asyncio
import os
import random

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import settings
from models import (
    GenerateRequest,
    Keyframe,
    KeyframeStatus,
    RenderRequest,
    UpdateKeyframeRequest,
)

app = FastAPI(title="v2_web Film Director")

# ── In-memory keyframe store ────────────────────────────────────────
keyframes: dict[str, Keyframe] = {}
render_tasks: dict[str, asyncio.Task] = {}

IMAGES_DIR = os.path.join(os.path.dirname(__file__), "output", "keyframes")
os.makedirs(IMAGES_DIR, exist_ok=True)


def _ordered_keyframes() -> list[Keyframe]:
    return sorted(keyframes.values(), key=lambda k: k.position)


# ── Keyframe CRUD ───────────────────────────────────────────────────

@app.get("/api/keyframes")
async def list_keyframes():
    return {"keyframes": [k.model_dump() for k in _ordered_keyframes()]}


@app.post("/api/keyframes/generate")
async def generate_keyframes(req: GenerateRequest):
    """Generate keyframe descriptions via LLM and create pending keyframes."""
    from llm import generate_keyframe_descriptions

    descriptions = await generate_keyframe_descriptions(
        theme=req.theme, count=req.count, style=req.style,
    )

    new_keyframes = []
    base_pos = max((k.position for k in keyframes.values()), default=-1) + 1
    for i, desc in enumerate(descriptions):
        kf = Keyframe(position=base_pos + i, prompt=desc)
        keyframes[kf.id] = kf
        new_keyframes.append(kf)

    return {"keyframes": [k.model_dump() for k in new_keyframes]}


@app.get("/api/keyframes/{keyframe_id}")
async def get_keyframe(keyframe_id: str):
    kf = keyframes.get(keyframe_id)
    if not kf:
        raise HTTPException(404, "Keyframe not found")
    return kf.model_dump()


@app.get("/api/keyframes/{keyframe_id}/status")
async def get_keyframe_status(keyframe_id: str):
    kf = keyframes.get(keyframe_id)
    if not kf:
        raise HTTPException(404, "Keyframe not found")
    image_url = f"/api/images/{kf.image_filename}" if kf.image_filename else None
    return {
        "id": kf.id,
        "status": kf.status,
        "image_url": image_url,
        "error_message": kf.error_message,
    }


@app.put("/api/keyframes/{keyframe_id}")
async def update_keyframe(keyframe_id: str, req: UpdateKeyframeRequest):
    kf = keyframes.get(keyframe_id)
    if not kf:
        raise HTTPException(404, "Keyframe not found")
    if req.prompt is not None:
        kf.prompt = req.prompt
    if req.position is not None:
        kf.position = req.position
    return kf.model_dump()


@app.delete("/api/keyframes/{keyframe_id}")
async def delete_keyframe(keyframe_id: str):
    kf = keyframes.pop(keyframe_id, None)
    if not kf:
        raise HTTPException(404, "Keyframe not found")
    # Cancel any in-progress render
    task = render_tasks.pop(keyframe_id, None)
    if task and not task.done():
        task.cancel()
    # Clean up image file
    if kf.image_filename:
        path = os.path.join(IMAGES_DIR, kf.image_filename)
        if os.path.exists(path):
            os.unlink(path)
    return {"deleted": keyframe_id}


@app.post("/api/keyframes/reorder")
async def reorder_keyframes(order: list[str]):
    """Reorder keyframes by providing the list of IDs in desired order."""
    for i, kid in enumerate(order):
        if kid in keyframes:
            keyframes[kid].position = i
    return {"keyframes": [k.model_dump() for k in _ordered_keyframes()]}


# ── Render ──────────────────────────────────────────────────────────

async def _do_render(kf: Keyframe, seed: int, width: int, height: int):
    """Background task: render a keyframe via ComfyUI."""
    from comfyui import download_output, run_workflow
    from workflows import T2I_WORKFLOW_PATH, load_workflow, patch_t2i_workflow

    try:
        base_wf = load_workflow(T2I_WORKFLOW_PATH)

        # Load negative prompt from style
        from llm import _load_style
        style = _load_style("transition-story")
        neg_prompt = style.get("negative_prompt", "")

        patched = patch_t2i_workflow(
            base_wf,
            prompt_text=kf.prompt,
            negative_prompt_text=neg_prompt,
            seed_value=seed,
            width=width,
            height=height,
            output_prefix=f"v2web/{kf.id}",
        )

        history = await run_workflow(patched, timeout=600)
        filename = f"{kf.id}.png"
        dest = os.path.join(IMAGES_DIR, filename)
        await download_output(history, dest, output_type="images")
        kf.image_filename = filename
        kf.seed = seed
        kf.status = KeyframeStatus.done
    except Exception as e:
        kf.status = KeyframeStatus.error
        kf.error_message = str(e)


@app.post("/api/keyframes/{keyframe_id}/render")
async def render_keyframe(keyframe_id: str, req: RenderRequest | None = None):
    kf = keyframes.get(keyframe_id)
    if not kf:
        raise HTTPException(404, "Keyframe not found")

    if req and req.prompt is not None:
        kf.prompt = req.prompt

    seed = (req.seed if req and req.seed is not None else None) or random.randint(0, 2**32 - 1)
    width = req.width if req else 1920
    height = req.height if req else 1088

    # Cancel previous render if any
    old = render_tasks.pop(keyframe_id, None)
    if old and not old.done():
        old.cancel()

    kf.status = KeyframeStatus.rendering
    kf.error_message = None
    task = asyncio.create_task(_do_render(kf, seed, width, height))
    render_tasks[keyframe_id] = task

    return {"id": kf.id, "status": kf.status, "seed": seed}


@app.post("/api/keyframes/{keyframe_id}/rerender")
async def rerender_keyframe(keyframe_id: str, req: RenderRequest | None = None):
    """Re-render with a new seed."""
    kf = keyframes.get(keyframe_id)
    if not kf:
        raise HTTPException(404, "Keyframe not found")
    seed = (req.seed if req and req.seed is not None else None) or random.randint(0, 2**32 - 1)
    width = req.width if req else 1920
    height = req.height if req else 1088
    return await render_keyframe(keyframe_id, RenderRequest(seed=seed, width=width, height=height))


@app.post("/api/keyframes/{keyframe_id}/lock")
async def lock_keyframe(keyframe_id: str):
    kf = keyframes.get(keyframe_id)
    if not kf:
        raise HTTPException(404, "Keyframe not found")
    kf.locked = True
    return kf.model_dump()


@app.post("/api/keyframes/{keyframe_id}/unlock")
async def unlock_keyframe(keyframe_id: str):
    kf = keyframes.get(keyframe_id)
    if not kf:
        raise HTTPException(404, "Keyframe not found")
    kf.locked = False
    return kf.model_dump()


# ── Image serving ───────────────────────────────────────────────────

@app.get("/api/images/{filename}")
async def get_image(filename: str):
    path = os.path.join(IMAGES_DIR, filename)
    if not os.path.isfile(path):
        raise HTTPException(404, "Image not found")
    return FileResponse(path)


# ── Static frontend (production) ────────────────────────────────────
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
