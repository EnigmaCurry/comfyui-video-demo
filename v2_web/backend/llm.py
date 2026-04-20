"""Async LLM client for generating keyframe descriptions.

Adapted from v1_tui/write_script.py — uses httpx for async streaming,
returns parsed data instead of writing files.
"""

import json
import os
import re

import httpx

from config import settings


def _load_style(name: str) -> dict:
    style_path = os.path.join(os.path.dirname(__file__), "styles", f"{name}.json")
    with open(style_path) as f:
        return json.load(f)


def _salvage_json_array(text: str) -> list[str] | None:
    """Try to recover complete items from a truncated JSON array."""
    matches = re.findall(r'"((?:[^"\\]|\\.)*)"', text)
    if not matches:
        return None
    for i in range(len(matches), 0, -1):
        attempt = json.dumps(matches[:i])
        try:
            return json.loads(attempt)
        except json.JSONDecodeError:
            continue
    return None


async def call_llm(system_prompt: str, user_msg: str,
                   temperature: float = 0.9) -> list[str]:
    """Call the LLM with streaming and return parsed JSON array."""
    payload = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        "temperature": temperature,
        "max_tokens": 16384,
        "stream": True,
    }

    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"

    url = f"{settings.llm_url}/v1/chat/completions"
    content = ""

    async with httpx.AsyncClient(timeout=600.0) as client:
        # Try streaming first
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            raw_lines = []
            async for line in resp.aiter_lines():
                raw_lines.append(line)
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk["choices"][0].get("delta", {})
                    content += delta.get("content", "")
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

        # If streaming yielded nothing, try parsing the raw response as
        # a non-streaming JSON response (some APIs ignore stream=true)
        if not content and raw_lines:
            full_body = "\n".join(raw_lines)
            try:
                resp_json = json.loads(full_body)
                content = resp_json["choices"][0]["message"]["content"]
            except (json.JSONDecodeError, KeyError, IndexError):
                import logging
                logging.error("LLM: no content from stream. Raw (%d lines): %s",
                              len(raw_lines), full_body[:1000])

    if not content:
        # Fall back to a non-streaming request
        import logging
        logging.info("LLM: retrying without streaming")
        payload["stream"] = False
        async with httpx.AsyncClient(timeout=600.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            resp_json = resp.json()
            content = resp_json["choices"][0]["message"]["content"]

    # Parse JSON (handle markdown code blocks)
    text = content.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        items = json.loads(text)
    except json.JSONDecodeError:
        items = _salvage_json_array(text)
        if items is None:
            raise ValueError(f"LLM response was not valid JSON: {content[:500]}")

    if not isinstance(items, list):
        raise ValueError(f"Expected JSON array, got {type(items).__name__}")

    return items


async def generate_keyframe_descriptions(theme: str, count: int,
                                         style: str = "transition-story") -> list[str]:
    """Generate keyframe descriptions via LLM."""
    style_data = _load_style(style)
    system_prompt = style_data["keyframe_system_prompt"]
    user_msg = f"Theme: {theme}\nNumber of keyframes: {count}"

    keyframes = await call_llm(system_prompt, user_msg)
    if len(keyframes) > count:
        keyframes = keyframes[:count]
    return keyframes
