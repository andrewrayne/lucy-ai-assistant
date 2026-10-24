"""Live voice conversations: a client (Telegram Mini App or Jarvis) <-> this server <-> Gemini Live.

VoiceSession is the engine shared by every client. It doesn't read the socket
itself: the client feeds it microphone audio (feed_audio) and gives it two
callbacks to send JSON events and audio back.

Mini App protocol on /ws/call:
  client -> server  first message  {"type": "auth", "init_data": "..."} or {"type": "auth", "token": "..."}
                    binary frames  16 kHz 16-bit mono PCM from the microphone
                    {"type": "hangup"}
  server -> client  {"type": "ready"}, {"type": "transcript", "role": "user"|"assistant", "text": "..."},
                    {"type": "interrupted"}, {"type": "status", "text": "..."}, {"type": "ended", "reason": "..."}
                    binary frames  24 kHz 16-bit mono PCM to play

The Gemini API key never leaves the server. The same tool registry as the text
agent is exposed to Gemini Live, and the transcript is saved to memory.
"""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import WebSocket, WebSocketDisconnect
from google.genai import types

from app import costs, security
from app.agent.prompts import system_prompt
from app.config import get_settings
from app.gemini import client
from app.live.auth import AuthError, verify_call_link_token, verify_init_data
from app.memory import store
from app.tools import registry

log = logging.getLogger(__name__)

INPUT_MIME = "audio/pcm;rate=16000"
AUTH_TIMEOUT = 10
MAX_RECONNECTS = 5

VOICE_STYLE = """
You are now talking with the owner by voice. Everything you say is spoken aloud.
- Talk like a warm, natural human assistant: short sentences, one idea at a time.
- No Markdown, lists, links, emoji or reading out URLs. Say numbers and times the way people say them.
- If the owner interrupts, stop and listen. Ask a short question if something is unclear.
- Use your tools exactly as in chat (calendar, email, reminders, Notion, search...). Briefly say what
  you're doing if a tool takes a moment, then give the result.
- You can search the web (web_search) and YouTube (youtube_search). Never say you can't browse:
  say "let me look that up", search, then summarize the top results.
- Language: speak English by default. If the owner asks you to speak another language (for example Russian or
  Ukrainian), switch completely and speak it like a native speaker, not English with an accent, and keep using it
  until asked to switch back. You are a woman: in languages with grammatical gender use feminine forms about
  yourself. Your name is Lucy (Люси in Russian, Люсі in Ukrainian).
"""

CALL_GREETING = "(The owner just called you. Greet them in one short sentence.)"

PRECONNECT_SECONDS = 10  # audio spoken while Gemini Live is connecting is kept and sent afterwards
REPEAT_WINDOW = 3  # seconds: an identical tool call is not run twice
REPEAT_WINDOW_OPENING = 30  # seconds for calls that open things (apps, links, music)
OPENING_TOOLS = {"mac_open", "spotify", "generate_image", "create_document"}
STOP_WORDS = {"stop", "enough", "quiet", "shut", "стоп", "хватит", "замолчи", "остановись", "стой", "досить"}
# Short endings that mean "that's it" once filler words are removed ("Okay, that's all", "Окей, всё").
END_PHRASES = {
    "that's all",
    "thats all",
    "that's it",
    "thats it",
    "that is all",
    "всё",
    "все",
    "всё всё",
    "на этом всё",
}
FILLERS = {"ok", "okay", "окей", "ок", "ну", "so", "well", "lucy", "люси", "thanks", "спасибо"}

