import asyncio
from unittest.mock import AsyncMock, patch

from aiogram.types import Update
from fastapi.testclient import TestClient

from app.main import app, bot, dp, settings
from app.memory.store import Context

client = TestClient(app)  # no context manager: skips the webhook setup


def make_update(user_id: int, text: str = "hello") -> dict:
    return {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "date": 0,
            "chat": {"id": user_id, "type": "private"},
            "from": {"id": user_id, "is_bot": False, "first_name": "T"},
            "text": text,
        },
    }


async def fake_reply(history, text, parts=None):
    yield "Hello "
    yield "**there**"


saved: list[tuple] = []


async def fake_save(role, content, chat_id=None, channel="telegram"):
    saved.append((role, content))


async def fake_context(text):
    return Context(history=[], memories=[], lessons=[])


def feed(update: dict) -> AsyncMock:
    """Run one update through the dispatcher with Telegram, Gemini and Supabase mocked out."""
    saved.clear()
    with (
        patch.object(type(bot), "__call__", new=AsyncMock()) as call,
        patch("app.bot.handlers.stream_reply", new=fake_reply),
        patch("app.memory.store.build_context", new=fake_context),
        patch("app.memory.store.save_message", new=fake_save),
    ):
        asyncio.run(dp.feed_update(bot, Update.model_validate(update, context={"bot": bot})))
    return call


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_webhook_rejects_wrong_secret():
    r = client.post(settings.webhook_path, json=make_update(111), headers={"X-Telegram-Bot-Api-Secret-Token": "nope"})
    assert r.status_code == 403


def test_owner_gets_reply():
    call = feed(make_update(111))
    sent = [c.args[0] for c in call.await_args_list]
    final = [m for m in sent if type(m).__name__ == "SendMessage"]
    assert final and final[-1].text == "Hello <b>there</b>"
    assert saved == [("user", "hello"), ("assistant", "Hello **there**")]


def test_stranger_gets_nothing():
    assert feed(make_update(999)).await_count == 0
    assert saved == []


def test_public_pages():
    assert "Privacy policy" in client.get("/privacy").text
    assert client.get("/").status_code == 200
    assert client.get("/docs").status_code == 404  # no public API docs
