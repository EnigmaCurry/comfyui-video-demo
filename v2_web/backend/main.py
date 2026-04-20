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
    Transition,
    TransitionRenderRequest,
    UpdateKeyframeRequest,
    UpdateTransitionRequest,
)
from projects import delete_project, images_dir, list_projects, load_project, save_project

app = FastAPI(title="v2_web Film Director")

# ── In-memory state ─────────────────────────────────────────────────
current_project: Project | None = None
render_tasks: dict[str, asyncio.Task] = {}
_render_semaphore = asyncio.Semaphore(1)


@app.on_event("startup")
async def _startup():
    global current_project
    projects = list_projects()
    if projects:
        proj = load_project(projects[0]["id"])
        if proj:
            current_project = proj
            print(f"Auto-loaded project: {proj.name} ({proj.id})", flush=True)


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


def _get_transition(transition_id: str) -> Transition:
    proj = _get_project()
    for tr in proj.transitions:
        if tr.id == transition_id:
            return tr
    raise HTTPException(404, "Transition not found")


def _save():
    if current_project is not None:
        try:
            save_project(current_project)
        except Exception:
            import traceback
            print(f"ERROR saving project: {traceback.format_exc()}", flush=True)


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
    from llm import suggest_premise
    premise = await suggest_premise(req.notes)
    return {"premise": premise}


@app.post("/api/premise/set")
async def api_set_premise(req: SetPremiseRequest):
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
    proj.original_prompts = list(descriptions)
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


@app.get("/api/keyframes/{keyframe_id}/status")
async def api_get_keyframe_status(keyframe_id: str):
    kf = _get_keyframe(keyframe_id)
    proj = _get_project()
    image_url = f"/api/projects/{proj.id}/images/{kf.image_filename}" if kf.image_filename else None
    return {
        "id": kf.id, "status": kf.status, "image_url": image_url,
        "seed": kf.seed, "error_message": kf.error_message,
    }


@app.put("/api/keyframes/{keyframe_id}")
async def api_update_keyframe(keyframe_id: str, req: UpdateKeyframeRequest):
    kf = _get_keyframe(keyframe_id)
    if req.prompt is not None:
        kf.prompt = req.prompt
    if req.negative_prompt is not None:
        kf.negative_prompt = req.negative_prompt
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


@app.post("/api/keyframes/reset")
async def api_reset_keyframes():
    proj = _get_project()
    if not proj.original_prompts:
        raise HTTPException(400, "No original story to reset to")
    for task in render_tasks.values():
        if not task.done():
            task.cancel()
    render_tasks.clear()
    img_dir = images_dir(proj.id)
    for kf in proj.keyframes:
        if kf.image_filename:
            path = os.path.join(img_dir, kf.image_filename)
            if os.path.exists(path):
                os.unlink(path)
    proj.keyframes = [
        Keyframe(position=i, prompt=desc)
        for i, desc in enumerate(proj.original_prompts)
    ]
    proj.active_index = 0
    proj.keyframes_locked = False
    proj.transitions = []
    proj.transition_active_index = 0
    _save()
    return {"project": proj.model_dump()}


@app.post("/api/keyframes/lock")
async def api_lock_keyframes():
    """Lock all keyframes and generate transition descriptions."""
    proj = _get_project()
    from llm import generate_transition_descriptions
    ordered = sorted(proj.keyframes, key=lambda k: k.position)
    prompts = [kf.prompt for kf in ordered]
    descriptions = await generate_transition_descriptions(
        prompts, duration=proj.scene_duration, style=proj.style,
    )
    proj.transitions = []
    for i, desc in enumerate(descriptions):
        proj.transitions.append(Transition(
            position=i,
            from_keyframe_id=ordered[i].id,
            to_keyframe_id=ordered[i + 1].id,
            prompt=desc,
        ))
    proj.keyframes_locked = True
    proj.transition_active_index = 0
    _save()
    return {"project": proj.model_dump()}


@app.post("/api/keyframes/auto-create")
async def api_auto_create_keyframes():
    """Render all pending keyframes sequentially."""
    proj = _get_project()
    ordered = sorted(proj.keyframes, key=lambda k: k.position)
    rendered = 0
    for kf in ordered:
        if kf.status == KeyframeStatus.pending:
            seed = random.randint(0, 2**32 - 1)
            kf.status = KeyframeStatus.rendering
            await _do_render_keyframe(proj.id, kf, seed, 1920, 1088)
            rendered += 1
    proj.active_index = len(ordered)
    _save()
    return {"rendered": rendered, "project": proj.model_dump()}


