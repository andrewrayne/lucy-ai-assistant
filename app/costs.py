"""What the assistant spends, and a daily limit.

Every Gemini call (text, voice, embeddings, images) and every Twilio call is priced and stored in the `usage`
table. If today's total reaches DAILY_COST_LIMIT_USD, Lucy pauses new requests and calls until tomorrow (the owner's
time zone) and says why; at 80% the owner gets a warning in Telegram.

Prices are USD per 1M tokens from https://ai.google.dev/gemini-api/docs/pricing (checked 2026-10-24). Gemini 3.8 and
3.6 Flash double on 2027-01-01, which is built in below. Update PRICES when Google changes them.
"""

import asyncio
import logging
from datetime import date

from app import owner
from app.config import get_settings

log = logging.getLogger(__name__)

# model: {"in": text/image input, "audio_in": audio input, "out": text output, "audio_out": audio output}
PRICES: dict[str, dict[str, float]] = {
    "gemini-3.8-flash": {"in": 0.75, "out": 3.75},
    "gemini-3.6-flash": {"in": 0.75, "out": 3.75},
    "gemini-3.5-flash": {"in": 0.75, "out": 3.75},  # not on the pricing page; assumed like 3.6
    "gemini-3.5-flash-lite": {"in": 0.30, "out": 2.50},
    "gemini-3.8-live": {"in": 0.75, "audio_in": 3.00, "out": 4.50, "audio_out": 12.00},
    "gemini-embedding-2": {"in": 0.20},
}
PRICES_FROM_2027 = {
    "gemini-3.8-flash": {"in": 1.50, "out": 7.50},
    "gemini-3.6-flash": {"in": 1.50, "out": 7.50},
}
IMAGE_PRICE = 0.067  # one 1K image from gemini-3.1-flash-image
UNKNOWN_MODEL = {"in": 1.50, "audio_in": 3.00, "out": 7.50, "audio_out": 12.00}  # be safe: overestimate

_today: date | None = None
_spent_today = 0.0
_warned: set[str] = set()
_tasks: set[asyncio.Task] = set()


def prices(model: str, day: date | None = None) -> dict[str, float]:
    day = day or owner.now().date()
    table = PRICES_FROM_2027 if day >= date(2027, 1, 1) and model in PRICES_FROM_2027 else PRICES
    return table.get(model, PRICES.get(model, UNKNOWN_MODEL))


def token_cost(model: str, input_tokens: int, output_tokens: int, audio_in: int = 0, audio_out: int = 0) -> float:
    p = prices(model)
    return (
        input_tokens * p.get("in", 0)
        + audio_in * p.get("audio_in", p.get("in", 0))
        + output_tokens * p.get("out", 0)
        + audio_out * p.get("audio_out", p.get("out", 0))
    ) / 1_000_000


def _roll_day() -> date:
    global _today, _spent_today, _warned
    today = owner.now().date()
    if today != _today:
        _today, _spent_today, _warned = today, 0.0, set()
    return today


def spent_today() -> float:
    _roll_day()
    return _spent_today


def limit() -> float:
    return get_settings().daily_cost_limit_usd


def over_limit() -> bool:
    return limit() > 0 and spent_today() >= limit()


def limit_message() -> str:
    return (
        f"⛔ Today's spending limit (${limit():.2f}) is reached, so I'm pausing until tomorrow. "
        "Raise DAILY_COST_LIMIT_USD on Railway if you need me today. /usage shows where it went."
    )


def record(service: str, model: str, cost: float, input_tokens: int = 0, output_tokens: int = 0, details=None) -> None:
    """Count a cost now and store it in the background (never slows down or breaks the request)."""
    global _spent_today
    day = _roll_day()
    _spent_today += cost
    _maybe_warn()
    row = {
        "day": day.isoformat(), "service": service, "model": model, "input_tokens": input_tokens,
        "output_tokens": output_tokens, "cost_usd": round(cost, 6), "details": details,
    }  # fmt: skip
    try:
        task = asyncio.get_running_loop().create_task(_store(row))
    except RuntimeError:
        return
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _store(row: dict) -> None:
    if not get_settings().supabase_url:
        return
    try:
        from app.memory.db import db

        await (await db()).table("usage").insert(row).execute()
    except Exception:
        log.warning("Couldn't store a usage row", exc_info=True)


def record_tokens(model: str, usage, service: str = "gemini") -> None:
    """usage = a Gemini response's usage_metadata (text models)."""
    if not usage:
        return
    inp = usage.prompt_token_count or 0
    out = (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
    record(service, model, token_cost(model, inp, out), inp, out)


def record_live(model: str, usage) -> None:
    """usage = a Gemini Live message's usage_metadata (one turn, including the context)."""
    if not usage:
        return

    def split(details, total):
        audio = sum(d.token_count or 0 for d in details or [] if d.modality and d.modality.value == "AUDIO")
        return audio, max((total or 0) - audio, 0)

    audio_in, text_in = split(usage.prompt_tokens_details, usage.prompt_token_count)
    audio_out, text_out = split(usage.response_tokens_details, usage.response_token_count)
    cost = token_cost(model, text_in, text_out, audio_in, audio_out)
    record("gemini-live", model, cost, text_in + audio_in, text_out + audio_out)


def _maybe_warn() -> None:
    if limit() <= 0:
        return
    for name, share in (("80", 0.8), ("100", 1.0)):
        if _spent_today >= limit() * share and name not in _warned:
            _warned.add(name)
            text = (
                f"💸 I've used 80% of today's ${limit():.2f} budget (${_spent_today:.2f})."
                if name == "80"
                else limit_message()
            )
            try:
                task = asyncio.get_running_loop().create_task(_tell_owner(text))
                _tasks.add(task)
                task.add_done_callback(_tasks.discard)
            except RuntimeError:
                pass


async def _tell_owner(text: str) -> None:
    from app.bot import outbox

    if outbox.bot() is not None:
        try:
            await outbox.send_text(text)
        except Exception:
            log.warning("Couldn't send the budget warning", exc_info=True)


async def load_today() -> None:
    """At startup: today's spending so far (the limit survives redeploys)."""
    global _spent_today
    day = _roll_day()
    if not get_settings().supabase_url:
        return
    try:
        from app.memory.db import db

        rows = (await (await db()).table("usage").select("cost_usd").eq("day", day.isoformat()).execute()).data
        _spent_today = sum(float(r["cost_usd"]) for r in rows)
        log.info("Spent today so far: $%.4f", _spent_today)
    except Exception:
        log.warning("Couldn't load today's usage", exc_info=True)


async def summary(days: int = 30) -> dict:
    """Totals for /usage: today, this month, and by service."""
    from app.memory.db import db

    today = _roll_day()
    first = today.replace(day=1)
    rows = (
        await (await db()).table("usage").select("day,service,cost_usd").gte("day", first.isoformat()).execute()
    ).data
    by_service: dict[str, float] = {}
    for r in rows:
        by_service[r["service"]] = by_service.get(r["service"], 0.0) + float(r["cost_usd"])
    return {
        "today": sum(float(r["cost_usd"]) for r in rows if r["day"] == today.isoformat()),
        "month": sum(by_service.values()),
        "by_service": dict(sorted(by_service.items(), key=lambda kv: -kv[1])),
        "limit": limit(),
    }
