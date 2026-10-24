"""The morning brief: today's calendar, markets and hourly weather in one message.

A fixed template (no AI rewriting), so the layout is always the same:

    🗓 Tasks for today, October 24 (Saturday):
    • 17:00 — Call with Anna

    💰 Markets
    BTC: $80,687 (-$1,106, -1.4%)
    S&P 500: 7,624 (-36, -0.5%)
    USD/EUR 0.8934 (+0.0010, +0.1%)

    🌤 Weather in Oeiras, Portugal
    08:00   10°  🌤
    ...

    📰 Tap /news for today's AI & tech news

Data sources need no API keys: CoinGecko (crypto), Yahoo Finance chart API
(indexes), Frankfurter (ECB currency rates) and Open-Meteo (weather). Each part
is optional: if one source fails, the brief still goes out with the rest.
"""

import asyncio
import logging
from datetime import date, timedelta

import httpx
from aiogram import Bot

from app import owner
from app.config import get_settings
from app.memory import store
from app.scheduler import reminders
from app.tools.calendar import calendar_list_events

log = logging.getLogger(__name__)

_http = httpx.AsyncClient(timeout=15, headers={"User-Agent": "Mozilla/5.0 (lucy-personal-assistant)"})

FIRST_HOUR, LAST_HOUR = 8, 22


# ---------- calendar ----------


async def todays_events() -> list[str]:
    today = owner.now().date().isoformat()
    res = await calendar_list_events(start=today, end=today)  # a date end includes that whole day
    lines = []
    for e in res["events"]:
        when = "All day" if e["all_day"] else e["start"][11:16]
        lines.append(f"• {when} — {e['title']}")
    return lines


# ---------- markets ----------


def change(price: float, previous: float, money: bool = False, digits: int = 0) -> str:
    """(-$1,106, -1.4%) style change string."""
    diff = price - previous
    pct = diff / previous * 100 if previous else 0
    sign = "+" if diff >= 0 else "-"
    amount = f"{abs(diff):,.{digits}f}"
    return f"({sign}{'$' if money else ''}{amount}, {sign}{abs(pct):.1f}%)"


async def crypto() -> list[str]:
    """BRIEF_CRYPTO like 'bitcoin:BTC,ethereum:ETH' (CoinGecko ids)."""
    pairs = [p.split(":") for p in get_settings().brief_crypto.split(",") if ":" in p]
    if not pairs:
        return []
    resp = await _http.get(
        "https://api.coingecko.com/api/v3/simple/price",
        params={"ids": ",".join(i for i, _ in pairs), "vs_currencies": "usd", "include_24hr_change": "true"},
    )
    data = resp.json()
    lines = []
    for coin_id, symbol in pairs:
        if coin_id in data:
            price = data[coin_id]["usd"]
            previous = price / (1 + data[coin_id]["usd_24h_change"] / 100)
            lines.append(f"{symbol}: ${price:,.0f} {change(price, previous, money=True)}")
    return lines


async def _index_line(ticker: str, name: str) -> str | None:
    resp = await _http.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}", params={"range": "5d", "interval": "1d"}
    )
    result = resp.json()["chart"]["result"][0]
    closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
    price = result["meta"].get("regularMarketPrice") or closes[-1]
    previous = closes[-2] if len(closes) >= 2 else result["meta"].get("chartPreviousClose")
    return f"{name}: {price:,.0f} {change(price, previous)}" if previous else None


async def indexes() -> list[str]:
    """BRIEF_INDEXES like '^GSPC:S&P 500,^IXIC:Nasdaq' (Yahoo tickers)."""
    pairs = [p.split(":", 1) for p in get_settings().brief_indexes.split(",") if ":" in p]
    lines = await asyncio.gather(*(_index_line(t, n) for t, n in pairs), return_exceptions=True)
    return [line for line in lines if isinstance(line, str)]


async def currencies() -> list[str]:
    """BRIEF_CURRENCIES like 'USD/EUR' (ECB data, so no UAH)."""
    lines = []
    for pair in get_settings().brief_currencies.split(","):
        if "/" not in pair:
            continue
        base, quote = (p.strip().upper() for p in pair.split("/", 1))
        start = (date.today() - timedelta(days=7)).isoformat()
        resp = await _http.get(f"https://api.frankfurter.dev/v1/{start}..", params={"base": base, "symbols": quote})
        days = sorted(resp.json().get("rates", {}).items())
        if len(days) >= 2:
            price, previous = days[-1][1][quote], days[-2][1][quote]
            lines.append(f"{base}/{quote} {price:.4f} {change(price, previous, digits=4)}")
    return lines


