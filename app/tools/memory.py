"""Memory tools: search past conversations, save and recall long-term facts."""

from datetime import UTC, datetime, timedelta

from app import owner
from app.memory import store
from app.tools.registry import registry

SNIPPET = 600  # characters per search hit sent back to the model


def _local(ts: str) -> str:
    """ISO timestamp -> 'Mon 20 Oct 2026, 14:05' in the owner's time zone."""
    dt = datetime.fromisoformat(ts).astimezone(owner.tz())
    return dt.strftime("%a %d %b %Y, %H:%M")


@registry.register(
    "search_history",
    "Search past conversations with the owner by meaning (all channels). Use it for questions like "
    "'what did we discuss about X' or 'when did I mention Y'. Returns matching messages with dates.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look for, in a few words."},
            "days_back": {
                "type": "integer",
                "description": "Only search the last N days, e.g. 7 for 'last week'. 0 means all time.",
            },
            "limit": {"type": "integer", "description": "Max results, default 8."},
        },
        "required": ["query"],
    },
)
async def search_history(query: str, days_back: int = 0, limit: int = 8) -> dict:
    since = datetime.now(UTC) - timedelta(days=days_back) if days_back and days_back > 0 else None
    hits = await store.search_messages(query, limit=min(max(limit, 1), 20), since=since)
    return {
        "results": [
            {
                "when": _local(h["created_at"]),
                "who": "owner" if h["role"] == "user" else "assistant",
                "channel": h["channel"],
                "text": h["content"][:SNIPPET],
                "relevance": round(h["similarity"], 2),
            }
            for h in hits
        ]
    }


@registry.register(
    "save_memory",
    "Save a lasting fact about the owner to long-term memory: preferences, people, projects, plans, "
    "important details. Call it when the owner shares something worth remembering or asks you to "
    "remember. Write one self-contained sentence. Don't save small talk.",
    {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "The fact, e.g. 'Andrew's sister Anna lives in Lisbon.'"},
            "kind": {"type": "string", "enum": ["fact", "preference", "person", "project"]},
        },
        "required": ["content"],
    },
)
async def save_memory(content: str, kind: str = "fact") -> dict:
    if kind not in {"fact", "preference", "person", "project"}:
        kind = "fact"
    return {"status": await store.save_memory(content.strip(), kind)}


@registry.register(
    "recall",
    "Look up long-term memories about the owner (facts, preferences, people, projects) and daily "
    "summaries of past conversations.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What you want to remember."},
            "limit": {"type": "integer", "description": "Max results, default 6."},
        },
        "required": ["query"],
    },
)
async def recall(query: str, limit: int = 6) -> dict:
    hits = await store.search_memories(query, limit=min(max(limit, 1), 20))
    return {
        "memories": [
            {
                "kind": h["kind"],
                "text": h["content"],
                "day": h["period_start"],
                "relevance": round(h["similarity"], 2),
            }
            for h in hits
        ]
    }
