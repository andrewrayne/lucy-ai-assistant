"""Google Calendar: list, create, update and delete events."""

from datetime import date, datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

from app import owner
from app.integrations.google import google
from app.tools.registry import registry

API = "https://www.googleapis.com/calendar/v3/calendars"


def _tz() -> ZoneInfo:
    return owner.tz()


def parse_when(value: str, *, end_of_day: bool = False) -> datetime:
    """'2026-10-24' or '2026-10-24T15:00' (owner's local time unless an offset is given)."""
    if len(value) == 10:
        d = date.fromisoformat(value)
        dt = datetime(d.year, d.month, d.day) + (timedelta(days=1) if end_of_day else timedelta())
    else:
        dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=_tz())


def event_time(value: str, all_day: bool) -> dict:
    if all_day:
        return {"date": value[:10]}
    return {"dateTime": parse_when(value).isoformat(), "timeZone": owner.timezone()}


def _event_out(e: dict) -> dict:
    start, end = e.get("start", {}), e.get("end", {})
    return {
        "id": e["id"],
        "title": e.get("summary", "(no title)"),
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
        "all_day": "date" in start,
        "location": e.get("location", ""),
        "description": (e.get("description") or "")[:500],
        "attendees": [a.get("email") for a in e.get("attendees", [])],
        "meet_link": e.get("hangoutLink", ""),
        "link": e.get("htmlLink", ""),
    }


def _url(calendar_id: str, suffix: str = "") -> str:
    return f"{API}/{quote(calendar_id or 'primary', safe='')}/events{suffix}"


@registry.register(
    "calendar_list_events",
    "List events in the owner's Google Calendar. Defaults to the next 7 days. Dates are in the owner's time zone.",
    {
        "type": "object",
        "properties": {
            "start": {"type": "string", "description": "From, e.g. '2026-10-24' or '2026-10-24T09:00'. Default: now."},
            "end": {"type": "string", "description": "Until; a plain date includes that whole day (start=end='2026-10-24' is just that day). Default: start + 7 days."},
            "query": {"type": "string", "description": "Optional text to search for."},
            "calendar_id": {"type": "string", "description": "Default 'primary'."},
        },
    },
)
async def calendar_list_events(start: str = "", end: str = "", query: str = "", calendar_id: str = "primary") -> dict:
    time_min = parse_when(start) if start else datetime.now(_tz())
    time_max = parse_when(end, end_of_day=True) if end else time_min + timedelta(days=7)
    params = {
        "timeMin": time_min.isoformat(),
        "timeMax": time_max.isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": 50,
        "timeZone": owner.timezone(),
    }
    if query:
        params["q"] = query
    res = await google.get(_url(calendar_id), params=params)
    return {"events": [_event_out(e) for e in res.get("items", [])], "timezone": owner.timezone()}


@registry.register(
    "calendar_create_event",
    "Create an event in the owner's Google Calendar. Times are the owner's local time.",
    {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "start": {"type": "string", "description": "'2026-10-24T15:00', or '2026-10-24' for all-day events."},
            "end": {"type": "string", "description": "Same format. Default: 1 hour after start (or the same day)."},
            "all_day": {"type": "boolean"},
            "description": {"type": "string"},
            "location": {"type": "string"},
            "attendees": {"type": "array", "items": {"type": "string"}, "description": "Emails to invite."},
            "calendar_id": {"type": "string"},
        },
        "required": ["title", "start"],
    },
)
async def calendar_create_event(
    title: str,
    start: str,
    end: str = "",
    all_day: bool = False,
    description: str = "",
    location: str = "",
    attendees: list[str] | None = None,
    calendar_id: str = "primary",
) -> dict:
    all_day = all_day or len(start) == 10
    if not end:
        end = (
            (date.fromisoformat(start[:10]) + timedelta(days=1)).isoformat()
            if all_day
            else (parse_when(start) + timedelta(hours=1)).isoformat()
        )
    body = {"summary": title, "start": event_time(start, all_day), "end": event_time(end, all_day)}
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if attendees:
        body["attendees"] = [{"email": a} for a in attendees]
    params = {"sendUpdates": "all"} if attendees else {}
    event = await google.post(_url(calendar_id), json=body, params=params)
    return {"status": "created", "event": _event_out(event)}


@registry.register(
    "calendar_update_event",
    "Change an existing event (only the fields you pass). Get the id from calendar_list_events.",
    {
        "type": "object",
        "properties": {
            "event_id": {"type": "string"},
            "title": {"type": "string"},
            "start": {"type": "string"},
            "end": {"type": "string"},
            "description": {"type": "string"},
            "location": {"type": "string"},
            "calendar_id": {"type": "string"},
        },
        "required": ["event_id"],
    },
)
async def calendar_update_event(
    event_id: str,
    title: str = "",
    start: str = "",
    end: str = "",
    description: str = "",
    location: str = "",
    calendar_id: str = "primary",
) -> dict:
    body: dict = {}
    if title:
        body["summary"] = title
    if start:
        body["start"] = event_time(start, len(start) == 10)
    if end:
        body["end"] = event_time(end, len(end) == 10)
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if start and not end:
        # Keep the original duration when only the start moves.
        old = await google.get(_url(calendar_id, f"/{event_id}"))
        if "dateTime" in old["start"] and len(start) > 10:
            duration = datetime.fromisoformat(old["end"]["dateTime"]) - datetime.fromisoformat(old["start"]["dateTime"])
            body["end"] = event_time((parse_when(start) + duration).isoformat(), False)
    event = await google.request("PATCH", _url(calendar_id, f"/{event_id}"), json=body)
    return {"status": "updated", "event": _event_out(event)}


@registry.register(
    "calendar_delete_event",
    "Delete an event from the owner's calendar.",
    {
        "type": "object",
        "properties": {"event_id": {"type": "string"}, "calendar_id": {"type": "string"}},
        "required": ["event_id"],
    },
)
async def calendar_delete_event(event_id: str, calendar_id: str = "primary") -> dict:
    await google.request("DELETE", _url(calendar_id, f"/{event_id}"))
    return {"status": "deleted", "event_id": event_id}
