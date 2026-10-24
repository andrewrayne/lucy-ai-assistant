import logging

from app import alerts
from app.config import get_settings


def test_alert_text_hides_secrets(monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "AIzaSECRETKEY123456")
    try:
        raise RuntimeError("bad key AIzaSECRETKEY123456")
    except RuntimeError:
        record = logging.LogRecord(
            "app.tools", logging.ERROR, __file__, 1, "Tool failed", None, exc_info=__import__("sys").exc_info()
        )
    text = alerts.format_alert(record)
    assert "AIzaSECRETKEY123456" not in text and "RuntimeError" in text and "app.tools" in text


def test_alerts_are_rate_limited(monkeypatch):
    monkeypatch.setattr(alerts, "_sent_at", {})
    monkeypatch.setattr(alerts, "_recent", [])
    assert alerts.should_send("a", now=1000)
    assert not alerts.should_send("a", now=1100)  # same error again within 30 min
    assert alerts.should_send("a", now=1000 + 31 * 60)
    for i in range(20):
        alerts.should_send(f"e{i}", now=5000 + i)
    assert len(alerts._recent) <= alerts.MAX_PER_HOUR
