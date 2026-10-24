from datetime import UTC, date, datetime

from app.scheduler.brief import change, render, weather_emoji
from app.scheduler.reminders import next_due, reminder_text
from app.tools.reminders import parse_local


def test_next_due_uses_owner_timezone():
    # 06:30 UTC on 20 Oct = 07:30 in Lisbon (summer time, UTC+1) -> 08:00 local = 07:00 UTC.
    assert next_due("0 8 * * *", datetime(2026, 10, 20, 6, 30, tzinfo=UTC)) == datetime(2026, 10, 20, 7, 0, tzinfo=UTC)


def test_next_due_handles_dst_change():
    # Portugal leaves summer time on 25 Oct 2026, so 08:00 local becomes 08:00 UTC that day.
    assert next_due("0 8 * * *", datetime(2026, 10, 24, 12, 0, tzinfo=UTC)) == datetime(2026, 10, 25, 8, 0, tzinfo=UTC)


def test_parse_local_is_owner_time():
    assert parse_local("2026-10-24T18:00").isoformat() == "2026-10-24T18:00:00+01:00"


def test_late_reminders_say_so():
    row = {"text": "Call mum", "due_at": "2026-10-24T08:00:00+00:00"}
    assert reminder_text(row, datetime(2026, 10, 24, 8, 1, tzinfo=UTC)) == "⏰ Reminder: Call mum"
    late = reminder_text(row, datetime(2026, 10, 24, 9, 0, tzinfo=UTC))
    assert "was due at 09:00" in late


def test_brief_layout():
    text = render(date(2026, 10, 24), ["• 17:00 — Call"], ["BTC: $80,687 (-$1,106, -1.4%)"], ["08:00   10°  🌤"], "Oeiras, Portugal")
    assert text == (
        "🗓 Tasks for today, October 24 (Saturday):\n• 17:00 — Call\n\n"
        "💰 Markets\nBTC: $80,687 (-$1,106, -1.4%)\n\n"
        "🌤 Weather in Oeiras, Portugal\n08:00   10°  🌤\n\n"
        "📰 Tap /news for today's AI & tech news"
    )


def test_brief_handles_empty_and_failed_sections():
    text = render(date(2026, 10, 24), [], None, None, "Oeiras")
    assert "• No events" in text and text.count("unavailable") == 2


def test_market_change_format():
    assert change(80687, 81793, money=True) == "(-$1,106, -1.4%)"
    assert change(0.8934, 0.8924, digits=4) == "(+0.0010, +0.1%)"
    assert weather_emoji(0, is_day=False) == "🌙" and weather_emoji(61) == "🌧"


def test_news_tidy_drops_sources_and_spaces_items():
    from app.tools.news import tidy

    raw = "📰 AI & Tech News — October 24\n- **A** — first thing (The Guardian).\n- **B** — second (CNA)\n"
    assert tidy(raw) == "📰 AI & Tech News — October 24\n\n- **A** — first thing\n\n- **B** — second"


def test_brief_asks_calendar_for_today_only():
    import inspect

    from app.scheduler import brief

    assert "end=today)" in inspect.getsource(brief.todays_events)
