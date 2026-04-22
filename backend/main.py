"""FastAPI application for the film director."""

import asyncio
import os
import random

from fastapi import FastAPI, File as fastapi_File, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from models import (
    GalleryImage,
    GenerateStoryRequest,
    Keyframe,
    KeyframeStatus,
    RefinementEntry,
    Project,
    RenderRequest,
    SetPremiseRequest,
    SoundtrackSection,
    SuggestPremiseRequest,
    Transition,
    TransitionRenderRequest,
    UpdateKeyframeRequest,
    UpdateTransitionRequest,
)
from projects import delete_project, images_dir, list_projects, load_project, save_project

app = FastAPI(title="Film Director")

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


def _get_section(section_id: str) -> SoundtrackSection:
    proj = _get_project()
    for sec in proj.soundtrack_sections:
        if sec.id == section_id:
            return sec
    raise HTTPException(404, "Soundtrack section not found")


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
async def api_list_projects(activity: str | None = None):
    return {"projects": list_projects(activity=activity)}


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


@app.put("/api/projects/current/resolution")
async def api_set_resolution(body: dict):
    proj = _get_project()
    proj.width = body.get("width", proj.width)
    proj.height = body.get("height", proj.height)
    _save()
    return {"width": proj.width, "height": proj.height}


@app.post("/api/projects/create")
async def api_create_project(body: dict):
    """Create a new project for any activity type."""
    global current_project
    activity = body.get("activity", "film-director")
    name = body.get("name", "Untitled")
    proj = Project(activity=activity, name=name)
    current_project = proj
    _save()
    return {"project": proj.model_dump()}


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
    proj = Project(activity=req.activity, name=name, premise=req.premise, premise_locked=True)
    current_project = proj
    _save()
    return {"project": proj.model_dump()}


# ── Skip to keyframes ──────────────────────────────────────────────

@app.post("/api/skip-to-keyframes")
async def api_skip_to_keyframes(body: dict | None = None):
    """Create a new project that skips premise/story, starting at keyframes."""
    global current_project
    name = (body or {}).get("name", "Freeform Keyframes")
    proj = Project(
        activity="film-director",
        name=name,
        premise="(freeform)",
        premise_locked=True,
        story_locked=True,
        keyframes=[Keyframe(position=0, prompt="")],
        active_index=0,
    )
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
    proj.width = req.width
    proj.height = req.height
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


@app.post("/api/keyframes/add")
async def api_add_keyframe(body: dict | None = None):
    """Add a new blank keyframe at the end."""
    proj = _get_project()
    ordered = sorted(proj.keyframes, key=lambda k: k.position)
    next_pos = (ordered[-1].position + 1) if ordered else 0
    model = "hidream"
    # Inherit model from last keyframe
    if ordered:
        model = ordered[-1].model
    kf = Keyframe(position=next_pos, prompt=body.get("prompt", "") if body else "", model=model)
    proj.keyframes.append(kf)
    _save()
    return kf.model_dump()


@app.post("/api/keyframes/{keyframe_id}/duplicate")
async def api_duplicate_keyframe(keyframe_id: str):
    """Duplicate a keyframe, inserting the copy right after the original."""
    import shutil
    proj = _get_project()
    src = _get_keyframe(keyframe_id)
    ordered = sorted(proj.keyframes, key=lambda k: k.position)

    # Shift positions of keyframes after the source
    for kf in ordered:
        if kf.position > src.position:
            kf.position += 1

    dup = Keyframe(
        position=src.position + 1,
        prompt=src.prompt,
        model=src.model,
        negative_prompt=src.negative_prompt,
        status=KeyframeStatus.done if src.image_filename else KeyframeStatus.pending,
    )

    # Copy the image file if it exists
    if src.image_filename:
        src_path = os.path.join(images_dir(proj.id), src.image_filename)
        if os.path.isfile(src_path):
            dup_filename = f"{dup.id}.png"
            shutil.copy2(src_path, os.path.join(images_dir(proj.id), dup_filename))
            dup.image_filename = dup_filename
            dup.seed = src.seed

    proj.keyframes.append(dup)
    _save()
    return {"keyframe": dup.model_dump(), "keyframes": [k.model_dump() for k in sorted(proj.keyframes, key=lambda k: k.position)]}


@app.get("/api/keyframes/{keyframe_id}/status")
async def api_get_keyframe_status(keyframe_id: str):
    kf = _get_keyframe(keyframe_id)
    proj = _get_project()
    image_url = f"/api/projects/{proj.id}/images/{kf.image_filename}" if kf.image_filename else None
    return {
        "id": kf.id, "status": kf.status, "image_url": image_url,
        "seed": kf.seed, "error_message": kf.error_message,
        "refinement_history": [e.model_dump() for e in kf.refinement_history],
        "refinement_index": kf.refinement_index,
    }


@app.put("/api/keyframes/{keyframe_id}")
async def api_update_keyframe(keyframe_id: str, req: UpdateKeyframeRequest):
    kf = _get_keyframe(keyframe_id)
    if req.prompt is not None:
        kf.prompt = req.prompt
    if req.negative_prompt is not None:
        kf.negative_prompt = req.negative_prompt
    if req.model is not None:
        kf.model = req.model
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
    proj.transitions = []
    proj.transition_active_index = 0
    _save()
    return {"project": proj.model_dump()}


@app.post("/api/transitions/sync")
async def api_sync_transitions():
    """Create transitions for adjacent done keyframe pairs, generate descriptions for new ones."""
    proj = _get_project()
    ordered = sorted(proj.keyframes, key=lambda k: k.position)

    # Find adjacent done pairs
    done_pairs = []
    for i in range(len(ordered) - 1):
        if ordered[i].status == KeyframeStatus.done and ordered[i + 1].status == KeyframeStatus.done:
            done_pairs.append((ordered[i], ordered[i + 1]))

    # Keep existing transitions that still match a done pair
    existing = {(tr.from_keyframe_id, tr.to_keyframe_id): tr for tr in proj.transitions}
    new_transitions = []
    needs_description = []

    for i, (from_kf, to_kf) in enumerate(done_pairs):
        pair = (from_kf.id, to_kf.id)
        if pair in existing:
            tr = existing[pair]
            tr.position = i
            new_transitions.append(tr)
        else:
            tr = Transition(
                position=i,
                from_keyframe_id=from_kf.id,
                to_keyframe_id=to_kf.id,
                prompt="",
            )
            new_transitions.append(tr)
            needs_description.append((i, from_kf, to_kf))

    # Generate descriptions for new transitions (per pair)
    if needs_description:
        from llm import call_llm_text
        for pos, from_kf, to_kf in needs_description:
            try:
                system_prompt = (
                    "You are a visual director writing a MOTION DESCRIPTION for a smooth "
                    "video transition between two keyframe images. Write 1-3 sentences "
                    "describing camera movement, subject motion, and visual transformation. "
                    "Reply with ONLY the description, no quotes."
                )
                user_msg = (f"From: {from_kf.prompt}\n\nTo: {to_kf.prompt}\n\n"
                            f"Duration: {proj.scene_duration} seconds")
                desc = await call_llm_text(system_prompt, user_msg, temperature=0.9)
                new_transitions[pos].prompt = desc
            except Exception as e:
                print(f"Warning: failed to generate description for transition {pos}: {e}", flush=True)

    proj.transitions = new_transitions
    print(f"Sync: {len(done_pairs)} done pairs, {len(new_transitions)} transitions", flush=True)
    _save()
    return {"project": proj.model_dump()}


