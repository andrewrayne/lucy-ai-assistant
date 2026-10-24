"""Weather for the owner's current city (or any city), from Open-Meteo. No API key."""

import httpx

from app import owner
from app.scheduler.brief import WEATHER_TEXT, weather_emoji
from app.tools.registry import registry

_http = httpx.AsyncClient(timeout=15)


@registry.register(
    "get_weather",
    "Current weather and forecast. Defaults to the owner's current city.",
    {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "Another city. Empty = where the owner is."},
            "days": {"type": "integer", "description": "Forecast days, 1-7. Default 1 (today, hour by hour)."},
        },
    },
)
async def get_weather(city: str = "", days: int = 1) -> dict:
    loc = await owner.geocode(city) if city else owner.location()
    if not loc:
        return {"error": f"I couldn't find '{city}'." if city else "I don't know where the owner is yet."}
    days = min(max(days, 1), 7)
    resp = await _http.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": loc.latitude,
            "longitude": loc.longitude,
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,is_day",
            "hourly": "temperature_2m,weather_code,precipitation_probability,is_day",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto",
            "forecast_days": days,
        },
    )
    d = resp.json()
    cur, daily, hourly = d["current"], d["daily"], d["hourly"]
    result = {
        "place": loc.label(),
        "now": {
            "temp_c": cur["temperature_2m"],
            "feels_like_c": cur["apparent_temperature"],
            "sky": WEATHER_TEXT.get(cur["weather_code"], "mixed"),
            "wind_kmh": cur["wind_speed_10m"],
        },
        "days": [
            {
                "date": daily["time"][i],
                "sky": WEATHER_TEXT.get(daily["weather_code"][i], "mixed"),
                "min_c": daily["temperature_2m_min"][i],
                "max_c": daily["temperature_2m_max"][i],
                "rain_chance_pct": daily["precipitation_probability_max"][i],
            }
            for i in range(len(daily["time"]))
        ],
    }
    if days == 1:
        result["hours"] = [
            f"{t[11:16]} {round(temp)}° {weather_emoji(code, bool(day))} rain {rain}%"
            for t, temp, code, rain, day in zip(
                hourly["time"], hourly["temperature_2m"], hourly["weather_code"],
                hourly["precipitation_probability"], hourly["is_day"], strict=True,
            )
            if 6 <= int(t[11:13]) <= 23
        ]
    return result
