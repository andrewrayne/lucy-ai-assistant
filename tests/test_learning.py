import asyncio
from unittest.mock import AsyncMock, patch

from aiogram.types import Update

from app.agent.prompts import system_prompt
from app.main import bot, dp
from app.memory.learning import skill_slug
from app.memory.store import Context
from app.scheduler.review import FORGET_PREFIX, render_review


def test_skill_names_are_slugs():
    assert skill_slug("Publish a Video!") == "publish-a-video"
    assert skill_slug("  weekly_expenses ") == "weekly-expenses"


def test_review_lists_lessons_with_delete_buttons():
    lessons = [{"id": 7, "content": "No emoji in emails."}, {"id": 9, "content": "Sign as Andrew."}]
    text, keyboard = render_review(lessons)
    assert "1. No emoji in emails.\n2. Sign as Andrew." in text
    buttons = keyboard.inline_keyboard[0]
    assert [b.text for b in buttons] == ["🗑 1", "🗑 2"]
    assert buttons[1].callback_data == f"{FORGET_PREFIX}9"


def test_review_without_lessons_has_no_buttons():
    text, keyboard = render_review([])
    assert "No lessons yet" in text and keyboard is None


def test_prompt_lists_skills():
    prompt = system_prompt(Context([], [], [], [{"name": "log-expense", "description": "Add an expense row"}]))
    assert "- log-expense: Add an expense row" in prompt and "load_skill" in prompt


def test_strangers_cannot_delete_lessons():
    update = {
        "update_id": 2,
        "callback_query": {
            "id": "1",
            "chat_instance": "x",
            "data": f"{FORGET_PREFIX}7",
            "from": {"id": 999, "is_bot": False, "first_name": "Eve"},
        },
    }
    with (
        patch.object(type(bot), "__call__", new=AsyncMock()) as call,
        patch("app.memory.learning.forget_lesson", new=AsyncMock()) as forget,
    ):
        asyncio.run(dp.feed_update(bot, Update.model_validate(update, context={"bot": bot})))
    assert forget.await_count == 0 and call.await_count == 0
