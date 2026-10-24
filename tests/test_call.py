import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.live.auth import AuthError, make_call_link_token, verify_call_link_token, verify_init_data
from app.main import app

TOKEN = "123456:TEST-token"


def signed_init_data(user_id=111, auth_date=None, extra=None, bot_token=TOKEN):
    fields = {
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "AAH",
        "user": json.dumps({"id": user_id, "first_name": "Andrew"}),
        "signature": "abc",  # newer Telegram field: part of the signed data, like any other
        **(extra or {}),
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_genuine_init_data_from_owner_is_accepted():
    assert verify_init_data(signed_init_data(), TOKEN, 111)["id"] == 111


@pytest.mark.parametrize(
    "init_data",
    [
        signed_init_data(user_id=999),  # someone else
        signed_init_data(bot_token="999:OTHER"),  # signed for another bot
        signed_init_data(auth_date=int(time.time()) - 3 * 24 * 3600),  # too old
        signed_init_data().replace("Andrew", "Mallory"),  # tampered
        "user=%7B%22id%22%3A111%7D",  # no signature at all
    ],
)
def test_bad_init_data_is_refused(init_data):
    with pytest.raises(AuthError):
        verify_init_data(init_data, TOKEN, 111)


def test_browser_link_token():
    token = make_call_link_token()
    verify_call_link_token(token)
    with pytest.raises(AuthError):
        verify_call_link_token(token, now=time.time() + 11 * 60)  # expired after 10 minutes
    with pytest.raises(AuthError):
        verify_call_link_token(token[:-1] + ("0" if token[-1] != "0" else "1"))


def test_call_socket_refuses_strangers():
    client = TestClient(app)
    with client.websocket_connect("/ws/call") as ws:
        ws.send_text(json.dumps({"type": "auth", "init_data": signed_init_data(user_id=999)}))
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert closed.value.code == 4401


def test_call_page_and_link_endpoint():
    client = TestClient(app)
    assert "Call Lucy" in client.get("/call").text
    assert client.post("/api/call/link", json={"init_data": signed_init_data(user_id=999)}).status_code == 401
    ok = client.post("/api/call/link", json={"init_data": signed_init_data()})
    assert ok.status_code == 200 and "/call?t=" in ok.json()["url"]
