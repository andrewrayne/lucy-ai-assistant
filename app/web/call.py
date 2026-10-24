"""Routes for voice calls: the Mini App page, the browser-fallback link and the WebSocket."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import get_settings
from app.live.auth import AuthError, make_call_link_token, verify_init_data
from app.live.call import run_call
from app.live.jarvis import run_jarvis

router = APIRouter()
PAGE = Path(__file__).parent / "static" / "call.html"


@router.get("/call", include_in_schema=False)
async def call_page() -> FileResponse:
    # The page itself is harmless; the WebSocket checks who is calling.
    return FileResponse(PAGE, media_type="text/html", headers={"Cache-Control": "no-store"})


class LinkRequest(BaseModel):
    init_data: str


@router.post("/api/call/link")
async def call_link(req: LinkRequest) -> dict:
    """Mini App -> a short-lived link that opens the call in the regular browser (mic fallback)."""
    try:
        verify_init_data(req.init_data)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail="Unauthorized") from exc
    return {"url": f"{get_settings().base_url}/call?t={make_call_link_token()}"}


@router.websocket("/ws/call")
async def call_socket(ws: WebSocket) -> None:
    await run_call(ws)


@router.websocket("/ws/jarvis")
async def jarvis_socket(ws: WebSocket) -> None:
    # Jarvis (the Mac app) authenticates with JARVIS_TOKEN in its first message.
    await run_jarvis(ws)
