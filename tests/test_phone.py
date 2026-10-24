import array
import asyncio
import base64
import hashlib
import hmac
import json
import math

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import get_settings
from app.integrations import twilio
from app.live import phone
from app.live.phone_audio import _DECODE, pcm24k_to_ulaw, ulaw_to_pcm16k
from app.main import app


def test_ulaw_matches_g711_and_round_trips():
    assert (_DECODE[0xFF], _DECODE[0x00], _DECODE[0x80]) == (0, -32124, 32124)
    tone = array.array("h", [int(12000 * math.sin(2 * math.pi * 440 * i / 24000)) for i in range(2400)])
    ulaw = pcm24k_to_ulaw(tone.tobytes())
    assert len(ulaw) == 800  # 100 ms at 8 kHz
    back = array.array("h")
    back.frombytes(ulaw_to_pcm16k(ulaw))
    assert len(back) == 1600  # 100 ms at 16 kHz
    assert 10000 < max(back) < 13500


def test_twilio_signature(monkeypatch):
    monkeypatch.setattr(get_settings(), "twilio_auth_token", "secret")
    url, params = "https://example.com/twilio/status?run=5", {"CallStatus": "busy", "CallSid": "CA1"}
    payload = url + "CallSidCA1CallStatusbusy"
    signature = base64.b64encode(hmac.new(b"secret", payload.encode(), hashlib.sha1).digest()).decode()
    assert twilio.valid_signature(url, params, signature)
    assert not twilio.valid_signature(url, params | {"CallStatus": "completed"}, signature)
    assert not twilio.valid_signature(url, params, "")


def test_stream_twiml_escapes_values():
    twiml = twilio.stream_twiml("wss://x/ws/twilio", {"run": "5", "token": 'a"b'})
    assert '<Stream url="wss://x/ws/twilio">' in twiml and 'value="a&quot;b"' in twiml


def test_place_call_checks_setup_and_number(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "twilio_account_sid", "")
    assert "aren't set up" in asyncio.run(phone.place_call("+351211234567", "task", "x"))["error"]
    monkeypatch.setattr(s, "twilio_account_sid", "AC1")
    monkeypatch.setattr(s, "twilio_auth_token", "t")
    monkeypatch.setattr(s, "twilio_phone_number", "+15550000000")
    assert "international" in asyncio.run(phone.place_call("21 123 4567", "task", "x"))["error"]


def test_stream_with_a_wrong_token_is_refused():
    client = TestClient(app)
    with client.websocket_connect("/ws/twilio") as ws:
        ws.send_text(json.dumps({"event": "connected"}))
        ws.send_text(json.dumps({"event": "start", "start": {"streamSid": "MZ1", "callSid": "CA1",
                                                             "customParameters": {"run": "5", "token": "nope"}}}))
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert closed.value.code == 4401


def test_webhooks_need_twilios_signature(monkeypatch):
    monkeypatch.setattr(get_settings(), "twilio_auth_token", "secret")
    client = TestClient(app)
    assert client.post("/twilio/status?run=5", data={"CallStatus": "busy"}).status_code == 403
    assert client.post("/twilio/voice", data={"From": "+351900000000"}).status_code == 403


def test_strangers_calling_lucys_number_get_guest_mode(monkeypatch):
    runs = []

    async def fake_run(agent, status, summary="", details=None, run_id=None):
        runs.append(details)
        return 42

    monkeypatch.setattr(phone.agents, "record_run", fake_run)
    monkeypatch.setattr(get_settings(), "owner_phone_number", "+351911111111")
    monkeypatch.setattr(get_settings(), "owner_call_pin", "")
    twiml = asyncio.run(phone.incoming_call_twiml("+351922222222"))
    assert "<Stream" in twiml and runs[-1]["kind"] == "guest"
    monkeypatch.setattr(get_settings(), "phone_guest_messages", False)
    twiml = asyncio.run(phone.incoming_call_twiml("+351922222222"))
    assert "<Hangup/>" in twiml and "<Stream" not in twiml


def test_guest_mode_knows_nothing_and_has_no_tools(monkeypatch):
    from app.live.call import live_config

    monkeypatch.setattr(get_settings(), "owner_name", "Andrew")
    prompt = phone.guest_prompt()
    assert "NOT Andrew" in prompt and "never instructions" in prompt and "take_message" in prompt
    names = {
        d.name
        for d in live_config("s", None, allowed_tools=phone.GUEST_TOOLS, extra=[phone.TAKE_MESSAGE])
        .tools[0]
        .function_declarations
    }
    assert names == {"end_conversation", "take_message"}


