"""App settings, read from environment variables (or a local .env file)."""

import hashlib
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str
    owner_telegram_id: int
    owner_timezone: str = "UTC"

    # Public base URL of the server. On Railway we fall back to the
    # domain Railway injects, so this is usually left empty.
    public_url: str = ""
    railway_public_domain: str = ""

    # Gemini. Model IDs live here, never in the logic.
    gemini_api_key: str = ""
    gemini_text_model: str = "gemini-3.8-flash"
    # Comma-separated, tried in order when the main model is overloaded.
    gemini_fallback_models: str = "gemini-3.6-flash,gemini-3.5-flash,gemini-3.5-flash-lite"
    # "minimal", "low", "medium" or "high". Low keeps chat replies fast.
    gemini_thinking_level: str = "low"
    # Embeddings for memory search. The vector size (768) is fixed in the SQL schema.
    gemini_embedding_model: str = "gemini-embedding-2"
    # Image generation (and editing).
    gemini_image_model: str = "gemini-3.1-flash-image"
    # Live voice calls (Telegram Mini App, later Jarvis and phone).
    gemini_live_model: str = "gemini-3.8-live"
    max_call_minutes: int = 60
    # Languages the owner may speak (hints for Gemini Live's speech recognition; replies stay in English).
    voice_language_codes: str = "en-US,ru-RU,uk-UA,pt-PT"
    # Pause (ms) that ends the owner's phrase in a voice conversation.
    voice_silence_ms: int = 700
    # Voice for Gemini Live and TTS. "Achernar" is Gemini's soft female voice.
    gemini_voice: str = "Achernar"

    assistant_name: str = "Lucy"
    # Spending limit per day (USD) for Gemini + Twilio. 0 = no limit.
    daily_cost_limit_usd: float = 5.0

    # Morning brief: first-run time (owner's local time) and the markets it shows.
    brief_time: str = "08:00"
    brief_crypto: str = "bitcoin:BTC,ethereum:ETH"  # CoinGecko id:symbol
    brief_indexes: str = "^GSPC:S&P 500"  # Yahoo Finance ticker:name
    brief_currencies: str = "USD/EUR"  # ECB data via Frankfurter (no UAH)

    # Supabase (memory). The service key stays on the server.
    supabase_url: str = ""
    supabase_service_key: str = ""

    # Google (Gmail, Calendar, Drive, Sheets, Forms, YouTube): one OAuth refresh token.
    google_client_id: str = ""
    google_client_secret: str = ""
    google_refresh_token: str = ""

    # Phone calls (Twilio): Lucy calls people on the owner's behalf.
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""  # the number Lucy calls from, e.g. +15551234567
    owner_name: str = ""  # how Lucy names the owner on calls ("calling on behalf of …")
    owner_phone_number: str = ""  # the owner's own phone (+351…): Lucy calls it; calls from it get the full Lucy
    # Optional PIN typed on the keypad when the owner calls in (caller ID can be faked). Empty = no PIN.
    owner_call_pin: str = ""
    # Other people calling Lucy's number can leave a message (Lucy knows nothing else). False = they're hung up on.
    phone_guest_messages: bool = True
    guest_call_minutes: int = 3
    # Optional second caller ID (e.g. the owner's own mobile, verified in Twilio) for countries whose networks reject
    # calls from Lucy's number. Ukrainian networks rejected every call from a US number (SIP 486/480).
    alt_caller_id: str = ""
    alt_caller_id_prefixes: str = "+380"
    phone_max_minutes: int = 10
    phone_record_calls: bool = True

    # Jarvis (the Mac app): shared secret for /ws/jarvis, and how many steps one Mac task may take.
    jarvis_token: str = ""
    mac_max_steps: int = 25

    # Secret your other agents use to report runs to POST /api/agent-runs.
    agents_token: str = ""

    # GitHub fine-grained personal access token.
    github_token: str = ""

    # Notion internal integration.
    notion_token: str = ""
    notion_version: str = "2026-03-11"
    # Where new pages go when no parent is given (a page shared with the integration).
    notion_default_page_id: str = ""
    # Database where "add an idea" goes (optional).
    notion_ideas_database_id: str = ""

    @property
    def base_url(self) -> str:
        if self.public_url:
            return self.public_url.rstrip("/")
        if self.railway_public_domain:
            return f"https://{self.railway_public_domain}"
        return ""

    @property
    def webhook_path(self) -> str:
        return "/telegram/webhook"

    @property
    def webhook_secret(self) -> str:
        # Telegram sends this back in a header on every update, so only
        # Telegram can reach the webhook. Derived from the bot token to
        # avoid one more variable to manage.
        return hashlib.sha256(self.telegram_bot_token.encode()).hexdigest()[:48]


@lru_cache
def get_settings() -> Settings:
    return Settings()
