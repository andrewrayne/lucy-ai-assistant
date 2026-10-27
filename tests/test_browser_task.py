"""Browser tasks handed to Claude Code on the Mac (optional, BROWSER_AGENT=claude)."""

import asyncio

from app.config import get_settings
from app.tools import browser
from app.tools.registry import registry


def tool_names() -> set[str]:
    return {d.name for d in registry.gemini_tools()[0].function_declarations}


def test_hidden_unless_turned_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "browser_agent", "")
    assert "browser_task" not in tool_names()
    monkeypatch.setattr(get_settings(), "browser_agent", "claude")
    assert "browser_task" in tool_names()


def test_offline_mac_is_reported(monkeypatch):
    monkeypatch.setattr(get_settings(), "browser_agent", "claude")
    monkeypatch.setattr(browser.mac, "_send", None)
    result = asyncio.run(browser.browser_task("Find a Rubik's cube on Amazon"))
    assert "offline" in result["error"]


def test_task_runs_on_the_mac_and_reports_to_telegram(monkeypatch):
    monkeypatch.setattr(get_settings(), "browser_agent", "claude")
    sent, requests, saved = [], [], []

    async def fake_send(_):
        pass

    async def fake_request(action, timeout=0, **params):
        requests.append((action, params))
        return {"ok": True, "result": "Added the cube to the cart: $9.99, https://amazon.example/cart"}

    async def fake_text(text):
        sent.append(text)

    async def fake_save(*args, **kwargs):
        saved.append(args)

    monkeypatch.setattr(browser.mac, "_send", fake_send)
    monkeypatch.setattr(browser.mac, "request", fake_request)
    monkeypatch.setattr(browser.outbox, "send_text", fake_text)
    monkeypatch.setattr(browser.store, "save_message", fake_save)

    async def scenario():
        started = await browser.browser_task("Put a Rubik's cube in my Amazon cart")
        assert started["started"]
        await asyncio.gather(*browser._running)

    asyncio.run(scenario())
    action, params = requests[0]
    assert action == "claude_task" and "Rubik's cube" in params["prompt"]
    assert "stop right before the final" in params["prompt"] and "explicitly confirmed" not in params["prompt"]
    assert "$9.99" in sent[0] and saved


def test_confirmed_order_pays_and_card_numbers_are_removed(monkeypatch):
    monkeypatch.setattr(get_settings(), "browser_agent", "claude")
    requests = []

    async def fake_send(_):
        pass

    async def fake_request(action, timeout=0, **params):
        requests.append(params)
        return {"ok": True, "result": "Order placed, total 4.10 EUR"}

    async def nothing(*args, **kwargs):
        pass

    monkeypatch.setattr(browser.mac, "_send", fake_send)
    monkeypatch.setattr(browser.mac, "request", fake_request)
    monkeypatch.setattr(browser.outbox, "send_text", nothing)
    monkeypatch.setattr(browser.store, "save_message", nothing)

    async def scenario():
        await browser.browser_task("Glovo: place the water order, total 4.10 EUR, card 4111 1111 1111 1111", True)
        await asyncio.gather(*browser._running)

    asyncio.run(scenario())
    prompt = requests[0]["prompt"]
    assert "explicitly confirmed" in prompt and "4111" not in prompt and "[card number removed]" in prompt
