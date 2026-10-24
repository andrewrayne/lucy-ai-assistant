"""Report your agent's runs to Lucy. Copy this file into any agent (standard library only).

Set two environment variables in that agent:
    LUCY_URL=https://<your-domain>.up.railway.app
    AGENTS_TOKEN=<the same value as AGENTS_TOKEN on Lucy's Railway service>

Usage:
    from report_agent_run import agent_run

    with agent_run("report-agent") as run:
        do_the_work()
        run.summary = "Processed 12 items"      # optional, shown in /agents

If the block raises, the run is reported as failed (with the error) and Lucy
alerts you in Telegram. Reporting problems never break your agent.
"""

import json
import os
import traceback
import urllib.request
from contextlib import contextmanager


def report(agent: str, status: str, summary: str = "", details: dict | None = None, run_id: int | None = None):
    """Send one report. Returns the run id, or None if Lucy couldn't be reached."""
    url, token = os.environ.get("LUCY_URL"), os.environ.get("AGENTS_TOKEN")
    if not url or not token:
        return None
    body = {"agent": agent, "status": status, "summary": summary[:1000], "details": details, "run_id": run_id}
    req = urllib.request.Request(
        url.rstrip("/") + "/api/agent-runs",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read()).get("run_id")
    except Exception as exc:  # never break the agent because reporting failed
        print(f"[report_agent_run] could not reach Lucy: {exc}")
        return None


class _Run:
    summary = ""
    details: dict | None = None


@contextmanager
def agent_run(agent: str):
    run = _Run()
    run_id = report(agent, "running")
    try:
        yield run
    except Exception as exc:
        report(agent, "failed", run.summary or f"{type(exc).__name__}: {exc}",
               {"traceback": traceback.format_exc()[-3000:]}, run_id)
        raise
    else:
        report(agent, "success", run.summary, run.details, run_id)
