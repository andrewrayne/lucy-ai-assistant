from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.agents import alert_text, render_overview, summarize
from app.main import app

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def run(agent, status, minutes_ago, summary=""):
    return {"agent": agent, "status": status, "summary": summary, "updated_at": (NOW - timedelta(minutes=minutes_ago)).isoformat()}


def test_overview_health_and_counts():
    rows = [
        run("report-agent", "failed", 5, "Bank API timeout"),
        run("sync-agent", "running", 300),  # 5 hours: stuck
        run("report-agent", "success", 60),
        run("news-agent", "success", 10),
    ]
    items = summarize(rows, NOW)
    assert [(a["agent"], a["health"]) for a in items] == [("report-agent", "failing"), ("sync-agent", "stuck"), ("news-agent", "ok")]
    expense = items[0]
    assert (expense["successes"], expense["failures"], expense["last_failure"]) == (1, 1, "Bank API timeout")


def test_render_overview_shows_problems_first():
    text = render_overview(summarize([run("a", "failed", 5, "boom"), run("b", "success", 5)], NOW))
    assert text.splitlines()[1].startswith("❌ a: failed") and "boom" in text and "✅ b: success" in text
    assert render_overview([]) == "🤖 No agent reports in the last 24 hours."


def test_alert_texts():
    assert alert_text({"agent": "x", "status": "failed", "summary": "disk full", "created_at": NOW.isoformat()}) == "🚨 Agent failed: x\ndisk full"
    assert alert_text({"agent": "y", "status": "running", "summary": "", "created_at": NOW.isoformat()}).startswith("⏳ Agent stuck: y")


def test_endpoint_requires_the_agents_token():
    client = TestClient(app)
    body = {"agent": "report-agent", "status": "success"}
    with patch("app.web.agents_api.get_settings") as settings, patch("app.agents.record_run", new=AsyncMock(return_value=7)):
        settings.return_value.agents_token = "secret-token"
        assert client.post("/api/agent-runs", json=body).status_code == 401
        assert client.post("/api/agent-runs", json=body, headers={"Authorization": "Bearer nope"}).status_code == 401
        ok = client.post("/api/agent-runs", json=body, headers={"Authorization": "Bearer secret-token"})
        assert ok.status_code == 200 and ok.json() == {"ok": True, "run_id": 7}
        bad = client.post("/api/agent-runs", json={"agent": "x", "status": "exploded"}, headers={"Authorization": "Bearer secret-token"})
        assert bad.status_code == 422


def test_endpoint_is_closed_when_no_token_is_configured():
    with patch("app.web.agents_api.get_settings") as settings:
        settings.return_value.agents_token = ""
        r = TestClient(app).post("/api/agent-runs", json={"agent": "x", "status": "success"}, headers={"Authorization": "Bearer "})
    assert r.status_code == 401
