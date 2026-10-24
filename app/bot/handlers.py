"""Telegram handlers: text goes to the Gemini agent, replies are streamed back.

Every message in and out is saved to Supabase (with an embedding), so the
assistant can search everything it has ever discussed with the owner.
"""

import asyncio
import logging
from collections import defaultdict

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from aiogram.utils.chat_action import ChatActionSender
from google.genai import types

from app import agents, costs, owner
from app.agent.agent import stream_reply
from app.bot.streaming import ReplyStreamer, send_markdown
from app.config import get_settings
from app.memory import learning, store
from app.scheduler.brief import send_brief
from app.scheduler.review import FORGET_PREFIX, build_review, send_lessons_review
from app.tools.news import news_digest
from app.voice import transcribe, voice_parts

log = logging.getLogger(__name__)
router = Router(name="main")

# One reply at a time per chat, so quick follow-ups don't interleave.
_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


async def _safe(coro, what: str) -> None:
    """Memory writes must never break the conversation."""
    try:
        await coro
    except Exception:
        log.exception("Could not %s", what)


@router.message(CommandStart())
async def on_start(message: Message) -> None:
    name = get_settings().assistant_name
    await message.answer(
        f"Hi! I'm {name}, your personal assistant. I run in the cloud, "
        "so I'm here even when your computer is off, and I remember our conversations.\n\n"
        "Just write to me. /new starts a fresh conversation (I'll still remember the old one), "
        "/call starts a voice call, /brief sends your morning brief now, /news the latest AI & tech news, /city sets where you are, "
        "/lessons and /skills show what I've learned."
    )


@router.message(Command("new"))
async def on_new(message: Message) -> None:
    await _safe(store.start_new_conversation(message.chat.id), "mark a new conversation")
    await message.answer("Fresh start. What's next?")


@router.message(Command("city"))
async def on_city(message: Message, command: CommandObject) -> None:
    name = (command.args or "").strip()
    if not name:
        loc = owner.location()
        current = f"I think you're in {loc.label()} ({loc.timezone})." if loc else f"Time zone: {owner.timezone()}."
        await message.answer(f"{current}\nTo change it: /city Berlin, or share your location from the 📎 menu.")
        return
    loc = await owner.geocode(name)
    if not loc:
        await message.answer(f"I couldn't find a city called “{name}”. Try the English name.")
        return
    await owner.save(loc)
    await message.answer(f"📍 Got it: {loc.label()}. Time zone {loc.timezone}; reminders and the brief follow you.")


@router.message(F.location)
async def on_location(message: Message) -> None:
    loc = await owner.from_coordinates(message.location.latitude, message.location.longitude)
    await owner.save(loc)
    await message.answer(f"📍 Location updated: {loc.label()} ({loc.timezone}).")


@router.message(Command("brief"))
async def on_brief(message: Message, bot: Bot) -> None:
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    await send_brief(bot, message.chat.id)


