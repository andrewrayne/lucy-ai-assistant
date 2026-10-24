"""POST /api/agent-runs: the owner's other agents report their status here.

Protected by its own secret (AGENTS_TOKEN), separate from every other key, so
agents never get database or Google access. Example:

    curl -X POST https://<domain>/api/agent-runs \\
      -H "Authorization: Bearer $AGENTS_TOKEN" -H "Content-Type: application/json" \\
      -d '{"agent": "report-agent", "status": "failed", "summary": "Bank API timeout"}'
"""

import asyncio
import hmac
import logging
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app import agents
from app.bot import outbox
from app.config import get_settings

log = logging.getLogger(__name__)
router = APIRouter()
_background: set[asyncio.Task] = set()


class RunReport(BaseModel):
    agent: str = Field(min_length=1, max_length=80)
    status: Literal["running", "success", "failed"]
    summary: str = Field(default="", max_length=1000)
    details: dict | None = None
    run_id: int | None = Field(default=None, description="Update an earlier report (e.g. running -> success).")


def _check_token(authorization: str | None) -> None:
    expected = get_settings().agents_token
    given = (authorization or "").removeprefix("Bearer ").strip()
    if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Invalid token")


@router.post("/api/agent-runs")
async def report_run(report: RunReport, authorization: str | None = Header(default=None)) -> dict:
    _check_token(authorization)
    try:
        run_id = await agents.record_run(report.agent, report.status, report.summary, report.details, report.run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if report.status == "failed" and outbox.bot() is not None:
        # Alert right away instead of waiting for the minute loop.
        task = asyncio.create_task(agents.alert_problems(outbox.bot(), get_settings().owner_telegram_id))
        _background.add(task)
        task.add_done_callback(_background.discard)
    return {"ok": True, "run_id": run_id}