# Actions: things Lucy does rather than answers. On the Mac they run silently: declared NON_BLOCKING and answered
# with a SILENT result, so the model has nothing to say ("Opening Spotify", "Done"). Tested with gemini-3.8-live:
# with normal (blocking) calls it stayed quiet but called "open Spotify" 8 times; non-blocking + silent = one call.
# A failed action is answered normally, so Lucy says what went wrong.
ACTION_TOOLS = {
    "mac_open",
    "mac_quit_app",
    "mac_volume",
    "mac_media",
    "mac_system",
    "mac_do",
    "spotify",
    "create_reminder",
    "cancel_reminder",
    "set_morning_brief",
    "set_location",
    "calendar_create_event",
    "calendar_update_event",
    "calendar_delete_event",
    "notion_create_page",
    "notion_add_database_entry",
    "notion_replace_text",
    "notion_delete_blocks",
    "notion_append_to_page",
    "save_memory",
    "save_lesson",
    "forget_lesson",
    "create_skill",
    "delete_skill",
    "sheets_create",
    "sheets_append",
    "sheets_update",
    "forms_create",
    "gmail_send",
    "gmail_create_draft",
    "github_create_issue",
    "github_comment_issue",
    "create_document",
    "generate_image",
    "deep_research",
}
QUIET_HOLD_SECONDS = 8  # after a silent action, a reply of up to 4 words is dropped (Katya's guard)

END_CONVERSATION = types.FunctionDeclaration(
    name="end_conversation",
    description="End this voice conversation (hang up) when it's finished: goodbye, thanks, that's all, stop, "
    "or the task of the call is done.",
    parameters_json_schema={"type": "object", "properties": {}},
)


def is_stop_phrase(text: str) -> bool:
    """A short phrase (up to 4 words) like "stop", "enough", "okay, that's all" ends the conversation silently."""
    words = [w.strip(".,!?…-").lower() for w in text.split()]
    words = [w for w in words if w]
    if not 0 < len(words) <= 4:
        return False
    if any(w in STOP_WORDS for w in words):
        return True
    rest = " ".join(w for w in words if w not in FILLERS)
    return rest in END_PHRASES


def is_failure(result: dict) -> bool:
    return bool(result.get("error")) or result.get("ok") is False or result.get("done") is False


SendJson = Callable[[dict], Awaitable[None]]
SendBytes = Callable[[bytes], Awaitable[None]]


def recent_dialogue(context: store.Context, limit: int = 12) -> str:
    lines = [
        f"{'Owner' if m.role == 'user' else 'You'}: {m.content[:400]}"
        for m in context.history[-limit:]
        if m.role in ("user", "assistant")
    ]
    return "\nRecent conversation (for context):\n" + "\n".join(lines) + "\n" if lines else ""


async def voice_system_prompt(extra: str = "", recent: bool = True) -> str:
    """recent=False leaves out the latest chat lines: on the Mac, Lucy only gets long-term memory
    (otherwise an unclear phrase got answered with an old question from the history)."""
    context = await store.build_context("")
    return system_prompt(context) + (recent_dialogue(context) if recent else "") + VOICE_STYLE + extra


def live_config(
    system: str,
    handle: str | None,
    quiet_actions: bool = False,
    allowed_tools: set[str] | None = None,
    extra: list[types.FunctionDeclaration] | None = None,
) -> types.LiveConnectConfig:
    """allowed_tools limits which registry tools the session gets (phone calls with strangers get almost none)."""
    s = get_settings()
    voice = types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=s.gemini_voice))
    tools = registry.gemini_tools()
    if allowed_tools is not None:
        tools[0].function_declarations = [d for d in tools[0].function_declarations if d.name in allowed_tools]
    if quiet_actions:
        for declaration in tools[0].function_declarations:
            if declaration.name in ACTION_TOOLS:
                declaration.behavior = types.Behavior.NON_BLOCKING
    tools[0].function_declarations.extend([END_CONVERSATION, *(extra or [])])
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(voice_config=voice),
        system_instruction=system,
        tools=tools,
        # Tell Gemini which languages to expect (without hints, Russian speech was once heard as Chinese).
        input_audio_transcription=types.AudioTranscriptionConfig(
            language_codes=[c.strip() for c in s.voice_language_codes.split(",") if c.strip()],
            adaptation_phrases=[s.assistant_name, "Notion", "Telegram", "Gmail", "Spotify"],
        ),
        # The owner's phrase ends after this much silence.
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(silence_duration_ms=s.voice_silence_ms)
        ),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        # Long calls: resume after the server rotates the connection, and keep the context window bounded.
        session_resumption=types.SessionResumptionConfig(handle=handle),
        context_window_compression=types.ContextWindowCompressionConfig(sliding_window=types.SlidingWindow()),
    )


