"""Read and write the assistant's memory in Supabase.

- messages: every message from every channel, with an embedding
- memories: long-term facts about the owner and one summary per past day
- lessons:  corrections from the owner (written in stage 7)
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from postgrest.types import ReturnMethod

from app.memory.db import db
from app.memory.embeddings import embed_document, embed_query

log = logging.getLogger(__name__)

NEW_CONVERSATION = "new conversation"
DUPLICATE_SIMILARITY = 0.9  # a new memory this close to an old one replaces it


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class Message:
    role: str  # "user" | "assistant" | "event"
    content: str
    created_at: str = ""
    channel: str = "telegram"


# ---------- messages ----------


async def save_message(role: str, content: str, chat_id: int | None = None, channel: str = "telegram") -> None:
    embedding = await embed_document(content) if role != "event" else None
    row = {"role": role, "content": content, "chat_id": chat_id, "channel": channel, "embedding": embedding}
    await (await db()).table("messages").insert(row, returning=ReturnMethod.minimal).execute()


async def start_new_conversation(chat_id: int | None = None) -> None:
    await save_message("event", NEW_CONVERSATION, chat_id)


def current_conversation(newest_first: list[Message]) -> list[Message]:
    """Messages since the last "new conversation" marker, oldest first."""
    convo = []
    for m in newest_first:
        if m.role == "event":
            break
        convo.append(m)
    return list(reversed(convo))


async def recent_messages(limit: int = 20) -> list[Message]:
    """The current conversation across all channels (one shared brain)."""
    res = await (
        (await db())
        .table("messages")
        .select("role, content, created_at, channel")
        .order("id", desc=True)
        .limit(limit)
        .execute()
    )
    return current_conversation([Message(**row) for row in res.data])


async def search_messages(query: str, limit: int = 8, since: datetime | None = None) -> list[dict]:
    embedding = await embed_query(query)
    if embedding is None:
        return []
    params = {"query_embedding": embedding, "match_count": limit, "since": since.isoformat() if since else None}
    return (await (await db()).rpc("match_messages", params).execute()).data


# ---------- memories ----------


async def save_memory(content: str, kind: str = "fact") -> str:
    """Save a long-term memory. Near-duplicates update the existing memory instead."""
    embedding = await embed_document(content)
    client = await db()
    if embedding is not None:
        similar = (
            await client.rpc(
                "match_memories", {"query_embedding": embedding, "match_count": 1, "kinds": [kind]}
            ).execute()
        ).data
        if similar and similar[0]["similarity"] >= DUPLICATE_SIMILARITY:
            await (
                client.table("memories")
                .update({"content": content, "embedding": embedding, "updated_at": _now()}, returning=ReturnMethod.minimal)
                .eq("id", similar[0]["id"])
                .execute()
            )
            return "updated"
    row = {"kind": kind, "content": content, "embedding": embedding}
    await client.table("memories").insert(row, returning=ReturnMethod.minimal).execute()
    return "saved"


async def search_memories(query: str, limit: int = 5, kinds: list[str] | None = None) -> list[dict]:
    embedding = await embed_query(query)
    if embedding is None:
        return []
    params = {"query_embedding": embedding, "match_count": limit, "kinds": kinds}
    return (await (await db()).rpc("match_memories", params).execute()).data


async def save_summary(day: str, content: str) -> None:
    """One summary per day; running it again for the same day replaces it."""
    embedding = await embed_document(content)
    client = await db()
    existing = (
        await client.table("memories").select("id").eq("kind", "summary").eq("period_start", day).execute()
    ).data
    row = {"kind": "summary", "period_start": day, "content": content, "embedding": embedding}
    if existing:
        await (
            client.table("memories")
            .update({**row, "updated_at": _now()}, returning=ReturnMethod.minimal)
            .eq("id", existing[0]["id"])
            .execute()
        )
    else:
        await client.table("memories").insert(row, returning=ReturnMethod.minimal).execute()


# ---------- lessons ----------


async def active_lessons(limit: int = 30) -> list[str]:
    res = await (
        (await db())
        .table("lessons")
        .select("content")
        .eq("active", True)
        .order("created_at")
        .limit(limit)
        .execute()
    )
    return [row["content"] for row in res.data]


# ---------- context for each request ----------


@dataclass
class Context:
    history: list[Message]
    memories: list[dict]
    lessons: list[str]
    skills: list[dict] = field(default_factory=list)  # name + description of every skill


MEMORY_MIN_SIMILARITY = 0.5


async def build_context(user_text: str) -> Context:
    """Recent conversation + relevant memories + lessons + skill list. Never fails: memory is a bonus."""
    from app.memory.learning import list_skills

    results = await asyncio.gather(
        recent_messages(),
        search_memories(user_text, limit=8),
        active_lessons(),
        list_skills(),
        return_exceptions=True,
    )
    for r in results:
        if isinstance(r, Exception):
            log.error("Memory lookup failed: %r", r)
    history, memories, lessons, skills = (r if not isinstance(r, Exception) else [] for r in results)
    memories = [m for m in memories if m["similarity"] >= MEMORY_MIN_SIMILARITY]
    return Context(history=history, memories=memories, lessons=lessons, skills=skills)