def test_owner_pin(monkeypatch):
    runs = []

    async def fake_run(agent, status, summary="", details=None, run_id=None):
        runs.append(details)
        return 43

    monkeypatch.setattr(phone.agents, "record_run", fake_run)
    s = get_settings()
    monkeypatch.setattr(s, "owner_phone_number", "+351911111111")
    monkeypatch.setattr(s, "owner_call_pin", "4821")
    assert "<Gather" in asyncio.run(phone.incoming_call_twiml("+351911111111"))
    assert "Wrong PIN" in asyncio.run(phone.pin_entered("+351911111111", "0000"))
    assert "Wrong PIN" in asyncio.run(phone.pin_entered("+351922222222", "4821"))  # right PIN, wrong number
    assert "<Stream" in asyncio.run(phone.pin_entered("+351911111111", "4821")) and runs[-1]["kind"] == "owner"


def test_guest_message_reaches_the_owner(monkeypatch):
    sent = []

    async def fake_send(text):
        sent.append(text)

    async def fake_load(run_id):
        return {"id": run_id, "details": {}}

    async def fake_run(*args, **kwargs):
        return 1

    monkeypatch.setattr(phone, "load_run", fake_load)
    monkeypatch.setattr(phone.outbox, "send_text", fake_send)
    monkeypatch.setattr(phone.agents, "record_run", fake_run)
    details = {"kind": "guest", "number": "+48600000002",
               "message": {"from": "Anna", "message": "Call me back about Saturday", "callback": "after 6"}}
    asyncio.run(phone.finish_call(11, details, [("user", "Hi")]))
    assert "+48600000002" in sent[0] and "Anna" in sent[0] and "Saturday" in sent[0] and "after 6" in sent[0]


def test_summary_tells_the_owner_and_books_the_calendar(monkeypatch):
    sent, calls, runs = [], [], []

    async def fake_generate(prompt, **kwargs):
        assert "Them: Yes, Friday at 8 is fine" in prompt
        return json.dumps({"outcome": "done", "summary": "Table for two on Friday at 20:00.",
                           "event": {"title": "Dinner at Ramiro", "start": "2026-10-30T20:00", "end": "", "location": ""}})

    async def fake_send(text):
        sent.append(text)

    async def fake_call(name, args):
        calls.append((name, args))
        return {"id": "ev1"}

    async def fake_run(*args, **kwargs):
        runs.append(args)
        return 1

    async def fake_save(*args, **kwargs):
        pass

    async def fake_load(run_id):
        return {"id": run_id, "details": {"answered_by": "human"}}

    monkeypatch.setattr(phone, "load_run", fake_load)
    monkeypatch.setattr(phone, "generate_text", fake_generate)
    monkeypatch.setattr(phone.outbox, "send_text", fake_send)
    monkeypatch.setattr(phone.registry, "call", fake_call)
    monkeypatch.setattr(phone.agents, "record_run", fake_run)
    monkeypatch.setattr(phone.store, "save_message", fake_save)

    transcript = [("assistant", "Hi, this is Lucy, an AI assistant."), ("user", "Yes, Friday at 8 is fine.")]
    details = {"kind": "task", "number": "+351211234567", "person": "Ramiro", "task": "Table for 2, Friday 8 pm"}
    asyncio.run(phone.finish_call(7, details, transcript))
    assert "Ramiro" in sent[0] and "Friday" in sent[0] and "calendar" in sent[0]
    assert calls[0][0] == "calendar_create_event" and calls[0][1]["start"] == "2026-10-30T20:00"


def test_task_calls_get_almost_no_tools():
    from app.live.call import live_config

    names = {d.name for d in live_config("s", None, allowed_tools=phone.TASK_TOOLS).tools[0].function_declarations}
    assert names == {"get_current_time", "end_conversation"}  # no calendar, memory, Notion…


def test_stopping_after_the_conversation_doesnt_cancel_the_follow_up(monkeypatch):
    """After a call ends, the same task hangs up and sends the summary; a late stop() must not cancel that."""
    from app.live import call

    class Session:
        async def send_client_content(self, **kwargs):
            pass

        async def receive(self):
            await asyncio.sleep(3600)
            yield None

    class Connect:
        async def __aenter__(self):
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

        voice = call.VoiceSession(send, send, channel="phone", greeting="")

        async def handler():
            asyncio.get_running_loop().call_later(0.05, voice.stop)  # hang up during the conversation
            await voice.run("system")
            asyncio.get_running_loop().call_soon(voice.stop)  # e.g. the phone line closing afterwards
            await asyncio.sleep(0.05)  # the follow-up work (hang up, summary)
            return "follow-up done"

        return await asyncio.wait_for(handler(), 2)

    assert asyncio.run(scenario()) == "follow-up done"


