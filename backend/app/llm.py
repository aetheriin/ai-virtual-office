"""Thin LLM client for OpenRouter and Google AI Studio (Gemini).

Every call is best-effort: when no API key is configured or the provider fails,
`chat()` returns None and the caller falls back to its deterministic rule engine.
That keeps the office usable offline and guarantees numbers never depend on a
hallucinating model.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from .config import settings

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


async def _openrouter(model: str, system: str, user: str, temperature: float) -> str | None:
    if not settings.openrouter_api_key:
        return None
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "HTTP-Referer": "http://localhost:3000",
        "X-Title": "AI Virtual Office",
    }
    body = {
        "model": model,
        "temperature": temperature,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(OPENROUTER_URL, headers=headers, json=body)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


async def _gemini(system: str, user: str, temperature: float) -> str | None:
    if not settings.gemini_api_key:
        return None
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": temperature},
    }
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            GEMINI_URL.format(model=settings.gemini_model),
            params={"key": settings.gemini_api_key},
            json=body,
        )
        r.raise_for_status()
        parts = r.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)


async def chat(model: str, system: str, user: str, *, prefer_gemini: bool = False, temperature: float = 0.4) -> str | None:
    """Return model text, or None when no provider is available/working."""
    providers = []
    if prefer_gemini:
        providers.append(lambda: _gemini(system, user, temperature))
    providers.append(lambda: _openrouter(model, system, user, temperature))
    if not prefer_gemini:
        providers.append(lambda: _gemini(system, user, temperature))

    for call in providers:
        try:
            text = await call()
            if text:
                return text.strip()
        except Exception as exc:  # network, quota, bad model id...
            log.warning("LLM call failed (%s): %s", model, exc)
    return None


def extract_json(text: str | None) -> Any | None:
    """Pull the first JSON object/array out of a model reply (handles ```json fences)."""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    candidate = fenced.group(1) if fenced else text
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = candidate.find(opener), candidate.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(candidate[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None
