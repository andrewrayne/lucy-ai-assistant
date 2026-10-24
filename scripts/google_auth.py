"""Get a Google refresh token for the assistant (run once on your computer).

1. Needs GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET (a "Desktop app" OAuth client)
   in .env or the environment.
2. Prints a sign-in link. Open it, pick the Google account that owns your
   email, calendar and YouTube channel, and allow access.
3. Writes GOOGLE_REFRESH_TOKEN to .env. Copy it to Railway Variables.

    python scripts/google_auth.py
"""

import json
import os
import secrets
import sys
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"

# One consent for everything the assistant does with Google.
SCOPES = [
    "openid",
    "email",
    "https://www.googleapis.com/auth/gmail.modify",  # read, label, draft and send email
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/forms.body",
    "https://www.googleapis.com/auth/forms.responses.readonly",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",  # comments + captions of the owner's private videos
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def load_env() -> None:
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def save_to_env(key: str, value: str) -> None:
    lines = ENV.read_text().splitlines() if ENV.exists() else []
    lines = [line for line in lines if not line.startswith(f"{key}=")]
    lines.append(f"{key}={value}")
    ENV.write_text("\n".join(lines) + "\n")


def main() -> None:
    load_env()
    client_id, client_secret = os.environ.get("GOOGLE_CLIENT_ID"), os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        sys.exit("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET first.")

    state = secrets.token_urlsafe(16)
    result: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (http.server naming)
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if query.get("state", [""])[0] != state:
                self.send_response(400)
                self.end_headers()
                return
            result.update({k: v[0] for k, v in query.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h2>Done. You can close this tab.</h2>")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    redirect_uri = f"http://127.0.0.1:{server.server_port}/"
    login_hint = sys.argv[1] if len(sys.argv) > 1 else ""
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",  # we need a refresh token
            "prompt": "consent",  # always return a refresh token
            "state": state,
            **({"login_hint": login_hint} if login_hint else {}),
        }
    )
    print("Open this link and allow access:\n" + url, flush=True)

    while "code" not in result and "error" not in result:
        server.handle_request()
    if "error" in result:
        sys.exit(f"Google returned an error: {result['error']}")

    data = urllib.parse.urlencode(
        {
            "code": result["code"],
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", data=data, timeout=30) as resp:
        tokens = json.loads(resp.read())

    refresh = tokens.get("refresh_token")
    if not refresh:
        sys.exit("No refresh token returned. Remove the app at myaccount.google.com/permissions and retry.")
    save_to_env("GOOGLE_REFRESH_TOKEN", refresh)
    granted = sorted(s.rsplit("/", 1)[-1] for s in tokens.get("scope", "").split())
    print("Saved GOOGLE_REFRESH_TOKEN to .env. Granted scopes:", ", ".join(granted))


if __name__ == "__main__":
    main()
