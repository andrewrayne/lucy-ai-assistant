import base64
import email

from app.tools.calendar import event_time, parse_when
from app.tools.forms import question_item
from app.tools.gmail import build_message, extract_body
from app.tools.notion import markdown_to_blocks, notion_id, property_value
from app.tools.sheets import file_id


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def test_gmail_reply_message_has_threading_headers():
    raw = build_message("anna@example.com", "Re: Trip", "See you!", in_reply_to="<abc@mail>")
    msg = email.message_from_bytes(base64.urlsafe_b64decode(raw))
    assert msg["To"] == "anna@example.com" and msg["In-Reply-To"] == "<abc@mail>"
    assert "See you!" in msg.get_payload()


def test_gmail_body_prefers_plain_text_and_lists_attachments():
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {"mimeType": "text/html", "body": {"data": b64("<p>Hi <b>there</b></p>")}},
            {"mimeType": "text/plain", "body": {"data": b64("Hi there")}},
            {"mimeType": "application/pdf", "filename": "invoice.pdf", "body": {}},
        ],
    }
    assert extract_body(payload) == ("Hi there", ["invoice.pdf"])
    html_only = {"mimeType": "text/html", "body": {"data": b64("<p>Hello</p><br>World")}}
    assert extract_body(html_only)[0] == "Hello\n\nWorld"


def test_calendar_times_use_owner_timezone():
    assert parse_when("2026-10-24T15:00").isoformat() == "2026-10-24T15:00:00+01:00"
    assert event_time("2026-10-24", all_day=True) == {"date": "2026-10-24"}
    assert event_time("2026-10-24T15:00", all_day=False)["timeZone"] == "Europe/Lisbon"


def test_ids_from_urls():
    assert file_id("https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz123/edit#gid=0") == "1AbCdEfGhIjKlMnOpQrStUvWxYz123"
    assert notion_id("https://www.notion.so/Ideas-0123456789abcdef0123456789abcdef?pvs=4") == "0123456789abcdef0123456789abcdef"


def test_forms_question_types():
    item = question_item({"title": "Rate us", "type": "scale", "max": 10}, 0)["createItem"]["item"]
    assert item["questionItem"]["question"]["scaleQuestion"] == {"low": 1, "high": 10}
    choice = question_item({"title": "Pick", "type": "checkbox", "options": ["A", "B"]}, 1)["createItem"]
    assert choice["item"]["questionItem"]["question"]["choiceQuestion"]["type"] == "CHECKBOX"


def test_notion_markdown_and_properties():
    blocks = markdown_to_blocks("# Plan\n- [ ] Film intro\n- Edit **fast**\n1. Upload")
    assert [b["type"] for b in blocks] == ["heading_1", "to_do", "bulleted_list_item", "numbered_list_item"]
    assert blocks[2]["bulleted_list_item"]["rich_text"][1]["annotations"]["bold"] is True
    assert property_value("multi_select", "AI, Tutorial") == {"multi_select": [{"name": "AI"}, {"name": "Tutorial"}]}
    assert property_value("checkbox", "yes") == {"checkbox": True}
    assert property_value("people", "x") is None


def test_notion_read_property_values():
    from app.tools.notion import read_property

    assert read_property({"type": "title", "title": [{"plain_text": "Goal"}]}) == "Goal"
    assert read_property({"type": "status", "status": {"name": "Done"}}) == "Done"
    assert read_property({"type": "date", "date": {"start": "2026-11-01", "end": None}}) == "2026-11-01"
    assert read_property({"type": "multi_select", "multi_select": [{"name": "AI"}]}) == ["AI"]
