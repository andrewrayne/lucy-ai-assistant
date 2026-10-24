"""Fixed settings for tests, so they never depend on a local .env file."""

import os

os.environ.update(
    {
        "TELEGRAM_BOT_TOKEN": "123456:TEST-token",
        "OWNER_TELEGRAM_ID": "111",
        "OWNER_TIMEZONE": "Europe/Lisbon",
        "SUPABASE_URL": "",
        "GEMINI_API_KEY": "test",
    }
)