async def markets() -> list[str]:
    parts = await asyncio.gather(crypto(), indexes(), currencies(), return_exceptions=True)
    lines = []
    for name, part in zip(("crypto", "indexes", "currencies"), parts, strict=True):
        if isinstance(part, Exception):
            log.warning("Brief: %s failed: %r", name, part)
        else:
            lines += part
    return lines


# ---------- weather ----------

# WMO weather codes used by Open-Meteo.
WEATHER_TEXT = {
    0: "clear sky", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "heavy freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow",
    77: "snow grains", 80: "light showers", 81: "showers", 82: "violent showers", 85: "snow showers",
    86: "heavy snow showers", 95: "thunderstorm", 96: "thunderstorm with hail", 99: "severe thunderstorm",
}


def weather_emoji(code: int, is_day: bool = True) -> str:
    if code == 0:
        return "☀️" if is_day else "🌙"
    if code in (1, 2):
        return "🌤" if is_day else "☁️"
    if code == 3:
        return "☁️"
    if code in (45, 48):
        return "🌫"
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67):
        return "🌧"
    if code in (80, 81, 82):
        return "🌦"
    if code in (71, 73, 75, 77, 85, 86):
        return "❄️"
    if code in (95, 96, 99):
        return "⛈"
    return "🌡"


async def hourly_weather() -> list[str]:
    loc = owner.location()
    if not loc:
        return []
    resp = await _http.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": loc.latitude,
            "longitude": loc.longitude,
            "hourly": "temperature_2m,weather_code,is_day",
            "timezone": "auto",
            "forecast_days": 1,
        },
    )
    h = resp.json()["hourly"]
    lines = []
    for time, temp, code, is_day in zip(h["time"], h["temperature_2m"], h["weather_code"], h["is_day"], strict=True):
        hour = int(time[11:13])
        if FIRST_HOUR <= hour <= LAST_HOUR:
            lines.append(f"{time[11:16]}   {round(temp)}°  {weather_emoji(code, bool(is_day))}")
    return lines


# ---------- the brief ----------


def render(today: date, events, market_lines, weather_lines, city: str) -> str:
    """Pure formatting, easy to test. None for a section means its source failed."""
    header = f"🗓 Tasks for today, {today.strftime('%B')} {today.day} ({today.strftime('%A')}):"
    parts = [header + "\n" + ("\n".join(events) if events else "• No events" if events is not None else "• unavailable")]
    parts.append("💰 Markets\n" + ("\n".join(market_lines) if market_lines else "unavailable"))
    parts.append(f"🌤 Weather in {city}\n" + ("\n".join(weather_lines) if weather_lines else "unavailable"))
    parts.append("📰 Tap /news for today's AI & tech news")
    return "\n\n".join(parts)


async def compose() -> str:
    names = ("calendar", "markets", "weather")
    results = await asyncio.gather(todays_events(), markets(), hourly_weather(), return_exceptions=True)
    for name, result in zip(names, results, strict=True):
        if isinstance(result, Exception):
            log.warning("Brief: %s failed: %r", name, result)
    events, market_lines, weather_lines = (None if isinstance(r, Exception) else r for r in results)
    loc = owner.location()
    return render(owner.now().date(), events, market_lines, weather_lines, loc.label() if loc else owner.timezone())


async def send_brief(bot: Bot, chat_id: int) -> None:
    text = await compose()
    await bot.send_message(chat_id, text)  # plain text: "/news" becomes a tappable command
    await store.save_message("assistant", text, chat_id)


async def ensure_morning_brief() -> None:
    """Create the daily brief on first start (time from BRIEF_TIME, owner's time zone)."""
    if await reminders.pending(kind="brief"):
        return
    hour, minute = (int(x) for x in get_settings().brief_time.split(":"))
    cron = f"{minute} {hour} * * *"
    await reminders.create("Morning brief", reminders.next_due(cron), recurrence=cron, kind="brief")
    log.info("Morning brief scheduled daily at %s", get_settings().brief_time)
