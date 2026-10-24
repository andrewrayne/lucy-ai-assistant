"""Crash alerts: every ERROR in the server log also reaches the owner's Telegram.

- Covers errors logged by our code, uncaught exceptions in requests (uvicorn logs them as ERROR) and in background
  tasks (the asyncio exception handler below logs them).
- The same error is sent at most once per 30 minutes, and at most 10 alerts per hour in total.
- Secret values (tokens, keys) are removed from the text before it's sent.
- Logs themselves stay in Railway (Deployments → Logs) or `railway logs`.
"""

import asyncio
import logging
import time
import traceback

from app.config import get_settings

REPEAT_SECONDS = 30 * 60
MAX_PER_HOUR = 10
_sent_at: dict[str, float] = {}
_recent: list[float] = []
_tasks: set[asyncio.Task] = set()


def _secrets() -> list[str]:
    s = get_settings()
    values = [
        s.telegram_bot_token, s.gemini_api_key, s.supabase_service_key, s.google_client_secret,
        s.google_refresh_token, s.notion_token, s.github_token, s.agents_token, s.jarvis_token, s.twilio_auth_token,
    ]  # fmt: skip
    return [v for v in values if v and len(v) >= 8]


def redact(text: str) -> str:
    for secret in _secrets():
        text = text.replace(secret, "•••")
    return text


def format_alert(record: logging.LogRecord) -> str:
    text = f"⚠️ Server error in {record.name}\n{record.getMessage()}"
    if record.exc_info and record.exc_info[1] is not None:
        exc = record.exc_info[1]
        last = traceback.extract_tb(record.exc_info[2])[-1:] if record.exc_info[2] else []
        where = f" ({last[0].filename.rsplit('/', 1)[-1]}:{last[0].lineno})" if last else ""
        text += f"\n{type(exc).__name__}: {exc}{where}"
    return redact(text)[:1500]


def should_send(key: str, now: float | None = None) -> bool:
    now = now or time.monotonic()
    if now - _sent_at.get(key, -REPEAT_SECONDS) < REPEAT_SECONDS:
        return False
    _recent[:] = [t for t in _recent if now - t < 3600]
    if len(_recent) >= MAX_PER_HOUR:
        return False
    _sent_at[key] = now
    _recent.append(now)
    return True


class TelegramAlertHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith("app.alerts"):
            return  # never alert about failing to alert
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # not inside the server's event loop
        key = f"{record.name}:{record.msg}"
        if not should_send(key):
            return
        task = loop.create_task(_send(format_alert(record)))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)


async def _send(text: str) -> None:
    from app.bot import outbox

    if outbox.bot() is None:
        return
    try:
        await outbox.bot().send_message(get_settings().owner_telegram_id, text)
    except Exception:
        logging.getLogger("app.alerts").warning("Couldn't send an error alert to Telegram", exc_info=True)


def install() -> None:
    """Call once at startup, inside the event loop."""
    root = logging.getLogger()
    if not any(isinstance(h, TelegramAlertHandler) for h in root.handlers):
        root.addHandler(TelegramAlertHandler())

    def on_task_error(loop: asyncio.AbstractEventLoop, context: dict) -> None:
        exc = context.get("exception")
        logging.getLogger("app.background").error(
            "Background task crashed: %s",
            context.get("message", ""),
            exc_info=(type(exc), exc, exc.__traceback__) if exc else None,
        )

    asyncio.get_running_loop().set_exception_handler(on_task_error)
