"""Twilio REST API (phone calls) with plain httpx, plus webhook signature checks.

Only what the assistant needs: place a call that streams its audio to our WebSocket, hang up, and fetch/delete
the recording. Docs: https://www.twilio.com/docs/voice/api/call-resource
"""

import base64
import hashlib
import hmac
import html
from urllib.parse import urlencode

import httpx

from app.config import get_settings

API = "https://api.twilio.com/2010-04-01"
_http = httpx.AsyncClient(timeout=30)


class TwilioError(Exception):
    pass


def configured() -> bool:
    s = get_settings()
    return bool(s.twilio_account_sid and s.twilio_auth_token and s.twilio_phone_number)


def _auth() -> tuple[str, str]:
    s = get_settings()
    return s.twilio_account_sid, s.twilio_auth_token


def caller_id_for(to: str) -> str:
    """Lucy's number, or ALT_CALLER_ID for destinations (ALT_CALLER_ID_PREFIXES) that reject it."""
    s = get_settings()
    prefixes = [p.strip() for p in s.alt_caller_id_prefixes.split(",") if p.strip()]
    if s.alt_caller_id and any(to.startswith(p) for p in prefixes):
        return s.alt_caller_id
    return s.twilio_phone_number


def stream_twiml(stream_url: str, parameters: dict[str, str]) -> str:
    """TwiML that connects the call's audio to our WebSocket. Twilio can't send headers there, so the call is
    identified (and authenticated) by custom parameters that arrive in the stream's first message."""
    params = "".join(
        f'<Parameter name="{html.escape(k)}" value="{html.escape(str(v))}"/>' for k, v in parameters.items()
    )
    return f'<Response><Connect><Stream url="{html.escape(stream_url)}">{params}</Stream></Connect></Response>'


async def create_call(
    to: str, twiml: str, status_callback: str, recording_callback: str, time_limit: int, machine_callback: str = ""
) -> str:
    """Start an outbound call. Returns the call SID.
    machine_callback: asynchronous answering-machine detection; the call connects at once and Twilio reports
    who answered (a person or voicemail) to this URL a few seconds later."""
    s = get_settings()
    data = {
        "To": to,
        "From": caller_id_for(to),
        "Twiml": twiml,
        "StatusCallback": status_callback,
        "StatusCallbackMethod": "POST",
        "TimeLimit": str(time_limit),
    }
    if machine_callback:
        data |= {
            # Wait for the end of a voicemail greeting before deciding: the early "machine_start" guess once hung
            # up on a call that may have been a person saying "hello".
            "MachineDetection": "DetectMessageEnd",
            "AsyncAmd": "true",
            "AsyncAmdStatusCallback": machine_callback,
            "AsyncAmdStatusCallbackMethod": "POST",
        }
    if recording_callback:
        data |= {
            "Record": "true",
            "RecordingStatusCallback": recording_callback,
            "RecordingStatusCallbackMethod": "POST",
        }
    # StatusCallbackEvent is a repeated field.
    body = urlencode(data) + "&" + urlencode([("StatusCallbackEvent", e) for e in ("answered", "completed")])
    resp = await _http.post(
        f"{API}/Accounts/{s.twilio_account_sid}/Calls.json",
        content=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        auth=_auth(),
    )
    if resp.status_code >= 400:
        raise TwilioError(_error(resp))
    return resp.json()["sid"]


async def call_price(call_sid: str) -> float | None:
    """The call's price in USD (negative in Twilio's API), or None until Twilio has set it."""
    s = get_settings()
    resp = await _http.get(f"{API}/Accounts/{s.twilio_account_sid}/Calls/{call_sid}.json", auth=_auth())
    if resp.status_code >= 400:
        raise TwilioError(_error(resp))
    price = resp.json().get("price")
    return float(price) if price not in (None, "") else None


async def hang_up(call_sid: str) -> None:
    s = get_settings()
    await _http.post(
        f"{API}/Accounts/{s.twilio_account_sid}/Calls/{call_sid}.json", data={"Status": "completed"}, auth=_auth()
    )


async def start_recording(call_sid: str, callback: str) -> None:
    """Record a call that's already in progress (used for incoming calls)."""
    s = get_settings()
    resp = await _http.post(
        f"{API}/Accounts/{s.twilio_account_sid}/Calls/{call_sid}/Recordings.json",
        data={"RecordingStatusCallback": callback, "RecordingStatusCallbackMethod": "POST"},
        auth=_auth(),
    )
    if resp.status_code >= 400:
        raise TwilioError(_error(resp))


async def stop_recording(call_sid: str) -> None:
    """Stop recording the current call (the other person asked not to be recorded)."""
    s = get_settings()
    resp = await _http.post(
        f"{API}/Accounts/{s.twilio_account_sid}/Calls/{call_sid}/Recordings/Twilio.CurrentCall.json",
        data={"Status": "stopped"},
        auth=_auth(),
    )
    if resp.status_code >= 400:
        raise TwilioError(_error(resp))


async def download_recording(recording_url: str) -> bytes:
    """recording_url comes from the recording callback (without extension)."""
    resp = await _http.get(f"{recording_url}.mp3", auth=_auth(), follow_redirects=True)
    if resp.status_code >= 400:
        raise TwilioError(_error(resp))
    return resp.content


async def delete_recording(recording_sid: str) -> None:
    """The recording is sent to the owner in Telegram, so Twilio doesn't need to keep it."""
    s = get_settings()
    await _http.delete(f"{API}/Accounts/{s.twilio_account_sid}/Recordings/{recording_sid}.json", auth=_auth())


def valid_signature(url: str, params: dict[str, str], signature: str) -> bool:
    """Check X-Twilio-Signature: base64(HMAC-SHA1(auth token, url + sorted key/value pairs)).
    https://www.twilio.com/docs/usage/security#validating-requests"""
    token = get_settings().twilio_auth_token
    if not token or not signature:
        return False
    payload = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    expected = base64.b64encode(hmac.new(token.encode(), payload.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(expected, signature)


def _error(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        return f"Twilio error {resp.status_code}: {body.get('message', '')} (code {body.get('code', '')})"
    except ValueError:
        return f"Twilio error {resp.status_code}: {resp.text[:200]}"
