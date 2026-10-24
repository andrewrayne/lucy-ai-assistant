"""The owner's current location and time zone.

Stored in Supabase (owner_settings) so it survives redeploys, cached in memory
for fast access. Changes with /city, a shared Telegram location, or the
set_location tool. Falls back to OWNER_TIMEZONE until a city is set.
"""

import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
REVERSE = "https://nominatim.openstreetmap.org/reverse"

_http = httpx.AsyncClient(timeout=15, headers={"User-Agent": "lucy-personal-assistant/1.0"})


@dataclass
class Location:
    city: str
    country: str
    latitude: float
    longitude: float
    timezone: str

    def label(self) -> str:
        return f"{self.city}, {self.country}" if self.country else self.city


_current: Location | None = None


def location() -> Location | None:
    return _current


def timezone() -> str:
    return _current.timezone if _current else get_settings().owner_timezone


def tz() -> ZoneInfo:
    return ZoneInfo(timezone())


def now() -> datetime:
    return datetime.now(tz())


async def geocode(city: str) -> Location | None:
    resp = await _http.get(GEOCODE, params={"name": city, "count": 1, "language": "en"})
    results = resp.json().get("results") or []
    if not results:
        return None
    r = results[0]
    return Location(r["name"], r.get("country", ""), r["latitude"], r["longitude"], r["timezone"])


async def from_coordinates(latitude: float, longitude: float) -> Location:
    """Telegram location -> city name and time zone."""
    forecast = await _http.get(
        FORECAST, params={"latitude": latitude, "longitude": longitude, "timezone": "auto", "forecast_days": 1}
    )
    tz_name = forecast.json().get("timezone", "UTC")
    city, country = "", ""
    try:
        place = await _http.get(
            REVERSE,
            params={"lat": latitude, "lon": longitude, "format": "json", "zoom": 10, "accept-language": "en"},
        )
        address = place.json().get("address", {})
        city = address.get("city") or address.get("town") or address.get("village") or address.get("county") or ""
        country = address.get("country", "")
    except Exception:
        log.warning("Reverse geocoding failed", exc_info=True)
    return Location(city or f"{latitude:.2f}, {longitude:.2f}", country, latitude, longitude, tz_name)


async def load() -> None:
    """Load the saved location at startup; if none, derive it from OWNER_TIMEZONE."""
    global _current
    from app.memory.db import db

    try:
        rows = (await (await db()).table("owner_settings").select("value").eq("key", "location").execute()).data
        if rows:
            _current = Location(**rows[0]["value"])
            return
        city = get_settings().owner_timezone.split("/")[-1].replace("_", " ")
        guess = await geocode(city)
        if guess and guess.timezone == get_settings().owner_timezone:
            await save(guess)
    except Exception:
        log.exception("Could not load the owner's location")


async def save(loc: Location) -> None:
    """Persist a new location and re-time recurring items to the new time zone."""
    global _current
    from app.memory.db import db
    from app.scheduler.reminders import retime_recurring

    old_tz = timezone()
    client = await db()
    await (
        client.table("owner_settings")
        .upsert({"key": "location", "value": asdict(loc), "updated_at": datetime.now(UTC).isoformat()})
        .execute()
    )
    _current = loc
    if loc.timezone != old_tz:
        await retime_recurring()
