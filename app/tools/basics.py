"""Small built-in tools that need no external service."""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app import owner
from app.tools.registry import registry


@registry.register(
    "get_current_time",
    "Get the current date, time and weekday. Defaults to the owner's time zone.",
    {
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": "IANA time zone, e.g. 'Europe/Lisbon'. Leave empty for the owner's time zone.",
            }
        },
    },
)
async def get_current_time(timezone: str = "") -> dict:
    tz_name = timezone or owner.timezone()
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return {"error": f"Unknown time zone: {tz_name}"}
    now = datetime.now(tz)
    return {
        "timezone": tz_name,
        "iso": now.isoformat(timespec="seconds"),
        "weekday": now.strftime("%A"),
        "human": now.strftime("%A, %d %B %Y, %H:%M"),
    }
