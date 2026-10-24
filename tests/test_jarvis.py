import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import get_settings
from app.live.device import OFFLINE, DeviceOffline, MacDevice, mac
from app.main import app
from app.tools import mac as mac_tools
from app.tools.registry import registry


def test_mac_tools_are_registered():
    for name in ("look_at_screen", "mac_do", "mac_open", "spotify", "mac_status"):
        assert name in registry.names()


def test_tools_say_offline_when_jarvis_is_not_connected():
    assert not mac.online
    result = asyncio.run(registry.call("mac_open", {"target": "Safari"}))
    assert result == {"error": OFFLINE}


def test_device_request_and_answer():
    async def scenario():
        device = MacDevice()
        sent = []

        async def send(data):
            sent.append(data)
            device.resolve({"type": "device_result", "id": data["id"], "ok": True, "opened": data["target"]})

        device.attach("conn", send)
        result = await device.request("open", target="Safari")
        assert sent[0]["action"] == "open" and result["opened"] == "Safari"
        device.detach("conn")
        with pytest.raises(DeviceOffline):
            await device.request("open", target="Safari")

    asyncio.run(scenario())


def test_disconnect_fails_pending_requests():
    async def scenario():
        device = MacDevice()

        async def send(data):
            asyncio.get_running_loop().call_later(0.01, device.detach, "conn")

        device.attach("conn", send)
        with pytest.raises(DeviceOffline):
            await device.request("screenshot")

    asyncio.run(scenario())


def test_parse_action_clamps_and_checks():
    action = mac_tools.parse_action('```json\n{"action": "click", "x": 1400, "y": -5}\n```')
    assert action == {"action": "click", "x": 1000, "y": 0}
    assert mac_tools.parse_action('[{"action": "done", "note": "ok"}]')["action"] == "done"
    with pytest.raises(ValueError):
        mac_tools.parse_action('{"action": "format_disk"}')


def test_jarvis_socket_refuses_a_wrong_token(monkeypatch):
    monkeypatch.setattr(get_settings(), "jarvis_token", "right-token")
    client = TestClient(app)
    with client.websocket_connect("/ws/jarvis") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": "wrong"}))
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert closed.value.code == 4401


def test_jarvis_socket_refuses_when_no_token_is_configured(monkeypatch):
    monkeypatch.setattr(get_settings(), "jarvis_token", "")
    client = TestClient(app)
    with client.websocket_connect("/ws/jarvis") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": ""}))
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()


def test_jarvis_socket_accepts_the_owner_mac(monkeypatch):
    monkeypatch.setattr(get_settings(), "jarvis_token", "right-token")
    client = TestClient(app)
    with client.websocket_connect("/ws/jarvis") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": "right-token"}))
        assert json.loads(ws.receive_text())["type"] == "hello"
        ws.send_text(json.dumps({"type": "ping"}))
        assert json.loads(ws.receive_text())["type"] == "pong"


def test_hanging_up_doesnt_wait_for_gemini_and_saves_what_was_heard(monkeypatch):
    """Gemini can stay silent; hanging up must still end the session and keep the transcript."""
    from app.live import call

    saved = []

    async def fake_save(role, text, owner_id, channel):
        saved.append((role, text, channel))

    class SilentSession:
        async def send_client_content(self, **kwargs):
            pass

        async def receive(self):
            await asyncio.sleep(3600)
            yield None

    class Connect:
        async def __aenter__(self):
            return SilentSession()

        async def __aexit__(self, *exc):
            pass

    class FakeClient:
        class aio:
            class live:
                @staticmethod
                def connect(**kwargs):
                    return Connect()

    monkeypatch.setattr(call.store, "save_message", fake_save)
    monkeypatch.setattr(call, "client", lambda: FakeClient())

    async def scenario():
        async def send(_):
            pass

        voice = call.VoiceSession(send, send, channel="jarvis")
        task = asyncio.create_task(voice.run("system"))
        await asyncio.sleep(0.05)
        voice.user_text.append("What is two plus two?")
        voice.stop()
        await asyncio.wait_for(task, 2)

    asyncio.run(scenario())
    assert saved == [("user", "What is two plus two?", "jarvis")]


