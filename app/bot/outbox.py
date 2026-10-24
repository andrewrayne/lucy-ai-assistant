"""Lets tools send files and photos to the owner's Telegram chat.

Tools don't receive the bot object, so main.py registers it here once at startup.
"""

from aiogram import Bot
from aiogram.types import BufferedInputFile

from app.config import get_settings

_bot: Bot | None = None

CAPTION_LIMIT = 1024


def set_bot(bot: Bot) -> None:
    global _bot
    _bot = bot


def bot() -> Bot | None:
    return _bot


def _require_bot() -> Bot:
    if _bot is None:
        raise RuntimeError("Telegram bot is not ready")
    return _bot


async def send_photo(data: bytes, caption: str = "", filename: str = "image.jpg") -> None:
    await _require_bot().send_photo(
        get_settings().owner_telegram_id, BufferedInputFile(data, filename), caption=caption[:CAPTION_LIMIT] or None
    )


async def send_document(data: bytes, filename: str, caption: str = "") -> None:
    await _require_bot().send_document(
        get_settings().owner_telegram_id, BufferedInputFile(data, filename), caption=caption[:CAPTION_LIMIT] or None
    )


async def send_audio(data: bytes, filename: str, caption: str = "") -> None:
    await _require_bot().send_audio(
        get_settings().owner_telegram_id, BufferedInputFile(data, filename), caption=caption[:CAPTION_LIMIT] or None
    )


async def send_text(text: str) -> None:
    from app.bot.streaming import send_markdown

    await send_markdown(_require_bot(), get_settings().owner_telegram_id, text)
