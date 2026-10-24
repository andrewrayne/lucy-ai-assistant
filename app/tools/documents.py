"""Create documents (Google Doc, PDF, DOCX), send them in Telegram and keep them in Drive.

Markdown -> HTML -> uploaded to Drive with conversion to a Google Doc (in the
"Lucy" folder) -> exported by Google as PDF/DOCX. No PDF library is needed on
the server, and every document also lives in Drive.
"""

import json
import re
import uuid

import markdown

from app.bot import outbox
from app.integrations.google import google
from app.tools.registry import registry

DRIVE = "https://www.googleapis.com/drive/v3/files"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER_MIME = "application/vnd.google-apps.folder"
DOC_MIME = "application/vnd.google-apps.document"
EXPORTS = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

_folders: dict[str, str] = {}

STYLE = """<style>
body { font-family: Arial, sans-serif; font-size: 11pt; line-height: 1.5; }
h1 { font-size: 20pt; } h2 { font-size: 15pt; margin-top: 18pt; } h3 { font-size: 12pt; }
table { border-collapse: collapse; } td, th { border: 1px solid #999; padding: 4px 8px; }
code, pre { font-family: "Courier New", monospace; }
</style>"""


async def ensure_folder(name: str) -> str:
    """Id of a top-level Drive folder with this name (created on first use)."""
    if name in _folders:
        return _folders[name]
    safe = name.replace("'", "\\'")
    res = await google.get(
        DRIVE, params={"q": f"name = '{safe}' and mimeType = '{FOLDER_MIME}' and trashed = false", "fields": "files(id)"}
    )
    if res.get("files"):
        _folders[name] = res["files"][0]["id"]
    else:
        folder = await google.post(DRIVE, json={"name": name, "mimeType": FOLDER_MIME}, params={"fields": "id"})
        _folders[name] = folder["id"]
    return _folders[name]


def to_html(title: str, text: str) -> str:
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    if not re.match(r"\s*<h1", body):
        body = f"<h1>{title}</h1>\n{body}"
    return f"<html><head><meta charset='utf-8'>{STYLE}</head><body>{body}</body></html>"


async def upload(
    name: str, data: bytes, content_type: str, folder: str = "Lucy", convert_to: str | None = None
) -> dict:
    """Multipart upload to Drive. convert_to=DOC_MIME turns HTML into a Google Doc."""
    meta = {"name": name, "parents": [await ensure_folder(folder)]}
    if convert_to:
        meta["mimeType"] = convert_to
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta)}\r\n"
        f"--{boundary}\r\nContent-Type: {content_type}\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--".encode()
    return await google.post(
        UPLOAD,
        params={"uploadType": "multipart", "fields": "id,name,webViewLink"},
        content=body,
        headers={"Content-Type": f"multipart/related; boundary={boundary}"},
    )


async def make_document(title: str, content: str, fmt: str = "pdf") -> dict:
    """Create the Google Doc, send the file in Telegram (pdf/docx). Returns the Drive link."""
    doc = await upload(title, to_html(title, content).encode(), "text/html", convert_to=DOC_MIME)
    fmt = fmt.lower()
    if fmt in EXPORTS:
        data = await google.get(f"{DRIVE}/{doc['id']}/export", params={"mimeType": EXPORTS[fmt]}, binary=True)
        filename = re.sub(r"[^\w\- ]", "", title).strip()[:80] or "document"
        await outbox.send_document(data, f"{filename}.{fmt}", caption=f"{title}\nGoogle Doc: {doc['webViewLink']}")
    return {"title": title, "google_doc": doc["webViewLink"], "sent_as": fmt if fmt in EXPORTS else "link only"}


@registry.register(
    "create_document",
    "Write a document (report, letter, plan, notes) from Markdown content. It's saved as a Google Doc "
    "in the owner's Drive (folder 'Lucy') and sent in Telegram as a PDF or DOCX file.",
    {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "content": {"type": "string", "description": "Full document in Markdown (headings, lists, tables, bold)."},
            "format": {"type": "string", "enum": ["pdf", "docx", "gdoc"], "description": "Default pdf. gdoc = link only."},
        },
        "required": ["title", "content"],
    },
)
async def create_document(title: str, content: str, format: str = "pdf") -> dict:  # noqa: A002
    result = await make_document(title, content, format)
    return {"status": "document created and sent in Telegram", **result}