class VoiceSession:
    """One live conversation with Gemini, independent of how audio reaches us."""

    def __init__(
        self,
        send_json: SendJson,
        send_bytes: SendBytes,
        channel: str = "call",
        greeting: str = CALL_GREETING,
        quiet_actions: bool = False,
        allowed_tools: set[str] | None = None,
        save_transcript: bool = True,
        end_on_stop_phrase: bool = True,
        extra_tools: dict | None = None,
        max_minutes: int | None = None,
    ):
        """quiet_actions=True (the Mac): actions run silently and Lucy only speaks to answer questions."""
        self._send_json, self._send_bytes = send_json, send_bytes
        self.quiet_actions = quiet_actions
        self.allowed_tools = allowed_tools
        # Phone calls with other people: their words must not go into the owner's history as the owner's.
        self.save_transcript = save_transcript
        self.end_on_stop_phrase = end_on_stop_phrase
        # Tools that only make sense in this session: {name: (FunctionDeclaration, async handler() -> dict)}.
        self.extra_tools = extra_tools or {}
        self.max_minutes = max_minutes  # default: MAX_CALL_MINUTES  # off on phone calls: "stop" there isn't for Lucy
        self.transcript: list[tuple[str, str]] = []  # the whole conversation, (role, text)
        self._hold_until = 0.0  # after a silent action: hold Lucy's voice until we know it's a real answer
        self._held: list[bytes] = []
        self._held_words = 0
        self._stop_timer: asyncio.Task | None = None
        self._turn = security.Turn()  # the owner's current spoken request (for prompt-injection checks)
        self.channel = channel
        self.greeting = greeting
        self.session = None  # current Gemini Live session (replaced on reconnect)
        self.handle: str | None = None
        self.active = True
        self.user_text: list[str] = []
        self.assistant_text: list[str] = []
        self.started = time.monotonic()
        self._tasks: set[asyncio.Task] = set()
        self._runner: asyncio.Task | None = None
        self._in_run = False
        self._pending_audio: list[bytes] = []  # spoken before Gemini Live connected
        self._recent_calls: dict[str, tuple[float, dict]] = {}
        self._connected_once = False
        self._stop_checked = False

    async def send_json(self, data: dict) -> None:
        try:
            await self._send_json(data)
        except Exception:
            self.active = False

    async def feed_audio(self, pcm16k: bytes) -> None:
        """Microphone audio from the client. Before the first connection it's kept (up to 10 s) and sent
        once Gemini is ready, so the first words after the chime aren't lost."""
        if self.active and self.session is None and not self._connected_once:
            self._pending_audio.append(pcm16k)
            while sum(map(len, self._pending_audio)) > PRECONNECT_SECONDS * 32000:
                self._pending_audio.pop(0)
            return
        if self.active and self.session is not None:
            try:
                await self.session.send_realtime_input(audio=types.Blob(data=pcm16k, mime_type=INPUT_MIME))
            except Exception:
                log.debug("Audio dropped during reconnect")

    async def flush_transcript(self) -> None:
        user, assistant = "".join(self.user_text).strip(), "".join(self.assistant_text).strip()
        self.user_text, self.assistant_text = [], []
        for role, text in (("user", user), ("assistant", assistant)):
            if text:
                self.transcript.append((role, text))
            if text and self.save_transcript:
                try:
                    await store.save_message(role, text, get_settings().owner_telegram_id, channel=self.channel)
                except Exception:
                    log.exception("Could not save the voice transcript")

    async def handle_tools(self, tool_call: types.LiveServerToolCall) -> None:
        security.use_turn(self._turn)  # this task's context: checks see the owner's latest phrase
        responses = []
        for fc in tool_call.function_calls or []:
            log.info("Voice tool: %s(%s)", fc.name, fc.args)
            if fc.name == "end_conversation":
                # Hang up right away, without a goodbye.
                log.info("Voice (%s): Lucy ended the conversation", self.channel)
                await self.flush_transcript()
                await self.send_json({"type": "ended", "reason": "Goodbye"})
                self.stop()
                return
            # The voice model sometimes repeats the same call; run it once and reuse the result.
            key = f"{fc.name}:{json.dumps(fc.args or {}, sort_keys=True, default=str)}"
            window = REPEAT_WINDOW_OPENING if fc.name in OPENING_TOOLS else REPEAT_WINDOW
            seen = self._recent_calls.get(key)
            if seen and time.monotonic() - seen[0] < window:
                log.info("Voice tool %s repeated, reusing the result", fc.name)
                self._recent_calls[key] = (time.monotonic(), seen[1])
                responses.append(types.FunctionResponse(id=fc.id, name=fc.name, response=seen[1]))
                continue
            await self.send_json({"type": "status", "text": f"Using {fc.name.replace('_', ' ')}…"})
            if fc.name in self.extra_tools:
                result = await self.extra_tools[fc.name][1](**(fc.args or {}))
            elif self.allowed_tools is not None and fc.name not in self.allowed_tools:
                result = {"error": f"{fc.name} isn't available in this conversation"}
            else:
                result = await registry.call(fc.name, fc.args)
            self._recent_calls[key] = (time.monotonic(), result)
            responses.append(
                types.FunctionResponse(id=fc.id, name=fc.name, response=result, **self._scheduling(fc, result))
            )
        if responses and self.session is not None:
            await self.session.send_tool_response(function_responses=responses)
        await self.send_json({"type": "status", "text": ""})

    def _is_quiet_action(self, fc: types.FunctionCall) -> bool:
        return (
            self.quiet_actions
            and fc.name in ACTION_TOOLS
            and not (fc.name == "spotify" and (fc.args or {}).get("action") == "now_playing")  # a question
        )

    def _scheduling(self, fc: types.FunctionCall, result: dict) -> dict:
        """Silent actions: success adds the result quietly; a failure makes Lucy say what went wrong."""
        if not (self.quiet_actions and fc.name in ACTION_TOOLS):
            return {}
        silent = self._is_quiet_action(fc) and not is_failure(result)
        scheduling = types.FunctionResponseScheduling.SILENT if silent else types.FunctionResponseScheduling.WHEN_IDLE
        return {"scheduling": scheduling}

    async def _send_voice(self, data: bytes) -> None:
        """Lucy's audio to the client. Right after a silent action it's held: more than 4 words means a real
        answer (released), a short "Done"/"Opening it" that ends the turn is dropped."""
        if time.monotonic() < self._hold_until:
            self._held.append(data)
            return
        await self._send_bytes(data)

    async def _release_held(self) -> None:
        held, self._held = self._held, []
        self._hold_until = 0.0
        for chunk in held:
            await self._send_bytes(chunk)

    async def _end_if_stop_phrase(self) -> None:
        """The owner said just "stop" / "that's all": wait a moment for more words, then hang up silently."""
        await asyncio.sleep(0.9)
        if self.active and is_stop_phrase("".join(self.user_text)):
            log.info("Voice (%s): stop phrase, ending", self.channel)
            await self.flush_transcript()
            await self.send_json({"type": "ended", "reason": "Stopped"})
            self.stop()

    async def pump(self, session) -> str:
        """Relay one Live connection until it ends. Returns why it ended."""
        while self.active:
            async for msg in session.receive():
                if not self.active:
                    return "hangup"
                if msg.usage_metadata:
                    costs.record_live(get_settings().gemini_live_model, msg.usage_metadata)
                if msg.session_resumption_update and msg.session_resumption_update.new_handle:
                    self.handle = msg.session_resumption_update.new_handle
                if msg.go_away:
                    return "go_away"
                if msg.tool_call:
                    if any(self._is_quiet_action(fc) for fc in msg.tool_call.function_calls or []):
                        self._hold_until = time.monotonic() + QUIET_HOLD_SECONDS
                        self._held_words = 0
                    # Run tools in the background so a long one (a Mac task) doesn't freeze the call.
                    task = asyncio.create_task(self.handle_tools(msg.tool_call))
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)
                sc = msg.server_content
                if not sc:
                    continue
                if sc.input_transcription and sc.input_transcription.text and not self.user_text:
                    log.info("Voice (%s): owner is speaking", self.channel)
                    self._turn = security.Turn()  # a new phrase: earlier outside content no longer counts
                    self._stop_checked = False
                # Once Lucy starts answering, the owner's phrase is complete: a bare "stop" ends the conversation.
                answering = bool(sc.model_turn or (sc.output_transcription and sc.output_transcription.text))
                if answering and self.end_on_stop_phrase and not self._stop_checked and self.user_text:
                    self._stop_checked = True
                    if is_stop_phrase("".join(self.user_text)):
                        log.info("Voice (%s): stop phrase, ending", self.channel)
                        await self.flush_transcript()
                        await self.send_json({"type": "ended", "reason": "Stopped"})
                        return "hangup"
                if sc.input_transcription and sc.input_transcription.text:
                    self.user_text.append(sc.input_transcription.text)
                    self._turn.request = "".join(self.user_text)
                    if self._stop_timer:
                        self._stop_timer.cancel()
                    if self.end_on_stop_phrase and is_stop_phrase("".join(self.user_text)):
                        self._stop_timer = asyncio.create_task(self._end_if_stop_phrase())
                    await self.send_json({"type": "transcript", "role": "user", "text": sc.input_transcription.text})
                if sc.output_transcription and sc.output_transcription.text:
                    self.assistant_text.append(sc.output_transcription.text)
                    if self._held or time.monotonic() < self._hold_until:
                        self._held_words += len(sc.output_transcription.text.split())
                        if self._held_words > 4:
                            await self._release_held()
                    await self.send_json(
                        {"type": "transcript", "role": "assistant", "text": sc.output_transcription.text}
                    )
                if sc.model_turn:
                    for part in sc.model_turn.parts or []:
                        if part.inline_data and part.inline_data.data:
                            await self._send_voice(part.inline_data.data)
                if sc.interrupted:
                    log.info("Voice (%s): interrupted", self.channel)
                    await self.send_json({"type": "interrupted"})
                if sc.turn_complete:
                    log.info("Voice (%s): turn complete", self.channel)
                    if self._held:
                        log.info("Voice (%s): dropped a short reply after a silent action", self.channel)
                        self._held = []
                    await self.send_json({"type": "turn_complete"})
                if sc.turn_complete or sc.interrupted:
                    await self.flush_transcript()
        return "hangup"

    async def run(self, system: str) -> None:
        """Talk until stopped (hang up, time limit or connection failure)."""
        s = get_settings()
        if costs.over_limit():
            await self.send_json({"type": "ended", "reason": "Today's spending limit is reached"})
            self.active = False
            return
        reconnects = 0
        self._runner = asyncio.current_task()
        self._in_run = True
        limit = asyncio.create_task(self._time_limit((self.max_minutes or s.max_call_minutes) * 60))
        try:
            while self.active:
                try:
                    async with client().aio.live.connect(
                        model=s.gemini_live_model,
                        config=live_config(
                            system,
                            self.handle,
                            self.quiet_actions,
                            self.allowed_tools,
                            [declaration for declaration, _ in self.extra_tools.values()],
                        ),
                    ) as session:
                        self.session = session
                        if not self._connected_once:
                            self._connected_once = True
                            pending, self._pending_audio = b"".join(self._pending_audio), []
                            if pending:
                                log.info(
                                    "Voice (%s): sending %.1fs said while connecting",
                                    self.channel,
                                    len(pending) / 32000,
                                )
                                for i in range(0, len(pending), 3200):  # 100 ms pieces, like live audio
                                    await session.send_realtime_input(
                                        audio=types.Blob(data=pending[i : i + 3200], mime_type=INPUT_MIME)
                                    )
                        if reconnects == 0:
                            await self.send_json({"type": "ready"})
                            if self.greeting:
                                await session.send_client_content(
                                    turns=types.Content(role="user", parts=[types.Part(text=self.greeting)])
                                )
                        reason = await self.pump(session)
                    self.session = None
                    if reason != "go_away":
                        break
                    log.info("Live session rotating (GoAway), resuming")
                except Exception:
                    self.session = None
                    if not self.active or not self.handle or reconnects >= MAX_RECONNECTS:
                        raise
                    log.warning("Live connection dropped, resuming", exc_info=True)
                reconnects += 1
        except asyncio.CancelledError:
            if self.active:
                raise  # cancelled from outside, not a normal hang-up
            self._runner.uncancel()  # our own hang-up: the caller carries on normally
        finally:
            self._in_run = False
            self.active = False
            limit.cancel()
            await self.flush_transcript()
            log.info("Voice session (%s) ended after %ds", self.channel, int(time.monotonic() - self.started))

    async def _time_limit(self, seconds: int) -> None:
        await asyncio.sleep(seconds)
        if self.active:
            await self.send_json({"type": "ended", "reason": "Call time limit reached"})
            self.stop()

    def stop(self) -> None:
        """Hang up now. Gemini may be silent, so don't wait for its next message: cancel the receive loop."""
        self.active = False
        # Only while run() is still talking to Gemini: afterwards the same task does other work (summaries,
        # hanging up the phone) that must not be cancelled.
        if self._in_run and self._runner and not self._runner.done() and self._runner is not asyncio.current_task():
            self._runner.cancel()