@app.put("/api/active-index")
async def api_set_active_index(body: dict):
    proj = _get_project()
    proj.active_index = body.get("active_index", 0)
    _save()
    return {"active_index": proj.active_index}


# ── Keyframe Render ─────────────────────────────────────────────────

async def _do_render_keyframe(proj_id: str, kf: Keyframe, seed: int, width: int, height: int):
    """Render a keyframe synchronously (for use in background tasks or auto-create)."""
    from comfyui import download_output, run_workflow
    from workflows import T2I_WORKFLOW_PATH, load_workflow, patch_t2i_workflow

    async with _render_semaphore:
        try:
            base_wf = load_workflow(T2I_WORKFLOW_PATH)
            from llm import _load_style
            style = _load_style("transition-story")
            neg_parts = [style.get("negative_prompt", "")]
            if kf.negative_prompt:
                neg_parts.append(kf.negative_prompt)
            neg_prompt = ", ".join(p for p in neg_parts if p)

            print(f"Rendering kf {kf.id}: seed={seed}", flush=True)
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
    task = asyncio.create_task(_do_render_keyframe(proj.id, kf, seed, width, height))
    render_tasks[keyframe_id] = task
    return {"id": kf.id, "status": kf.status, "seed": seed}


@app.post("/api/keyframes/{keyframe_id}/rerender")
async def api_rerender_keyframe(keyframe_id: str, req: RenderRequest | None = None):
    _get_keyframe(keyframe_id)
    seed = (req.seed if req and req.seed is not None else None) or random.randint(0, 2**32 - 1)
    width = req.width if req else 1920
    height = req.height if req else 1088
    return await api_render_keyframe(keyframe_id, RenderRequest(seed=seed, width=width, height=height))


@app.post("/api/keyframes/{keyframe_id}/rewrite")
async def api_rewrite_keyframe(keyframe_id: str, body: dict):
    """Rewrite keyframe prompt via LLM and auto-render."""
    from llm import rewrite_keyframe_prompt
    kf = _get_keyframe(keyframe_id)
    instruction = body.get("instruction", "")
    if not instruction.strip():
        raise HTTPException(400, "Instruction is required")
    new_prompt = await rewrite_keyframe_prompt(kf.prompt, instruction)
    kf.prompt = new_prompt
    _save()
    # Auto-render with new prompt
    result = await api_render_keyframe(keyframe_id)
    return {"prompt": new_prompt, **result}


# ── Transition endpoints ────────────────────────────────────────────

@app.get("/api/transitions")
async def api_list_transitions():
    proj = _get_project()
    ordered = sorted(proj.transitions, key=lambda t: t.position)
    return {"transitions": [t.model_dump() for t in ordered]}


@app.get("/api/transitions/{transition_id}/status")
async def api_get_transition_status(transition_id: str):
    tr = _get_transition(transition_id)
    proj = _get_project()
    video_url = f"/api/projects/{proj.id}/videos/{tr.video_filename}" if tr.video_filename else None
    return {
        "id": tr.id, "status": tr.status, "video_url": video_url,
        "seed": tr.seed, "error_message": tr.error_message,
    }


@app.put("/api/transitions/{transition_id}")
async def api_update_transition(transition_id: str, req: UpdateTransitionRequest):
    tr = _get_transition(transition_id)
    if req.prompt is not None:
        tr.prompt = req.prompt
    if req.negative_prompt is not None:
        tr.negative_prompt = req.negative_prompt
    _save()
    return tr.model_dump()


@app.put("/api/transition-active-index")
async def api_set_transition_active_index(body: dict):
    proj = _get_project()
    proj.transition_active_index = body.get("active_index", 0)
    _save()
    return {"active_index": proj.transition_active_index}


