import asyncio
from datetime import date
from types import SimpleNamespace

from app import costs
from app.config import get_settings


def test_prices_and_the_2027_change():
    assert costs.token_cost("gemini-3.8-flash", 1_000_000, 0) == 0.75
    assert costs.prices("gemini-3.8-flash", date(2027, 1, 1))["in"] == 1.50
    assert costs.prices("gemini-3.5-flash-lite", date(2027, 1, 1))["in"] == 0.30  # unchanged
    # Live: 1M audio in + 1M audio out = $3 + $12
    assert costs.token_cost("gemini-3.8-live", 0, 0, audio_in=1_000_000, audio_out=1_000_000) == 15.0


def test_live_usage_splits_text_and_audio(monkeypatch):
    seen = []
    monkeypatch.setattr(costs, "record", lambda *a, **k: seen.append(a))
    detail = lambda m, n: SimpleNamespace(modality=SimpleNamespace(value=m), token_count=n)  # noqa: E731
    usage = SimpleNamespace(
        prompt_token_count=609, prompt_tokens_details=[detail("TEXT", 313), detail("AUDIO", 269)],
        response_token_count=60, response_tokens_details=[detail("AUDIO", 60)],
    )  # fmt: skip
    costs.record_live("gemini-3.8-live", usage)
    service, model, cost = seen[0][:3]
    expected = (340 * 0.75 + 269 * 3.00 + 60 * 12.00) / 1_000_000
    assert service == "gemini-live" and abs(cost - expected) < 1e-12


def test_daily_limit(monkeypatch):
    monkeypatch.setattr(get_settings(), "daily_cost_limit_usd", 1.0)
    monkeypatch.setattr(get_settings(), "supabase_url", "")
    monkeypatch.setattr(costs, "_today", None)
    sent = []

    async def fake_tell(text):
        sent.append(text)

    monkeypatch.setattr(costs, "_tell_owner", fake_tell)

    async def scenario():
        costs.record("gemini", "gemini-3.8-flash", 0.85)
        assert not costs.over_limit()
        costs.record("gemini", "gemini-3.8-flash", 0.20)
        await asyncio.sleep(0)
        return costs.over_limit()

    assert asyncio.run(scenario())
    assert any("80%" in t for t in sent) and any("limit" in t for t in sent)


def test_agent_stops_when_over_the_limit(monkeypatch):
    from app.agent import agent

    monkeypatch.setattr(costs, "over_limit", lambda: True)

    async def collect():
        return [piece async for piece in agent.stream_reply(None, "hi")]

    assert "spending limit" in "".join(asyncio.run(collect()))
