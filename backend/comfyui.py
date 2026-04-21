"""Async ComfyUI HTTP API client.

Uses httpx for async I/O and returns values instead of writing to stdout.
"""

import asyncio
import json
import os
import uuid

import httpx

from config import settings


def _auth_headers() -> dict[str, str]:
    if settings.comfyui_token:
        return {"Authorization": f"Bearer {settings.comfyui_token}"}
    return {}


def _client(**kwargs) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.comfyui_url,
        headers=_auth_headers(),
        timeout=30.0,
        follow_redirects=True,
        **kwargs,
    )


async def queue_prompt(workflow: dict, client_id: str | None = None) -> dict:
    """Submit a workflow prompt to ComfyUI. Returns response with prompt_id."""
    if client_id is None:
        client_id = uuid.uuid4().hex
    async with _client() as c:
        resp = await c.post(
            "/api/prompt",
            json={"prompt": workflow, "client_id": client_id},
        )
        resp.raise_for_status()
        return resp.json()


async def get_history(prompt_id: str) -> dict:
    async with _client() as c:
        resp = await c.get(f"/api/history/{prompt_id}")
        resp.raise_for_status()
        return resp.json()


async def poll_until_done(prompt_id: str, timeout: int = 600) -> dict:
    """Poll ComfyUI until the prompt completes or fails."""
    import time
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        history = await get_history(prompt_id)
        if prompt_id in history:
            status = history[prompt_id].get("status", {})
            if status.get("completed", False) or status.get("status_str") == "success":
                return history[prompt_id]
            if status.get("status_str") == "error":
                msgs = status.get("messages", [])
                raise RuntimeError(f"Workflow failed: {msgs}")
        await asyncio.sleep(2)
    raise TimeoutError(f"Workflow did not complete within {timeout}s")


async def download_output(history_entry: dict, dest_path: str,
                          output_type: str = "images") -> str:
    """Download the first output from a completed workflow."""
    outputs = history_entry.get("outputs", {})
    for node_id, node_out in outputs.items():
        for key in (output_type, "images", "video", "gifs"):
            if key in node_out:
                for item in node_out[key]:
                    filename = item["filename"]
                    subfolder = item.get("subfolder", "")
                    filetype = item.get("type", "output")
                    params = {
                        "filename": filename,
                        "subfolder": subfolder,
                        "type": filetype,
                    }
                    async with _client() as c:
                        resp = await c.get("/api/view", params=params)
                        resp.raise_for_status()
                        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                        with open(dest_path, "wb") as f:
                            f.write(resp.content)
                    return dest_path
    raise RuntimeError(
        f"No output found. Available keys: "
        f"{[(nid, list(no.keys())) for nid, no in outputs.items()]}"
    )


async def upload_image(image_path: str, subfolder: str = "",
                       overwrite: bool = True) -> str:
    """Upload an image to ComfyUI's input folder. Returns server filename."""
    import mimetypes
    filename = os.path.basename(image_path)
    content_type = mimetypes.guess_type(image_path)[0] or "image/png"

    with open(image_path, "rb") as f:
        image_data = f.read()

    async with _client() as c:
        resp = await c.post(
            "/api/upload/image",
            files={"image": (filename, image_data, content_type)},
            data={
                "subfolder": subfolder,
                "overwrite": "true" if overwrite else "false",
            },
        )
        resp.raise_for_status()
        result = resp.json()
    return result.get("name", filename)


async def run_workflow(workflow: dict, timeout: int = 600) -> dict:
    """Submit a workflow and wait for completion. Returns history entry."""
    client_id = uuid.uuid4().hex
    result = await queue_prompt(workflow, client_id)
    prompt_id = result["prompt_id"]
    return await poll_until_done(prompt_id, timeout=timeout)


async def cancel_queue():
    """Cancel all queued and running prompts."""
    async with _client() as c:
        await c.post("/api/interrupt", json={})
        try:
            await c.post("/api/queue", json={"clear": True})
        except Exception:
            pass