async def _auto_create_keyframes_task(proj_id: str):
    """Background: render all pending keyframes sequentially."""
    proj = current_project
    if not proj or proj.id != proj_id:
        return
    ordered = sorted(proj.keyframes, key=lambda k: k.position)
    for kf in ordered:
        if kf.status == KeyframeStatus.pending:
            seed = random.randint(0, 2**32 - 1)
            kf.status = KeyframeStatus.rendering
            await _do_render_keyframe(proj_id, kf, seed, proj.width, proj.height)
    proj.active_index = len(ordered)
    _save()


@app.post("/api/keyframes/auto-create")
async def api_auto_create_keyframes():
    """Start rendering all pending keyframes in the background."""
    proj = _get_project()
    # Mark all pending as rendering so frontend shows spinners
    ordered = sorted(proj.keyframes, key=lambda k: k.position)
    count = sum(1 for kf in ordered if kf.status == KeyframeStatus.pending)
    old = render_tasks.pop("auto_kf", None)
    if old and not old.done():
        old.cancel()
    task = asyncio.create_task(_auto_create_keyframes_task(proj.id))
    render_tasks["auto_kf"] = task
    return {"started": count}


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
    from workflows import get_t2i_workflow_and_patcher, load_workflow

    async with _render_semaphore:
        try:
            wf_path, patch_fn = get_t2i_workflow_and_patcher(kf.model)
            base_wf = load_workflow(wf_path)
            from llm import _load_style
            style = _load_style("transition-story")
            neg_parts = [style.get("negative_prompt", "")]
            if kf.negative_prompt:
                neg_parts.append(kf.negative_prompt)
            neg_prompt = ", ".join(p for p in neg_parts if p)

            print(f"Rendering kf {kf.id} ({kf.model}): seed={seed}", flush=True)
            patched = patch_fn(
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
    width = proj.width
    height = proj.height
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
    return await api_render_keyframe(keyframe_id, RenderRequest(seed=seed))


@app.post("/api/keyframes/{keyframe_id}/upload")
async def api_upload_keyframe_image(keyframe_id: str, file: bytes = fastapi_File(...)):
    """Upload a replacement image for a keyframe."""
    proj = _get_project()
    kf = _get_keyframe(keyframe_id)
    filename = f"{kf.id}.png"
    dest = os.path.join(images_dir(proj.id), filename)
    with open(dest, "wb") as f:
        f.write(file)
    kf.image_filename = filename
    kf.seed = random.randint(0, 2**32 - 1)  # Change seed for cache bust
    kf.status = KeyframeStatus.done
    _save()
    return kf.model_dump()


@app.post("/api/keyframes/{keyframe_id}/refine")
async def api_refine_keyframe(keyframe_id: str, body: dict):
    """Refine a keyframe image using Capybara I2I (image-to-image)."""
    import shutil
    proj = _get_project()
    kf = _get_keyframe(keyframe_id)
    prompt = body.get("prompt", "")
    if not prompt.strip():
        raise HTTPException(400, "Refinement prompt is required")
    if not kf.image_filename:
        raise HTTPException(400, "Keyframe has no image to refine")
    source_path = os.path.join(images_dir(proj.id), kf.image_filename)
    if not os.path.isfile(source_path):
        raise HTTPException(400, "Keyframe image file not found")

    old = render_tasks.pop(keyframe_id, None)
    if old and not old.done():
        old.cancel()

    # Snapshot current image into history if this is the first refinement
    if not kf.refinement_history:
        orig_filename = f"{kf.id}_v0.png"
        shutil.copy2(source_path, os.path.join(images_dir(proj.id), orig_filename))
        kf.refinement_history.append(RefinementEntry(
            prompt=kf.prompt, seed=kf.seed, image_filename=orig_filename,
            model=kf.model,
        ))
        kf.refinement_index = 0

    # Truncate any redo entries beyond current index
    kf.refinement_history = kf.refinement_history[:kf.refinement_index + 1]

    # Next version number — the result will be snapshotted after render completes
    version = len(kf.refinement_history)
    version_filename = f"{kf.id}_v{version}.png"

    seed = body.get("seed") or random.randint(0, 2**32 - 1)
    kf.status = KeyframeStatus.rendering
    kf.error_message = None
    _save()

    task = asyncio.create_task(
        _do_refine_keyframe(proj.id, kf, source_path, seed, proj.width, proj.height,
                            prompt.strip(), body.get("negative_prompt", kf.negative_prompt),
                            version_filename)
    )
    render_tasks[keyframe_id] = task
    return {"id": kf.id, "status": kf.status, "seed": seed}


async def _do_refine_keyframe(proj_id: str, kf: Keyframe, source_path: str,
                               seed: int, width: int, height: int,
                               prompt: str, negative_prompt: str,
                               version_filename: str):
    """Refine a keyframe image using Capybara I2I."""
    from comfyui import download_output, run_workflow, upload_image
    from workflows import CAPY_I2I_WORKFLOW_PATH, load_workflow, patch_capybara_i2i_workflow

    async with _render_semaphore:
        try:
            import shutil
            server_name = await upload_image(source_path)
            base_wf = load_workflow(CAPY_I2I_WORKFLOW_PATH)
            neg_prompt = negative_prompt or "blurry, low quality, distorted, ugly, watermark, text"

            print(f"Refining keyframe {kf.id}: seed={seed}", flush=True)
            patched = patch_capybara_i2i_workflow(
                base_wf, input_image_name=server_name,
                prompt_text=prompt, negative_prompt_text=neg_prompt,
                seed_value=seed, width=width, height=height,
                output_prefix=f"v2web/{kf.id}",
            )
            history = await run_workflow(patched, timeout=600)
            filename = f"{kf.id}.png"
            dest = os.path.join(images_dir(proj_id), filename)
            await download_output(history, dest, output_type="images")
            # Snapshot the result for redo support
            shutil.copy2(dest, os.path.join(images_dir(proj_id), version_filename))
            kf.image_filename = filename
            kf.seed = seed
            kf.status = KeyframeStatus.done
            # Record in refinement history and advance index
            kf.refinement_history.append(RefinementEntry(
                prompt=prompt, seed=seed, image_filename=version_filename,
                model="Capybara I2I",
            ))
            kf.refinement_index = len(kf.refinement_history) - 1
            if current_project and current_project.id == proj_id:
                _save()
        except asyncio.CancelledError:
            kf.status = KeyframeStatus.pending
        except Exception as e:
            import traceback
            print(f"ERROR refining keyframe {kf.id}: {traceback.format_exc()}", flush=True)
            kf.status = KeyframeStatus.error
            kf.error_message = str(e)


def _refine_restore(proj, kf, idx):
    """Restore keyframe image from refinement history at given index."""
    import shutil
    entry = kf.refinement_history[idx]
    src = os.path.join(images_dir(proj.id), entry.image_filename)
    dst = os.path.join(images_dir(proj.id), f"{kf.id}.png")
    if os.path.isfile(src):
        shutil.copy2(src, dst)
    kf.image_filename = f"{kf.id}.png"
    kf.seed = entry.seed
    kf.refinement_index = idx
    kf.status = KeyframeStatus.done
    kf.error_message = None


def _refine_response(proj, kf):
    image_url = f"/api/projects/{proj.id}/images/{kf.image_filename}"
    return {
        "id": kf.id, "status": kf.status, "seed": kf.seed,
        "image_url": image_url,
        "refinement_history": [e.model_dump() for e in kf.refinement_history],
        "refinement_index": kf.refinement_index,
    }


@app.post("/api/keyframes/{keyframe_id}/refine-undo")
async def api_refine_undo(keyframe_id: str):
    """Move back one step in refinement history."""
    proj = _get_project()
    kf = _get_keyframe(keyframe_id)
    if kf.refinement_index <= 0:
        raise HTTPException(400, "Nothing to undo")

    old = render_tasks.pop(keyframe_id, None)
    if old and not old.done():
        old.cancel()

    _refine_restore(proj, kf, kf.refinement_index - 1)
    _save()
    return _refine_response(proj, kf)


@app.post("/api/keyframes/{keyframe_id}/refine-redo")
async def api_refine_redo(keyframe_id: str):
    """Move forward one step in refinement history."""
    proj = _get_project()
    kf = _get_keyframe(keyframe_id)
    if kf.refinement_index >= len(kf.refinement_history) - 1:
        raise HTTPException(400, "Nothing to redo")

    old = render_tasks.pop(keyframe_id, None)
    if old and not old.done():
        old.cancel()

    _refine_restore(proj, kf, kf.refinement_index + 1)
    _save()
    return _refine_response(proj, kf)


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
    if req.duration is not None:
        tr.duration = req.duration if req.duration > 0 else None
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
    width = proj.width
    height = proj.height
    frame_rate = req.frame_rate if req else 25
    duration = tr.duration or (req.duration_seconds if req else proj.scene_duration)
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
                proj.id, tr, seed, proj.width, proj.height, 25,
                tr.duration or proj.scene_duration
            )
            rendered += 1
    proj.transition_active_index = len(ordered)
    _save()
    return {"rendered": rendered, "project": proj.model_dump()}