async def _do_render_transition(proj_id: str, tr: Transition, seed: int,
                                 width: int, height: int, frame_rate: int,
                                 duration_seconds: int):
    """Render a transition video via ComfyUI."""
    from comfyui import download_output, run_workflow, upload_image
    from workflows import TRANSITION_WORKFLOW_PATH, load_workflow, patch_transition_workflow

    async with _render_semaphore:
        try:
            proj = current_project
            if not proj:
                raise RuntimeError("No project loaded")

            # Find keyframe images
            from_kf = next((kf for kf in proj.keyframes if kf.id == tr.from_keyframe_id), None)
            to_kf = next((kf for kf in proj.keyframes if kf.id == tr.to_keyframe_id), None)
            if not from_kf or not to_kf:
                raise RuntimeError("Keyframes not found for transition")
            if not from_kf.image_filename or not to_kf.image_filename:
                raise RuntimeError("Keyframe images not rendered yet")

            # Upload images to ComfyUI
            from_path = os.path.join(images_dir(proj_id), from_kf.image_filename)
            to_path = os.path.join(images_dir(proj_id), to_kf.image_filename)
            first_name = await upload_image(from_path)
            last_name = await upload_image(to_path)

            from llm import _load_style
            style = _load_style("transition-story")
            neg_parts = [style.get("negative_prompt", "")]
            if tr.negative_prompt:
                neg_parts.append(tr.negative_prompt)
            neg_prompt = ", ".join(p for p in neg_parts if p)

            print(f"Rendering transition {tr.id}: seed={seed}, {from_kf.id} -> {to_kf.id}", flush=True)

            base_wf = load_workflow(TRANSITION_WORKFLOW_PATH)
            patched = patch_transition_workflow(
                base_wf,
                first_image_name=first_name,
                last_image_name=last_name,
                prompt_text=tr.prompt,
                negative_prompt_text=neg_prompt,
                seed_value=seed,
                width=width,
                height=height,
                frame_rate=frame_rate,
                duration_seconds=duration_seconds,
                output_prefix=f"v2web/trans_{tr.id}",
            )

            history = await run_workflow(patched, timeout=1200)
            filename = f"{tr.id}.mp4"
            dest = os.path.join(images_dir(proj_id), filename)
            await download_output(history, dest, output_type="video")
            tr.video_filename = filename
            tr.seed = seed
            tr.status = KeyframeStatus.done
            if current_project and current_project.id == proj_id:
                _save()
        except asyncio.CancelledError:
            tr.status = KeyframeStatus.pending
        except Exception as e:
            tr.status = KeyframeStatus.error
            tr.error_message = str(e)
            print(f"Transition render error: {e}", flush=True)


@app.post("/api/transitions/{transition_id}/render")
async def api_render_transition(transition_id: str, req: TransitionRenderRequest | None = None):
    proj = _get_project()
    tr = _get_transition(transition_id)
    seed = (req.seed if req and req.seed is not None else None) or random.randint(0, 2**32 - 1)
    width = req.width if req else 640
    height = req.height if req else 480
    frame_rate = req.frame_rate if req else 25
    duration = req.duration_seconds if req else proj.scene_duration
    old = render_tasks.pop(transition_id, None)
    if old and not old.done():
        old.cancel()
    tr.status = KeyframeStatus.rendering
    tr.error_message = None
    task = asyncio.create_task(
        _do_render_transition(proj.id, tr, seed, width, height, frame_rate, duration)
    )
    render_tasks[transition_id] = task
    return {"id": tr.id, "status": tr.status, "seed": seed}


@app.post("/api/transitions/{transition_id}/rerender")
async def api_rerender_transition(transition_id: str, req: TransitionRenderRequest | None = None):
    _get_transition(transition_id)
    seed = (req.seed if req and req.seed is not None else None) or random.randint(0, 2**32 - 1)
    return await api_render_transition(transition_id, TransitionRenderRequest(seed=seed))


@app.post("/api/transitions/auto-create")
async def api_auto_create_transitions():
    """Render all pending transitions sequentially."""
    proj = _get_project()
    ordered = sorted(proj.transitions, key=lambda t: t.position)
    rendered = 0
    for tr in ordered:
        if tr.status == KeyframeStatus.pending:
            seed = random.randint(0, 2**32 - 1)
            tr.status = KeyframeStatus.rendering
            await _do_render_transition(
                proj.id, tr, seed, 640, 480, 25, proj.scene_duration
            )
            rendered += 1
    proj.transition_active_index = len(ordered)
    _save()
    return {"rendered": rendered, "project": proj.model_dump()}


