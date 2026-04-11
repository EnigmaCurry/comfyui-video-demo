"""ComfyUI HTTP API client for video workflows."""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")
COMFYUI_TOKEN = os.environ.get("COMFYUI_TOKEN", "")


def _auth_headers():
    """Return auth headers dict if a token is configured."""
    if COMFYUI_TOKEN:
        return {"Authorization": f"Bearer {COMFYUI_TOKEN}"}
    return {}


def _authed_request(url, **kwargs):
    """Create a urllib Request with auth headers."""
    headers = kwargs.pop("headers", {})
    headers.update(_auth_headers())
    return urllib.request.Request(url, headers=headers, **kwargs)


def _urlopen(req_or_url):
    """Open a URL or Request, adding auth headers if given a plain URL string."""
    if isinstance(req_or_url, str):
        req_or_url = _authed_request(req_or_url)
    return urllib.request.urlopen(req_or_url)


def post_json(url, payload):
    """POST JSON, following redirects while preserving the body."""
    data = json.dumps(payload).encode()
    for _ in range(5):
        req = _authed_request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 307, 308):
                url = e.headers["Location"]
            else:
                body = e.read().decode(errors="replace")
                raise RuntimeError(f"HTTP {e.code} {e.reason}: {body}") from e
    raise RuntimeError(f"Too many redirects for {url}")


def queue_prompt(base_url, prompt, client_id=None):
    """Submit a workflow prompt to ComfyUI. Returns response with prompt_id."""
    if client_id is None:
        client_id = str(uuid.uuid4())
    return post_json(
        f"{base_url}/api/prompt",
        {"prompt": prompt, "client_id": client_id},
    )


def get_history(base_url, prompt_id):
    """Get execution history for a prompt."""
    with _urlopen(f"{base_url}/api/history/{prompt_id}") as resp:
        return json.loads(resp.read())


def poll_until_done(base_url, prompt_id, timeout=600):
    """Poll ComfyUI until the prompt completes or fails."""
    start = time.time()
    while time.time() - start < timeout:
        history = get_history(base_url, prompt_id)
        if prompt_id in history:
            status = history[prompt_id].get("status", {})
            if status.get("completed", False) or status.get("status_str") == "success":
                return history[prompt_id]
            if status.get("status_str") == "error":
                msgs = status.get("messages", [])
                raise RuntimeError(f"Workflow failed: {msgs}")
        time.sleep(2)
        sys.stdout.write(".")
        sys.stdout.flush()
    raise TimeoutError(f"Workflow did not complete within {timeout}s")


def download_output(base_url, history_entry, dest_path, output_type="video"):
    """Download the first video/image output from a completed workflow.

    output_type: key to look for in node outputs ("video", "images", "gifs")
    """
    outputs = history_entry.get("outputs", {})
    for node_id, node_out in outputs.items():
        for key in (output_type, "video", "gifs", "images"):
            if key in node_out:
                for item in node_out[key]:
                    filename = item["filename"]
                    subfolder = item.get("subfolder", "")
                    filetype = item.get("type", "output")
                    params = urllib.parse.urlencode(
                        {"filename": filename, "subfolder": subfolder, "type": filetype}
                    )
                    url = f"{base_url}/api/view?{params}"
                    req = _authed_request(url)
                    with urllib.request.urlopen(req) as resp:
                        with open(dest_path, "wb") as out_f:
                            out_f.write(resp.read())
                    return dest_path
    raise RuntimeError(
        f"No output found in workflow results. "
        f"Available output keys: {[(nid, list(no.keys())) for nid, no in outputs.items()]}"
    )


def upload_image(base_url, image_path, subfolder="", overwrite=True):
    """Upload an image to ComfyUI's input folder.

    Returns the filename as stored on the server.
    """
    import mimetypes

    filename = os.path.basename(image_path)
    content_type = mimetypes.guess_type(image_path)[0] or "image/png"

    boundary = uuid.uuid4().hex
    with open(image_path, "rb") as f:
        image_data = f.read()

    body = b""
    # image field
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'.encode()
    body += f"Content-Type: {content_type}\r\n\r\n".encode()
    body += image_data
    body += b"\r\n"
    # subfolder field
    if subfolder:
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="subfolder"\r\n\r\n'.encode()
        body += subfolder.encode()
        body += b"\r\n"
    # overwrite field
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="overwrite"\r\n\r\n'.encode()
    body += b"true" if overwrite else b"false"
    body += b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    req = _authed_request(
        f"{base_url}/api/upload/image",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
    return result.get("name", filename)


def cancel_queue(base_url):
    """Cancel all queued and running prompts on the ComfyUI server."""
    post_json(f"{base_url}/api/interrupt", {})
    try:
        post_json(f"{base_url}/api/queue", {"clear": True})
    except Exception:
        pass


def run_workflow(base_url, workflow, timeout=600):
    """Submit a workflow and wait for completion. Returns history entry."""
    client_id = str(uuid.uuid4())
    result = queue_prompt(base_url, workflow, client_id)
    prompt_id = result["prompt_id"]
    print(f"  queued: {prompt_id}")
    try:
        history = poll_until_done(base_url, prompt_id, timeout=timeout)
    except KeyboardInterrupt:
        print("\n  interrupted — cancelling job on ComfyUI...")
        cancel_queue(base_url)
        raise
    print()
    return history
