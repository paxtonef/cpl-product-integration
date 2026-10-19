"""Test support for PI end-user authentication: fictitious accounts created
through the real account primitive, and clients carrying a real session
cookie plus its CSRF header (obtained from POST /auth/login, never forged).
"""
from __future__ import annotations

import secrets
import uuid
from http.cookies import SimpleCookie

import httpx

from product_integration.auth import accounts

SESSION_COOKIE = "pi_session"
CSRF_HEADER = "X-CSRF-Token"


def new_account(prefix: str = "user") -> tuple[str, str]:
    """Creates a fictitious account; returns (login, password)."""
    login = f"{prefix}-{uuid.uuid4().hex[:10]}"
    password = "fictive-" + secrets.token_urlsafe(12)
    accounts.create_account(login, password, display_name=f"Fictive {prefix}")
    return login, password


def session_cookie(response: httpx.Response) -> str | None:
    for header in response.headers.get_list("set-cookie"):
        cookie = SimpleCookie()
        cookie.load(header)
        if SESSION_COOKIE in cookie and cookie[SESSION_COOKIE].value:
            return cookie[SESSION_COOKIE].value
    return None


def _apply(client, response) -> dict:
    assert response.status_code == 200, response.text
    token = session_cookie(response)
    assert token, "login must set the session cookie"
    # The cookie is Secure; the test transports are plain http, so it is
    # carried explicitly, exactly as a browser would send it back.
    client.headers["Cookie"] = f"{SESSION_COOKIE}={token}"
    client.headers[CSRF_HEADER] = response.json()["csrf_token"]
    return response.json()


async def log_in(client: httpx.AsyncClient, login: str, password: str) -> dict:
    return _apply(client, await client.post("/auth/login", json={"login": login, "password": password}))


def log_in_sync(client: httpx.Client, login: str, password: str) -> dict:
    return _apply(client, client.post("/auth/login", json={"login": login, "password": password}))


_live_headers: dict[str, dict[str, str]] = {}


def live_client(base_url: str, timeout: float = 30) -> httpx.Client:
    """A client of a running PI-05 process (same database), logged in as one
    fictitious account per base URL for the whole test run, so that objects
    created through one client stay reachable through the next."""
    if base_url not in _live_headers:
        with httpx.Client(base_url=base_url, timeout=timeout) as client:
            log_in_sync(client, *new_account("live"))
            _live_headers[base_url] = {k: client.headers[k] for k in ("Cookie", CSRF_HEADER)}
    return httpx.Client(base_url=base_url, timeout=timeout, headers=_live_headers[base_url])


TINY_JPEG = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffdb004300" + "10" * 61 + "ffd9")


def upload_media(client: httpx.Client) -> str:
    """Media references are accepted only for media the user uploaded."""
    r = client.post("/media", files={"file": ("dashboard.jpg", TINY_JPEG, "image/jpeg")})
    assert r.status_code == 201, r.text
    return r.json()["media_id"]
