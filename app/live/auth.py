"""Who may start a call.

1. Telegram Mini App: Telegram signs the `initData` string with the bot token.
   We recompute the signature (https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app)
   and accept only the owner's user id.
2. Browser fallback (when the mic doesn't work inside Telegram): the Mini App
   asks for a short-lived signed link that opens the same call page in a browser.
"""

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from app.config import get_settings

INIT_DATA_MAX_AGE = 24 * 3600  # seconds; Telegram issues fresh initData every time the Mini App opens
LINK_MAX_AGE = 10 * 60


class AuthError(Exception):
    pass


def verify_init_data(init_data: str, bot_token: str | None = None, owner_id: int | None = None, now: float | None = None) -> dict:
    """Return the Telegram user if initData is genuine, fresh and from the owner."""
    s = get_settings()
    bot_token = bot_token or s.telegram_bot_token
    owner_id = owner_id if owner_id is not None else s.owner_telegram_id
    pairs = dict(parse_qsl(init_data or "", keep_blank_values=True))
    received_hash = pairs.pop("hash", "")
    if not received_hash:
        raise AuthError("Missing signature")
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise AuthError("Bad signature")
    if (now or time.time()) - int(pairs.get("auth_date", "0")) > INIT_DATA_MAX_AGE:
        raise AuthError("Expired")
    user = json.loads(pairs.get("user", "{}"))
    if user.get("id") != owner_id:
        raise AuthError("Not the owner")
    return user


def _link_secret() -> bytes:
    return hashlib.sha256(f"call-link:{get_settings().telegram_bot_token}".encode()).digest()


def make_call_link_token(now: float | None = None) -> str:
    expires = int((now or time.time()) + LINK_MAX_AGE)
    sig = hmac.new(_link_secret(), str(expires).encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{sig}"


def verify_call_link_token(token: str, now: float | None = None) -> None:
    try:
        expires_str, sig = token.split(".", 1)
        expires = int(expires_str)
    except ValueError as exc:
        raise AuthError("Bad link") from exc
    expected = hmac.new(_link_secret(), expires_str.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise AuthError("Bad link")
    if (now or time.time()) > expires:
        raise AuthError("Link expired")
