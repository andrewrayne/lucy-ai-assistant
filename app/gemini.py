"""Shared Gemini client and model fallback.

The main text model is tried first; if it is overloaded, rate-limited or slow
to start, the next model in GEMINI_FALLBACK_MODELS is used. A model that fails
is skipped for a few minutes.
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from functools import lru_cache

from google import genai
from google.genai import errors, types

from app import costs
from app.config import get_settings

log = logging.getLogger(__name__)

FIRST_CHUNK_TIMEOUT = 10  # seconds to wait for a model to start answering
COOLDOWN = 300  # seconds to skip a model after it failed
RETRYABLE_CODES = {429, 500, 503, 504}

_cooldown_until: dict[str, float] = {}


@lru_cache
def client() -> genai.Client:
    return genai.Client(api_key=get_settings().gemini_api_key)


def text_models() -> list[str]:
    """Primary model first, then fallbacks. Models in cooldown go last."""
    s = get_settings()
    models = [s.gemini_text_model, *[m.strip() for m in s.gemini_fallback_models.split(",") if m.strip()]]
    now = time.monotonic()
    healthy = [m for m in models if _cooldown_until.get(m, 0) <= now]
    return healthy + [m for m in models if m not in healthy]


def _mark_failed(model: str, exc: Exception) -> None:
    if isinstance(exc, errors.APIError) and exc.code not in RETRYABLE_CODES:
        raise exc
    log.warning("Model %s unavailable (%s), trying the next one", model, exc or "timeout")
    _cooldown_until[model] = time.monotonic() + COOLDOWN


async def stream(contents, config: types.GenerateContentConfig) -> AsyncIterator[types.GenerateContentResponse]:
    """Stream a response from the first model that starts answering."""
    last_error: Exception | None = None
    for model in text_models():
        try:
            response = await asyncio.wait_for(
                client().aio.models.generate_content_stream(model=model, contents=contents, config=config),
                FIRST_CHUNK_TIMEOUT,
            )
            first = await asyncio.wait_for(anext(response), FIRST_CHUNK_TIMEOUT)
        except (TimeoutError, errors.APIError) as exc:
            _mark_failed(model, exc)
            last_error = exc
            continue
        usage = first.usage_metadata
        yield first
        async for chunk in response:
            usage = chunk.usage_metadata or usage
            yield chunk
        costs.record_tokens(model, usage)
        return
    raise RuntimeError("All Gemini models are unavailable right now") from last_error


async def search_answer(prompt: str, timeout: float = 120) -> tuple[str, list[dict]]:
    """Answer grounded in Google Search. Returns (text, [{title, url}, ...])."""
    config = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
        thinking_config=types.ThinkingConfig(thinking_level=get_settings().gemini_thinking_level),
    )
    last_error: Exception | None = None
    for model in text_models():
        try:
            response = await asyncio.wait_for(
                client().aio.models.generate_content(model=model, contents=prompt, config=config), timeout
            )
        except (TimeoutError, errors.APIError) as exc:
            _mark_failed(model, exc)
            last_error = exc
            continue
        costs.record_tokens(model, response.usage_metadata)
        sources, seen = [], set()
        meta = response.candidates[0].grounding_metadata if response.candidates else None
        for chunk in (meta.grounding_chunks or []) if meta else []:
            if chunk.web and chunk.web.uri not in seen:
                seen.add(chunk.web.uri)
                sources.append({"title": chunk.web.title or chunk.web.uri, "url": chunk.web.uri})
        return response.text or "", sources
    raise RuntimeError("All Gemini models are unavailable right now") from last_error


async def generate_text(
    prompt, system: str = "", timeout: float = 90, search: bool = False, json_output: bool = False
) -> str:
    """One-shot text generation (no streaming), with the same fallback.

    search=True lets Gemini ground its answer in Google Search (for news).
    json_output=True asks for a JSON answer (used by Mac control).
    """
    config = types.GenerateContentConfig(
        system_instruction=system or None,
        response_mime_type="application/json" if json_output else None,
        thinking_config=types.ThinkingConfig(thinking_level=get_settings().gemini_thinking_level),
        tools=[types.Tool(google_search=types.GoogleSearch())] if search else None,
    )
    last_error: Exception | None = None
    for model in text_models():
        try:
            response = await asyncio.wait_for(
                client().aio.models.generate_content(model=model, contents=prompt, config=config), timeout
            )
            costs.record_tokens(model, response.usage_metadata)
            return response.text or ""
        except (TimeoutError, errors.APIError) as exc:
            _mark_failed(model, exc)
            last_error = exc
    raise RuntimeError("All Gemini models are unavailable right now") from last_error