# ---------- Telegram Mini App ----------


async def authenticate(ws: WebSocket) -> None:
    """First message must prove the caller is the owner."""
    raw = await asyncio.wait_for(ws.receive_text(), AUTH_TIMEOUT)
    msg = json.loads(raw)
    if msg.get("type") != "auth":
        raise AuthError("Expected auth")
    if msg.get("init_data"):
        verify_init_data(msg["init_data"])
    elif msg.get("token"):
        verify_call_link_token(msg["token"])
    else:
        raise AuthError("No credentials")


async def run_call(ws: WebSocket) -> None:
    await ws.accept()
    try:
        await authenticate(ws)
    except (AuthError, TimeoutError, ValueError, WebSocketDisconnect) as exc:
        log.warning("Call refused: %r", exc)
        await ws.close(code=4401, reason="Unauthorized")
        return

    voice = VoiceSession(lambda d: ws.send_text(json.dumps(d)), ws.send_bytes, channel="call")

    async def upstream() -> None:
        try:
            while voice.active:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:
                    await voice.feed_audio(msg["bytes"])
                elif msg.get("text") and json.loads(msg["text"]).get("type") == "hangup":
                    break
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            voice.stop()

    log.info("Call started")
    up = asyncio.create_task(upstream())
    try:
        await voice.run(await voice_system_prompt())
    except Exception as exc:
        log.error("Call failed: %r", exc)
        await voice.send_json({"type": "ended", "reason": "Connection problem. Please call again."})
    finally:
        up.cancel()
        try:
            await ws.close()
        except Exception:
            pass
