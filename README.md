# Lucy: a personal AI assistant

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/deploy/EkjrZZ)

A personal AI assistant with one brain and one memory in the cloud, and three ways to reach her:

- **Telegram:** chat, voice notes, photos, documents, and voice calls (a Mini App call button).
- **The Mac ("Jarvis"):** say "Lucy" or press ⇧⌘F and talk; she sees the screen, opens apps, clicks and types.
- **The phone:** she calls you, calls businesses for you ("book a table for Friday at 8"), and takes messages.

She uses your Gmail, Calendar, Drive, Sheets, Forms, Notion, YouTube channel and GitHub, sends a morning brief,
keeps reminders, remembers everything you tell her, learns from your corrections, and runs 24/7 on Railway, even when
your computer is off. Every model is Google Gemini (Flash for text, Live for voice).

`PLAN.md` is the full build log: 13 stages, what each one does, how it works and what was changed along the way.
This README is the short version: how to get your own copy running.

## What you need

| Service | What for | Cost |
|---|---|---|
| [Railway](https://railway.com) (Hobby plan) | runs the server 24/7 | about $5–15/month |
| [Google AI Studio](https://aistudio.google.com) (billing on) | Gemini: every model | pay as you go; a daily limit is built in |
| [Supabase](https://supabase.com) | memory (Postgres + pgvector) | free to start |
| Telegram | the chat | free |
| Google Cloud project (optional) | Gmail, Calendar, Drive, Sheets, Forms, YouTube | free |
| Notion integration (optional) | Notion pages and databases | free |
| [Twilio](https://twilio.com) (optional) | phone calls | number ~$1–2/month + minutes |
| A Mac with macOS 26+ (optional) | Jarvis | free |

## Quick start

1. **Get your copy:** click **Deploy on Railway** above. It creates the project from
   [the public repository](https://github.com/andrewrayne/lucy-ai-assistant) and asks for the variables (five are
   required, the rest have defaults or are optional; `JARVIS_TOKEN` and `AGENTS_TOKEN` are generated for you). Or
   fork the repository and deploy it yourself (step 5).
2. **Telegram:** create a bot with [@BotFather](https://t.me/BotFather) → `TELEGRAM_BOT_TOKEN`. Your own numeric
   ID (ask [@userinfobot](https://t.me/userinfobot)) → `OWNER_TELEGRAM_ID`. The bot answers only this ID.
3. **Gemini:** create an API key in Google AI Studio and turn on billing → `GEMINI_API_KEY`. Model names change
   often; the defaults are in `app/config.py` and can be overridden by variables.
4. **Supabase:** create a project → `SUPABASE_URL` and the `service_role` key → `SUPABASE_SERVICE_KEY`. Apply the
   database schema from your computer (it uses a personal access token, which never goes to Railway):
   ```bash
   cp .env.example .env   # fill in SUPABASE_PROJECT_REF and SUPABASE_ACCESS_TOKEN
   python scripts/migrate.py
   ```
5. **Railway:** new project → deploy from your GitHub repo. In the service settings: 1 replica, healthcheck path
   `/health`, restart on failure, deploy from `main`, and generate a public domain. Add the variables from steps
   2–4 and `OWNER_TIMEZONE`. On start the server registers its Telegram webhook by itself.
6. Write to your bot. That's the core: chat, memory, reminders, morning brief, research, documents and images.

Each optional part below is switched on just by adding its variables (see `.env.example`, grouped by part).

## Optional parts

- **Google (Gmail, Calendar, Drive, Sheets, Forms, YouTube):** create a Google Cloud project, enable those APIs,
  make an OAuth client of type "Desktop app", and publish the consent screen ("In production"; in "Testing" the
  token expires after 7 days; Google asks for a home page and privacy policy, which the server provides at `/` and
  `/privacy`). Then run `python scripts/google_auth.py` once on your computer and copy the three `GOOGLE_*`
  values. For YouTube, sign in with the account that owns the channel.
- **Notion:** create an internal integration, share your pages/databases with it → `NOTION_TOKEN`, and optionally
  `NOTION_DEFAULT_PAGE_ID` and `NOTION_IDEAS_DATABASE_ID`.
- **GitHub:** a fine-grained token with Contents read-only and Issues read/write → `GITHUB_TOKEN`.
- **Your other AI agents:** they report runs to `POST /api/agent-runs` with `AGENTS_TOKEN`; Lucy shows them in
  `/agents` and alerts you when one fails (`examples/report_agent_run.py`).
  ```bash
  curl -X POST https://<your-domain>/api/agent-runs \
    -H "Authorization: Bearer $AGENTS_TOKEN" -H "Content-Type: application/json" \
    -d '{"agent": "report-agent", "status": "failed", "summary": "Bank API timeout"}'
  ```
- **Voice calls in Telegram:** nothing to set up: the chat's "📞 Call" button and `/call` work once the server runs.
- **Jarvis on the Mac:** set `JARVIS_TOKEN` (a long random string) on Railway, then on the Mac (Command Line Tools
  only, `xcode-select --install`):
  ```bash
  JARVIS_SERVER=wss://<your-domain>/ws/jarvis JARVIS_TOKEN=<same token> scripts/build_jarvis.sh
  ```
  It installs as `Lucy.app` with your bot's Telegram profile picture as its icon. Allow Microphone and Speech
  Recognition, turn Lucy on in Privacy & Security → Screen Recording and Accessibility, reopen it. Details and troubleshooting: stage 11 in `PLAN.md`.
- **Phone calls (Twilio):** stage 12 in `PLAN.md` has a "choose your region" guide (US/Canada, Europe, India,
  other), because numbers and recording rules differ by country. In short: a Full-access Twilio account, an approved
  Primary Customer Profile (Trust Hub), a number with Voice, Geo permissions for the countries you'll call, then
  `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`, `OWNER_NAME`, `OWNER_PHONE_NUMBER`, and the
  number's incoming-call webhook `https://<your-domain>/twilio/voice` (POST).

## Telegram commands

`/call` voice call · `/brief` morning brief now · `/news` AI and tech news · `/city Berlin` you moved ·
`/agents` your agents · `/lessons` and `/skills` what she learned · `/usage` spending · `/new` fresh conversation

## Safety built in

- Only the owner: Telegram checks your user ID; the call page checks Telegram's signature; Jarvis and agents use
  their own tokens; Twilio webhooks are signature-checked; nobody else's call reaches your data (other callers get a
  "leave a message" mode, optional PIN for yours).
- Prompt injection: content from emails, web pages, documents and Notion is data. In code, once such content was
  read, risky actions (sending email, calls, deleting events, GitHub posts, clicking on the Mac) run only if a
  separate check confirms that your own words asked for them.
- Secrets live only in variables; the Gemini key never leaves the server. Backups go to your Google Drive.
- Crash alerts: server errors reach your Telegram (rate-limited, secrets removed).
- Spending: every Gemini and Twilio cost is counted; `DAILY_COST_LIMIT_USD` (default $5) pauses the assistant for
  the rest of the day, with a warning at 80%. `/usage` shows where it went.

## Develop

```bash
uv venv --python 3.12 && uv pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q        # tests (no network needed)
python scripts/migrate.py            # apply new SQL migrations in supabase/migrations
railway logs                         # server logs
```

Code map: `app/bot` (Telegram), `app/agent` (text agent and prompt), `app/tools` (one module per integration, one
registry for every channel), `app/live` (voice: Telegram call, Jarvis, phone), `app/memory`, `app/scheduler`,
`app/web` (HTTP routes), `jarvis/` (Swift Mac app), `supabase/migrations`.

## Make your own one-click template (for sharing a fork)

1. Make sure no personal data is in the repository (`.env` is git-ignored; use placeholders in docs and tests).
   Publish a clean public copy (a new repository without your private history is safest).
2. In Railway: your project → Settings → "Create template" (or railway.com/compose → New template from the repo).
   Add every variable from the "Required" block of `.env.example` with its comment as the description, mark the
   optional ones optional, set the service settings above, and publish.
3. Put the button at the top of this README:
   `[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/deploy/<template-code>)`