@app.post("/api/transitions/repair")
async def api_repair_transitions():
    """Add missing transitions without removing existing ones."""
    proj = _get_project()
    ordered_kf = sorted(proj.keyframes, key=lambda k: k.position)
    n_expected = len(ordered_kf) - 1
    # Build a map of existing transitions by (from, to) pair
    existing = {(tr.from_keyframe_id, tr.to_keyframe_id): tr for tr in proj.transitions}
    new_transitions = []
    for i in range(n_expected):
        pair = (ordered_kf[i].id, ordered_kf[i + 1].id)
        if pair in existing:
            tr = existing[pair]
            tr.position = i
            new_transitions.append(tr)
        else:
            new_transitions.append(Transition(
                position=i,
                from_keyframe_id=ordered_kf[i].id,
                to_keyframe_id=ordered_kf[i + 1].id,
                prompt="",
            ))
    proj.transitions = new_transitions
    _save()
    return {"project": proj.model_dump()}


@app.post("/api/transitions/reset")
async def api_reset_transitions():
    """Re-generate transition descriptions and reset all to pending."""
    proj = _get_project()
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
    n_expected = len(ordered_kf) - 1
    proj.transitions = []
    for i in range(n_expected):
        desc = descriptions[i] if i < len(descriptions) else ""
        if isinstance(desc, dict):
            desc = " ".join(str(v) for v in desc.values())
        proj.transitions.append(Transition(
            position=i,
            from_keyframe_id=ordered_kf[i].id,
            to_keyframe_id=ordered_kf[i + 1].id,
            prompt=str(desc),
        ))
    proj.transition_active_index = 0
    _save()
    return {"project": proj.model_dump()}


# ── Narration endpoints ────────────────��─────────────────────────────

@app.post("/api/transitions/lock")
async def api_lock_transitions():
    """Lock transitions and generate narration text via LLM."""
    proj = _get_project()
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
    if "direction" in body:
        proj.narration_direction = body["direction"]
    if "voice" in body:
        proj.narration_voice = body["voice"]
    _save()
    return {"direction": proj.narration_direction, "voice": proj.narration_voice}


@app.post("/api/narration/rewrite/{transition_id}")
async def api_rewrite_narration(transition_id: str, body: dict):
    from llm import rewrite_narration
    proj = _get_project()
    tr = _get_transition(transition_id)
    instruction = body.get("instruction", "")
    if not instruction.strip():
        raise HTTPException(400, "Instruction is required")
    new_text = await rewrite_narration(
        tr.narration, instruction,
        direction=proj.narration_direction,
        duration=proj.scene_duration,
    )
    tr.narration = new_text
    tr.narration_status = KeyframeStatus.pending
    tr.narrated_video_filename = None
    _save()
    return {"narration": new_text}


