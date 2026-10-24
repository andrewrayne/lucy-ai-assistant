"""Minimal async Google API client using the owner's OAuth refresh token."""

import asyncio
import time

import httpx

from app.config import get_settings

TOKEN_URL = "https://oauth2.googleapis.com/token"


class GoogleError(Exception):
    pass


class GoogleClient:
    def __init__(self) -> None:
        self._token = ""
        self._expires = 0.0
        self._lock = asyncio.Lock()
        self._http = httpx.AsyncClient(timeout=120)

    async def _access_token(self) -> str:
        async with self._lock:
            if self._token and time.monotonic() < self._expires - 60:
                return self._token
            s = get_settings()
            if not s.google_refresh_token:
                raise GoogleError("Google isn't connected yet (GOOGLE_REFRESH_TOKEN is missing).")
            resp = await self._http.post(
                TOKEN_URL,
                data={
                    "client_id": s.google_client_id,
                    "client_secret": s.google_client_secret,
                    "refresh_token": s.google_refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            if resp.status_code != 200:
                raise GoogleError(f"Google sign-in failed ({resp.status_code}): {resp.text[:200]}")
            data = resp.json()
            self._token = data["access_token"]
            self._expires = time.monotonic() + data.get("expires_in", 3600)
            return self._token

    async def request(self, method: str, url: str, *, raw: bool = False, binary: bool = False, **kwargs):
        """Call a Google API. Returns parsed JSON, text (raw=True) or bytes (binary=True)."""
        headers = {"Authorization": f"Bearer {await self._access_token()}", **kwargs.pop("headers", {})}
        resp = await self._http.request(method, url, headers=headers, **kwargs)
        if resp.status_code >= 400:
            try:
                message = resp.json()["error"]["message"]
            except Exception:
                message = resp.text[:300]
            raise GoogleError(f"Google API error {resp.status_code}: {message}")
        if binary:
            return resp.content
        if raw:
            return resp.text
        return resp.json() if resp.content else {}

    async def get(self, url: str, **kwargs):
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs):
        return await self.request("POST", url, **kwargs)


google = GoogleClient()
