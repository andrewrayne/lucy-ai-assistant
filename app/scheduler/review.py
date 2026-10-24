"""Lessons review on demand (/lessons): every lesson with a one-tap delete button.

Nothing is sent automatically; the owner checks lessons when they want to.
"""

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.memory import learning

FORGET_PREFIX = "forget_lesson:"
BUTTONS_PER_ROW = 5


def render_review(lessons: list[dict]) -> tuple[str, InlineKeyboardMarkup | None]:
    if not lessons:
        return "🧠 Lessons\n\nNo lessons yet. Correct me any time and I'll remember.", None
    lines = [f"🧠 Lessons I follow ({len(lessons)}):"]
    lines += [f"{i}. {row['content']}" for i, row in enumerate(lessons, start=1)]
    lines.append("\nTap 🗑 with a number to delete a lesson that's wrong.")
    buttons = [
        InlineKeyboardButton(text=f"🗑 {i}", callback_data=f"{FORGET_PREFIX}{row['id']}")
        for i, row in enumerate(lessons, start=1)
    ]
    rows = [buttons[i : i + BUTTONS_PER_ROW] for i in range(0, len(buttons), BUTTONS_PER_ROW)]
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


async def build_review() -> tuple[str, InlineKeyboardMarkup | None]:
    return render_review(await learning.list_lessons())


async def send_lessons_review(bot: Bot, chat_id: int) -> None:
    text, keyboard = await build_review()
    await bot.send_message(chat_id, text, reply_markup=keyboard)
