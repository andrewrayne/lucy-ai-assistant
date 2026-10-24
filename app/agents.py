"""The owner's other AI agents: their runs, an overview, and alerts.

Agents report through POST /api/agent-runs (see app/web/agents_api.py) or by
writing to the agent_runs table directly. A minute loop alerts the owner once
about every failed run and every run stuck in 'running' too long.
"""

import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from aiogram import Bot

from app import owner
from app.memory.db import db

log = logging.getLogger(__name__)

STATUSES = ("running", "success", "failed")
STUCK_AFTER = timedelta(hours=3)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _local(ts: str) -> str:
    return datetime.fromisoformat(ts).astimezone(owner.tz()).strftime("%d %b %H:%M")


async def record_run(
    agent: str, status: str, summary: str = "", details: dict | None = None, run_id: int | None = None
) -> int:
    """Create a run, or update one (e.g. running -> success). Returns the run id."""
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    table = (await db()).table("agent_runs")
    row = {"agent": agent.strip()[:80], "status": status, "summary": summary[:1000], "updated_at": _now()}
    if details is not None:
        row["details"] = details
    if status == "failed":
        row["alerted_at"] = None  # a failure always alerts, even if this run was alerted as stuck before
    if run_id:
        res = await table.update(row).eq("id", run_id).execute()
        if not res.data:
            raise LookupError(f"No run with id {run_id}")
        return run_id
    return (await table.insert(row).execute()).data[0]["id"]


def summarize(rows: list[dict], now: datetime) -> list[dict]:
    """Per-agent overview from runs (newest first)."""
    by_agent: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_agent[row["agent"]].append(row)
    overview = []
    for agent, runs in by_agent.items():
        last = runs[0]
        failures = [r for r in runs if r["status"] == "failed"]
        stuck = last["status"] == "running" and now - datetime.fromisoformat(last["updated_at"]) > STUCK_AFTER
        overview.append(
            {
                "agent": agent,
                "health": "failing" if last["status"] == "failed" else "stuck" if stuck else "ok",
                "last_status": last["status"],
                "last_run": last["updated_at"],
                "last_summary": last["summary"] or "",
                "runs": len(runs),
                "successes": sum(r["status"] == "success" for r in runs),
                "failures": len(failures),
                "last_failure": failures[0]["summary"] if failures else None,
            }
        )
    order = {"failing": 0, "stuck": 1, "ok": 2}
    return sorted(overview, key=lambda a: (order[a["health"]], a["agent"]))


async def overview(hours: int = 24) -> list[dict]:
    since = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    rows = (
        await (await db())
        .table("agent_runs")
        .select("agent, status, summary, updated_at")
        .gte("updated_at", since)
        .order("updated_at", desc=True)
        .limit(2000)
        .execute()
    ).data
    return summarize(rows, datetime.now(UTC))


async def history(agent: str, limit: int = 10) -> list[dict]:
    res = await (
        (await db())
        .table("agent_runs")
        .select("id, status, summary, details, created_at, updated_at")
        .eq("agent", agent)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data


def render_overview(items: list[dict], hours: int = 24) -> str:
    if not items:
        return f"🤖 No agent reports in the last {hours} hours."
    icon = {"ok": "✅", "failing": "❌", "stuck": "⏳"}
    lines = [f"🤖 Agents, last {hours} hours"]
    for a in items:
        line = f"{icon[a['health']]} {a['agent']}: {a['last_status']} at {_local(a['last_run'])}"
        line += f" · {a['successes']} ok, {a['failures']} failed"
        lines.append(line)
        if a["health"] != "ok" and a["last_summary"]:
            lines.append(f"    {a['last_summary'][:200]}")
    return "\n".join(lines)


def alert_text(row: dict) -> str:
    if row["status"] == "failed":
        head = f"🚨 Agent failed: {row['agent']}"
    else:
        head = f"⏳ Agent stuck: {row['agent']} has been running since {_local(row['created_at'])}"
    return f"{head}\n{row['summary']}".strip() if row.get("summary") else head


async def alert_problems(bot: Bot, chat_id: int) -> int:
    """Alert once about new failures and stuck runs. Returns how many alerts were sent."""
    table = (await db()).table("agent_runs")
    stuck_before = (datetime.now(UTC) - STUCK_AFTER).isoformat()
    failed = (
        await table.select("id, agent, status, summary, created_at").is_("alerted_at", "null")
        .eq("status", "failed").limit(20).execute()
    ).data
    stuck = (
        await table.select("id, agent, status, summary, created_at").is_("alerted_at", "null")
        .eq("status", "running").lt("updated_at", stuck_before).limit(20).execute()
    ).data
    sent = 0
    for row in failed + stuck:
        # Claim first, so two instances never alert twice.
        claimed = await table.update({"alerted_at": _now()}).eq("id", row["id"]).is_("alerted_at", "null").execute()
        if not claimed.data:
            continue
        try:
            await bot.send_message(chat_id, alert_text(row))
            sent += 1
        except Exception:
            log.exception("Could not send the agent alert for run %s", row["id"])
    return sent
