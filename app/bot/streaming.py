"""Show a reply in Telegram while it is being generated.

Uses Telegram's native draft preview (sendMessageDraft). If that is not
available, falls back to sending one message and editing it.
"""

import logging
import random
import time
from collections.abc import AsyncIterator

from aiogram import Bot
from aiogram.enums import ChatAction, ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest

from app.bot.formatting import TELEGRAM_LIMIT, markdown_to_html, split_message

log = logging.getLogger(__name__)

UPDATE_EVERY = 0.6  # seconds between preview updates (Telegram rate limits)


async def send_markdown(bot: Bot, chat_id: int, text: str) -> None:
    """Send a complete (non-streamed) Markdown message, split if it is too long."""
    for chunk in split_message(text):
        try:
            await bot.send_message(chat_id, markdown_to_html(chunk), parse_mode=ParseMode.HTML)
        except TelegramBadRequest:
            await bot.send_message(chat_id, chunk)


class ReplyStreamer:
    def __init__(self, bot: Bot, chat_id: int) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self.draft_id = random.randint(1, 2**31 - 1)
        self.use_drafts = True
        self.preview_message_id: int | None = None
        self.text = ""
        self._last_update = 0.0

    async def run(self, pieces: AsyncIterator[str]) -> str:
        """Stream all pieces into the chat and return the full text."""
        await self.bot.send_chat_action(self.chat_id, ChatAction.TYPING)
        async for piece in pieces:
            self.text += piece
            if time.monotonic() - self._last_update >= UPDATE_EVERY:
                await self._preview()
        await self.finish()
        return self.text

    async def _preview(self) -> None:
        self._last_update = time.monotonic()
        # Plain text while streaming: half-finished Markdown would break HTML parsing.
        preview = self.text[:TELEGRAM_LIMIT]
        if not preview.strip():
            return
        if self.use_drafts:
            try:
                await self.bot.send_message_draft(chat_id=self.chat_id, draft_id=self.draft_id, text=preview)
                return
            except TelegramAPIError as exc:
                log.warning("Drafts unavailable (%s), falling back to message edits", exc)
                self.use_drafts = False
        try:
            if self.preview_message_id is None:
                msg = await self.bot.send_message(self.chat_id, preview)
                self.preview_message_id = msg.message_id
            else:
                await self.bot.edit_message_text(preview, chat_id=self.chat_id, message_id=self.preview_message_id)
        except TelegramBadRequest as exc:  # e.g. "message is not modified"
            log.debug("Preview update skipped: %s", exc)

    async def finish(self, note: str = "") -> None:
        """Send the final, formatted message (a draft is only a temporary preview)."""
        text = self.text.strip() + (f"\n\n{note}" if note else "")
        if not text.strip():
            text = "I couldn't come up with a reply. Could you rephrase that?"
        chunks = split_message(text)
        for i, chunk in enumerate(chunks):
            if i == 0 and self.preview_message_id is not None:
                await self._edit_formatted(chunk)
            else:
                await self._send_formatted(chunk)

    async def _send_formatted(self, chunk: str) -> None:
        try:
            await self.bot.send_message(self.chat_id, markdown_to_html(chunk), parse_mode=ParseMode.HTML)
        except TelegramBadRequest:
            await self.bot.send_message(self.chat_id, chunk)

    async def _edit_formatted(self, chunk: str) -> None:
        try:
            await self.bot.edit_message_text(
                markdown_to_html(chunk),
                chat_id=self.chat_id,
                message_id=self.preview_message_id,
                parse_mode=ParseMode.HTML,
            )
        except TelegramBadRequest:
            try:
                await self.bot.edit_message_text(chunk, chat_id=self.chat_id, message_id=self.preview_message_id)
            except TelegramBadRequest as exc:  # "message is not modified"
                log.debug("Final edit skipped: %s", exc)
