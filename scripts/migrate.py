"""Apply new SQL migrations from supabase/migrations to the Supabase project.

Uses the Supabase Management API, so no database password or CLI is needed.
Needs SUPABASE_ACCESS_TOKEN and SUPABASE_PROJECT_REF (in .env or the environment).

    python scripts/migrate.py           # apply pending migrations
    python scripts/migrate.py --status  # only show what is applied / pending
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "supabase" / "migrations"
API = "https://api.supabase.com/v1/projects/{ref}/database/migrations"


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def request(method: str, url: str, token: str, body: dict | None = None):
    req = urllib.request.Request(
        url,
        method=method,
        data=json.dumps(body).encode() if body else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "assistant-migrate",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            text = resp.read().decode()
            return json.loads(text) if text else None
    except urllib.error.HTTPError as exc:
        sys.exit(f"{method} {url} failed: {exc.code} {exc.read().decode()}")


def main() -> None:
    load_env()
    token, ref = os.environ.get("SUPABASE_ACCESS_TOKEN"), os.environ.get("SUPABASE_PROJECT_REF")
    if not token or not ref:
        sys.exit("Set SUPABASE_ACCESS_TOKEN and SUPABASE_PROJECT_REF first.")
    url = API.format(ref=ref)

    applied = {m["name"] for m in request("GET", url, token) or []}
    files = sorted(MIGRATIONS.glob("*.sql"))
    pending = [f for f in files if f.stem not in applied]

    for f in files:
        print(("  applied  " if f.stem in applied else "  pending  ") + f.name)
    if "--status" in sys.argv or not pending:
        print("Nothing to apply." if not pending else "")
        return

    for f in pending:
        print(f"Applying {f.name} ...")
        request("POST", url, token, {"name": f.stem, "query": f.read_text()})
    print("Done.")


if __name__ == "__main__":
    main()
