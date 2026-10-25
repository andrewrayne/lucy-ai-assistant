"""Several photos sent together (a Telegram album) get one combined answer."""

import asyncio
import io
from types import SimpleNamespace

from app.bot import handlers


class FakeBot:
    async def download(self, media):
        return io.BytesIO(media.file_id.encode())

    async def send_message(self, *args, **kwargs):
        pass

    async def send_chat_action(self, *args, **kwargs):
        pass


def photo(mid: int, group: str | None, caption: str | None = None):
    return SimpleNamespace(
        message_id=mid, media_group_id=group, caption=caption, chat=SimpleNamespace(id=1),
        photo=[SimpleNamespace(file_id=f"small{mid}"), SimpleNamespace(file_id=f"big{mid}")], document=None,
    )  # fmt: skip


def test_album_is_answered_once(monkeypatch):
    replies = []

    async def fake_reply(bot, chat_id, text, channel="telegram", parts=None):
        replies.append((text, parts))

    monkeypatch.setattr(handlers, "_reply", fake_reply)
    monkeypatch.setattr(handlers, "ALBUM_WAIT", 0.2)

    class NoTyping:
        async def __aenter__(self):
            pass

        async def __aexit__(self, *exc):
            pass

    monkeypatch.setattr(handlers.ChatActionSender, "typing", staticmethod(lambda **kw: NoTyping()))
    bot = FakeBot()

    async def scenario():
        await handlers.on_photo(photo(11, "g1", "Which one is best?"), bot)
        await asyncio.sleep(0.05)
        await handlers.on_photo(photo(13, "g1"), bot)
        await handlers.on_photo(photo(12, "g1"), bot)
        await handlers.on_photo(photo(20, None), bot)  # a single photo is answered on its own, right away
        await asyncio.sleep(0.5)

    asyncio.run(scenario())
    assert len(replies) == 2
    single, album = replies
    assert single[0] == "[photo]" and len(single[1]) == 2
    text, parts = album
    assert text == "[3 photos] Which one is best?"
    assert [p.inline_data.data for p in parts[:3]] == [b"big11", b"big12", b"big13"]  # in order, largest size
    assert "3 images together" in parts[3].text and "Which one is best?" in parts[3].text
