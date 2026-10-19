"""Bloc 3B, point 5 — the Origin check covers every write route of the product.

Bloc 3A checked the Origin on the relayed writes of PGDR's page only; the
product's other writes relied on the CSRF token alone. Now every write
(POST, PUT, PATCH, DELETE) -- sign-in included, which has no CSRF token --
is refused when the browser says it comes from elsewhere: an Origin that is
not the product's (PI_PUBLIC_ORIGIN, else the scheme and Host this server
sees), or a Sec-Fetch-Site other than same-origin. Browsers send Origin on
every such fetch; a client that sends none (operator tools, tests) still
needs the session's CSRF token, as before. The relay keeps its stricter rule
(Origin required). The routes are taken from the application itself, so a
write route added later is covered by this test.
"""
from __future__ import annotations

import re
import uuid

import pytest
from fastapi.routing import APIRoute

from tests.auth_support import CSRF_HEADER, log_in, new_account
from tests.test_notice_parcours import app, case, pgdr, user, user_a, vir_store  # noqa: F401  (fixtures)

WRITES = {"POST", "PUT", "PATCH", "DELETE"}
FOREIGN = [{"Origin": "https://evil.test"}, {"Origin": "null"}, {"Origin": "http://api.test:8443"},
           {"Origin": "http://api.test", "Sec-Fetch-Site": "cross-site"},
           {"Origin": "http://api.test", "Sec-Fetch-Site": "same-site"}]


def write_routes(application) -> list[tuple[str, str]]:
    """(method, path) of every write route, through included routers (no prefix is used by PI's includes)."""
    found = []

    def walk(routes):
        for route in routes:
            if isinstance(route, APIRoute):
                found.extend((m, route.path) for m in sorted(route.methods & WRITES))
            elif hasattr(route, "original_router"):        # FastAPI's included router (recent versions)
                walk(route.original_router.routes)
    walk(application.routes)
    return found


def concrete(path: str) -> str:
    def value(m):
        name = m.group(1).split(":")[0]
        if name == "pid":
            return "V1-" + uuid.uuid4().hex
        if name == "sub_path":
            return "/return"
        if name == "field_path":
            return "driven_wheels"
        return str(uuid.uuid4())
    return re.sub(r"\{([^}]+)\}", value, path)


async def test_every_write_route_refuses_a_foreign_origin(app, user_a):
    routes = write_routes(app)
    assert ("POST", "/auth/login") in routes and ("DELETE", "/cases/{case_id}/vir/confirmations/{field_path}") in routes
    assert len(routes) >= 15, routes
    for method, path in routes:
        for headers in FOREIGN:
            r = await user_a.request(method, concrete(path), json={}, headers=headers)
            assert r.status_code == 403, (method, path, headers, r.status_code, r.text)
            assert r.json().get("error_category") == "CSRF_REJECTED", (method, path, r.text)


async def test_a_foreign_origin_changes_nothing(app, user_a):
    case_id = await case(user_a)
    vehicles = await user_a.post("/vehicles", headers={"Origin": "https://evil.test"},
                                 json={"contact_idempotency_key": "c-" + uuid.uuid4().hex[:8],
                                       "asset_idempotency_key": "a-" + uuid.uuid4().hex[:8]})
    assert vehicles.status_code == 403
    before = (await user_a.get(f"/cases/{case_id}")).json()
    r = await user_a.post(f"/cases/{case_id}/vir/confirmations", headers={"Origin": "https://evil.test"},
                          json={"field_path": "driven_wheels", "value": "front_wheel_drive"})
    assert r.status_code == 403
    assert (await user_a.get(f"/cases/{case_id}")).json() == before
    assert (await user_a.get("/me")).status_code == 200          # reads are not concerned


async def test_sign_in_from_a_foreign_origin_opens_no_session(app):
    from httpx import ASGITransport, AsyncClient
    login, password = new_account("orig")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api.test") as c:
        r = await c.post("/auth/login", json={"login": login, "password": password},
                         headers={"Origin": "https://evil.test"})
        assert r.status_code == 403 and "pi_session" not in r.headers.get("set-cookie", "")
        # The same sign-in from the product, or from a client without Origin, works.
        ok = await c.post("/auth/login", json={"login": login, "password": password}, headers={"Origin": "http://api.test"})
        assert ok.status_code == 200
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api.test") as c:
        assert (await log_in(c, login, password))["csrf_token"]


async def test_same_origin_and_originless_writes_still_need_the_csrf_token(app, user_a):
    body = {"contact_idempotency_key": "c-" + uuid.uuid4().hex[:8], "asset_idempotency_key": "a-" + uuid.uuid4().hex[:8]}
    same = await user_a.post("/vehicles", json=body, headers={"Origin": "http://api.test", "Sec-Fetch-Site": "same-origin"})
    assert same.status_code == 201
    token = user_a.headers.pop(CSRF_HEADER)
    try:
        for headers in ({"Origin": "http://api.test"}, {}):
            r = await user_a.post("/vehicles", json=body, headers=headers)
            assert r.status_code == 403 and r.json()["error_category"] == "CSRF_REJECTED"
    finally:
        user_a.headers[CSRF_HEADER] = token


async def test_configured_public_origin_is_the_only_one_accepted(app, user_a, monkeypatch):
    monkeypatch.setenv("PI_PUBLIC_ORIGIN", "https://produit.example")
    body = {"contact_idempotency_key": "c-" + uuid.uuid4().hex[:8], "asset_idempotency_key": "a-" + uuid.uuid4().hex[:8]}
    assert (await user_a.post("/vehicles", json=body, headers={"Origin": "http://api.test"})).status_code == 403
    assert (await user_a.post("/vehicles", json=body, headers={"Origin": "https://produit.example"})).status_code == 201


pytestmark = pytest.mark.asyncio
