# Personal AI Assistant: Project Plan

**Stack:** Railway (hosting) · Supabase (memory) · Gemini (every model) · Telegram · Swift (Jarvis on Mac)
**Built with:** Claude Code. One stage = one session = one chapter of the tutorial.
**Language:** the whole product (bot messages, voice, UI) is in English.

## Architecture

```
                 ┌──────────── RAILWAY (24/7) ──────────────┐
Telegram ───────►│ Bot (aiogram) + server (FastAPI)          │
 text, voice,    │        │                                  │
 Call button ───►│  Gemini Flash ── text and tasks           │
 (Mini App)      │  Gemini Live  ── real-time voice          │
                 │        │                                  │
Jarvis (Mac) ◄──WebSocket─►  Tools: Gmail, Calendar, Notion,  │
 hotkey, wake    │        │  Sheets, Forms, YouTube, search,  │
 word, screen,   │        │  GitHub, files, Spotify           │
 mouse           │        ▼                                  │
Phone ──────────►│  Scheduler: morning brief, reminders      │
 (Twilio)        └────────┬──────────────────────────────────┘
                          ▼
                 SUPABASE: history, memory, lessons, skills
```

Which model does what:

| Gemini model | Used for |
|---|---|
| Flash (text) | Telegram messages, tasks, research, morning brief |
| Live (real-time voice) | Telegram Call, Jarvis, phone calls |
| Flash with screenshots | seeing the Mac screen and clicking/typing in Jarvis (the Computer Use preview model was unavailable, stage 11) |
| Embeddings | memory search |
| TTS | not used: voice notes are answered in text (owner's choice, stage 6); spoken voice is Gemini Live |

Before you start, check the current model names in Google AI Studio (Live models are updated often).

**External services with no API key needed:** weather from Open-Meteo, currency rates from Frankfurter (ECB data), news via Gemini + Google Search. Fewer sign-ups.

**Rough monthly cost:** Railway Hobby $5–15, Supabase free to start, Gemini pay-as-you-go, Twilio number + minutes (stage 12 only).

---

## Stage 0. Setup ("What you'll need")

- [x] Google AI Studio → Gemini API key. **Enable billing (paid tier):** on the free tier Google may use your prompts to improve its models, and your emails and calendar will go through this assistant
- [x] Telegram → @BotFather → `/newbot` → bot token; get your own Telegram user ID (@userinfobot)
- [x] Supabase → new project
- [x] Railway → account, Hobby plan
- [x] GitHub → new private repository, add `CLAUDE.md` and `PLAN.md` to it
- [x] Try Gemini Live voices in AI Studio and pick the assistant's voice

Google Cloud (OAuth) and Notion come later, in stage 4, to keep the first chapter short.

**Result:** every key you need to start is in one place.

## Stage 1. The bot lives in the cloud

- [x] Bot skeleton in Python (aiogram 3) + FastAPI, using a webhook (not polling: polling conflicts during redeploys)
- [x] Whitelist: the bot only answers your user ID
- [x] Deploy to Railway from GitHub, keys in Variables, exactly 1 replica
- [x] `/health` endpoint to check the server is alive
- [ ] Test: message the bot and it replies; turn your computer off and it still replies

**Result:** the bot runs 24/7 without your computer.

## Stage 2. The Gemini brain

- [x] Connect Gemini Flash with function calling
- [x] System prompt: assistant persona, English, rules
- [x] Streaming replies (the message updates as it's generated)

**Result:** you can have a real conversation with the bot.

## Stage 3. Memory

- [x] Supabase tables: `messages`, `memories`, `lessons`, `skills`, `reminders`, `agent_runs`
- [x] pgvector + Gemini embeddings for semantic search
- [x] Tools: `search_history`, `save_memory`, `recall`
- [x] Daily job that compresses old conversations into summaries

**Result:** "What did we discuss about X last week?" works.

## Stage 4. Email, calendar, Notion, spreadsheets

- [x] Google Cloud: create a project, enable Gmail, Calendar, Sheets, Forms, Drive, YouTube Data and YouTube Analytics APIs; create an OAuth client
- [x] **Set the OAuth consent screen to "In production"** (no Google review needed for personal use, you'll just see a warning when signing in). In "Testing" mode the refresh token expires after 7 days and the assistant silently loses access to your email
- [x] Sign in with the Google account that owns your YouTube channel (if the channel is on a brand account, pick it at sign-in)
- [x] Store the refresh token on the server
- [x] Notion: create an integration token, share the pages you want with the integration
- [x] Gmail: search, read, draft, send
- [x] Calendar: list, create, update events
- [x] Sheets, Forms, Drive
- [x] Notion: search, create pages, add database entries

**Result:** "Add an idea to Notion" and "What's on my calendar tomorrow?" work.

## Stage 5. Morning brief and reminders

- [x] All scheduled items live in Supabase, not in process memory: the scheduler checks the `reminders` table every minute, so nothing is lost on redeploy
- [x] Current city and time zone: a `/city` command or sharing your location in Telegram (handy if you travel)
- [x] Morning brief every day: today's calendar, markets, hourly weather (format below)
- [x] `/news` command: AI & tech news on demand (Gemini + Google Search), linked from the end of the brief
- [x] Reminders: "Remind me at 6 pm to…" → row in `reminders` → message at the right time
- [x] Recurring reminders

### How the morning brief works

- **When:** every day at 08:00 in the owner's current time zone (`BRIEF_TIME` for the first run; change by chat: "move my brief to 7:30", or turn it off). Stored as one recurring row in `reminders` (`kind = 'brief'`), sent by the minute loop. `/brief` sends it on demand.
- **Built from a fixed template**, not written by the AI: same layout every day, ready in under a second, no "please wait" message.
- **Sources (no API keys):**
  - Tasks: today's Google Calendar events only (start = end = today)
  - Markets: BTC and ETH from CoinGecko (24h change), S&P 500 from the Yahoo Finance chart API (vs previous close), USD/EUR from Frankfurter / ECB (vs previous day). Configurable: `BRIEF_CRYPTO`, `BRIEF_INDEXES`, `BRIEF_CURRENCIES` (the ECB has no UAH)
  - Weather: Open-Meteo hourly forecast for the owner's current city, 08:00–22:00, with day/night emoji
- If one source fails, its section says "unavailable" and the rest still goes out.
- **Layout** (plain text so `/news` is tappable):

```
🗓 Tasks for today, October 24 (Saturday):
• 17:00 — call

💰 Markets
BTC: $80,458 (-$1,050, -1.3%)
ETH: $2,357 (-$36, -1.5%)
S&P 500: 7,624 (-40, -0.5%)
USD/EUR 0.8934 (+0.0010, +0.1%)

🌤 Weather in Oeiras, Portugal
08:00   10°  🌤
09:00   12°  ☀️
…
22:00   13°  ☁️

📰 Tap /news for today's AI & tech news
```

- **`/news`:** 6–8 of the day's top AI & tech stories found with Gemini + Google Search. Format: `📰 AI & Tech News — October 24`, then `- **Headline** — one sentence on why it matters`, a blank line between items, no source names (enforced in code). While it loads, only Telegram's "typing…" shows, no extra message. Also available in chat as the `get_news` tool for any topic.

**Result:** a brief arrives every morning and reminders fire on time.

## Stage 6. Voice messages

- [x] Incoming voice note → Gemini understands the audio directly: the recording itself goes to the agent together with a transcript (the transcript is what's stored in memory)
- [x] ~~Voice reply via Gemini TTS~~ Changed by the owner: replies to voice notes are always **text** (streamed like any message). Spoken conversation happens in calls (stage 10), not in Telegram messages

**Result:** you can talk to the assistant with voice notes.

## Stage 7. Skills and self-learning

- [x] Skills: task instructions stored in Supabase; the model sees the list and loads the one it needs
- [x] `create_skill` tool: the assistant writes and saves new skills itself
- [x] `save_lesson` tool: when you correct the assistant, the lesson is saved and added to the prompt
- [x] ~~Weekly list of lessons for you to review~~ Changed by the owner: no automatic weekly message. Lessons and skills are saved as usual; `/lessons` shows them on demand with a 🗑 button per lesson, `/skills` lists the skills

**Result:** the assistant remembers its mistakes and improves.

## Stage 8. Research, YouTube, files, GitHub, photos

- [x] Research via Gemini + Google Search grounding; long research runs in the background and comes back as a document
- [x] YouTube Data + Analytics: views, retention, comparison with your channel average, comment summary
- [x] Video transcription (Gemini accepts a public YouTube link directly; for private/unlisted videos use the channel's captions)
- [x] Create documents (docx/pdf), send them in Telegram, copy to Drive
- [x] GitHub: repos, commits, issues
- [x] Daily database backup to Google Drive (not to GitHub: it will contain personal data from your email)
- [x] Send photos and images in Telegram
- [x] YouTube search across all of YouTube (`youtube_search`): channels with subscriber counts and the links from their descriptions (e.g. Skool communities), or videos with views

**Result:** "How did my last video do?", "Transcribe this video", "Research X" work.

## Stage 9. AI agents overview

- [x] Your other agents write their status to `agent_runs`
- [x] "How are my agents doing?" → summary
- [x] Automatic alert when an agent fails

**Result:** full context on your projects in one place.

## Stage 10. Call button in Telegram

- [x] **Test first:** a simple page with microphone access inside Telegram on iPhone and Mac (Mini App microphone support depends on the Telegram version). If it doesn't work, the button opens the same page in the external browser
- [x] Telegram Mini App with a Call button, added to the bot's menu
- [x] Verify the Telegram `initData` signature on the server: only you can call, otherwise the page is an open door to your email and calendar
- [x] WebSocket: Mini App ↔ Railway server ↔ Gemini Live (the Gemini key stays on the server)
- [x] All tools are available by voice too (Notion, calendar, reminders)
- [x] Interruptions: start talking and the assistant stops (built into Gemini Live)
- [x] Session resumption and context compression in Gemini Live so long calls don't drop at the session limit
- [x] Call transcript is saved to history
- [x] Call screen shows the whole conversation as live captions: scrollable, nothing cut off, follows new text only when you're at the bottom (owner feedback)
- [x] Research by voice: on a call the assistant searches the web and YouTube instead of saying "I can't browse" (owner feedback; clicking around real web pages comes with Jarvis in stage 11)

**Result:** you can call your assistant from Telegram when you're away from your computer.

## Stage 11. Lucy on the Mac (Jarvis app)

A menu bar app called Jarvis. Say "Lucy" (or press ⇧E), speak in any language, and Lucy answers in English with the
same memory and tools as in Telegram, plus eyes and hands on the Mac. Actions happen silently; she speaks only to
answer a question. The wake word and microphone handling follow the owner's earlier, working assistant (Katya).

- [x] Swift menu bar app, English UI (Swift Package in `/jarvis`, built without Xcode), starts at login
- [x] One WebSocket to the server (`/ws/jarvis`, `JARVIS_TOKEN`): same memory and tools; the Gemini key stays on the server
- [x] Wake word "Lucy" / "Люси" on the Mac, free and offline (Apple SpeechAnalyzer; works without macOS Dictation)
- [x] Hotkey ⇧E: start talking without the wake word; cuts Lucy off while she speaks; otherwise ends the conversation
- [x] Same Gemini Live model and voice as the Telegram Call (`gemini-3.8-live`, Achernar); understands the owner's language, answers in English
- [x] Interrupt Lucy by voice: just start talking while she speaks (tested by the owner)
- [x] Actions run silently ("open Spotify", "volume 30", "add a reminder"); Lucy speaks only to answer or to say an action failed
- [x] "Stop", "okay, that's all", "окей, всё" end the conversation silently
- [x] Screen: `look_at_screen` answers about what's on the screen
- [x] Control: `mac_open`, `mac_quit_app`, `mac_volume`, `mac_media`, `mac_system`, and `mac_do` for multi-step clicking and typing
- [x] Spotify: "play Miyagi I Got Love" finds and plays it (tested by the owner)
- [x] macOS permissions: Microphone, Speech Recognition, Screen Recording, Accessibility (menu → Permissions…)
- [x] Mac tools also work from Telegram chat and calls while Jarvis is online; when it's offline Lucy says so

**Result:** "Lucy, what's this error? Fix it." She sees the screen and fixes it.

### How it fits together

```
Mac (Jarvis.app)                                    Railway server                      Google
mic ─► Audio hub ─► wake word "Lucy" (on-device)
          │ (after "Lucy" or ⇧E)
          └─ 16 kHz PCM ──── /ws/jarvis ──────────► VoiceSession ◄─────────────────► Gemini Live
speaker ◄─ Lucy's voice (24 kHz) ◄────────────────── (same engine as the          (gemini-3.8-live)
Device.swift ◄─ {"type":"device", ...} ◄─────────── Telegram call) + tool registry
   screenshot, click, type, open, volume, Spotify ─► {"type":"device_result"} ─► mac_* tools ─► Gemini Flash (mac_do)
```

Protocol on `/ws/jarvis`: the first message is `{"type":"auth","token":JARVIS_TOKEN}` (wrong token → closed with
4401). Then `call_start` (with the app in front and the list of installed apps), binary microphone audio,
`call_end`, `ping`; the server sends `hello`, transcripts, `turn_complete`, `interrupted`, `ended`/`call_ended`,
binary audio of Lucy's voice, and `device` requests that Jarvis answers with `device_result`.

### How to build it (step by step)

**1. Server: the voice engine** (`app/live/call.py`)
- One engine, `VoiceSession`, for the Telegram call and the Mac. It doesn't read any socket: the client feeds
  microphone audio in (`feed_audio`) and gets JSON events and Lucy's audio back through two callbacks.
- Gemini Live settings (`live_config`):
  - language hints for the owner's speech (`VOICE_LANGUAGE_CODES`, default `en-US,ru-RU,uk-UA`) and
    `adaptation_phrases` (Lucy, Notion, Telegram, Gmail, Spotify). Without hints, Russian speech was once transcribed
    as Chinese and the reply had nothing to do with the question;
  - the owner's phrase ends after 0.7 s of silence (`VOICE_SILENCE_MS`);
  - sliding-window context compression and session resumption, so long conversations don't drop;
  - all registry tools plus `end_conversation`.
- Audio said while Gemini Live is still connecting (up to 10 s) is kept and sent once it's ready, in 100 ms pieces,
  so the first words after the wake word aren't lost.
- Tool calls run in the background, so a long one doesn't freeze the conversation. An identical call is not run
  twice within 3 s (30 s for things that open apps, links or music); the first result is reused.
- **Silent actions** (`quiet_actions=True`, used for the Mac): the tools that *do* something (`ACTION_TOOLS`: Mac
  actions, Spotify, reminders, calendar changes, Notion pages and entries, memory, lessons, skills, sheets, email,
  GitHub issues, documents, images, research) are declared `NON_BLOCKING`, and a successful result is sent back with
  `scheduling = SILENT`: it lands in Lucy's context without making her talk. A failed result (`error`, `ok: false`,
  `done: false`) is sent with `WHEN_IDLE`, so she says what went wrong. "What's playing?" (`spotify now_playing`) is a
  question and is answered normally. Tested with gemini-3.8-live: with ordinary (blocking) calls she stayed quiet but
  called "open Spotify" 8 times; non-blocking + silent gave one call and silence.
- Backup for silence (from Katya): right after an action, Lucy's voice is held for up to 8 s. More than 4 words means
  a real answer and it plays; a short "Done" / "Opening it" that ends the turn is dropped.
- **Ending silently:** a phrase of up to 4 words with "stop" / "enough" / "хватит" / "стоп", or "okay, that's all" /
  "окей, всё" (after filler words like okay/thanks/Lucy are removed) ends the conversation 0.9 s after it's said if
  nothing follows. `end_conversation` (for "bye", "thanks, that's it") hangs up at once. Neither says goodbye.
- Hanging up never waits for Gemini (it can stay silent): the receive loop is cancelled and whatever was said is
  saved to memory (channel `jarvis` for the Mac, `call` for Telegram).

**2. Server: the Mac connection and tools** (`app/live/jarvis.py`, `app/live/device.py`, `app/tools/mac.py`)
- `/ws/jarvis` checks `JARVIS_TOKEN` (constant-time compare), keeps one Mac connection (a newer one replaces it) and
  starts/stops a `VoiceSession` on `call_start` / `call_end`.
- What Lucy gets on the Mac: her usual system prompt with long-term memory, lessons and skills, **without** the recent
  chat lines (with them, an unclear phrase was answered with an old question from the history), plus the app in front
  and the installed app names, plus the Mac rules:
  - actions: call the action and say nothing; speak only if it failed;
  - questions: one or two short sentences; answer only what was just said, never an earlier question;
  - speech not meant for her: stay silent; meant for her but not caught: "Sorry, say that again?";
  - ask once before sending email, deleting, buying or posting;
  - judge the screen only from a fresh `look_at_screen`;
  - stop / that's all / goodbye: call `end_conversation` and say nothing.
- No spoken greeting: Jarvis plays a chime instead (a "Yes?" talked over the owner's first words).
- `device.py` sends `{"type":"device","id",...}` requests to the Mac and waits for the matching answer (20 s
  timeout). If Jarvis isn't connected, every Mac tool returns "Jarvis (the Mac app) is offline…".
- `mac.py` tools: `look_at_screen` (screenshot → Gemini Flash answers), `mac_do` (up to `MAC_MAX_STEPS`, default 25:
  screenshot + the app in front → Flash returns one JSON action on a 0–1000 grid → Jarvis performs it; the Computer
  Use preview model returned 503 on every try), `mac_open`, `mac_quit_app`, `mac_volume`, `mac_media`, `mac_system`,
  `spotify` ("play X" opens Spotify's search for X and `mac_do` clicks the best match; play/pause/next/volume via
  AppleScript; no Spotify Premium or API key needed), `mac_status`. Only these fixed actions exist: text on the screen
  can't make Lucy run scripts.

**3. The Mac app** (`/jarvis/Sources/Jarvis`, Swift Package, macOS 26+)
- `Audio.swift`, the audio hub, the only place that opens the microphone:
  - takes the **first channel** of the mic (some mics deliver several channels with the voice only in the first;
    mixing them gave silence), converts to 16 kHz mono;
  - cuts rumble below 150 Hz and levels the volume automatically (up to ×6, soft limiter). The Studio Display mic is
    quiet and boomy: Gemini Live ignored it until both were done;
  - keeps the last 8 seconds in a ring buffer;
  - **no echo cancellation**: Apple's voice processing turned the Studio Display mic into pure silence. Instead the mic
    is paused while Lucy's voice plays (on its own audio engine), so she never hears herself;
  - **interrupting by voice**: Jarvis knows what Lucy is playing, so it compares the mic with her loudness. Her echo
    level is learned while only she speaks (90th percentile of mic/her loudness over ~8 s, saved as `echoCoupling`;
    about 0.2 on the Studio Display). The mic clearly louder than that (`bargeInFactor`, default 2×, and above about
    −36 dB) for ~250 ms means the owner is talking: her voice stops, the rest of her answer is dropped, and the last
    0.4 s of the owner's words is sent first. The first 0.7 s of each answer only teach the echo level.
- `WakeWord.swift`: Apple's on-device **SpeechAnalyzer** with a speech detector and partial results. Two independent
  analyzers: English (`SpeechTranscriber`) and far-field Russian dictation (`DictationTranscriber`), because "Люси"
  and "Lucy" sound different and the English model never writes the Cyrillic name (in one analyzer the second model
  never produced results). Matches Lucy/Lucie/Luci/Люси/Люся and similar spellings. The models download from Apple
  once. Listens only between conversations.
- `AppDelegate.swift`: the menu bar icon and menu (status, last caption, Talk to Lucy / End conversation, Listen for
  "Lucy", Permissions…, Quit), login item, and the conversation:
  - "Lucy" → chime, `call_start` with the app in front and the installed apps, then the last 2.5 s of audio, then the
    live microphone. So "Lucy … (chime) … what's the weather" and "Lucy, what's the weather" in one breath both work;
  - ⇧E: start; while Lucy speaks, cut her off; otherwise end;
  - ends after 15 s with nobody talking and no action running (`idleSeconds`), or when the server says `ended`; then a
    "pop" sound and it listens for the name again. An error sound means the server isn't connected.
- `Connection.swift`: the WebSocket, with the token in the first message, a ping every 20 s and reconnect after 3 s.
- `Device.swift`: screenshot of the main display (ScreenCaptureKit, max 1440 px, JPEG), click/type/keys/scroll
  (CGEvent), open apps/links/files (for apps it waits up to 5 s and reports whether they really started), quit apps,
  volume (AppleScript), media (Spotify/Music via AppleScript, otherwise the media keys), lock screen, display off,
  screen saver, Spotify commands.
- `Hotkey.swift`: ⇧E via Carbon `RegisterEventHotKey` (no permission needed). While Jarvis runs, Shift + E belongs to
  it, so type a capital E with Caps Lock.
- `Config.swift`: reads `~/Library/Application Support/Jarvis/config.json` (`server`, `token`); nothing secret is
  built into the app.
- `Permissions.swift`: asks for Microphone, Speech Recognition, Screen Recording and Accessibility and shows what's
  missing.

**4. Build, sign and install** (`scripts/build_jarvis.sh`)
- Needs only the Command Line Tools (`xcode-select --install`), not Xcode.
- `JARVIS_SERVER=wss://<domain>/ws/jarvis JARVIS_TOKEN=<token> scripts/build_jarvis.sh` builds (in
  `~/Library/Caches/Jarvis-build`, outside iCloud and git), packages `Jarvis.app` with `jarvis/Info.plist`, signs it,
  writes `config.json` (mode 600), installs to `~/Applications/Jarvis.app` and starts it.
- Signing: the first run creates a self-made certificate "Jarvis Local Signing" in its own keychain file
  (`~/Library/Application Support/Jarvis/signing`, not the login keychain). The same certificate every time means
  macOS keeps the permissions across rebuilds (an ad-hoc signature changed with every build and macOS asked again).
  To give the app to someone else, sign with an Apple Developer ID and notarize instead.
- First launch: allow Microphone and Speech Recognition; turn on Jarvis in Privacy & Security → Screen Recording and
  Accessibility (on macOS 27 both are under "Device Control and Data Access"); reopen Jarvis. The speech models
  download in the background (about 15 s).

**5. Settings and troubleshooting**
- Server env: `JARVIS_TOKEN`, optional `VOICE_LANGUAGE_CODES`, `VOICE_SILENCE_MS`, `MAC_MAX_STEPS`.
- Mac settings (`defaults write com.andrewrayne.jarvis <key> <value>`): `idleSeconds` (5–60, default 15),
  `bargeInFactor` (lower = easier to interrupt, default 2), `voiceBargeIn -bool NO` (turn voice interrupting off).
- Logs: `log stream --predicate 'subsystem == "com.andrewrayne.jarvis"'` (microphone, wake word, hotkey, conversations,
  interrupts). Off by default, for troubleshooting only: `debugWakeWord -bool YES` logs what the recognisers hear,
  `debugBargeIn -bool YES` logs mic vs Lucy loudness. Server logs show the conversation events ("owner is speaking",
  tool calls, "turn complete") without the words.

**6. Test**
- "Lucy" → chime → "what's the weather?"; "Люси, какая погода?"; "Lucy, open Notion" in one breath (opens silently);
  ⇧E and talk; talk over Lucy during a long answer; "what's on my screen?"; "play Daft Punk on Spotify";
  "turn the volume down"; "okay, that's all" (hangs up silently); quit Jarvis and ask in Telegram "open Safari on my
  Mac" (Lucy says the Mac is offline).

### What didn't work (and why the final version is different)
- `SFSpeechRecognizer` for the wake word: refuses to run when macOS Dictation is off ("Siri and Dictation are
  disabled"); it also restarted in a loop when cancelled recognitions reported errors.
- Apple's echo cancellation (voice processing): with the Studio Display it first failed to start (format error), then
  passed only digital silence, so Lucy never heard the owner.
- Raw Studio Display audio: Gemini Live's speech detection ignored it; a fixed ×4 boost helped in tests but the
  automatic level is safer for a real voice.
- Recent chat lines in the Mac prompt: when Lucy didn't understand, she answered an old question from the history.
- A spoken "Yes?" after the wake word: talked over the owner's first words, and the mic is paused while she speaks.
- Hotkeys ⌃⌥J and ` + Tab: replaced by ⇧E at the owner's request.
- Ordinary (blocking) tool calls for actions: Lucy narrated them ("Opening Spotify") or repeated the call many times.

## Stage 12. Phone calls

Lucy gets a phone number. She calls businesses and people for you ("book a table for two on Friday at 8"), calls you
("call me"), and answers when you call her number. Calls are recorded; after a call you get a summary, the recording
and, if something was booked, a calendar event. Works in any country Twilio serves; pick your region below.

- [x] A Twilio number for Lucy (see "Choose your region"): a US local number, bought through the API
- [x] Twilio Media Streams ↔ server ↔ Gemini Live (8 kHz μ-law ↔ 16/24 kHz PCM, converted on the server)
- [x] `phone_call`: call someone and do one task → summary, recording and calendar event in Telegram (real calls to
  Poland and Ukraine placed from Telegram; summary and calendar logic covered by tests)
- [x] `call_me`: Lucy calls the owner's own phone; full Lucy with memory and tools (tested: answered from memory, hung up on "that's all", recording arrived in Telegram and was deleted from Twilio)
- [ ] The owner calls Lucy's number and talks to her (optional keypad PIN, because caller ID can be faked) — built,
  not yet tried on a real call
- [ ] Anyone else who calls her number gets guest mode: Lucy knows only the owner's first name, has no tools and no
  data, and only takes a message, which arrives in Telegram with the recording (3 minutes max) — built and tested
  in code, not yet tried on a real call
- [x] Calls to other people get no access to the owner's data (no memory, calendar, Notion, email…)
- [x] Portuguese: for +351 numbers she speaks European Portuguese by herself (tested: barbershop booking); without
  a language she speaks the local language of the number
- [x] Lucy says she's an AI assistant and that the call is recorded (tested with the live model in Ukrainian and
  Portuguese); stops recording if the other person objects (built, not tried on a call)
- [x] Languages by voice: English by default; on request she speaks Russian or Ukrainian natively (female forms,
  "Люси" / "Люсі"); calls to others in the language you name (tested with the live model)
- [x] Voicemail or no answer: the owner gets "didn't pick up" or the network's reason (busy, unavailable…) instead of
  a recording (seen on real calls)
- [x] Calls to Ukraine allowed too (about $0.31–0.41/min), but Ukrainian networks reject calls from the US number;
  `ALT_CALLER_ID` (the owner's verified mobile for `+380`) is ready but not switched on
- [x] Calls to Poland allowed in Geo permissions (ordinary numbers only; premium and high-risk stay blocked); `call_me` takes a language too

**Result:** "Book a table for two on Friday at 8 pm" — she calls, books, and it's in your calendar.

### Choose your region (before buying a number)

Twilio sells numbers in many countries, but the rules differ. Check Twilio's "Phone Number Regulations" page for your
country, and pick one of these:

| Region | Lucy's number | What to know |
|---|---|---|
| US / Canada | Local US or Canadian number, bought instantly, no documents (about $1–2/month) | AI voices count as "artificial voice" under the US TCPA: only call businesses and people who expect it. Some US states require everyone's consent to record (e.g. California); Lucy announces the recording on every call |
| Europe (EU, UK) | A local number needs a regulatory bundle (ID and proof of address); approval takes days. A US number works right away and can call European numbers, but shows a foreign caller ID | The EU AI Act requires saying you're an AI (Lucy always does). GDPR and national laws (e.g. Portugal) require telling people a call is recorded and respecting a "no"; Lucy announces it and stops the recording on request |
| India | Twilio's Indian numbers are tightly regulated (TRAI); many builders use a number from another country or a local provider. Check before buying | Announce AI and recording as above; use the local language codes |
| Other countries | Check Twilio's regulations page for the country; a US number is the quickest way to start | Same rules of thumb: say it's an AI, announce recording, call only people who expect it |

Wherever you are:
- **Geo permissions:** Twilio Console → Voice → Settings → Geo permissions: allow the countries Lucy will call
  (e.g. Portugal), otherwise calls are blocked.
- **Trial accounts** can only call verified numbers and play a Twilio message first. Upgrade (add a balance) for real
  calls.
- **Languages:** add the local language to `VOICE_LANGUAGE_CODES` (e.g. `pt-PT`, `es-ES`, `hi-IN`) and set
  `OWNER_TIMEZONE`. Lucy starts a call in the language you ask for and switches to the other person's language.

### Setup
1. Create a Twilio account and choose **Full access** (pay as you go; the limited trial only calls up to 5 verified
   numbers in your own country). Add a balance (about $20).
2. **Identity check (KYC):** Twilio won't sell any number, even a US one, until your Primary Customer Profile is
   approved: Console → Trust Hub → Profiles → create a Primary profile (Individual if you have no company) → submit.
   Ours was approved within minutes.
3. Buy a number with Voice capability (see the table above). Ours: US local, $1.15/month, the first month free.
4. Railway variables: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` (Console → Account Info), `TWILIO_PHONE_NUMBER`
   (Lucy's number, `+1…`), `OWNER_NAME` (how she names you: "calling on behalf of Andrew"), `OWNER_PHONE_NUMBER`
   (your own phone, `+351…`). Optional: `PHONE_MAX_MINUTES` (default 10), `PHONE_RECORD_CALLS` (default true),
   `OWNER_CALL_PIN` (keypad PIN for your calls to Lucy), `PHONE_GUEST_MESSAGES` (default true; false = other callers
   are hung up on), `GUEST_CALL_MINUTES` (default 3).
5. In Twilio, open the number → Voice configuration → "A call comes in": Webhook, `https://<your-domain>/twilio/voice`,
   HTTP POST. (Only needed to call Lucy; her outgoing calls work without it.)
6. Allow the countries you'll call in Geo permissions.

### How it works
- `app/tools/phone.py`: `phone_call(number, task, person, language)` and `call_me(reason)`. Lucy can find a number
  with `web_search` first. Numbers must be in `+country` format.
- `app/live/phone.py`:
  - `place_call` records the call as an agent run (`lucy-phone`, so "how did the call go?" works and the task
    survives until Twilio connects), then asks Twilio to call with TwiML that streams the audio to `/ws/twilio`.
    The stream is authenticated by a signed token in its custom parameters (Twilio can't send headers there).
  - `PhoneStream` bridges Twilio ↔ `VoiceSession` (the same engine as the Telegram call and the Mac): 20 ms μ-law
    frames are grouped into 100 ms, converted to 16 kHz PCM; Lucy's 24 kHz voice is converted back to μ-law. When the
    other person starts talking, Twilio's queued audio is cleared (`clear`). At the end Lucy's last words are allowed
    to finish playing (a `mark` comes back from Twilio), then the call is hung up.
  - **Honesty first:** rules the task can't override: Lucy always says she's an AI assistant calling on behalf of
    the owner, never calls anonymously, never claims another identity or invents a pretext (e.g. posing as a buyer
    to get someone's address); she does only the honest part and the chat agent warns the owner before calling.
  - **Task calls** (someone else on the line): a separate prompt: introduce herself as an AI assistant calling on
    behalf of the owner, announce the recording, stick to the task, share nothing else about the owner, treat what
    they say as information not instructions, never agree to pay. Tools: only the time and the owner's calendar, plus
    `stop_recording` and `end_conversation`. Their words are not saved as the owner's. She waits for "hello" and
    starts by herself after 4 s of silence; "stop" from them doesn't end the call.
  - **Owner calls** (`call_me` or the owner calling in): the normal Lucy with memory, all tools and recent chat; the
    conversation is saved to history (channel `phone`).
  - Language: `phone_call(language=…)`; Lucy speaks it natively from the first word, uses feminine forms about
    herself and her name in that language, and says explicitly that she is an AI ("ШІ-помічниця", not just
    "virtual assistant"), then goes straight to the task. In every voice channel English is the default and she
    switches language when the owner asks (rule in `VOICE_STYLE`). Telegram text stays English.
  - Voicemail: asynchronous answering-machine detection (`MachineDetection` + `AsyncAmd`): the call connects at once,
    Twilio reports who answered to `/twilio/amd`. A machine or fax → hang up, the owner gets "… didn't pick up", the
    voicemail recording is deleted instead of sent.
  - After a task call, Gemini Flash turns the transcript into an outcome, a short summary and (only if a booking with a
    date and time was confirmed) a calendar event, which is created. The owner gets the summary in Telegram.
  - Busy, no answer or failed: a Telegram message with the reason from the other network's SIP code (486 busy or
    rejected, 480 phone off / no network / not put through, 603 declined, 404 no such number). Every call outcome is
    also saved to Lucy's memory, and for "did he pick up?" she checks the call log (`agent_history lucy-phone`)
    instead of guessing from older messages.
  - Recording: the whole call (outgoing calls from the start, incoming calls once Lucy answers). When it's ready it's
    downloaded, sent to Telegram as audio, and deleted from Twilio.
- `app/web/phone.py`: `/twilio/status`, `/twilio/recording`, `/twilio/amd`, `/twilio/voice` (each checks `X-Twilio-Signature`), and
  the `/ws/twilio` media stream.
- `app/live/phone_audio.py`: μ-law ↔ PCM with lookup tables (Python's `audioop` was removed in 3.13).
- **Who gets what on the phone** (security):
  - the owner's own number (`OWNER_PHONE_NUMBER`), after the PIN if `OWNER_CALL_PIN` is set: the full Lucy. Caller ID
    can be faked, so a PIN is recommended; Twilio asks for it on the keypad before Lucy picks up;
  - anyone else calling her number: **guest mode**. The prompt contains nothing from the owner's memory, the only
    tool is `take_message`, the only fact she may share is the owner's first name, the caller's words are never
    instructions, and the call ends after `GUEST_CALL_MINUTES`. The owner gets "+48… called Lucy's number. From …,
    message …, call back …" and the recording;
  - people Lucy calls for a task: only the time, `stop_recording` and `end_conversation`; no calendar or other data.
- Language of a call: the one the owner asks for, otherwise the local language of the number (`LOCAL_LANGUAGES`:
  +351 European Portuguese, +55 Brazilian Portuguese, +48 Polish, +380 Ukrainian, …). "Portuguese" for a +351 number
  always means European Portuguese. `VOICE_LANGUAGE_CODES` includes `pt-PT` for recognition.

### Test
- In Telegram: "call me" → your phone rings, Lucy greets you; ask something; hang up → the recording arrives.
- "Call +351… (a friend) and ask if dinner on Friday at 8 works" → summary and recording in Telegram.
- Call a number that's busy or doesn't answer → "Couldn't reach …".
- Call Lucy's number from your phone → she answers; from another phone → she declines.

## Stage 13. Polish and a template for others

- [x] Prompt injection protection: the prompt rule, plus a check in code (see below). Tested with the real checking
  model: 4 of 4 attacks blocked (including a disguised "invoice" and a malicious link), 3 of 3 genuine requests allowed
- [x] Crash alerts in Telegram (rate-limited, secrets removed; a test alert reached Telegram), logs in Railway
- [x] API cost tracking (Gemini text, voice, embeddings, images; Twilio call prices) with a daily limit and `/usage`
- [x] Railway template "Lucy AI Assistant" with a "Deploy on Railway" button (`railway.com/deploy/EkjrZZ`, from the
  public repository; 5 required variables with descriptions, 13 optional ones, JARVIS/AGENTS tokens generated)
- [x] README with setup instructions (quick start, optional parts, safety, development, how to make the template)
- [x] Personal data removed from the repository files (emails, phone numbers, domain, Notion page names); the old
  versions remain only in the private repository's history
- [x] Clean public copy: https://github.com/andrewrayne/lucy-ai-assistant (a fresh repository with no history)

### How it works

- **Prompt injection** (`app/security.py`): every owner request (a chat message, or one spoken phrase in a voice
  session) is a "turn". When a tool returns third-party content (`UNTRUSTED_TOOLS`: email, web search, Drive,
  Sheets, Forms, Notion, YouTube comments/transcripts, GitHub issues, the screen), the turn is tainted. After that,
  `GUARDED_TOOLS` (send email, phone call, delete event, GitHub issue/comment, create a form, Mac clicks and opening
  links) run only if a separate Gemini call agrees that the owner's own words ask for that action. The check sees
  only the owner's words and the proposed action, never the content, so injected text can't argue with it. If the
  check fails or errors, the action is blocked and Lucy asks the owner to confirm in their own words. This lives in
  the tool registry, so it covers chat, voice, Jarvis and phone at once.
- **Crash alerts** (`app/alerts.py`): a logging handler sends every ERROR to Telegram (the same error at most every
  30 min, at most 10 per hour, secret values replaced by •••); an asyncio exception handler logs crashed
  background tasks so they're alerted too. Logs: Railway → Deployments → Logs, or `railway logs`.
- **Public copy and template:** the private repository (`personal-assistant`) stays the working copy with its
  history. The public `lucy-ai-assistant` was created from the current files as a single commit (`git archive` →
  new repository), so nothing from the history (old emails, numbers) is public. Before that, every tracked file was
  scanned for personal data (emails, phone numbers, IDs, the Railway domain, friends' names, Notion page names).
  The Railway template comes from a separate project, `lucy-template`, with no secrets: one service from the public
  repository, healthcheck `/health`, restart on failure, one replica, a public domain on port 8080 (the Dockerfile
  defaults to 8080 when `PORT` is missing). `templateGenerate` (Railway API) needs the repository to be visible to
  Railway's GitHub app (GitHub → Settings → Applications → Railway → Repository access; GitHub asks to confirm access
  by email first). Variables, descriptions and defaults were pasted as JSON into the template editor's Raw Editor
  (`{"NAME": {"value": "...", "description": "..."}}`; `${{secret(48)}}` generates a secret); "optional" isn't read
  from the JSON, so each optional variable was ticked in the editor. Name and description are in Template Settings
  (description ≤ 75 characters). The template isn't listed in Railway's marketplace; the link works for everyone.
- **Costs** (`app/costs.py`, table `usage`): prices per 1M tokens from Google's pricing page (Flash 3.8 doubles on
  2027-01-01, built in). Text calls are priced from `usage_metadata`; Gemini Live reports usage per turn (including the
  context), split into text and audio; embeddings are estimated (about 4 characters per token); images per image;
  Twilio's real call price is fetched a minute after the call. Today's total is kept in memory (loaded at startup);
  at 80% of `DAILY_COST_LIMIT_USD` the owner gets a warning, at 100% the chat answers with the limit message and new
  voice sessions and calls are refused until midnight (owner's time zone). New tables need explicit grants for
  `service_role` (the project revokes default privileges).

**Result:** the project is ready to share.

---

## How to work with Claude Code

1. Put `PLAN.md` and `CLAUDE.md` in the project folder. Claude Code reads `CLAUDE.md` automatically.
2. A new session for each stage: "Read PLAN.md, do stage N."
3. Claude Code works autonomously: writes the code, runs every terminal command itself, deploys, and only stops for things only you can do (signing up, logging in, copying a key).
4. Test the result yourself.
5. Commit, tick the boxes in PLAN.md, next stage.
6. If something was replaced along the way (a service, a model, an approach), Claude Code adds it to the "Deviations from the plan" table below.

## Deviations from the plan

| Stage | Planned | Actually used | Why |
|---|---|---|---|
| 0 | New Supabase project in the main account | Separate Supabase account, org "Personal Assistant", project `personal-assistant` in eu-central-1 | Main account's free plan allows only 2 active projects and the owner didn't want to pause existing ones |
| 0 | Pick a voice | `Achernar` (Gemini's "Soft" female voice), stored as `GEMINI_VOICE` | Owner asked for a soft female voice |
| 1 | Railway settings in `railway.json` | Settings set in the Railway dashboard (1 replica, healthcheck `/health`, restart on failure); `railway.json` removed | Railway deprecated Config as Code: services created after 2026-08-28 can't opt in, so the file was ignored. Infrastructure as Code (`.railway/railway.ts`) is the new option if needed later |
| 2 | Gemini Flash | `gemini-3.8-flash` with automatic fallback to `gemini-3.6-flash`, `gemini-3.5-flash`, `gemini-3.5-flash-lite` (a model that fails is skipped for 5 min) | 3.8 Flash returned 503 "high demand" and stalled while the key was on the free tier; after enabling billing it answers in ~2 s. Fallback kept as insurance |
| 2 | Conversation context | Last 10 turns kept in process memory (replaced in stage 3 by the `messages` table; `/new` now writes a marker row) | Temporary until stage 3 |
| 2 | Streaming by editing a message | Telegram `sendMessageDraft` (native streaming preview), falls back to editing a message | Built for exactly this; smoother and no edit rate limits |
| 3 | Supabase CLI for migrations | `scripts/migrate.py` applies `supabase/migrations/*.sql` through the Supabase Management API | The Supabase CLI failed to install on the Mac (needs Xcode tools) and the plan avoids installing things locally; the API needs only an access token |
| 3 | Gemini embedding model | `gemini-embedding-2` at 768 dimensions (normalized), HNSW cosine indexes | Current GA embedding model; 768 dims keeps indexes small with near-identical retrieval quality |
| 3 | Conversation summaries | Stored in `memories` with `kind = 'summary'`, one per local day; raw messages stay searchable and get `summarized_at` | Keeps the six planned tables; summaries are searchable alongside facts |
| 4 | OAuth sign-in | "Desktop app" OAuth client + `scripts/google_auth.py` (local loopback redirect) gives one refresh token with all 8 scopes | No web callback needed on the server; one consent covers Gmail, Calendar, Drive, Sheets, Forms and YouTube |
| 4 | Consent screen "In production" | Needed a public home page and privacy policy: served by the bot itself at `/` and `/privacy`; authorized domain = the Railway domain | Google requires both URLs before publishing |
| 4 | Google account | The owner's main Google account (it owns the YouTube channel) | Chosen by the owner; switching = re-run `scripts/google_auth.py` with another account |
| 4 | Google API client library | Direct REST calls with `httpx` (`app/integrations/google.py`) | Async, no heavy SDK; each tool is a few readable lines |
| 4 | Notion API version | `2026-03-11` (databases are "data sources") | Current Notion API version; configurable via `NOTION_VERSION` |
| 4 | Notion pages to share | Integration "Lucy" (API token) with access to the owner's main workspace page and its databases; new pages default to that page, ideas go to the owner's ideas database (`NOTION_DEFAULT_PAGE_ID`, `NOTION_IDEAS_DATABASE_ID`) | That page is the owner's main hub; defaults make "add an idea to Notion" work without guessing |
| 5 | Six database tables | Added `owner_settings` (key/value: current city, coordinates, time zone) and a `kind` column on `reminders` | The location must survive redeploys; the morning brief is one recurring `reminders` row with `kind = 'brief'` |
| 5 | Recurring reminders | Cron expressions evaluated in the owner's current time zone (APScheduler `CronTrigger`), recomputed when the city changes | Handles DST and travel; the model writes cron easily |
| 5 | Minute loop | APScheduler job inside the single replica; each due row is claimed with a conditional update before sending | No duplicate reminders even when two instances overlap during a redeploy |
| 5 | Location sharing | Telegram location → Open-Meteo (time zone) + OpenStreetMap Nominatim (city name) | No API keys needed |
| 5 | Brief contents | Fixed template chosen by the owner: today's events, markets (BTC/ETH via CoinGecko, S&P 500 via Yahoo Finance chart API, USD/EUR via Frankfurter) and hourly weather 08:00–22:00 for the current city; AI news moved to a tappable `/news` command (also a `get_news` tool), without source names, items separated by a blank line; no "please wait" messages | Owner's preferred layout; a template is instant and never reworded. Frankfurter's ECB data has no UAH |
| 6 | Voice replies via Gemini TTS | Voice notes are answered in **text** only (no TTS in Telegram) | Owner's decision: talking by voice is for calls (stage 10); messages get text |
| 6 | Understanding voice notes | The original recording goes to the agent with a helper transcript; the transcript is saved to memory (channel `voice`) | A real recording was transcribed only as its first phrase ("Hello Lucene"); the agent hearing the audio itself answers correctly even when the transcript is incomplete |
| 6 | Weather in chat | Added a `get_weather` tool (Open-Meteo, current city or any city, up to 7 days) | Voice testing showed the assistant couldn't answer weather questions outside the brief |
| 7 | Skills and lessons tools | `create_skill` (same name updates), `load_skill`, `delete_skill`, `save_lesson`, `list_lessons`, `forget_lesson`; skill names stored as slugs (`log-expense`) | The model updates its own skills as it learns details (e.g. a sheet id) and the owner can prune by chat |
| 7 | Weekly list of lessons to review | No scheduled message. `/lessons` on demand (one 🗑 button per lesson) and `/skills` | Owner's decision: they don't want a message every Sunday; everything is still saved |
| 7 | Who can teach | Only the owner's own messages create lessons or skills, never emails, pages or files | Prompt-injection protection: content can't rewrite the assistant's rules |
| 8 | Documents (docx/pdf) | Markdown → HTML uploaded to Drive as a Google Doc (folder "Lucy"), exported by Google as PDF/DOCX and sent in Telegram | No PDF/Word libraries or fonts on the server; every document also lives in Drive |
| 8 | Long research | In-process background task: Gemini plans 5 sub-questions → parallel Google-grounded answers → report → document; logged in `agent_runs` (`lucy-research`) | Typically about a minute; the chat stays free meanwhile |
| 8 | Photos | Incoming photos/image files go to Gemini with the caption; `generate_image` (Gemini 3.1 Flash Image) sends pictures | Covers both directions of "photos and images in Telegram" |
| 8 | Database backup | Hourly check makes sure `Lucy Backups/backup-YYYY-MM-DD.zip` exists after 03:00 local; JSON per table, embeddings omitted, last 14 kept; silent unless it fails | Stateless and redeploy-safe; embeddings can be recomputed |
| 8 | YouTube permissions | Added the `youtube.force-ssl` scope (owner approved; re-consent via `scripts/google_auth.py`) | Needed to read comments and the captions of private/unlisted videos; the tools only read |
| 8 | GitHub access | Fine-grained token `lucy-assistant`: all repos, Contents read-only, Issues read & write, expires 2027-10-24; REST via `httpx` | Least privilege: Lucy can read code and manage issues but can't push or delete |
| 9 | How agents write status | `POST /api/agent-runs` with its own `AGENTS_TOKEN` (statuses running/success/failed, `run_id` to update); direct table writes still work; drop-in `examples/report_agent_run.py` | Agents never get the Supabase service key or Google access |
| 9 | Alerts | Minute loop alerts once per failed run and per run stuck in `running` for more than 3 hours (`alerted_at` column); failures reported via the endpoint alert immediately | Covers crashed agents that never report failure |
| 10 | Live model | `gemini-3.8-live` (GA), voice Achernar, all registry tools, input/output transcription | Current stable Live model; tested: greeting in ~1.4 s, interruptions, tool calls by voice |
| 10 | Mic fallback | If the Mini App can't get the microphone, "Open in browser" uses a signed 10-minute link (`/call?t=…`) instead of `initData` | The external browser has no Telegram `initData`; the link is only issued to a verified owner |
| 10 | Call button | Chat menu button "📞 Call" set for the owner's chat only (commands still appear when typing "/"), plus a `/call` command | The menu button can hold one Web App; strangers don't get it |
| 10 | Call limits | Lucy greets first; calls end after `MAX_CALL_MINUTES` (60); GoAway or a dropped connection resumes with the session handle (up to 5 times) | Natural start, bounded cost, long calls survive server rotation |
| 10 | Captions in the call screen | Full conversation kept and scrollable; auto-scroll only when already at the bottom; text wraps instead of being clipped | Owner feedback: captions were cut off and couldn't be scrolled |
| 10 | "Open YouTube and research" by voice | Prompt rule: never say "I can't browse", search instead (`web_search`, `youtube_search`, `deep_research`); new `youtube_search` tool | Owner feedback: on a call the assistant refused a research request it could do with search |
| 11 | Wake word with Porcupine / openWakeWord, "Hey Jarvis" | "Lucy" (owner's choice) with Apple's on-device SpeechAnalyzer: English + far-field Russian recognisers in separate analyzers, speech detector, partial results | Free, offline, no extra SDK. Replaced SFSpeechRecognizer, which refuses to run with macOS Dictation off; one analyzer with two recognisers gave no Russian results |
| 11 | Gemini Computer Use model | `mac_do`: screenshot → Gemini Flash returns one JSON action on a 0–1000 grid → Jarvis clicks/types | The Computer Use preview model returned 503 on every try |
| 11 | Echo cancellation + talking over Lucy | No echo cancellation: mic paused while Lucy speaks; Jarvis detects the owner talking over her by comparing the mic with her known loudness (learned echo level), plus ⇧E | Apple's voice processing passed only silence from the Studio Display mic; the owner wants to interrupt by voice |
| 11 | Raw microphone audio | First channel only, 150 Hz low-cut, automatic level (up to ×6) | Gemini Live ignored the quiet, boomy Studio Display audio |
| 11 | Context on the Mac | Long-term memory only, no recent chat lines; language hints; "answer only what was just said" | Lucy answered an old test question when she didn't understand the owner |
| 11 | Global hotkey | ⇧E via Carbon (owner's choice, after ⌃⌥J and ` + Tab) | No permission needed; Shift + E no longer types a capital E while Jarvis runs |
| 11 | Greeting when summoned | A chime; the 2.5 s before it are sent too | A spoken "Yes?" overlapped the owner's first words; one-breath commands still work |
| 11 | Signing and notarizing | Local self-signed certificate in its own keychain file, created by the build script | No Apple Developer account needed; permissions survive rebuilds |
| 11 | Arbitrary AppleScript | Only fixed actions | Text on screen can't make Lucy run scripts |
| 11 | Mac features of the owner's earlier assistant (local reminders and calendar, window presets, English practice mode, Claude Code agent, Spotify Web API search) | Not ported: reminders, calendar, memory and research already live on the server; Spotify uses search in the app | Kept to what the Mac needs for voice; can be added later on request |
| 11 | Lucy confirms what she does ("Opening Spotify") | Actions are non-blocking with SILENT results; she speaks only to answer or report a failure; short replies after actions are dropped | Owner's request; tested: silence for "open TextEdit", "volume 30", one call per request |
| 11 | Goodbye when ending | "Stop" / "that's all" / goodbye ends the conversation silently | Owner's request |
| 12 | Virtual number "in your country" | Region-specific guide (US/Canada, Europe, India, other); a US number is the quickest start | Local EU numbers need documents and days of approval; the tutorial is for viewers worldwide (owner's request) |
| 12 | Calls only to others | Also `call_me` (Lucy calls the owner) and incoming calls from the owner's number | Owner's request: Lucy should call him and talk, with the whole conversation recorded |
| 12 | Recording | Every call recorded and announced; `stop_recording` if the other person objects; recordings deleted from Twilio after delivery | Recording consent rules (EU, some US states); less data kept |
| 12 | μ-law conversion with `audioop` | Small pure-Python codec (`phone_audio.py`) | `audioop` was removed in Python 3.13 |
| 12 | Buy a number right away | Twilio first requires an approved Primary Customer Profile (KYC in Trust Hub), even for US numbers | Twilio's rule since 2025-2026; the purchase API answers "Primary compliance profile is not approved" |
| 12 | Voice in English only | English by default; native Russian/Ukrainian (or any language) on the owner's request; calls to others in the language asked | Owner's request; the product's text and UI stay English |
| 12 | Voicemail | Answering-machine detection: voicemail = "didn't pick up", no message left | Owner's request: know whether the person answered |
| 12 | Calls to a new country right after KYC | The first call to Poland failed with Twilio 20003 "Primary compliance profile is not approved" although the profile was approved; a few minutes later the same account could call Poland | Twilio needs some time after approval (or after enabling a country) before international calls unlock; just retry later |
| 12 | Only the owner may call Lucy | Owner: full Lucy (+ optional PIN); others: guest mode that only takes a message; task calls without any owner data | Owner's request: callers must not reach his data, but people Lucy called may call back |
| 12 | Language per call | Local language of the number by default (+351 → European Portuguese) | Owner's request: book barbershops and the like in Portuguese |
| 12 | Calls to Ukraine | Allowed in Geo permissions, but every Ukrainian network (Vodafone +38099, Kyivstar +38096/97/98) rejected calls from the US number: SIP 486 in 1 s or 480. Option: `ALT_CALLER_ID` = the owner's own mobile, verified in Twilio, used only for `+380` | Ukrainian operators filter calls from foreign VoIP numbers (480 can mean "flagged as spam") |
| 12 | Voicemail detection on `machine_start` | `DetectMessageEnd`: hang up only after a finished greeting (`machine_end_*`) or a fax | The early guess hung up a Ukrainian call after 4 s that may have been a person |
| 13 | Six database tables | Added `usage` (one row per priced call) | Cost tracking and the daily limit need history that survives redeploys |
| 13 | Prompt-injection protection by prompt | Prompt rule + taint tracking + an owner-intent check before risky actions | A prompt alone can be argued with; the check never sees the injected text |
| 13 | Railway template from the working project | A separate secret-free `lucy-template` project linked to a fresh public repository | The working project holds real keys and points at the private repository with personal history |