@app.post("/api/transitions/reset")
async def api_reset_transitions():
    """Re-generate transition descriptions and reset all to pending."""
    proj = _get_project()
    if not proj.keyframes_locked:
        raise HTTPException(400, "Keyframes must be locked first")
    for task in render_tasks.values():
        if not task.done():
            task.cancel()
    render_tasks.clear()
    # Delete rendered videos
    img_dir = images_dir(proj.id)
    for tr in proj.transitions:
        if tr.video_filename:
            path = os.path.join(img_dir, tr.video_filename)
            if os.path.exists(path):
                os.unlink(path)
    # Re-generate descriptions
    from llm import generate_transition_descriptions
    ordered_kf = sorted(proj.keyframes, key=lambda k: k.position)
    prompts = [kf.prompt for kf in ordered_kf]
    descriptions = await generate_transition_descriptions(
        prompts, duration=proj.scene_duration, style=proj.style,
    )
    proj.transitions = []
    for i, desc in enumerate(descriptions):
        proj.transitions.append(Transition(
            position=i,
            from_keyframe_id=ordered_kf[i].id,
            to_keyframe_id=ordered_kf[i + 1].id,
            prompt=desc,
        ))
    proj.transition_active_index = 0
    _save()
    return {"project": proj.model_dump()}


# ── Narration endpoints ────────────────��─────────────────────────────

@app.post("/api/transitions/lock")
async def api_lock_transitions():
    """Lock transitions and generate narration text via LLM."""
    proj = _get_project()
    if not proj.keyframes_locked:
        raise HTTPException(400, "Keyframes must be locked first")
    from llm import generate_narration
    ordered_kf = sorted(proj.keyframes, key=lambda k: k.position)
    ordered_tr = sorted(proj.transitions, key=lambda t: t.position)
    kf_prompts = [kf.prompt for kf in ordered_kf]
    tr_prompts = [tr.prompt for tr in ordered_tr]
    narrations = await generate_narration(
        kf_prompts, tr_prompts, duration=proj.scene_duration, style=proj.style,
        direction=proj.narration_direction,
    )
    for i, tr in enumerate(ordered_tr):
        tr.narration = narrations[i] if i < len(narrations) else ""
    proj.transitions_locked = True
    proj.narration_active_index = 0
    _save()
    return {"project": proj.model_dump()}


@app.put("/api/narration/direction")
async def api_set_narration_direction(body: dict):
    proj = _get_project()
    proj.narration_direction = body.get("direction", "")
    _save()
    return {"direction": proj.narration_direction}


@app.put("/api/narration/{transition_id}")
async def api_update_narration(transition_id: str, body: dict):
    tr = _get_transition(transition_id)
    tr.narration = body.get("narration", tr.narration)
    _save()
    return {"narration": tr.narration}


@app.put("/api/narration-active-index")
async def api_set_narration_active_index(body: dict):
    proj = _get_project()
    proj.narration_active_index = body.get("active_index", 0)
    _save()
    return {"active_index": proj.narration_active_index}


@app.post("/api/narration/regenerate")
async def api_regenerate_narration(body: dict | None = None):
    """Regenerate all narration text, optionally updating direction first."""
    proj = _get_project()
    if body and "direction" in body:
        proj.narration_direction = body["direction"]
    from llm import generate_narration
    ordered_kf = sorted(proj.keyframes, key=lambda k: k.position)
    ordered_tr = sorted(proj.transitions, key=lambda t: t.position)
    kf_prompts = [kf.prompt for kf in ordered_kf]
    tr_prompts = [tr.prompt for tr in ordered_tr]
    narrations = await generate_narration(
        kf_prompts, tr_prompts, duration=proj.scene_duration, style=proj.style,
        direction=proj.narration_direction,
    )
    for i, tr in enumerate(ordered_tr):
        tr.narration = narrations[i] if i < len(narrations) else ""
    proj.narration_active_index = 0
    _save()
    return {"project": proj.model_dump()}


# ── File serving ────────────────────────────────────────────────────

@app.get("/api/projects/{project_id}/images/{filename}")
async def api_get_image(project_id: str, filename: str):
    path = os.path.join(images_dir(project_id), filename)
    if not os.path.isfile(path):
        raise HTTPException(404, "Image not found")
    return FileResponse(path)


@app.get("/api/projects/{project_id}/videos/{filename}")
async def api_get_video(project_id: str, filename: str):
    path = os.path.join(images_dir(project_id), filename)
    if not os.path.isfile(path):
        raise HTTPException(404, "Video not found")
    return FileResponse(path, media_type="video/mp4")


# ── Static frontend (production) ────────────────────────────────────
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