async def _do_render_narration(proj_id: str, tr: Transition, voice: str | None = None):
    """Render TTS audio from narration text, then mux with transition video."""
    import subprocess
    import sys
    from config import settings

    async with _render_semaphore:
        try:
            proj = current_project
            if not proj:
                raise RuntimeError("No project loaded")

            img_dir = images_dir(proj_id)
            if not tr.video_filename:
                raise RuntimeError("Transition video not rendered yet")
            if not tr.narration.strip():
                raise RuntimeError("No narration text")

            video_path = os.path.join(img_dir, tr.video_filename)
            audio_path = os.path.join(img_dir, f"{tr.id}_narration.wav")
            narrated_path = os.path.join(img_dir, f"{tr.id}_narrated.mp4")

            # Resolve tts-demo directory
            tts_dir = settings.tts_demo_dir
            if not tts_dir:
                # Default: sibling directory to the repo
                repo_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
                tts_dir = os.path.join(os.path.dirname(repo_root), "tts-demo")
            tts_script = os.path.join(tts_dir, "tts.py")

            if not os.path.isfile(tts_script):
                raise RuntimeError(f"tts-demo not found at {tts_dir}")

            # 1. Render TTS
            print(f"Rendering TTS for {tr.id}: {tr.narration[:60]!r}", flush=True)
            cmd = [
                sys.executable, tts_script,
                "--url", settings.comfyui_url,
                "--voice", voice or settings.tts_voice,
                "--output", os.path.abspath(audio_path),
                "--seed", str(tr.narration_seed if tr.narration_seed is not None else settings.tts_seed),
                "--token-scale", str(settings.tts_token_scale),
                "--no-play",
                tr.narration,
            ]
            # Pass token via environment (tts.py reads COMFYUI_TOKEN)
            env = {**os.environ}
            if settings.comfyui_token:
                env["COMFYUI_TOKEN"] = settings.comfyui_token

            result = await asyncio.to_thread(
                subprocess.run, cmd, cwd=tts_dir,
                capture_output=True, text=True, timeout=120,
                env=env,
            )
            if result.returncode != 0:
                raise RuntimeError(f"TTS failed: {result.stderr[:500]}")

            tr.audio_filename = f"{tr.id}_narration.wav"

            # 2. Get video duration
            probe = await asyncio.to_thread(
                subprocess.run,
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "csv=p=0", video_path],
                capture_output=True, text=True,
            )
            video_dur = float(probe.stdout.strip()) if probe.returncode == 0 else 10.0

            # Log TTS output duration
            dur_probe = await asyncio.to_thread(
                subprocess.run,
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "csv=p=0", audio_path],
                capture_output=True, text=True,
            )
            tts_dur = dur_probe.stdout.strip() if dur_probe.returncode == 0 else "?"
            print(f"TTS for {tr.id}: text={tr.narration[:50]!r}, audio={tts_dur}s, video={video_dur}s", flush=True)

            # 3. Mux: overlay centered narration audio on video
            # Pad audio to center it within the video duration
            audio_probe = await asyncio.to_thread(
                subprocess.run,
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "csv=p=0", audio_path],
                capture_output=True, text=True,
            )
            audio_dur = float(audio_probe.stdout.strip()) if audio_probe.returncode == 0 else 0

            # Discard original audio, only use narration voice
            # Pad audio with silence to match video duration exactly
            mux_cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", audio_path,
                "-filter_complex",
                f"[1:a]volume=1.0,apad=whole_dur={video_dur:.3f}[vo]",
                "-map", "0:v", "-map", "[vo]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                narrated_path,
            ]

            mux_result = await asyncio.to_thread(
                subprocess.run, mux_cmd,
                capture_output=True, text=True, timeout=120,
            )
            if mux_result.returncode != 0:
                raise RuntimeError(f"Mux failed: {mux_result.stderr[:500]}")

            tr.narrated_video_filename = f"{tr.id}_narrated.mp4"
            tr.narration_status = KeyframeStatus.done
            if current_project and current_project.id == proj_id:
                _save()
            print(f"Narration rendered for {tr.id}", flush=True)

        except asyncio.CancelledError:
            tr.narration_status = KeyframeStatus.pending
        except Exception as e:
            tr.narration_status = KeyframeStatus.error
            tr.narration_error = str(e)
            print(f"Narration render error: {e}", flush=True)


@app.post("/api/narration/{transition_id}/render")
async def api_render_narration(transition_id: str, body: dict | None = None):
    proj = _get_project()
    tr = _get_transition(transition_id)
    voice = tr.narration_voice or (body.get("voice") if body else None)
    # Seed: use provided, or keep existing, or generate new
    if body and "seed" in body and body["seed"] is not None:
        tr.narration_seed = int(body["seed"])
    elif tr.narration_seed is None:
        tr.narration_seed = random.randint(0, 2**32 - 1)
    old = render_tasks.pop(f"narr_{transition_id}", None)
    if old and not old.done():
        old.cancel()
    tr.narration_status = KeyframeStatus.rendering
    tr.narration_error = None
    task = asyncio.create_task(_do_render_narration(proj.id, tr, voice=voice))
    render_tasks[f"narr_{transition_id}"] = task
    return {"id": tr.id, "status": tr.narration_status, "seed": tr.narration_seed}


@app.get("/api/narration/{transition_id}/status")
async def api_get_narration_status(transition_id: str):
    tr = _get_transition(transition_id)
    proj = _get_project()
    video_url = None
    if tr.narrated_video_filename:
        video_url = f"/api/projects/{proj.id}/videos/{tr.narrated_video_filename}"
    return {
        "id": tr.id,
        "status": tr.narration_status,
        "video_url": video_url,
        "seed": tr.narration_seed,
        "error": tr.narration_error,
    }


@app.put("/api/narration/{transition_id}")
async def api_update_narration(transition_id: str, body: dict):
    tr = _get_transition(transition_id)
    text_changed = False
    if "narration" in body and body["narration"] != tr.narration:
        tr.narration = body["narration"]
        text_changed = True
    if "voice" in body:
        tr.narration_voice = body["voice"]
    if "seed" in body:
        tr.narration_seed = int(body["seed"]) if body["seed"] is not None else None
    # Randomize seed when text changes (unless seed explicitly set)
    if text_changed and "seed" not in body:
        tr.narration_seed = random.randint(0, 2**32 - 1)
    _save()
    return tr.model_dump()


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


# ── Soundtrack endpoints ─────────────────────────────────────────────

@app.post("/api/narration/lock")
async def api_lock_narration():
    """Lock narration and create default soundtrack section (all transitions)."""
    proj = _get_project()
    if not proj.transitions_locked:
        raise HTTPException(400, "Transitions must be locked first")
    ordered_tr = sorted(proj.transitions, key=lambda t: t.position)
    # Default: one section with all transitions
    proj.soundtrack_sections = [SoundtrackSection(
        position=0,
        transition_ids=[tr.id for tr in ordered_tr],
    )]
    proj.narration_locked = True
    _save()
    return {"project": proj.model_dump()}


@app.get("/api/soundtrack")
async def api_list_soundtrack():
    proj = _get_project()
    return {"sections": [s.model_dump() for s in proj.soundtrack_sections]}


