"""Editing existing Notion pages through the API (no clicking on the Mac)."""

import asyncio
import re

from app.live.call import ACTION_TOOLS
from app.tools import notion

TIMECODE = r"\s*\(?\d{1,2}:\d{2}(?:\s*[–-]\s*\d{1,2}:\d{2})?\)?"


def run(text: str, bold: bool = False) -> dict:
    return {"type": "text", "text": {"content": text, "link": None}, "annotations": {"bold": bold}}


def block(bid: str, text: str, kind: str = "heading_2", children: bool = False) -> dict:
    return {"id": bid, "type": kind, "has_children": children, kind: {"rich_text": [run(text)]}}


def test_edit_rich_text_keeps_formatting_and_trims():
    rich = [run("Intro ", bold=True), run("(4:30–7:00)")]
    out = notion.edit_rich_text(rich, re.compile(TIMECODE), "")
    assert out == [run("Intro", bold=True)]


def test_edit_rich_text_returns_none_without_match():
    assert notion.edit_rich_text([run("No time here")], re.compile(TIMECODE), "") is None


def test_replace_text_walks_pages_and_children(monkeypatch):
    pages = {
        "/blocks/p/children?page_size=100": {
            "results": [block("a", "Chapter 1 (0:00–4:30)"), block("t", "Toggle", "toggle", children=True)],
            "has_more": True,
            "next_cursor": "c2",
        },
        "/blocks/p/children?page_size=100&start_cursor=c2": {
            "results": [block("b", "Plain line", "paragraph")],
            "has_more": False,
        },
        "/blocks/t/children?page_size=100": {"results": [block("n", "Inside 12:05", "paragraph")], "has_more": False},
    }
    patched = {}

    async def fake(method, path, body=None):
        if method == "GET":
            return pages[path]
        patched[path] = body
        return {}

    monkeypatch.setattr(notion, "notion", fake)
    monkeypatch.setattr(notion, "notion_id", lambda v: v)
    result = asyncio.run(notion.notion_replace_text("p", TIMECODE, regex=True))
    assert result["changed_blocks"] == 2 and result["saved"]
    assert patched["/blocks/a"]["heading_2"]["rich_text"][0]["text"]["content"] == "Chapter 1"
    assert patched["/blocks/n"]["paragraph"]["rich_text"][0]["text"]["content"] == "Inside"

    patched.clear()
    preview = asyncio.run(notion.notion_replace_text("p", TIMECODE, regex=True, preview=True))
    assert preview["changed_blocks"] == 2 and not preview["saved"] and not patched


def test_delete_blocks(monkeypatch):
    calls = []

    async def fake(method, path, body=None):
        if method == "GET":
            return {"results": [block("a", "keep"), block("b", "remove me")], "has_more": False}
        calls.append((method, path))
        return {}

    monkeypatch.setattr(notion, "notion", fake)
    monkeypatch.setattr(notion, "notion_id", lambda v: v)
    result = asyncio.run(notion.notion_delete_blocks("p", "remove"))
    assert result["deleted"] == 1 and calls == [("DELETE", "/blocks/b")]


def test_edit_tools_are_silent_actions_on_the_mac():
    assert {"notion_replace_text", "notion_delete_blocks", "notion_append_to_page"} <= ACTION_TOOLS


def test_unmatched_text_is_left_alone():
    assert notion.edit_rich_text([run("two  spaces")], re.compile(TIMECODE), "") is None
