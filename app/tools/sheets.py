"""Google Sheets: create, read, append and update spreadsheets."""

import re
from urllib.parse import quote

from app.integrations.google import google
from app.tools.registry import registry

API = "https://sheets.googleapis.com/v4/spreadsheets"


def file_id(value: str) -> str:
    """Accept a bare id or a full Google Docs/Sheets/Forms/Drive URL."""
    match = re.search(r"/d/(?:e/)?([a-zA-Z0-9_-]{20,})", value)
    return match.group(1) if match else value.strip()


ROWS = {
    "type": "array",
    "items": {"type": "array", "items": {"type": "string"}},
    "description": "Rows of cell values, e.g. [['Date', 'Amount'], ['2026-10-24', '12.50']].",
}


@registry.register(
    "sheets_create",
    "Create a new Google Sheet, optionally with a header row. Returns its id and link.",
    {
        "type": "object",
        "properties": {"title": {"type": "string"}, "headers": {"type": "array", "items": {"type": "string"}}},
        "required": ["title"],
    },
)
async def sheets_create(title: str, headers: list[str] | None = None) -> dict:
    sheet = await google.post(API, json={"properties": {"title": title}})
    if headers:
        await sheets_append(sheet["spreadsheetId"], [headers])
    return {"spreadsheet_id": sheet["spreadsheetId"], "url": sheet["spreadsheetUrl"]}


@registry.register(
    "sheets_read",
    "Read cells from a Google Sheet. Without a range, reads the first sheet.",
    {
        "type": "object",
        "properties": {
            "spreadsheet": {"type": "string", "description": "Spreadsheet id or URL."},
            "range": {"type": "string", "description": "A1 range like 'Sheet1!A1:D50'. Optional."},
        },
        "required": ["spreadsheet"],
    },
)
async def sheets_read(spreadsheet: str, range: str = "") -> dict:  # noqa: A002 (matches the API name)
    sid = file_id(spreadsheet)
    meta = await google.get(f"{API}/{sid}", params={"fields": "properties.title,sheets.properties.title"})
    rng = range or meta["sheets"][0]["properties"]["title"]
    res = await google.get(f"{API}/{sid}/values/{quote(rng, safe='')}")
    values = res.get("values", [])
    return {
        "title": meta["properties"]["title"],
        "sheets": [s["properties"]["title"] for s in meta["sheets"]],
        "range": res.get("range"),
        "rows": values[:300],
        "total_rows": len(values),
    }


@registry.register(
    "sheets_append",
    "Add rows to the end of a Google Sheet.",
    {
        "type": "object",
        "properties": {
            "spreadsheet": {"type": "string", "description": "Spreadsheet id or URL."},
            "rows": ROWS,
            "sheet": {"type": "string", "description": "Sheet (tab) name. Default: the first one."},
        },
        "required": ["spreadsheet", "rows"],
    },
)
async def sheets_append(spreadsheet: str, rows: list[list], sheet: str = "") -> dict:
    sid = file_id(spreadsheet)
    rng = f"{sheet}!A1" if sheet else "A1"
    res = await google.post(
        f"{API}/{sid}/values/{quote(rng, safe='')}:append",
        params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
        json={"values": rows},
    )
    return {"status": "appended", "updated_range": res.get("updates", {}).get("updatedRange")}


@registry.register(
    "sheets_update",
    "Overwrite cells in a Google Sheet starting at a range.",
    {
        "type": "object",
        "properties": {
            "spreadsheet": {"type": "string", "description": "Spreadsheet id or URL."},
            "range": {"type": "string", "description": "A1 range like 'Sheet1!B2'."},
            "rows": ROWS,
        },
        "required": ["spreadsheet", "range", "rows"],
    },
)
async def sheets_update(spreadsheet: str, range: str, rows: list[list]) -> dict:  # noqa: A002
    sid = file_id(spreadsheet)
    res = await google.request(
        "PUT",
        f"{API}/{sid}/values/{quote(range, safe='')}",
        params={"valueInputOption": "USER_ENTERED"},
        json={"values": rows},
    )
    return {"status": "updated", "updated_range": res.get("updatedRange")}
