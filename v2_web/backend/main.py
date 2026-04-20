"""FastAPI application for the v2_web film director."""

import asyncio
import os
import random

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from models import (
    GenerateStoryRequest,
    Keyframe,
    KeyframeStatus,
    Project,
    RenderRequest,
    SetPremiseRequest,
    SuggestPremiseRequest,
    UpdateKeyframeRequest,
)
from projects import delete_project, images_dir, list_projects, load_project, save_project

app = FastAPI(title="v2_web Film Director")

# ── In-memory state ─────────────────────────────────────────────────
current_project: Project | None = None
render_tasks: dict[str, asyncio.Task] = {}
_render_semaphore = asyncio.Semaphore(1)


def _get_project() -> Project:
    if current_project is None:
        raise HTTPException(404, "No project loaded")
    return current_project


def _get_keyframe(keyframe_id: str) -> Keyframe:
    proj = _get_project()
    for kf in proj.keyframes:
        if kf.id == keyframe_id:
            return kf
    raise HTTPException(404, "Keyframe not found")


def _save():
    if current_project is not None:
        save_project(current_project)


# ── Project endpoints ───────────────────────────────────────────────

@app.get("/api/projects")
async def api_list_projects():
    return {"projects": list_projects()}


@app.get("/api/projects/current")
async def api_get_current_project():
    if current_project is None:
        return {"project": None}
    return {"project": current_project.model_dump()}


@app.post("/api/projects/{project_id}/load")
async def api_load_project(project_id: str):
    global current_project
    proj = load_project(project_id)
    if proj is None:
        raise HTTPException(404, "Project not found")
    current_project = proj
    return {"project": current_project.model_dump()}


@app.delete("/api/projects/{project_id}")
async def api_delete_project(project_id: str):
    global current_project
    if current_project and current_project.id == project_id:
        current_project = None
    delete_project(project_id)
    return {"deleted": project_id}


@app.put("/api/projects/current/name")
async def api_rename_project(body: dict):
    proj = _get_project()
    proj.name = body.get("name", proj.name)
    _save()
    return {"name": proj.name}


# ── Premise flow ────────────────────────────────────────────────────

@app.post("/api/premise/suggest")
async def api_suggest_premise(req: SuggestPremiseRequest):
    """Generate a premise from freeform notes."""
    from llm import suggest_premise
    premise = await suggest_premise(req.notes)
    return {"premise": premise}


@app.post("/api/premise/set")
async def api_set_premise(req: SetPremiseRequest):
    """Lock the premise and create a project."""
    global current_project
    from llm import generate_project_name

    name = await generate_project_name(req.premise)
    proj = Project(name=name, premise=req.premise, premise_locked=True)
    current_project = proj
    _save()
    return {"project": proj.model_dump()}


# ── Story flow ──────────────────────────────────────────────────────

@app.post("/api/story/generate")
async def api_generate_story(req: GenerateStoryRequest):
    """Generate scene descriptions from the locked premise."""
    proj = _get_project()
    if not proj.premise_locked:
        raise HTTPException(400, "Premise must be locked first")

    from llm import generate_keyframe_descriptions

    descriptions = await generate_keyframe_descriptions(
        theme=proj.premise, count=req.scene_count, style=req.style,
    )

    proj.scene_count = req.scene_count
    proj.scene_duration = req.scene_duration
    proj.style = req.style
    proj.keyframes = [Keyframe(position=i, prompt=desc) for i, desc in enumerate(descriptions)]
    proj.story_locked = True
    proj.active_index = 0
    _save()

    return {"project": proj.model_dump()}


# ── Keyframe CRUD ───────────────────────────────────────────────────

@app.get("/api/keyframes")
async def api_list_keyframes():
    proj = _get_project()
    ordered = sorted(proj.keyframes, key=lambda k: k.position)
    return {"keyframes": [k.model_dump() for k in ordered]}


@app.get("/api/keyframes/{keyframe_id}")
async def api_get_keyframe(keyframe_id: str):
    return _get_keyframe(keyframe_id).model_dump()


@app.get("/api/keyframes/{keyframe_id}/status")
async def api_get_keyframe_status(keyframe_id: str):
    kf = _get_keyframe(keyframe_id)
    proj = _get_project()
    image_url = f"/api/projects/{proj.id}/images/{kf.image_filename}" if kf.image_filename else None
    return {
        "id": kf.id,
        "status": kf.status,
        "image_url": image_url,
        "error_message": kf.error_message,
    }


@app.put("/api/keyframes/{keyframe_id}")
async def api_update_keyframe(keyframe_id: str, req: UpdateKeyframeRequest):
    kf = _get_keyframe(keyframe_id)
    if req.prompt is not None:
        kf.prompt = req.prompt
    if req.position is not None:
        kf.position = req.position
    _save()
    return kf.model_dump()