@app.put("/api/soundtrack/{section_id}")
async def api_update_section(section_id: str, body: dict):
    sec = _get_section(section_id)
    # Track if soundtrack-affecting fields changed (not volume)
    soundtrack_changed = False
    if "seed" in body:
        sec.seed = int(body["seed"]) if body["seed"] is not None else None
    if "prompt" in body and body["prompt"] != sec.prompt:
        sec.prompt = body["prompt"]
        soundtrack_changed = True
    if "bpm" in body and body["bpm"] != sec.bpm:
        sec.bpm = body["bpm"]
        soundtrack_changed = True
    if "keyscale" in body and body["keyscale"] != sec.keyscale:
        sec.keyscale = body["keyscale"]
        soundtrack_changed = True
    if "music_volume" in body:
        sec.music_volume = float(body["music_volume"])
    if "narration_volume" in body:
        sec.narration_volume = float(body["narration_volume"])
    # Randomize seed if soundtrack-affecting fields changed (but not if seed was explicitly set)
    if soundtrack_changed and "seed" not in body:
        sec.seed = random.randint(0, 2**32 - 1)
    _save()
    return sec.model_dump()


@app.post("/api/soundtrack/suggest/{section_id}")
async def api_suggest_soundtrack_prompt(section_id: str):
    """Generate a soundtrack prompt via LLM for a section."""
    from llm import suggest_soundtrack_prompt
    proj = _get_project()
    sec = _get_section(section_id)
    # Gather the scene descriptions for this section's transitions
    tr_map = {tr.id: tr for tr in proj.transitions}
    descriptions = [tr_map[tid].prompt for tid in sec.transition_ids if tid in tr_map]
    prompt = await suggest_soundtrack_prompt(descriptions, premise=proj.premise)
    sec.prompt = prompt
    _save()
    return {"prompt": prompt}


@app.post("/api/soundtrack/split")
async def api_split_sections(body: dict):
    """Split soundtrack into sections. Body: { groups: [[tr_id, ...], [tr_id, ...]] }"""
    proj = _get_project()
    groups = body.get("groups", [])
    if not groups:
        raise HTTPException(400, "Groups required")
    proj.soundtrack_sections = []
    for i, tr_ids in enumerate(groups):
        proj.soundtrack_sections.append(SoundtrackSection(
            position=i,
            transition_ids=tr_ids,
        ))
    _save()
    return {"sections": [s.model_dump() for s in proj.soundtrack_sections]}


@app.post("/api/soundtrack/unsplit")
async def api_unsplit_sections():
    """Reset to a single section with all transitions."""
    proj = _get_project()
    ordered_tr = sorted(proj.transitions, key=lambda t: t.position)
    proj.soundtrack_sections = [SoundtrackSection(
        position=0,
        transition_ids=[tr.id for tr in ordered_tr],
    )]
    _save()
    return {"sections": [s.model_dump() for s in proj.soundtrack_sections]}


@app.get("/api/soundtrack/{section_id}/status")
async def api_get_section_status(section_id: str):
    sec = _get_section(section_id)
    proj = _get_project()
    preview_url = None
    if sec.preview_filename:
        preview_url = f"/api/projects/{proj.id}/videos/{sec.preview_filename}"
    return {
        "id": sec.id, "status": sec.status,
        "preview_url": preview_url,
        "seed": sec.seed,
        "error_message": sec.error_message,
    }


