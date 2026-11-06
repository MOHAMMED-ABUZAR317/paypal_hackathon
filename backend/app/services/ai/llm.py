"""Minimal OpenAI-compatible chat client used for structured JSON output.

Works with OpenAI, Groq, Together, OpenRouter, vLLM, Ollama's compatible
endpoint, or Azure-style gateways - anything that accepts
``POST {base_url}/chat/completions`` and returns ``choices[0].message.content``.

No SDK dependency: the whole integration is ~100 lines of httpx, which makes the
hackathon build easy to audit.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass

import httpx

from ...config import get_settings

logger = logging.getLogger("raincheck.ai")

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    data: dict
    model: str
    latency_ms: int


def strip_code_fence(text: str) -> str:
    return _FENCE.sub("", text.strip())


async def complete_json(
    *,
    system: str,
    user: str,
    max_tokens: int = 900,
    temperature: float = 0.1,
) -> LLMResult:
    """One chat completion that must return a JSON object."""
    settings = get_settings()
    if not settings.ai_configured:
        raise LLMError("No AI_API_KEY configured")

    body = {
        "model": settings.ai_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {settings.ai_api_key}",
        "Content-Type": "application/json",
    }
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=settings.ai_timeout_seconds) as client:
            response = await client.post(
                f"{settings.ai_base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=body,
            )
    except httpx.HTTPError as exc:
        raise LLMError(f"AI request failed: {exc}") from exc

    if response.status_code >= 400:
        raise LLMError(
            f"AI provider returned {response.status_code}: {response.text[:300]}"
        )

    payload = response.json()
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError("AI response had no message content") from exc

    try:
        data = json.loads(strip_code_fence(content))
    except ValueError as exc:
        raise LLMError(f"AI did not return valid JSON: {content[:200]}") from exc
    if not isinstance(data, dict):
        raise LLMError("AI returned JSON that is not an object")

    return LLMResult(
        data=data,
        model=payload.get("model", settings.ai_model),
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
