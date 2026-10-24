"""Twilio webhooks and the media-stream WebSocket for phone calls.

Every webhook is checked against Twilio's signature (X-Twilio-Signature, made with the auth token), so nobody else
can fake a call status, a recording or an incoming call.
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request, WebSocket
from fastapi.responses import Response

from app.config import get_settings
from app.integrations import twilio
from app.live import phone

log = logging.getLogger(__name__)
router = APIRouter()
_background: set[asyncio.Task] = set()


async def _verified_form(request: Request) -> dict[str, str]:
    form = {k: str(v) for k, v in (await request.form()).items()}
    # Twilio signs the exact public URL it called (we sit behind Railway's proxy, so rebuild it).
    url = get_settings().base_url + request.url.path + (f"?{request.url.query}" if request.url.query else "")
    if not twilio.valid_signature(url, form, request.headers.get("X-Twilio-Signature", "")):
        log.warning("Twilio webhook with a bad signature: %s", request.url.path)
        raise HTTPException(status_code=403, detail="Bad signature")
    return form


def _later(coro) -> None:
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)


@router.post("/twilio/status", include_in_schema=False)
async def call_status(request: Request, run: int) -> Response:
    form = await _verified_form(request)
    _later(
        phone.call_status(run, form.get("CallStatus", ""), form.get("SipResponseCode", ""), form.get("CallSid", ""))
    )
    return Response(status_code=204)


@router.post("/twilio/recording", include_in_schema=False)
async def recording(request: Request, run: int) -> Response:
    form = await _verified_form(request)
    if form.get("RecordingStatus") == "completed" and form.get("RecordingUrl"):
        _later(phone.recording_ready(run, form["RecordingUrl"], form.get("RecordingSid", "")))
    return Response(status_code=204)


@router.post("/twilio/amd", include_in_schema=False)
async def machine_detection(request: Request, run: int) -> Response:
    form = await _verified_form(request)
    _later(phone.answered_by(run, form.get("CallSid", ""), form.get("AnsweredBy", "unknown")))
    return Response(status_code=204)


@router.post("/twilio/voice", include_in_schema=False)
async def incoming_call(request: Request) -> Response:
    """Set this URL as the number's "A call comes in" webhook in Twilio."""
    form = await _verified_form(request)
    return Response(await phone.incoming_call_twiml(form.get("From", "")), media_type="text/xml")


@router.post("/twilio/pin", include_in_schema=False)
async def pin(request: Request) -> Response:
    form = await _verified_form(request)
    return Response(await phone.pin_entered(form.get("From", ""), form.get("Digits", "")), media_type="text/xml")


@router.websocket("/ws/twilio")
async def media_stream(ws: WebSocket) -> None:
    # Authenticated by the signed run token in the stream's custom parameters.
    await phone.run_phone_stream(ws)
