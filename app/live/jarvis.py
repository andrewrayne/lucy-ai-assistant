"""WebSocket for Jarvis, the owner's Mac app.

One long-lived connection per Mac. It carries two things:
1. Voice: Jarvis says "call_start" (wake word "Lucy" or the Shift + Command + F hotkey), streams microphone
   audio, and plays Lucy's audio back. Same engine as the Telegram call.
2. Device control: the server sends {"type": "device", ...} requests and Jarvis
   answers with {"type": "device_result", ...} (see app/live/device.py).

Protocol on /ws/jarvis:
  client -> server  first message  {"type": "auth", "token": JARVIS_TOKEN}
                    {"type": "call_start", "front_app": "...", "apps": [...]}, {"type": "call_end"}, {"type": "ping"}
                    binary frames  16 kHz 16-bit mono PCM (only while a call is on)
                    {"type": "device_result", "id": "...", "ok": true, ...}
  server -> client  {"type": "hello"} after auth
                    the call events from app/live/call.py, then {"type": "call_ended"}
                    binary frames  24 kHz 16-bit mono PCM
                    {"type": "device", "id": "...", "action": "...", ...}
"""

import asyncio
import hmac
import json
import logging

from fastapi import WebSocket, WebSocketDisconnect

from app.config import get_settings
from app.live.call import AUTH_TIMEOUT, VoiceSession, voice_system_prompt
from app.live.device import mac

log = logging.getLogger(__name__)

JARVIS_STYLE = """
You are talking through Jarvis, the app on the owner's Mac. The owner said your name ("Lucy") or pressed the
hotkey (Shift + Command + F); you are still Lucy.
How to behave on the Mac (it's a quick voice remote, not a chat):
- The owner may speak another language; understand it and answer in English, unless the owner asks you to switch
  language (see the language rule above).
- These rules override the general voice rules above.
- When asked to DO something (open or quit an app, play or pause music, volume, a note, reminder, event,
  memory), call the action and say NOTHING: no "okay", no "opening it", no "done". The action itself is the answer.
  Speak only if it failed, with the reason. Exception: after adding or changing a calendar event, say one word:
  "I wrote it down" as a single first-person feminine verb in the language you're speaking ("Added." in
  English), nothing more.
- When asked a QUESTION, answer in one or two short sentences. Speak only to answer.
- Answer only what the owner just said. Never repeat or answer an earlier question.
- If the speech clearly isn't meant for you (someone else talking, TV, background), stay silent.
  If it was for you but you didn't catch it, say "Sorry, say that again?"
- Never invent the result of an action: wait for it. Each request = one call; don't repeat a call.
- Before sending email, deleting, buying or posting anything, ask once and act only after a clear yes.
- About the screen: only judge from a fresh look_at_screen; after a click, look again.
- Tasks on websites (buy, compare, book, fill a form, find something on a site): browser_task when it's available
  (Claude does it in the owner's Chrome and reports to Telegram); mac_do only if browser_task isn't available.
  Paying is a second browser_task call with confirmed=true, only after the owner said yes to the reported total.
  Never put passwords or card numbers into a task.
- Change data with its own tool, in the cloud: Notion (notion_replace_text, notion_delete_blocks,
  notion_append_to_page), email, calendar, Drive, Sheets. Use mac_do (clicking) only for things that exist only on the
  Mac, or when the owner explicitly asks to do it on the screen. "Don't click" means: never use mac_do.
- When the owner says stop, that's all, goodbye or thanks-and-done: call end_conversation and say nothing.
Mac actions: mac_open (apps, links, files), mac_quit_app, mac_volume, mac_media (play/pause/next/previous),
mac_system (lock screen, display off, screen saver), spotify (find and play music), look_at_screen
(see the screen), mac_do (multi-step clicking and typing). Everything else (calendar, email, Notion, reminders,
memory, web search, weather) works exactly like in chat.
"""

# No spoken greeting on the Mac: the chime says "go ahead", and people start talking right away
# (a "Yes?" would talk over them, and the Mac mutes its mic while Lucy speaks).
JARVIS_GREETING = ""


def mac_context(info: dict) -> str:
    """What Jarvis tells us about the Mac when a conversation starts."""
    lines = []
    if info.get("front_app"):
        lines.append(f"The app in front right now: {str(info['front_app'])[:80]}.")
    apps = [str(a)[:60] for a in (info.get("apps") or [])][:300]
    if apps:
        lines.append("Apps installed on the Mac (use these exact names with mac_open): " + ", ".join(apps) + ".")
    return ("\n" + "\n".join(lines) + "\n") if lines else ""


def token_ok(given: str) -> bool:
    expected = get_settings().jarvis_token
    return bool(expected) and hmac.compare_digest(given.encode(), expected.encode())


class JarvisConnection:
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.voice: VoiceSession | None = None
        self.voice_task: asyncio.Task | None = None
        self._send_lock = asyncio.Lock()

    async def send_json(self, data: dict) -> None:
        async with self._send_lock:
            await self.ws.send_text(json.dumps(data))

    async def send_bytes(self, data: bytes) -> None:
        async with self._send_lock:
            await self.ws.send_bytes(data)

    async def start_call(self, info: dict) -> None:
        if self.voice and self.voice.active:
            return
        log.info("Jarvis conversation started")
        self.voice = VoiceSession(
            self.send_json, self.send_bytes, channel="jarvis", greeting=JARVIS_GREETING, quiet_actions=True
        )
        self.voice_task = asyncio.create_task(self._run_call(self.voice, mac_context(info)))

    async def _run_call(self, voice: VoiceSession, mac_info: str) -> None:
        try:
            await voice.run(await voice_system_prompt(JARVIS_STYLE + mac_info, recent=False))
        except Exception as exc:
            log.error("Jarvis call failed: %r", exc)
        finally:
            try:
                await self.send_json({"type": "call_ended"})
            except Exception:
                pass

    def end_call(self) -> None:
        if self.voice:
            self.voice.stop()

    async def handle(self, msg: dict) -> None:
        if msg.get("bytes") is not None:
            if self.voice and self.voice.active:
                await self.voice.feed_audio(msg["bytes"])
            return
        if not msg.get("text"):
            return
        data = json.loads(msg["text"])
        kind = data.get("type")
        if kind == "device_result":
            mac.resolve(data)
        elif kind == "call_start":
            await self.start_call(data)
        elif kind == "call_end":
            self.end_call()
        elif kind == "ping":
            await self.send_json({"type": "pong"})

    async def run(self) -> None:
        mac.attach(self, self.send_json)
        await self.send_json({"type": "hello", "name": get_settings().assistant_name})
        try:
            while True:
                msg = await self.ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                await self.handle(msg)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            mac.detach(self)
            self.end_call()
            if self.voice_task:
                self.voice_task.cancel()


async def run_jarvis(ws: WebSocket) -> None:
    await ws.accept()
    try:
        first = json.loads(await asyncio.wait_for(ws.receive_text(), AUTH_TIMEOUT))
        if first.get("type") != "auth" or not token_ok(str(first.get("token", ""))):
            raise PermissionError("Bad token")
    except (PermissionError, TimeoutError, ValueError, WebSocketDisconnect) as exc:
        log.warning("Jarvis refused: %r", exc)
        await ws.close(code=4401, reason="Unauthorized")
        return
    await JarvisConnection(ws).run()
