"""Tools for reminders, the morning brief and the owner's location."""

from datetime import UTC, datetime, timedelta

from app import owner
from app.scheduler import reminders
from app.tools.registry import registry


def _local(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(owner.tz()).strftime("%a %d %b %Y, %H:%M")


def parse_local(value: str) -> datetime:
    """'2026-10-24T18:00' in the owner's time zone (or with an explicit offset) -> aware datetime."""
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=owner.tz())


@registry.register(
    "create_reminder",
    "Remind the owner about something later via a Telegram message. Give either 'at' (local date-time), "
    "'in_minutes', or a 'recurrence' for repeating reminders.",
    {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "What to remind about, e.g. 'Call mum'."},
            "at": {"type": "string", "description": "Local date-time, e.g. '2026-10-24T18:00'."},
            "in_minutes": {"type": "integer", "description": "Alternative to 'at': minutes from now."},
            "recurrence": {
                "type": "string",
                "description": "Cron expression in the owner's time zone for repeating reminders: "
                "'0 9 * * *' every day 09:00, '30 18 * * 1-5' weekdays 18:30, '0 10 * * 1' Mondays 10:00, "
                "'0 12 1 * *' the 1st of each month.",
            },
        },
        "required": ["text"],
    },
)
async def create_reminder(text: str, at: str = "", in_minutes: int = 0, recurrence: str = "") -> dict:
    if recurrence:
        due = parse_local(at).astimezone(UTC) if at else reminders.next_due(recurrence)
    elif in_minutes:
        due = datetime.now(UTC) + timedelta(minutes=in_minutes)
    elif at:
        due = parse_local(at).astimezone(UTC)
    else:
        return {"error": "Give 'at', 'in_minutes' or 'recurrence'."}
    if not recurrence and due < datetime.now(UTC) - timedelta(minutes=1):
        return {"error": f"That time is in the past ({_local(due.isoformat())}). Pick a future time."}
    row = await reminders.create(text, due, recurrence or None)
    return {
        "status": "scheduled",
        "id": row["id"],
        "first_time": _local(row["due_at"]),
        "repeats": recurrence or "no",
        "timezone": owner.timezone(),
    }


@registry.register("list_reminders", "List the owner's upcoming reminders and the morning brief schedule.")
async def list_reminders() -> dict:
    rows = await reminders.pending()
    return {
        "reminders": [
            {
                "id": r["id"],
                "text": r["text"],
                "next": _local(r["due_at"]),
                "repeats": r["recurrence"] or "no",
                "kind": r["kind"],
            }
            for r in rows
        ],
        "timezone": owner.timezone(),
    }


@registry.register(
    "cancel_reminder",
    "Cancel a reminder (or the morning brief) by id. Use list_reminders to find the id.",
    {"type": "object", "properties": {"reminder_id": {"type": "integer"}}, "required": ["reminder_id"]},
)
async def cancel_reminder(reminder_id: int) -> dict:
    return {"status": "cancelled" if await reminders.cancel(reminder_id) else "not found or already done"}


@registry.register(
    "set_morning_brief",
    "Change the time of the daily morning brief, or turn it off/on.",
    {
        "type": "object",
        "properties": {
            "time": {"type": "string", "description": "Local time 'HH:MM', e.g. '07:30'."},
            "enabled": {"type": "boolean", "description": "false turns the brief off."},
        },
    },
)
async def set_morning_brief(time: str = "08:00", enabled: bool = True) -> dict:
    for row in await reminders.pending(kind="brief"):
        await reminders.cancel(row["id"])
    if not enabled:
        return {"status": "morning brief turned off"}
    hour, minute = (int(x) for x in time.split(":"))
    cron = f"{minute} {hour} * * *"
    row = await reminders.create("Morning brief", reminders.next_due(cron), recurrence=cron, kind="brief")
    return {"status": "morning brief scheduled", "daily_at": f"{hour:02d}:{minute:02d}", "next": _local(row["due_at"])}


@registry.register(
    "set_location",
    "Set the owner's current city (when they travel). Updates the time zone, weather and reminder times.",
    {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
)
async def set_location(city: str) -> dict:
    loc = await owner.geocode(city)
    if not loc:
        return {"error": f"I couldn't find a city called '{city}'."}
    await owner.save(loc)
    return {"status": "location updated", "city": loc.label(), "timezone": loc.timezone}