async def _do_mux_section(proj_id: str, sec: SoundtrackSection):
    """Concat narrated clips and mix with existing soundtrack audio."""
    import subprocess

    proj = current_project
    if not proj:
        raise RuntimeError("No project loaded")

    img_dir = images_dir(proj_id)
    audio_path = os.path.join(img_dir, sec.audio_filename) if sec.audio_filename else None
    if not audio_path or not os.path.isfile(audio_path):
        raise RuntimeError("Soundtrack audio not generated yet")

    tr_map = {tr.id: tr for tr in proj.transitions}
    section_transitions = [tr_map[tid] for tid in sec.transition_ids if tid in tr_map]

    narrated_clips = []
    for tr in section_transitions:
        if tr.narrated_video_filename:
            narrated_clips.append(os.path.join(img_dir, tr.narrated_video_filename))
        elif tr.video_filename:
            narrated_clips.append(os.path.join(img_dir, tr.video_filename))

    if not narrated_clips:
        raise RuntimeError("No video clips for section")

    concat_list = os.path.join(img_dir, f"{sec.id}_concat.txt")
    with open(concat_list, "w") as f:
        for clip in narrated_clips:
            f.write(f"file '{os.path.abspath(clip)}'\n")

    concat_video = os.path.join(img_dir, f"{sec.id}_concat.mp4")
    result = await asyncio.to_thread(
        subprocess.run,
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
         "-i", concat_list, "-c", "copy", concat_video],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Concat failed: {result.stderr[:300]}")

    preview_file = f"{sec.id}_preview.mp4"
    preview_path = os.path.join(img_dir, preview_file)

    probe = await asyncio.to_thread(
        subprocess.run,
        ["ffprobe", "-v", "quiet", "-select_streams", "a",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", concat_video],
        capture_output=True, text=True,
    )
    has_audio = bool(probe.stdout.strip())

    mv = sec.music_volume
    nv = sec.narration_volume
    if has_audio:
        mux_cmd = [
            "ffmpeg", "-y",
            "-i", concat_video, "-i", audio_path,
            "-filter_complex",
            f"[0:a]volume={nv}[voice];[1:a]volume={mv}[music];"
            f"[voice][music]amix=inputs=2:duration=first[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", preview_path,
        ]
    else:
        mux_cmd = [
            "ffmpeg", "-y",
            "-i", concat_video, "-i", audio_path,
            "-filter_complex", f"[1:a]volume={mv}[music]",
            "-map", "0:v", "-map", "[music]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", preview_path,
        ]

    result = await asyncio.to_thread(
        subprocess.run, mux_cmd, capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Mux failed: {result.stderr[:300]}")

    sec.preview_filename = preview_file

    for f in [concat_list, concat_video]:
        if os.path.exists(f):
            os.unlink(f)


async def _do_render_soundtrack(proj_id: str, sec: SoundtrackSection):
    """Generate soundtrack via AceStep, then mux with narrated clips."""
    from comfyui import download_output, run_workflow
    from workflows import AUDIO_WORKFLOW_PATH, load_workflow, patch_audio_workflow

    async with _render_semaphore:
        try:
            proj = current_project
            if not proj:
                raise RuntimeError("No project loaded")

            img_dir = images_dir(proj_id)
            seed = sec.seed if sec.seed is not None else random.randint(0, 2**32 - 1)
            sec.seed = seed

            tr_map = {tr.id: tr for tr in proj.transitions}
            section_transitions = [tr_map[tid] for tid in sec.transition_ids if tid in tr_map]
            total_duration = len(section_transitions) * proj.scene_duration

            print(f"Rendering soundtrack {sec.id}: {sec.prompt[:60]!r}, {total_duration}s", flush=True)
            base_wf = load_workflow(AUDIO_WORKFLOW_PATH)
            patched = patch_audio_workflow(
                base_wf, prompt_text=sec.prompt, seed_value=seed,
                duration_seconds=total_duration, bpm=sec.bpm,
                keyscale=sec.keyscale,
                output_prefix=f"v2web/soundtrack_{sec.id}",
            )
            history = await run_workflow(patched, timeout=1200)
            audio_file = f"{sec.id}_soundtrack.wav"
            audio_path = os.path.join(img_dir, audio_file)
            await download_output(history, audio_path, output_type="audio")
            sec.audio_filename = audio_file

            await _do_mux_section(proj_id, sec)

            sec.status = KeyframeStatus.done
            if current_project and current_project.id == proj_id:
                _save()
            print(f"Soundtrack rendered for section {sec.id}", flush=True)

        except asyncio.CancelledError:
            sec.status = KeyframeStatus.pending
        except Exception as e:
            sec.status = KeyframeStatus.error
            sec.error_message = str(e)
            print(f"Soundtrack render error: {e}", flush=True)


async def _do_remux_section(proj_id: str, sec: SoundtrackSection):
    """Re-mux existing soundtrack with adjusted volumes (no AceStep)."""
    async with _render_semaphore:
        try:
            print(f"Remuxing section {sec.id}: music={sec.music_volume}, narration={sec.narration_volume}", flush=True)
            await _do_mux_section(proj_id, sec)
            sec.status = KeyframeStatus.done
            if current_project and current_project.id == proj_id:
                _save()
        except asyncio.CancelledError:
            sec.status = KeyframeStatus.pending
        except Exception as e:
            sec.status = KeyframeStatus.error
            sec.error_message = str(e)
            print(f"Remux error: {e}", flush=True)


@app.post("/api/soundtrack/{section_id}/render")
async def api_render_soundtrack(section_id: str, body: dict | None = None):
    proj = _get_project()
    sec = _get_section(section_id)
    if not sec.prompt.strip():
        raise HTTPException(400, "Soundtrack prompt is required")
    # Use provided seed, or keep existing, or generate new
    if body and "seed" in body and body["seed"] is not None:
        sec.seed = int(body["seed"])
    elif sec.seed is None:
        sec.seed = random.randint(0, 2**32 - 1)
    old = render_tasks.pop(f"snd_{section_id}", None)
    if old and not old.done():
        old.cancel()
    sec.status = KeyframeStatus.rendering
    sec.error_message = None
    task = asyncio.create_task(_do_render_soundtrack(proj.id, sec))
    render_tasks[f"snd_{section_id}"] = task
    return {"id": sec.id, "status": sec.status, "seed": sec.seed}


@app.post("/api/soundtrack/{section_id}/remux")
async def api_remux_soundtrack(section_id: str, body: dict | None = None):
    """Re-mux with existing soundtrack audio at new volume levels."""
    proj = _get_project()
    sec = _get_section(section_id)
    if not sec.audio_filename:
        raise HTTPException(400, "No soundtrack audio — render first")
    if body:
        if "music_volume" in body:
            sec.music_volume = float(body["music_volume"])
        if "narration_volume" in body:
            sec.narration_volume = float(body["narration_volume"])
        _save()
    old = render_tasks.pop(f"snd_{section_id}", None)
    if old and not old.done():
        old.cancel()
    sec.status = KeyframeStatus.rendering
    sec.error_message = None
    task = asyncio.create_task(_do_remux_section(proj.id, sec))
    render_tasks[f"snd_{section_id}"] = task
    return {"id": sec.id, "status": sec.status}


# ── Final assembly ──────────────────────────────────────────────────

@app.post("/api/score/lock")
async def api_lock_score():
    """Lock the score and proceed to final assembly."""
    proj = _get_project()
    if not proj.narration_locked:
        raise HTTPException(400, "Narration must be locked first")
    proj.score_locked = True
    _save()
    return {"project": proj.model_dump()}


@app.post("/api/final/render")
async def api_render_final():
    """Assemble all scored sections into one final video."""
    proj = _get_project()
    if not proj.score_locked:
        raise HTTPException(400, "Score must be locked first")

    import subprocess
    img_dir = images_dir(proj.id)

    # Collect preview files from all sections in order
    ordered = sorted(proj.soundtrack_sections, key=lambda s: s.position)
    clips = []
    for sec in ordered:
        if sec.preview_filename:
            clips.append(os.path.join(img_dir, sec.preview_filename))

    if not clips:
        raise HTTPException(400, "No scored sections to assemble")

    # Concat all section previews
    concat_list = os.path.join(img_dir, "final_concat.txt")
    with open(concat_list, "w") as f:
        for clip in clips:
            f.write(f"file '{os.path.abspath(clip)}'\n")

    final_file = f"{proj.name.replace(' ', '_')}.mp4"
    final_path = os.path.join(img_dir, final_file)

    result = await asyncio.to_thread(
        subprocess.run,
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
         "-i", concat_list, "-c", "copy", final_path],
        capture_output=True, text=True, timeout=120,
    )
    if os.path.exists(concat_list):
        os.unlink(concat_list)

    if result.returncode != 0:
        raise HTTPException(500, f"Assembly failed: {result.stderr[:300]}")

    proj.final_filename = final_file
    _save()
    return {
        "filename": final_file,
        "url": f"/api/projects/{proj.id}/videos/{final_file}",
    }


@app.get("/api/final/status")
async def api_final_status():
    proj = _get_project()
    url = None
    if proj.final_filename:
        url = f"/api/projects/{proj.id}/videos/{proj.final_filename}"
    return {"filename": proj.final_filename, "url": url}


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


# ── Image Generator endpoints ───────────────────────────────────────


def _get_gallery_image(image_id: str) -> GalleryImage:
    proj = _get_project()
    for img in proj.images:
        if img.id == image_id:
            return img
    raise HTTPException(404, "Gallery image not found")


async def _do_render_gallery_image(proj_id: str, img: GalleryImage, seed: int):
    """Render a gallery image in the background."""
    from comfyui import download_output, run_workflow
    from workflows import get_t2i_workflow_and_patcher, load_workflow

    print(f"Gallery render task started for {img.id}, waiting for semaphore...", flush=True)
    async with _render_semaphore:
        print(f"Gallery render task acquired semaphore for {img.id}", flush=True)
        try:
            wf_path, patch_fn = get_t2i_workflow_and_patcher(img.model)
            base_wf = load_workflow(wf_path)
            from llm import _load_style
            style = _load_style("transition-story")
            neg_parts = [style.get("negative_prompt", "")]
            if img.negative_prompt:
                neg_parts.append(img.negative_prompt)
            neg_prompt = ", ".join(p for p in neg_parts if p)

            print(f"Rendering gallery image {img.id} ({img.model}): seed={seed}", flush=True)
            patched = patch_fn(
                base_wf, prompt_text=img.prompt, negative_prompt_text=neg_prompt,
                seed_value=seed, width=img.width, height=img.height,
                output_prefix=f"v2web/{img.id}",
            )
            history = await run_workflow(patched, timeout=600)
            filename = f"{img.id}.png"
            dest = os.path.join(images_dir(proj_id), filename)
            await download_output(history, dest, output_type="images")
            img.image_filename = filename
            img.seed = seed
            img.status = KeyframeStatus.done
            if current_project and current_project.id == proj_id:
                _save()
        except asyncio.CancelledError:
            img.status = KeyframeStatus.pending
        except Exception as e:
            import traceback
            print(f"ERROR rendering gallery image {img.id}: {traceback.format_exc()}", flush=True)
            img.status = KeyframeStatus.error
            img.error_message = str(e)


def _preview_images(proj: Project) -> list[GalleryImage]:
    """Return preview stack entries sorted by index."""
    previews = [i for i in proj.images if i.id.startswith("preview_")]
    previews.sort(key=lambda i: int(i.id.split("_")[1]))
    return previews


def _next_preview_id(proj: Project) -> str:
    previews = _preview_images(proj)
    idx = int(previews[-1].id.split("_")[1]) + 1 if previews else 0
    return f"preview_{idx}"


def _clear_preview_stack(proj: Project):
    """Remove all preview entries and their files."""
    for img in list(proj.images):
        if img.id.startswith("preview_"):
            if img.image_filename:
                path = os.path.join(images_dir(proj.id), img.image_filename)
                if os.path.exists(path):
                    os.unlink(path)
    proj.images = [i for i in proj.images if not i.id.startswith("preview_")]


@app.post("/api/gallery/generate")
async def api_gallery_generate(body: dict):
    """Generate a preview image. Creates the project if needed. Clears any existing preview stack."""
    global current_project
    proj = current_project
    if proj is None or proj.activity != "image-generator":
        proj = Project(activity="image-generator", name=body.get("name", "Untitled Gallery"))
        current_project = proj

    prompt = body.get("prompt", "")
    if not prompt.strip():
        raise HTTPException(400, "Prompt is required")

    # Cancel any previous preview render
    old = render_tasks.pop("gallery_preview", None)
    if old and not old.done():
        old.cancel()

    # Clear previous preview stack
    _clear_preview_stack(proj)

    seed = body.get("seed") or random.randint(0, 2**32 - 1)
    preview_id = "preview_0"
    img = GalleryImage(
        id=preview_id,
        prompt=prompt.strip(),
        negative_prompt=body.get("negative_prompt", ""),
        model=body.get("model", "hidream"),
        width=body.get("width", 1024),
        height=body.get("height", 576),
        seed=seed,
        status=KeyframeStatus.rendering,
    )
    proj.images.insert(0, img)
    _save()

    task = asyncio.create_task(_do_render_gallery_image(proj.id, img, seed))
    render_tasks["gallery_preview"] = task
    return {"project": proj.model_dump(), "preview_id": preview_id}


@app.get("/api/gallery/preview/status")
async def api_gallery_preview_status():
    proj = _get_project()
    previews = _preview_images(proj)
    if not previews:
        raise HTTPException(404, "No preview")
    img = previews[-1]  # Latest preview
    image_url = f"/api/projects/{proj.id}/images/{img.image_filename}" if img.image_filename else None
    return {
        "id": img.id, "status": img.status, "image_url": image_url,
        "seed": img.seed, "error_message": img.error_message,
    }


@app.post("/api/gallery/cancel")
async def api_gallery_cancel():
    """Cancel the current preview render and remove the in-progress entry."""
    task = render_tasks.pop("gallery_preview", None)
    if task and not task.done():
        task.cancel()
    proj = _get_project()
    # Remove the latest preview if it's still rendering
    previews = _preview_images(proj)
    if previews and previews[-1].status == KeyframeStatus.rendering:
        proj.images = [i for i in proj.images if i.id != previews[-1].id]
    _save()
    # Return info about the now-current preview (if any)
    previews = _preview_images(proj)
    if previews:
        img = previews[-1]
        image_url = f"/api/projects/{proj.id}/images/{img.image_filename}" if img.image_filename else None
        return {"cancelled": True, "current": {
            "id": img.id, "status": img.status, "image_url": image_url, "seed": img.seed,
        }}
    return {"cancelled": True, "current": None}


async def _do_refine_gallery_image(proj_id: str, img: GalleryImage,
                                    source_path: str, seed: int):
    """Refine a gallery image using Capybara I2I in the background."""
    from comfyui import download_output, run_workflow, upload_image
    from workflows import CAPY_I2I_WORKFLOW_PATH, load_workflow, patch_capybara_i2i_workflow

    async with _render_semaphore:
        try:
            server_name = await upload_image(source_path)
            base_wf = load_workflow(CAPY_I2I_WORKFLOW_PATH)
            neg_prompt = img.negative_prompt or "blurry, low quality, distorted, ugly, watermark, text"

            print(f"Refining gallery image {img.id}: seed={seed}", flush=True)
            patched = patch_capybara_i2i_workflow(
                base_wf, input_image_name=server_name,
                prompt_text=img.prompt, negative_prompt_text=neg_prompt,
                seed_value=seed, width=img.width, height=img.height,
                output_prefix=f"v2web/{img.id}",
            )
            history = await run_workflow(patched, timeout=600)
            filename = f"{img.id}.png"
            dest = os.path.join(images_dir(proj_id), filename)
            await download_output(history, dest, output_type="images")
            img.image_filename = filename
            img.seed = seed
            img.status = KeyframeStatus.done
            if current_project and current_project.id == proj_id:
                _save()
        except asyncio.CancelledError:
            img.status = KeyframeStatus.pending
        except Exception as e:
            import traceback
            print(f"ERROR refining gallery image {img.id}: {traceback.format_exc()}", flush=True)
            img.status = KeyframeStatus.error
            img.error_message = str(e)


@app.post("/api/gallery/refine")
async def api_gallery_refine(body: dict):
    """Refine the current preview image with a new prompt using Capybara I2I."""
    proj = _get_project()
    prompt = body.get("prompt", "")
    if not prompt.strip():
        raise HTTPException(400, "Refinement prompt is required")

    previews = _preview_images(proj)
    if not previews or not previews[-1].image_filename:
        raise HTTPException(400, "No preview image to refine")

    source = previews[-1]
    source_path = os.path.join(images_dir(proj.id), source.image_filename)
    if not os.path.isfile(source_path):
        raise HTTPException(400, "Preview image file not found")

    # Cancel any previous preview render
    old = render_tasks.pop("gallery_preview", None)
    if old and not old.done():
        old.cancel()

    seed = body.get("seed") or random.randint(0, 2**32 - 1)
    preview_id = _next_preview_id(proj)
    img = GalleryImage(
        id=preview_id,
        prompt=prompt.strip(),
        negative_prompt=body.get("negative_prompt", source.negative_prompt),
        model="capybara_i2i",
        width=source.width,
        height=source.height,
        seed=seed,
        status=KeyframeStatus.rendering,
    )
    proj.images.append(img)

    task = asyncio.create_task(_do_refine_gallery_image(proj.id, img, source_path, seed))
    render_tasks["gallery_preview"] = task
    return {"status": "rendering", "seed": seed, "preview_id": preview_id}


@app.post("/api/gallery/undo")
async def api_gallery_undo():
    """Remove the latest preview entry and revert to the previous one."""
    proj = _get_project()
    previews = _preview_images(proj)
    if len(previews) <= 1:
        raise HTTPException(400, "Nothing to undo")

    # Cancel any in-progress render
    old = render_tasks.pop("gallery_preview", None)
    if old and not old.done():
        old.cancel()

    # Remove the latest preview and its file
    latest = previews[-1]
    if latest.image_filename:
        path = os.path.join(images_dir(proj.id), latest.image_filename)
        if os.path.exists(path):
            os.unlink(path)
    proj.images = [i for i in proj.images if i.id != latest.id]
    _save()

    # Return the now-current preview
    current = _preview_images(proj)[-1]
    image_url = f"/api/projects/{proj.id}/images/{current.image_filename}" if current.image_filename else None
    return {
        "id": current.id, "status": current.status, "image_url": image_url,
        "seed": current.seed,
    }


@app.post("/api/gallery/edit/{image_id}")
async def api_gallery_edit(image_id: str):
    """Copy a saved gallery image into the preview stack for refinement."""
    import shutil
    proj = _get_project()
    img = _get_gallery_image(image_id)
    if not img.image_filename:
        raise HTTPException(400, "Image has no file")

    source_path = os.path.join(images_dir(proj.id), img.image_filename)
    if not os.path.isfile(source_path):
        raise HTTPException(400, "Image file not found")

    # Cancel any previous preview render
    old = render_tasks.pop("gallery_preview", None)
    if old and not old.done():
        old.cancel()

    # Clear previous preview stack
    _clear_preview_stack(proj)

    preview_id = "preview_0"
    preview_filename = f"{preview_id}.png"
    dest_path = os.path.join(images_dir(proj.id), preview_filename)
    shutil.copy2(source_path, dest_path)

    preview = GalleryImage(
        id=preview_id,
        prompt=img.prompt,
        negative_prompt=img.negative_prompt,
        model=img.model,
        width=img.width,
        height=img.height,
        seed=img.seed,
        image_filename=preview_filename,
        status=KeyframeStatus.done,
    )
    proj.images.insert(0, preview)
    _save()

    image_url = f"/api/projects/{proj.id}/images/{preview_filename}"
    return {
        "project": proj.model_dump(),
        "image_url": image_url,
        "seed": img.seed,
        "prompt": img.prompt,
        "negative_prompt": img.negative_prompt or "",
        "model": img.model,
        "width": img.width,
        "height": img.height,
    }


@app.post("/api/gallery/save")
async def api_gallery_save():
    """Save the latest preview to the gallery with a permanent ID. Clears the preview stack."""
    proj = _get_project()
    previews = _preview_images(proj)
    if not previews or previews[-1].status != KeyframeStatus.done:
        raise HTTPException(400, "No completed preview to save")

    import uuid as _uuid
    latest = previews[-1]
    new_id = _uuid.uuid4().hex[:12]

    # Rename the latest preview file
    old_path = os.path.join(images_dir(proj.id), latest.image_filename)
    new_filename = f"{new_id}.png"
    new_path = os.path.join(images_dir(proj.id), new_filename)
    if os.path.exists(old_path):
        os.rename(old_path, new_path)

    latest.id = new_id
    latest.image_filename = new_filename

    # Remove all other preview entries and their files
    for img in previews[:-1]:
        if img.image_filename:
            path = os.path.join(images_dir(proj.id), img.image_filename)
            if os.path.exists(path):
                os.unlink(path)
    proj.images = [i for i in proj.images if not i.id.startswith("preview_")]
    _save()
    return {"image": latest.model_dump(), "project": proj.model_dump()}


@app.get("/api/gallery")
async def api_gallery_list():
    proj = _get_project()
    results = []
    for img in proj.images:
        if img.id.startswith("preview"):
            continue
        image_url = f"/api/projects/{proj.id}/images/{img.image_filename}" if img.image_filename else None
        results.append({**img.model_dump(), "image_url": image_url})
    return {"images": results}


@app.delete("/api/gallery/{image_id}")
async def api_gallery_delete(image_id: str):
    proj = _get_project()
    img = _get_gallery_image(image_id)
    if img.image_filename:
        path = os.path.join(images_dir(proj.id), img.image_filename)
        if os.path.exists(path):
            os.unlink(path)
    proj.images = [i for i in proj.images if i.id != image_id]
    _save()
    return {"deleted": image_id}


@app.post("/api/gallery/upload")
async def api_gallery_upload(file: bytes = fastapi_File(...)):
    """Upload an image directly to the gallery."""
    global current_project
    proj = current_project
    if proj is None or proj.activity != "image-generator":
        proj = Project(activity="image-generator", name="Untitled Gallery")
        current_project = proj

    import uuid as _uuid
    new_id = _uuid.uuid4().hex[:12]
    filename = f"{new_id}.png"
    dest = os.path.join(images_dir(proj.id), filename)
    with open(dest, "wb") as f:
        f.write(file)

    # Detect dimensions
    width, height = 0, 0
    try:
        from PIL import Image as PILImage
        with PILImage.open(dest) as pil_img:
            width, height = pil_img.size
    except Exception:
        pass

    img = GalleryImage(
        id=new_id,
        prompt="(uploaded)",
        model="upload",
        width=width,
        height=height,
        image_filename=filename,
        status=KeyframeStatus.done,
    )
    proj.images.append(img)
    _save()
    image_url = f"/api/projects/{proj.id}/images/{filename}"
    return {"image": {**img.model_dump(), "image_url": image_url}, "project": proj.model_dump()}


# ── Favicon ─────────────────────────────────────────────────────────
FAVICON_PATH = os.path.join(os.path.dirname(__file__), "..", "frontend", "public", "favicon.svg")


@app.get("/favicon.ico")
async def favicon():
    if os.path.isfile(FAVICON_PATH):
        return FileResponse(FAVICON_PATH, media_type="image/svg+xml")
    raise HTTPException(404)


# ── Static frontend (production) ────────────────────────────────────
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
