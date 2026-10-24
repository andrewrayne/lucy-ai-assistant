import asyncio
from types import SimpleNamespace

from google.genai import errors, types

import app.agent.agent as agent
import app.gemini as gemini
from app.config import get_settings
from app.tools import registry


def run(coro):
    return asyncio.run(coro)


def test_get_current_time_tool():
    result = run(registry.call("get_current_time", {"timezone": "Asia/Tokyo"}))
    assert result["timezone"] == "Asia/Tokyo" and "iso" in result


def test_registry_reports_errors_instead_of_crashing():
    assert "error" in run(registry.call("no_such_tool", {}))
    assert "error" in run(registry.call("get_current_time", {"timezone": "Mars/Base"}))


def chunk(*parts: types.Part):
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)))]
    )


class FakeModels:
    """Stands in for client.aio.models. Scripted responses per call."""

    def __init__(self, script):
        self.script = script  # list of (model_or_None, chunks_or_exception)
        self.calls = []

    async def generate_content_stream(self, model, contents, config):
        self.calls.append((model, contents))
        expected_model, outcome = self.script.pop(0)
        assert expected_model in (None, model)
        if isinstance(outcome, Exception):
            raise outcome

        async def gen():
            for c in outcome:
                yield c

        return gen()


def use_fake(monkeypatch, script):
    fake = FakeModels(script)
    monkeypatch.setattr(gemini, "client", lambda: SimpleNamespace(aio=SimpleNamespace(models=fake)))
    gemini._cooldown_until.clear()
    return fake


async def collect(gen):
    return "".join([piece async for piece in gen])


def test_tool_loop(monkeypatch):
    call = types.Part(function_call=types.FunctionCall(id="c1", name="get_current_time", args={}))
    fake = use_fake(
        monkeypatch,
        [(None, [chunk(call)]), (None, [chunk(types.Part(text="It's "), types.Part(text="noon."))])],
    )
    assert run(collect(agent.stream_reply(None, "time?"))) == "It's noon."
    # Second request carries the tool result back to the model, with the call id.
    response = fake.calls[1][1][-1].parts[0].function_response
    assert response.name == "get_current_time" and response.id == "c1" and "iso" in response.response


def test_falls_back_when_main_model_is_overloaded(monkeypatch):
    s = get_settings()
    overloaded = errors.ServerError(503, {"error": {"message": "high demand", "status": "UNAVAILABLE"}})
    use_fake(
        monkeypatch,
        [(s.gemini_text_model, overloaded), (s.gemini_fallback_models.split(",")[0], [chunk(types.Part(text="Hi"))])],
    )
    assert run(collect(agent.stream_reply(None, "hi"))) == "Hi"
    assert s.gemini_text_model in gemini._cooldown_until