@app.delete("/api/keyframes/{keyframe_id}")
async def api_delete_keyframe(keyframe_id: str):
    proj = _get_project()
    kf = _get_keyframe(keyframe_id)
    task = render_tasks.pop(keyframe_id, None)
    if task and not task.done():
        task.cancel()
    if kf.image_filename:
        path = os.path.join(images_dir(proj.id), kf.image_filename)
        if os.path.exists(path):
            os.unlink(path)
    proj.keyframes = [k for k in proj.keyframes if k.id != keyframe_id]
    _save()
    return {"deleted": keyframe_id}


@app.post("/api/keyframes/reorder")
async def api_reorder_keyframes(order: list[str]):
    proj = _get_project()
    id_to_kf = {kf.id: kf for kf in proj.keyframes}
    for i, kid in enumerate(order):
        if kid in id_to_kf:
            id_to_kf[kid].position = i
    _save()
    ordered = sorted(proj.keyframes, key=lambda k: k.position)
    return {"keyframes": [k.model_dump() for k in ordered]}


@app.put("/api/active-index")
async def api_set_active_index(body: dict):
    proj = _get_project()
    proj.active_index = body.get("active_index", 0)
    _save()
    return {"active_index": proj.active_index}


# ── Render ──────────────────────────────────────────────────────────

async def _do_render(proj_id: str, kf: Keyframe, seed: int, width: int, height: int):
    from comfyui import download_output, run_workflow
    from workflows import T2I_WORKFLOW_PATH, load_workflow, patch_t2i_workflow

    async with _render_semaphore:
        try:
            base_wf = load_workflow(T2I_WORKFLOW_PATH)
            from llm import _load_style
            style = _load_style("transition-story")
            neg_prompt = style.get("negative_prompt", "")

            patched = patch_t2i_workflow(
                base_wf, prompt_text=kf.prompt, negative_prompt_text=neg_prompt,
                seed_value=seed, width=width, height=height,
                output_prefix=f"v2web/{kf.id}",
            )

            history = await run_workflow(patched, timeout=600)
            filename = f"{kf.id}.png"
            dest = os.path.join(images_dir(proj_id), filename)
            await download_output(history, dest, output_type="images")
            kf.image_filename = filename
            kf.seed = seed
            kf.status = KeyframeStatus.done
            if current_project and current_project.id == proj_id:
                _save()
        except asyncio.CancelledError:
            kf.status = KeyframeStatus.pending
        except Exception as e:
            kf.status = KeyframeStatus.error
            kf.error_message = str(e)


@app.post("/api/keyframes/{keyframe_id}/render")
async def api_render_keyframe(keyframe_id: str, req: RenderRequest | None = None):
    proj = _get_project()
    kf = _get_keyframe(keyframe_id)
    if req and req.prompt is not None:
        kf.prompt = req.prompt
    seed = (req.seed if req and req.seed is not None else None) or random.randint(0, 2**32 - 1)
    width = req.width if req else 1920
    height = req.height if req else 1088
    old = render_tasks.pop(keyframe_id, None)
    if old and not old.done():
        old.cancel()
    kf.status = KeyframeStatus.rendering
    kf.error_message = None
    task = asyncio.create_task(_do_render(proj.id, kf, seed, width, height))
    render_tasks[keyframe_id] = task
    return {"id": kf.id, "status": kf.status, "seed": seed}


@app.post("/api/keyframes/{keyframe_id}/rerender")
async def api_rerender_keyframe(keyframe_id: str, req: RenderRequest | None = None):
    _get_keyframe(keyframe_id)
    seed = (req.seed if req and req.seed is not None else None) or random.randint(0, 2**32 - 1)
    width = req.width if req else 1920
    height = req.height if req else 1088
    return await api_render_keyframe(keyframe_id, RenderRequest(seed=seed, width=width, height=height))


@app.post("/api/keyframes/{keyframe_id}/lock")
async def api_lock_keyframe(keyframe_id: str):
    kf = _get_keyframe(keyframe_id)
    kf.locked = True
    _save()
    return kf.model_dump()


@app.post("/api/keyframes/{keyframe_id}/unlock")
async def api_unlock_keyframe(keyframe_id: str):
    kf = _get_keyframe(keyframe_id)
    kf.locked = False
    _save()
    return kf.model_dump()


# ── Image serving ───────────────────────────────────────────────────

@app.get("/api/projects/{project_id}/images/{filename}")
async def api_get_image(project_id: str, filename: str):
    path = os.path.join(images_dir(project_id), filename)
    if not os.path.isfile(path):
        raise HTTPException(404, "Image not found")
    return FileResponse(path)


# ── Static frontend (production) ────────────────────────────────────
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
