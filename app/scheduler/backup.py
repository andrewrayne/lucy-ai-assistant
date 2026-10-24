"""Daily database backup to Google Drive (never to git: it contains personal data).

An hourly job makes sure today's backup exists after BACKUP_HOUR (owner's time):
every table is exported to JSON, zipped and uploaded to Drive as
"Lucy Backups/backup-YYYY-MM-DD.zip". The last KEEP backups are kept; older ones
go to the Drive trash. Embedding vectors are left out (they can be recomputed).
Silent on success; the owner only hears about failures.
"""

import io
import json
import logging
import zipfile

from app import owner
from app.bot import outbox
from app.integrations.google import google
from app.memory.db import db
from app.tools.documents import DRIVE, ensure_folder, upload

log = logging.getLogger(__name__)

FOLDER = "Lucy Backups"
BACKUP_HOUR = 3
KEEP = 14
PAGE = 1000
TABLES = {
    "messages": "id, created_at, channel, chat_id, role, content, summarized_at",
    "memories": "id, created_at, updated_at, kind, content, period_start",
    "lessons": "*",
    "skills": "*",
    "reminders": "*",
    "agent_runs": "*",
    "owner_settings": "*",
}


async def export_table(name: str, columns: str) -> list[dict]:
    client, rows, start = await db(), [], 0
    order = "key" if name == "owner_settings" else "id"
    while True:
        page = (await client.table(name).select(columns).order(order).range(start, start + PAGE - 1).execute()).data
        rows += page
        if len(page) < PAGE:
            return rows
        start += PAGE


def build_zip(tables: dict[str, list[dict]], day: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, rows in tables.items():
            zf.writestr(f"{name}.json", json.dumps(rows, ensure_ascii=False, indent=1, default=str))
        zf.writestr("README.txt", f"Lucy database backup for {day}.\nOne JSON file per Supabase table. Embeddings omitted.\n")
    return buffer.getvalue()


async def _existing_backups(folder_id: str) -> list[dict]:
    res = await google.get(
        DRIVE,
        params={
            "q": f"'{folder_id}' in parents and trashed = false and name contains 'backup-'",
            "orderBy": "name desc",
            "fields": "files(id,name)",
            "pageSize": 100,
        },
    )
    return res.get("files", [])


async def backup_now() -> dict:
    day = owner.now().date().isoformat()
    tables = {name: await export_table(name, cols) for name, cols in TABLES.items()}
    data = build_zip(tables, day)
    file = await upload(f"backup-{day}.zip", data, "application/zip", folder=FOLDER)
    folder_id = await ensure_folder(FOLDER)
    for old in (await _existing_backups(folder_id))[KEEP:]:
        await google.request("PATCH", f"{DRIVE}/{old['id']}", json={"trashed": True})
    counts = {name: len(rows) for name, rows in tables.items()}
    log.info("Backup %s uploaded (%d KB): %s", day, len(data) // 1024, counts)
    return {"file": file["name"], "size_kb": len(data) // 1024, "rows": counts}


async def ensure_daily_backup() -> None:
    """Hourly: create today's backup once it's past BACKUP_HOUR and none exists yet."""
    now = owner.now()
    if now.hour < BACKUP_HOUR:
        return
    folder_id = await ensure_folder(FOLDER)
    if any(f["name"] == f"backup-{now.date().isoformat()}.zip" for f in await _existing_backups(folder_id)):
        return
    try:
        await backup_now()
    except Exception:
        log.exception("Daily backup failed")
        await outbox.send_text("⚠️ Today's database backup to Google Drive failed. I'll retry within the hour.")
