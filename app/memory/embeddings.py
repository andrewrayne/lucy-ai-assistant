"""Gemini embeddings for semantic memory search."""

import logging

from google.genai import types

from app import costs
from app.config import get_settings
from app.gemini import client

log = logging.getLogger(__name__)

DIMENSIONS = 768  # must match vector(768) in supabase/migrations
MAX_CHARS = 8000


async def _embed(text: str, task_type: str) -> list[float] | None:
    text = text.strip()[:MAX_CHARS]
    if not text:
        return None
    try:
        result = await client().aio.models.embed_content(
            model=get_settings().gemini_embedding_model,
            contents=text,
            config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=DIMENSIONS),
        )
        model = get_settings().gemini_embedding_model
        tokens = len(text) // 4  # the embedding API doesn't report tokens; about 4 characters per token
        costs.record("gemini-embedding", model, costs.token_cost(model, tokens, 0), tokens)
        return list(result.embeddings[0].values)
    except Exception:
        # A missing embedding only means the row won't show up in semantic search.
        log.exception("Embedding failed")
        return None


async def embed_document(text: str) -> list[float] | None:
    """For text we store (messages, memories)."""
    return await _embed(text, "RETRIEVAL_DOCUMENT")


async def embed_query(text: str) -> list[float] | None:
    """For a search query."""
    return await _embed(text, "RETRIEVAL_QUERY")
