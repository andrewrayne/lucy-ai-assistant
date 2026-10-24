import asyncio
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.agent.prompts import system_prompt
from app.memory.store import Context, Message, current_conversation
from app.scheduler.daily_summary import group_by_day, transcript
from app.tools import registry


def test_current_conversation_stops_at_new_marker():
    newest_first = [
        Message("assistant", "b2"),
        Message("user", "b1"),
        Message("event", "new conversation"),
        Message("user", "old"),
    ]
    assert [m.content for m in current_conversation(newest_first)] == ["b1", "b2"]


def test_group_by_local_day_and_transcript():
    tz = ZoneInfo("Europe/Lisbon")
    rows = [
        {"id": 1, "created_at": "2026-10-20T22:30:00+00:00", "role": "user", "content": "late hi"},
        {"id": 2, "created_at": "2026-10-20T23:30:00+00:00", "role": "assistant", "content": "after midnight"},
        {"id": 3, "created_at": "2026-10-20T23:31:00+00:00", "role": "event", "content": "new conversation"},
    ]
    days = group_by_day(rows, tz)  # Lisbon is UTC+1 in October
    assert sorted(days) == ["2026-10-20", "2026-10-21"]
    text = transcript(days["2026-10-21"], tz, "Lucy")
    assert text == "[00:30] Lucy: after midnight"  # event rows are left out


def test_prompt_includes_memories_and_lessons():
    ctx = Context(
        history=[],
        memories=[
            {"kind": "preference", "content": "Andrew drinks oat flat whites.", "period_start": None, "similarity": 0.7},
            {"kind": "summary", "content": "- Planned the Porto trip", "period_start": "2026-10-20", "similarity": 0.6},
        ],
        lessons=["Never use emojis."],
    )
    prompt = system_prompt(ctx)
    assert "oat flat whites" in prompt and "2026-10-20: - Planned the Porto trip" in prompt
    assert "Never use emojis." in prompt


def test_search_history_tool_formats_results():
    hits = [{"created_at": "2026-10-20T12:00:00+00:00", "role": "user", "channel": "telegram",
             "content": "Let's plan Porto", "similarity": 0.81234}]

    async def fake_search(query, limit=8, since=None):
        assert since is not None  # days_back=7 sets a window
        return hits

    with patch("app.memory.store.search_messages", new=fake_search):
        result = asyncio.run(registry.call("search_history", {"query": "Porto", "days_back": 7}))
    assert result["results"][0] == {
        "when": "Tue 20 Oct 2026, 13:00", "who": "owner", "channel": "telegram",
        "text": "Let's plan Porto", "relevance": 0.81,
    }
