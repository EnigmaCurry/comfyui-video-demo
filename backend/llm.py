"""Async LLM client for generating keyframe descriptions.

Uses httpx for async streaming, returns parsed data instead of writing files.
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

    base = settings.llm_url.rstrip("/")
    if base.endswith("/v1"):
        url = f"{base}/chat/completions"
    else:
        url = f"{base}/v1/chat/completions"
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


async def call_llm_text(system_prompt: str, user_msg: str,
                        temperature: float = 0.7,
                        max_tokens: int = 500) -> str:
    """Call the LLM and return raw text (not parsed as JSON)."""
    payload = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"

    base = settings.llm_url.rstrip("/")
    if base.endswith("/v1"):
        url = f"{base}/chat/completions"
    else:
        url = f"{base}/v1/chat/completions"

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        resp_json = resp.json()
        content = resp_json["choices"][0]["message"]["content"]
        if content is None:
            return ""
        return content.strip()


async def suggest_premise(notes: str) -> str:
    """Generate a premise from freeform notes/ideas."""
    system_prompt = (
        "You are a screenwriter. The user will give you freeform notes — a stream of "
        "consciousness, a list of nouns, half-formed ideas, moods, images. Your job is to "
        "synthesize these into a clear, vivid PREMISE for a short cinematic film.\n\n"
        "The premise should be 2-4 sentences that establish:\n"
        "- A specific setting (where and when)\n"
        "- A character or subject (who or what)\n"
        "- A situation or tension (what's happening or about to happen)\n\n"
        "Be concrete and visual. Don't explain or narrate — just state the premise.\n"
        "Reply with ONLY the premise text, no quotes, no labels, no explanation."
    )
    return await call_llm_text(system_prompt, notes, temperature=0.8)


async def generate_project_name(theme: str) -> str:
    """Generate a short project name from the theme."""
    system_prompt = (
        "Generate a short, evocative project title (2-5 words) for a film based on "
        "the given initial conditions. Reply with ONLY the title, no quotes, no punctuation, "
        "no explanation."
    )
    return await call_llm_text(system_prompt, theme)


async def generate_keyframe_descriptions(theme: str, count: int,
                                         style: str = "transition-story") -> list[str]:
    """Generate keyframe descriptions via LLM."""
    style_data = _load_style(style)
    system_prompt = style_data["keyframe_system_prompt"]
    user_msg = (f"Initial conditions: {theme}\n"
                f"Number of keyframes: {count}\n"
                f"Total film duration: approximately {count * style_data.get('default_duration', 10)} seconds")

    keyframes = await call_llm(system_prompt, user_msg)
    if len(keyframes) > count:
        keyframes = keyframes[:count]
    return keyframes


async def rewrite_keyframe_prompt(current_prompt: str, instruction: str) -> str:
    """Rewrite a keyframe prompt based on user instruction."""
    system_prompt = (
        "You are a visual director rewriting a keyframe image description. "
        "You will be given the current description and an instruction for how to change it. "
        "Rewrite the description following the instruction while keeping the same style "
        "(1-3 sentences of concrete visual language describing a still image). "
        "Reply with ONLY the new description, no quotes, no explanation."
    )
    user_msg = f"Current description:\n{current_prompt}\n\nInstruction:\n{instruction}"
    return await call_llm_text(system_prompt, user_msg, temperature=0.8)


async def rewrite_narration(current_narration: str, instruction: str,
                            direction: str = "", duration: int = 10) -> str:
    """Rewrite a single narration line based on instruction."""
    wlo, whi = _voiceover_word_range(duration)
    system_prompt = (
        "You are rewriting a single spoken narration line for a cinematic video.\n\n"
        f"CRITICAL: The narration MUST be between {wlo} and {whi} words. "
        f"Aim for {whi} words to fill ~{duration} seconds of speech. "
        f"Do NOT write fewer than {wlo} words.\n"
    )
    if direction.strip():
        system_prompt += f"\nNARRATOR DIRECTION:\n{direction.strip()}\n"
    system_prompt += (
        "\nRewrite the narration following the instruction while respecting the word count "
        "and narrator direction. Reply with ONLY the new narration text, no quotes, no explanation."
    )
    user_msg = f"Current narration:\n{current_narration}\n\nInstruction:\n{instruction}"
    return await call_llm_text(system_prompt, user_msg, temperature=0.8)


async def suggest_soundtrack_prompt(scene_descriptions: list[str],
                                    premise: str = "") -> str:
    """Generate a soundtrack prompt (tags) for AceStep from scene descriptions."""
    system_prompt = (
        "You are a music director writing a description for an AI music generator. "
        "Given scene descriptions from a film, write a short comma-separated list of "
        "music tags describing the ideal soundtrack.\n\n"
        "Include: genre, mood, instruments, tempo feel, and energy level.\n"
        "Example: 'cinematic orchestral, suspenseful, strings, piano, slow build, dark atmosphere'\n\n"
        "Reply with ONLY the comma-separated tags, no quotes, no explanation."
    )
    scenes = "\n".join(f"  - {s}" for s in scene_descriptions)
    user_msg = f"Film premise: {premise}\n\nScenes:\n{scenes}"
    return await call_llm_text(system_prompt, user_msg, temperature=0.7)


async def generate_transition_descriptions(keyframe_prompts: list[str],
                                           duration: int = 10,
                                           style: str = "transition-story") -> list[str]:
    """Generate transition descriptions for consecutive keyframe pairs."""
    style_data = _load_style(style)
    system_prompt = style_data["transition_system_prompt"].format(duration=duration)

    kf_list = "\n".join(f"  Keyframe {i+1}: {k}" for i, k in enumerate(keyframe_prompts))
    user_msg = (f"Number of keyframes: {len(keyframe_prompts)}\n\n"
                f"Keyframe descriptions:\n{kf_list}")

    n_expected = len(keyframe_prompts) - 1
    transitions = await call_llm(system_prompt, user_msg)
    if len(transitions) > n_expected:
        transitions = transitions[:n_expected]

    # If truncated, request remaining in a follow-up call
    while len(transitions) < n_expected:
        remaining = n_expected - len(transitions)
        start_idx = len(transitions)
        partial_kf = keyframe_prompts[start_idx:start_idx + remaining + 1]
        partial_list = "\n".join(
            f"  Keyframe {start_idx + i + 1}: {k}" for i, k in enumerate(partial_kf))
        partial_msg = (f"Continue generating transition descriptions. "
                       f"You already wrote {start_idx} transitions. "
                       f"Now write the next {remaining} transitions.\n\n"
                       f"Keyframe descriptions:\n{partial_list}")
        more = await call_llm(system_prompt, partial_msg)
        if not more:
            break
        transitions.extend(more)
    if len(transitions) > n_expected:
        transitions = transitions[:n_expected]
    return transitions


def _voiceover_word_range(duration: int) -> tuple[int, int]:
    lo = max(1, int(duration * 1.0))
    hi = max(lo, int(duration * 1.7))
    return lo, hi


async def generate_narration(keyframe_prompts: list[str],
                             transition_prompts: list[str],
                             duration: int = 10,
                             style: str = "transition-story",
                             direction: str = "") -> list[str]:
    """Generate voiceover narration for each transition."""
    style_data = _load_style(style)
    wlo, whi = _voiceover_word_range(duration)
    vo_template = style_data.get("voiceover_system_prompt", "")
    system_prompt = vo_template.format(duration=duration, word_lo=wlo, word_hi=whi)

    kf_list = "\n".join(f"  Keyframe {i+1}: {k}" for i, k in enumerate(keyframe_prompts))
    tr_list = "\n".join(
        f"  Transition {i+1} (keyframe {i+1} -> {i+2}): {t}"
        for i, t in enumerate(transition_prompts))
    dir_text = direction.strip() if direction.strip() else "A contemplative, poetic narrator experiencing the scene firsthand."
    user_msg = (f"NARRATOR DIRECTION:\n{dir_text}\n\n"
                f"Number of transitions: {len(transition_prompts)}\n\n"
                f"Keyframe descriptions:\n{kf_list}\n\n"
                f"Transition descriptions:\n{tr_list}")

    n_expected = len(transition_prompts)
    narrations = await call_llm(system_prompt, user_msg)

    # If truncated, request remaining
    while len(narrations) < n_expected:
        remaining = n_expected - len(narrations)
        start_idx = len(narrations)
        partial_tr = transition_prompts[start_idx:start_idx + remaining]
        partial_list = "\n".join(
            f"  Transition {start_idx + i + 1}: {t}" for i, t in enumerate(partial_tr))
        partial_msg = (f"NARRATOR DIRECTION:\n{dir_text}\n\n"
                       f"Continue. You already wrote {start_idx} narrations. "
                       f"Now write the next {remaining}.\n\n"
                       f"Transition descriptions:\n{partial_list}")
        more = await call_llm(system_prompt, partial_msg)
        if not more:
            break
        narrations.extend(more)

    if len(narrations) > n_expected:
        narrations = narrations[:n_expected]
    return narrations
