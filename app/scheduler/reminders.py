"""Reminders and other scheduled items, stored in Supabase.

A loop calls deliver_due() every minute. Nothing lives only in process memory,
so redeploys lose nothing. Each due row is claimed with a conditional update
before it is sent, so two overlapping instances (during a redeploy) can never
send the same reminder twice.
"""

import logging
from datetime import UTC, datetime, timedelta

from aiogram import Bot
from apscheduler.triggers.cron import CronTrigger

from app import owner
from app.config import get_settings
from app.memory import store
from app.memory.db import db

log = logging.getLogger(__name__)

LATE_AFTER = timedelta(minutes=10)


def next_due(cron: str, after: datetime | None = None) -> datetime:
    """Next fire time of a cron expression ('0 8 * * *') in the owner's time zone, as UTC."""
    trigger = CronTrigger.from_crontab(cron, timezone=owner.tz())
    now = after or datetime.now(UTC)
    nxt = trigger.get_next_fire_time(None, now.astimezone(owner.tz()))
    if nxt is None:
        raise ValueError(f"Cron expression never fires: {cron}")
    return nxt.astimezone(UTC)


def validate_cron(cron: str) -> None:
    CronTrigger.from_crontab(cron)  # raises ValueError on bad input


async def create(text: str, due_at: datetime, recurrence: str | None = None, kind: str = "reminder") -> dict:
    if recurrence:
        validate_cron(recurrence)
    row = {
        "chat_id": get_settings().owner_telegram_id,
        "text": text,
        "due_at": due_at.astimezone(UTC).isoformat(),
        "recurrence": recurrence,
        "kind": kind,
    }
    return (await (await db()).table("reminders").insert(row).execute()).data[0]


async def pending(kind: str | None = None) -> list[dict]:
    query = (await db()).table("reminders").select("id, text, due_at, recurrence, kind").eq("status", "pending")
    if kind:
        query = query.eq("kind", kind)
    return (await query.order("due_at").limit(100).execute()).data


async def cancel(reminder_id: int) -> bool:
    res = await (
        (await db())
        .table("reminders")
        .update({"status": "cancelled"})
        .eq("id", reminder_id)
        .eq("status", "pending")
        .execute()
    )
    return bool(res.data)


async def retime_recurring() -> None:
    """After a time zone change, recompute when every recurring item fires next."""
    for row in await pending():
        if row["recurrence"]:
            await (
                (await db())
                .table("reminders")
                .update({"due_at": next_due(row["recurrence"]).isoformat()})
                .eq("id", row["id"])
                .execute()
            )


async def _claim(row: dict) -> bool:
    """Mark a due row as handled. Returns False if another instance got it first."""
    now = datetime.now(UTC)
    table = (await db()).table("reminders")
    if row["recurrence"]:
        update = {"due_at": next_due(row["recurrence"], now).isoformat(), "sent_at": now.isoformat()}
        res = await table.update(update).eq("id", row["id"]).eq("due_at", row["due_at"]).eq("status", "pending").execute()
    else:
        update = {"status": "sent", "sent_at": now.isoformat()}
        res = await table.update(update).eq("id", row["id"]).eq("status", "pending").execute()
    return bool(res.data)


def reminder_text(row: dict, now: datetime) -> str:
    due = datetime.fromisoformat(row["due_at"])
    text = f"⏰ Reminder: {row['text']}"
    if now - due > LATE_AFTER:
        text += f"\n(This was due at {due.astimezone(owner.tz()).strftime('%H:%M, %d %b')}; I was offline.)"
    return text


async def deliver_due(bot: Bot) -> int:
    """Send everything that is due. Returns how many items were sent."""
    now = datetime.now(UTC)
    rows = (
        await (await db())
        .table("reminders")
        .select("id, chat_id, text, due_at, recurrence, kind")
        .eq("status", "pending")
        .lte("due_at", now.isoformat())
        .order("due_at")
        .limit(50)
        .execute()
    ).data

    sent = 0
    for row in rows:
        if not await _claim(row):
            continue
        try:
            if row["kind"] == "brief":
                from app.scheduler.brief import send_brief

                await send_brief(bot, row["chat_id"])
            else:
                text = reminder_text(row, now)
                await bot.send_message(row["chat_id"], text)
                await store.save_message("assistant", text, row["chat_id"])
            sent += 1
        except Exception:
            log.exception("Could not deliver reminder %s", row["id"])
    return sent