@router.message(Command("call"))
async def on_call(message: Message) -> None:
    button = InlineKeyboardButton(text="📞 Call Lucy", web_app=WebAppInfo(url=get_settings().base_url + "/call"))
    await message.answer("Tap to call me:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[button]]))


@router.message(Command("agents"))
async def on_agents(message: Message) -> None:
    await message.answer(agents.render_overview(await agents.overview(24)))


@router.message(Command("usage"))
async def on_usage(message: Message) -> None:
    data = await costs.summary()
    lines = [
        f"💸 **Today:** ${data['today']:.2f}" + (f" of ${data['limit']:.2f}" if data["limit"] > 0 else ""),
        f"**This month:** ${data['month']:.2f}",
    ]
    names = {"gemini": "Chat and tools", "gemini-live": "Voice (calls, Mac)", "twilio": "Phone minutes",
             "gemini-embedding": "Memory search", "gemini-image": "Images"}  # fmt: skip
    lines += [f"- {names.get(k, k)}: ${v:.2f}" for k, v in data["by_service"].items()]
    lines.append("\n(Twilio's monthly number fee isn't included.)")
    await send_markdown(message.bot, message.chat.id, "\n".join(lines))


@router.message(Command("lessons"))
async def on_lessons(message: Message, bot: Bot) -> None:
    await send_lessons_review(bot, message.chat.id)


@router.message(Command("skills"))
async def on_skills(message: Message) -> None:
    skills = await learning.list_skills()
    if not skills:
        await message.answer("🛠 No skills yet. Teach me how you want a recurring task done and I'll save it.")
        return
    lines = [f"🛠 Skills ({len(skills)}):"] + [f"• {s['name']} — {s['description']}" for s in skills]
    lines.append("\nAsk me to change or delete one by name.")
    await message.answer("\n".join(lines))


@router.callback_query(F.data.startswith(FORGET_PREFIX))
async def on_forget_lesson(callback: CallbackQuery) -> None:
    lesson_id = int(callback.data.removeprefix(FORGET_PREFIX))
    removed = await learning.forget_lesson(lesson_id)
    text, keyboard = await build_review()
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest:
        pass  # unchanged
    await callback.answer("Lesson deleted" if removed else "Already deleted")


@router.message(Command("news"))
async def on_news(message: Message, bot: Bot) -> None:
    try:
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):  # "typing…" until done
            digest = await news_digest()
    except Exception:
        log.exception("News failed")
        await message.answer("⚠️ I couldn't fetch the news right now. Try /news again in a minute.")
        return
    await send_markdown(bot, message.chat.id, digest)
    await _safe(store.save_message("assistant", digest, message.chat.id), "save the news")


async def _reply(bot: Bot, chat_id: int, text: str, channel: str = "telegram", parts=None) -> None:
    """Answer one owner message with a streamed text reply and save both sides to memory."""
    async with _locks[chat_id]:
        # Context first (so the new message isn't in its own history), then save it in parallel.
        context = await store.build_context(text)
        saving_user = asyncio.create_task(
            _safe(store.save_message("user", text, chat_id, channel=channel), "save a message")
        )

        streamer = ReplyStreamer(bot, chat_id)
        try:
            reply = await streamer.run(stream_reply(context, text, parts))
        except Exception:
            log.exception("Agent failed")
            await streamer.finish(note="⚠️ Gemini is overloaded or unreachable right now. Please try again in a minute.")
            await saving_user
            return

        await saving_user
        await _safe(store.save_message("assistant", reply, chat_id, channel=channel), "save a reply")


@router.message(F.text)
async def on_text(message: Message, bot: Bot) -> None:
    await _reply(bot, message.chat.id, message.text)


@router.message(F.voice | F.audio)
async def on_voice(message: Message, bot: Bot) -> None:
    """Voice note -> Gemini hears the recording (plus a transcript for memory) -> text reply."""
    media = message.voice or message.audio
    mime = media.mime_type or "audio/ogg"
    try:
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            audio = (await bot.download(media)).read()
            transcript = await transcribe(audio, mime)
    except Exception:
        log.exception("Could not read voice message")
        await message.answer("⚠️ I couldn't process that voice message. Please try again.")
        return
    log.info("Voice note %ss, file %s -> %r", media.duration, media.file_id, transcript[:200])
    await _reply(
        bot, message.chat.id, transcript or "(voice message)", channel="voice",
        parts=voice_parts(audio, mime, transcript),
    )


@router.message(F.photo | (F.document & F.document.mime_type.startswith("image/")))
async def on_photo(message: Message, bot: Bot) -> None:
    """Photo (or image file) -> Gemini sees it, together with the caption -> text reply."""
    media = message.photo[-1] if message.photo else message.document  # largest photo size
    mime = "image/jpeg" if message.photo else message.document.mime_type
    try:
        image = (await bot.download(media)).read()
    except Exception:
        log.exception("Could not download photo")
        await message.answer("⚠️ I couldn't open that image. Please try again.")
        return
    caption = (message.caption or "").strip()
    parts = [
        types.Part.from_bytes(data=image, mime_type=mime),
        types.Part(text=caption or "(The owner sent this image without a caption. Describe what matters in it.)"),
    ]
    await _reply(bot, message.chat.id, f"[photo] {caption}".strip(), parts=parts)


@router.message()
async def on_other(message: Message) -> None:
    await message.answer("I can read text and images, listen to voice notes and see shared locations.")