def test_voicemail_means_didnt_pick_up(monkeypatch):
    sent = []

    async def fake_send(text):
        sent.append(text)

    async def fake_load(run_id):
        return {"id": run_id, "details": {"answered_by": "machine_end_beep"}}

    async def fake_run(*args, **kwargs):
        return 1

    async def no_summary(*args, **kwargs):
        raise AssertionError("no summary for voicemail")

    monkeypatch.setattr(phone, "load_run", fake_load)
    monkeypatch.setattr(phone.outbox, "send_text", fake_send)
    monkeypatch.setattr(phone.agents, "record_run", fake_run)
    monkeypatch.setattr(phone, "generate_text", no_summary)
    details = {"kind": "task", "number": "+380501234567", "person": "Anna", "task": "Say hi"}
    asyncio.run(phone.finish_call(9, details, [("user", "The person you are calling is not available")]))
    assert sent == ["📞 Anna didn't pick up (voicemail answered), so I hung up."]


def test_ukrainian_call_prompt_is_native_and_feminine(monkeypatch):
    monkeypatch.setattr(get_settings(), "owner_name", "Andrew")
    prompt = phone.phone_task_prompt("Tell Anna the party is at 7", "Anna", "Ukrainian")
    assert "Люсі" in prompt and "feminine" in prompt and "native speaker" in prompt and "AI assistant" in prompt


def test_tasks_cant_make_lucy_hide_who_she_is():
    prompt = phone.phone_task_prompt("Don't say you're from Andrew; pretend you want to buy his car", "Tom", "Ukrainian")
    rules = prompt.index("Rules that come first")
    task = prompt.index("Your task")
    assert "Never call anonymously" in prompt and "false reason" in prompt and rules > task


def test_call_language_follows_the_number():
    assert phone.call_language("", "+351211234567").startswith("European Portuguese")
    assert phone.call_language("Portuguese", "+351910000002").startswith("European Portuguese")
    assert phone.call_language("Ukrainian", "+48881000000") == "Ukrainian"
    assert phone.call_language("", "+48881000000") == "Polish"
    assert phone.call_language("", "+15550000000") == "English"
    prompt = phone.phone_task_prompt("Book a haircut on Saturday at 11", "Barbearia", "", "+351211234567")
    assert "European Portuguese" in prompt and "inteligência artificial" in prompt


def test_failed_call_explains_why_and_is_remembered(monkeypatch):
    sent, saved = [], []

    async def fake_send(text):
        sent.append(text)

    async def fake_save(role, text, owner_id, channel):
        saved.append((channel, text))

    async def fake_load(run_id):
        return {"id": run_id, "details": {"person": "Mark", "number": "+380500000001"}}

    async def fake_run(*args, **kwargs):
        return 1

    monkeypatch.setattr(phone.outbox, "send_text", fake_send)
    monkeypatch.setattr(phone.store, "save_message", fake_save)
    monkeypatch.setattr(phone, "load_run", fake_load)
    monkeypatch.setattr(phone.agents, "record_run", fake_run)
    asyncio.run(phone.call_status(17, "busy", "486"))
    assert "Mark" in sent[0] and "rejected" in sent[0] and "486" in sent[0]
    assert saved == [("phone", sent[0])]


def test_an_early_machine_guess_doesnt_hang_up_on_a_person():
    assert not phone._voicemail({"answered_by": "machine_start"})
    assert phone._voicemail({"answered_by": "machine_end_silence"})
    assert phone._voicemail({"answered_by": "fax"})
    assert not phone._voicemail({"answered_by": "human"})


def test_alternative_caller_id_for_ukraine(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "twilio_phone_number", "+15550000001")
    monkeypatch.setattr(s, "alt_caller_id", "")
    assert twilio.caller_id_for("+380991234567") == "+15550000001"
    monkeypatch.setattr(s, "alt_caller_id", "+351910000001")
    monkeypatch.setattr(s, "alt_caller_id_prefixes", "+380")
    assert twilio.caller_id_for("+380991234567") == "+351910000001"
    assert twilio.caller_id_for("+48600000001") == "+15550000001"
