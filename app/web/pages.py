"""Two public pages Google requires before an OAuth app can go "In production":
a home page and a privacy policy. Neither page exposes any data.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.config import get_settings

router = APIRouter()

_STYLE = """
<style>
  :root { color-scheme: light dark; }
  body { font: 16px/1.6 system-ui, sans-serif; max-width: 680px; margin: 48px auto; padding: 0 16px; }
  h1 { font-size: 28px; margin-bottom: 4px; }
  .muted { opacity: .7; }
</style>
"""


def _page(title: str, body: str) -> HTMLResponse:
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>{_STYLE}</head><body>{body}</body></html>"""
    return HTMLResponse(html)


@router.get("/", include_in_schema=False)
async def home() -> HTMLResponse:
    name = get_settings().assistant_name
    return _page(
        f"{name}: personal assistant",
        f"""<h1>{name}</h1>
<p class="muted">A private AI assistant for one person.</p>
<p>{name} lives in Telegram and helps its owner with email, calendar, notes and
documents. It is not a public service: it only answers its owner, and there is
nothing to sign up for.</p>
<p><a href="/privacy">Privacy policy</a></p>""",
    )


@router.get("/privacy", include_in_schema=False)
async def privacy() -> HTMLResponse:
    name = get_settings().assistant_name
    return _page(
        f"{name}: privacy policy",
        f"""<h1>Privacy policy</h1>
<p class="muted">Last updated: October 2026</p>
<p>{name} is a personal assistant used by a single person, its owner. It is not
offered to the public.</p>
<h2>What data it accesses</h2>
<p>With the owner's permission, {name} reads and acts on the owner's own Google
data (Gmail, Calendar, Drive, Sheets, Forms, YouTube) and Notion pages, only to
carry out the owner's requests.</p>
<h2>How data is stored</h2>
<p>Conversation history and memories are stored in the owner's private database.
Google data is fetched on demand and is not sold, shared or used for advertising.
Data is only sent to the services needed to answer a request (Google Gemini for
language processing).</p>
<h2>Google user data</h2>
<p>{name}'s use of information received from Google APIs adheres to the
<a href="https://developers.google.com/terms/api-services-user-data-policy">Google API
Services User Data Policy</a>, including the Limited Use requirements.</p>
<h2>Deleting data</h2>
<p>The owner can revoke access at any time at
<a href="https://myaccount.google.com/permissions">myaccount.google.com/permissions</a>
and delete the stored data from the database.</p>""",
    )
