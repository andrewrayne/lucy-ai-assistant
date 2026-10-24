"""Compress finished days of conversation into one summary memory per day.

Raw messages stay searchable; the summary gives the assistant a compact view
of the past ("what did we talk about last week?"). The job is idempotent: all
state lives in Supabase (messages.summarized_at), so redeploys are harmless.
"""

import logging
from collections import defaultdict
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from postgrest.types import ReturnMethod

from app import owner
from app.config import get_settings
from app.gemini import generate_text
from app.memory import store
from app.memory.db import db

log = logging.getLogger(__name__)

MAX_DAYS_PER_RUN = 7
MAX_MESSAGE_CHARS = 1500
MAX_TRANSCRIPT_CHARS = 60_000

PROMPT = """Summarize one day of conversation between the owner and their AI assistant {name}.
Date: {day}.

Write a compact memory note in English, as "- " bullet points, at most 150 words:
- topics discussed and questions asked
- decisions made and facts learned about the owner
- open tasks or promises
Skip greetings and small talk. If an earlier summary of this day is given, merge it in.
{previous}
Conversation:
{transcript}
"""


def group_by_day(rows: list[dict], tz: ZoneInfo) -> dict[str, list[dict]]:
    """Group message rows by their local calendar day (YYYY-MM-DD)."""
    days: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        day = datetime.fromisoformat(row["created_at"]).astimezone(tz).date().isoformat()
        days[day].append(row)
    return dict(days)


def transcript(rows: list[dict], tz: ZoneInfo, name: str) -> str:
    lines = []
    for r in rows:
        if r["role"] not in ("user", "assistant"):
            continue
        time = datetime.fromisoformat(r["created_at"]).astimezone(tz).strftime("%H:%M")
        who = "Owner" if r["role"] == "user" else name
        lines.append(f"[{time}] {who}: {r['content'][:MAX_MESSAGE_CHARS]}")
    return "\n".join(lines)[-MAX_TRANSCRIPT_CHARS:]


async def summarize_past_days() -> int:
    """Summarize every finished day that has unsummarized messages. Returns days done."""
    s = get_settings()
    tz = owner.tz()
    start_of_today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    client = await db()

    rows = (
        await client.table("messages")
        .select("id, created_at, role, content")
        .is_("summarized_at", "null")
        .lt("created_at", start_of_today.astimezone(UTC).isoformat())
        .order("id")
        .limit(5000)
        .execute()
    ).data
    if not rows:
        return 0

    done = 0
    for day, day_rows in sorted(group_by_day(rows, tz).items())[:MAX_DAYS_PER_RUN]:
        text = transcript(day_rows, tz, s.assistant_name)
        if text:
            previous = (
                await client.table("memories").select("content").eq("kind", "summary").eq("period_start", day).execute()
            ).data
            prev_text = f"\nEarlier summary of this day:\n{previous[0]['content']}\n" if previous else ""
            summary = await generate_text(
                PROMPT.format(name=s.assistant_name, day=day, previous=prev_text, transcript=text)
            )
            await store.save_summary(day, summary.strip())

        ids = [r["id"] for r in day_rows]
        for i in range(0, len(ids), 500):
            await (
                client.table("messages")
                .update({"summarized_at": datetime.now(UTC).isoformat()}, returning=ReturnMethod.minimal)
                .in_("id", ids[i : i + 500])
                .execute()
            )
        log.info("Summarized %s (%d messages)", day, len(ids))
        done += 1
    return done