def test_stop_phrases():
    from app.live.call import is_stop_phrase

    assert is_stop_phrase("Stop.")
    assert is_stop_phrase("Хватит!")
    assert is_stop_phrase("ok stop it")
    assert is_stop_phrase("Окей, всё, стоп.")
    assert is_stop_phrase("Okay, that's all.")
    assert is_stop_phrase("Окей, всё")
    assert not is_stop_phrase("Всё, открой Spotify")
    assert not is_stop_phrase("Don't stop the music on Spotify please")
    assert not is_stop_phrase("")


def test_mac_context_lists_front_app_and_apps():
    from app.live.jarvis import mac_context

    text = mac_context({"front_app": "Safari", "apps": ["Notion", "Telegram"]})
    assert "Safari" in text and "Notion, Telegram" in text
    assert mac_context({}) == ""


def test_voice_config_has_language_hints_and_end_tool():
    from app.live.call import live_config

    config = live_config("system", None)
    assert "ru-RU" in config.input_audio_transcription.language_codes
    names = [f.name for f in config.tools[0].function_declarations]
    assert "end_conversation" in names and "mac_volume" in names


def test_audio_spoken_while_connecting_is_sent_after_connect(monkeypatch):
    from app.live import call

    received = []

    class Session:
        async def send_client_content(self, **kwargs):
            pass

        async def send_realtime_input(self, audio):
            received.append(audio.data)

        async def receive(self):
            await asyncio.sleep(3600)
            yield None

    class Connect:
        async def __aenter__(self):
            await asyncio.sleep(0.05)  # connecting takes a moment
            return Session()

        async def __aexit__(self, *exc):
            pass

    class FakeClient:
        class aio:
            class live:
                @staticmethod
                def connect(**kwargs):
                    return Connect()

    async def no_save(*args, **kwargs):
        pass

    monkeypatch.setattr(call, "client", lambda: FakeClient())
    monkeypatch.setattr(call.store, "save_message", no_save)

    async def scenario():
        async def send(_):
            pass

        voice = call.VoiceSession(send, send, channel="jarvis", greeting="")
        task = asyncio.create_task(voice.run("system"))
        await voice.feed_audio(b"\x01\x00" * 8000)  # half a second, before Gemini is connected
        await asyncio.sleep(0.2)
        voice.stop()
        await asyncio.wait_for(task, 2)

    asyncio.run(scenario())
    assert b"".join(received) == b"\x01\x00" * 8000


def test_actions_are_silent_on_the_mac_but_questions_are_not():
    from google.genai import types

    from app.live.call import VoiceSession, live_config

    async def send(_):
        pass

    mac = VoiceSession(send, send, channel="jarvis", quiet_actions=True)
    phone = VoiceSession(send, send, channel="call")
    open_app = types.FunctionCall(name="mac_open", args={"target": "Spotify"})
    now_playing = types.FunctionCall(name="spotify", args={"action": "now_playing"})
    weather = types.FunctionCall(name="get_weather", args={})

    silent = types.FunctionResponseScheduling.SILENT
    assert mac._scheduling(open_app, {"ok": True}) == {"scheduling": silent}
    assert mac._scheduling(open_app, {"error": "No app called Spotyfi"})["scheduling"] != silent  # failures are spoken
    assert mac._scheduling(now_playing, {"ok": True})["scheduling"] != silent  # a question
    assert mac._scheduling(weather, {"now": {}}) == {}
    assert phone._scheduling(open_app, {"ok": True}) == {}  # the Telegram call keeps talking as before

    declarations = {d.name: d for d in live_config("s", None, quiet_actions=True).tools[0].function_declarations}
    assert declarations["mac_open"].behavior == types.Behavior.NON_BLOCKING
    assert declarations["get_weather"].behavior is None
    plain = {d.name: d for d in live_config("s", None).tools[0].function_declarations}
    assert plain["mac_open"].behavior is None


def test_short_reply_after_silent_action_is_dropped_long_one_plays():
    import time

    from app.live.call import VoiceSession

    played = []

    async def send_json(_):
        pass

    async def send_bytes(data):
        played.append(data)

    async def scenario():
        voice = VoiceSession(send_json, send_bytes, channel="jarvis", quiet_actions=True)
        voice._hold_until = time.monotonic() + 8
        await voice._send_voice(b"done")
        assert played == []  # held
        voice._held_words = 6
        await voice._release_held()
        assert played == [b"done"]
        await voice._send_voice(b"more")
        assert played == [b"done", b"more"]

    asyncio.run(scenario())
