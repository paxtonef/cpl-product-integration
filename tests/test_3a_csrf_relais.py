"""Bloc 3A, point 4 — PI's own CSRF token protects the relayed PGDR parcours.

PI places the session's CSRF token in the page it relays
(``<meta name="csrf-token">``; the page sends it as X-CSRF-Token, PGDR
48d5da4). Every relayed write must carry: the session cookie, that token
(compared with the session's own), an Origin equal to the product's origin
(PI_PUBLIC_ORIGIN, or the scheme and Host the server itself sees -- uvicorn
takes X-Forwarded-* only from proxies it is configured to trust),
Sec-Fetch-Site same-origin when the browser sends it, and a JSON body; the
parcours owner is checked on every request. SameSite or Sec-Fetch-Site alone
are not relied on. No service token ever reaches the browser; the page's
CSP is unchanged.
"""
from __future__ import annotations

import re

import httpx
import pytest

from tests.auth_support import CSRF_HEADER, log_in, new_account
from tests.test_notice_parcours import (  # noqa: F401  (fixtures)
    TOKEN, UNKNOWN, app, case, open_parcours, pgdr, user_a, user_b, vir_store,
)

ORIGIN = "http://api.test"


def browser(client: httpx.AsyncClient, *, token: str | None = "own", origin: str | None = ORIGIN,
            extra: dict | None = None) -> httpx.AsyncClient:
    headers = {"Cookie": client.headers["Cookie"]}
    if token == "own":
        token = client.headers[CSRF_HEADER]
    if token is not None:
        headers[CSRF_HEADER] = token
    if origin is not None:
        headers["Origin"] = origin
    headers.update(extra or {})
    return httpx.AsyncClient(transport=client._transport, base_url="http://api.test", headers=headers)


async def opened(client) -> str:
    r = await open_parcours(client, await case(client))
    assert r["status"] == "opened", r
    return r["page"].split("p=", 1)[1]


async def phase(client, pid) -> str:
    async with browser(client) as b:
        return (await b.get(f"/v1/parcours/{pid}")).json()["phase"]


async def test_page_carries_the_sessions_token_and_keeps_its_csp(app, pgdr, user_a, user_b):
    pid = await opened(user_a)
    async with browser(user_a, token=None, origin=None) as b:
        page = await b.get("/v1", params={"p": pid})
    assert page.status_code == 200
    metas = re.findall(r'<meta name="csrf-token" content="([0-9a-f]+)">', page.text)
    assert metas == [user_a.headers[CSRF_HEADER]] and user_b.headers[CSRF_HEADER] not in page.text
    csp = page.headers["content-security-policy"]
    script_src = csp.split("script-src ", 1)[1].split(";")[0]
    assert re.fullmatch(r"('sha256-[A-Za-z0-9+/=]+' ?)+", script_src)
    assert "default-src 'none'" in csp and "form-action 'none'" in csp and "connect-src 'self'" in csp
    assert TOKEN not in page.text and page.headers["cache-control"] == "no-store"


async def test_legitimate_write_with_token_and_origin(app, pgdr, user_a):
    pid = await opened(user_a)
    async with browser(user_a, extra={"Sec-Fetch-Site": "same-origin"}) as b:
        r = await b.post(f"/v1/parcours/{pid}/vir-seen", json={})
    assert r.status_code == 200 and r.json()["phase"] == "consent"


@pytest.mark.parametrize("token", [None, "", "0" * 64, "not-a-token"])
async def test_missing_or_false_token_is_refused(app, pgdr, user_a, token):
    pid = await opened(user_a)
    async with browser(user_a, token=token) as b:
        r = await b.post(f"/v1/parcours/{pid}/vir-seen", json={})
    assert (r.status_code, r.json()["error_category"]) == (403, "CSRF_REJECTED")
    assert await phase(user_a, pid) == "vir"


async def test_token_of_another_session_is_refused(app, pgdr, user_a, user_b):
    pid = await opened(user_a)
    async with browser(user_a, token=user_b.headers[CSRF_HEADER]) as b:
        r = await b.post(f"/v1/parcours/{pid}/vir-seen", json={})
    assert (r.status_code, r.json()["error_category"]) == (403, "CSRF_REJECTED")
    assert await phase(user_a, pid) == "vir"


@pytest.mark.parametrize("origin,fetch_site", [
    ("http://evil.test", None),               # cross-origin
    ("http://evil.test", "cross-site"),
    ("http://other.api.test", "same-site"),    # same site, another origin
    ("http://other.api.test", None),
    ("https://api.test", None),                # another scheme
    ("http://api.test:8443", None),            # another port
    ("null", None),                            # opaque origin (sandbox, file)
    (None, None),                              # no Origin at all
    (ORIGIN, "cross-site"),                    # browser says cross-site
])
async def test_other_origins_are_refused_even_with_the_token(app, pgdr, user_a, origin, fetch_site):
    pid = await opened(user_a)
    extra = {"Sec-Fetch-Site": fetch_site} if fetch_site else {}
    async with browser(user_a, origin=origin, extra=extra) as b:
        r = await b.post(f"/v1/parcours/{pid}/vir-seen", json={})
    assert (r.status_code, r.json()["error_category"]) == (403, "CSRF_REJECTED")
    assert await phase(user_a, pid) == "vir"


async def test_forwarded_headers_from_the_client_are_not_believed(app, pgdr, user_a):
    pid = await opened(user_a)
    extra = {"X-Forwarded-Host": "evil.test", "X-Forwarded-Proto": "https", "Forwarded": "host=evil.test;proto=https"}
    for origin in ("http://evil.test", "https://evil.test", "https://api.test"):
        async with browser(user_a, origin=origin, extra=extra) as b:
            assert (await b.post(f"/v1/parcours/{pid}/vir-seen", json={})).status_code == 403
    assert await phase(user_a, pid) == "vir"


async def test_configured_public_origin_is_the_only_one(app, pgdr, user_a, monkeypatch):
    pid = await opened(user_a)
    monkeypatch.setenv("PI_PUBLIC_ORIGIN", "https://produit.example")
    async with browser(user_a) as b:            # the Host-derived origin is no longer enough
        assert (await b.post(f"/v1/parcours/{pid}/vir-seen", json={})).status_code == 403
    async with browser(user_a, origin="https://produit.example") as b:
        assert (await b.post(f"/v1/parcours/{pid}/vir-seen", json={})).status_code == 200


async def test_simple_form_and_unexpected_types_are_refused(app, pgdr, user_a):
    pid = await opened(user_a)
    async with browser(user_a, token=None) as b:      # what a cross-site HTML form can send
        r = await b.post(f"/v1/parcours/{pid}/vir-seen", content=b"x=1",
                         headers={"Content-Type": "application/x-www-form-urlencoded"})
        assert r.status_code in (403, 415)
    async with browser(user_a) as b:
        for ctype in ("application/x-www-form-urlencoded", "multipart/form-data; boundary=x", "text/plain", ""):
            r = await b.post(f"/v1/parcours/{pid}/vir-seen", content=b"{}", headers={"Content-Type": ctype})
            assert r.status_code == 415, ctype
        for method in ("PUT", "PATCH", "DELETE"):
            assert (await b.request(method, f"/v1/parcours/{pid}/vir-seen", json={})).status_code == 405
    assert await phase(user_a, pid) == "vir"


async def test_another_accounts_parcours_with_a_valid_token_is_unknown(app, pgdr, user_a, user_b):
    pid = await opened(user_a)
    async with browser(user_b) as b:
        r = await b.post(f"/v1/parcours/{pid}/vir-seen", json={})
        assert (r.status_code, r.json()) == (404, UNKNOWN)
        assert (await b.get(f"/v1/parcours/{pid}")).status_code == 404
        page = await b.get("/v1", params={"p": pid})
        assert user_a.headers[CSRF_HEADER] not in page.text
    assert await phase(user_a, pid) == "vir"


async def test_legitimate_parcours_under_the_https_production_entry(monkeypatch, app, pgdr, tmp_path):
    from starlette.routing import Mount
    from product_integration.api.production import create_production_app
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><div id=root></div>")
    monkeypatch.delenv("PI_COOKIE_SECURE", raising=False)
    public = create_production_app(frontend_dist=str(dist))
    inner = next(r.app for r in public.routes if isinstance(r, Mount) and r.path == "/api")
    inner.dependency_overrides.update(app.dependency_overrides)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=public), base_url="https://app.test/api") as api:
        await log_in(api, *new_account("csrfprod"))
        r = await api.post("/vehicles", json={"contact_idempotency_key": "c-" + TOKEN[-8:] + "p",
                                              "asset_idempotency_key": "a-" + TOKEN[-8:] + "p"})
        v = r.json()
        r = await api.post("/cases", json={"contact_id": v["contact_id"], "asset_id": v["asset_id"],
                                           "request_id": "vir-csrfprod", "registration_country_code": "FR",
                                           "consent": {"external_lookup_allowed": True}, "vin": "VF3XXXXXXXXXXXXXX",
                                           "case_idempotency_key": "case-csrfprod-" + TOKEN[-8:]})
        opened_ = (await api.post(f"/cases/{r.json()['case_id']}/notice-parcours")).json()
        page = await api.get(opened_["page"])
        token = re.search(r'<meta name="csrf-token" content="([0-9a-f]+)">', page.text).group(1)
        pid = opened_["page"].split("p=", 1)[1]
        as_page = {"Cookie": api.headers["Cookie"], CSRF_HEADER: token, "Origin": "https://app.test",
                   "Sec-Fetch-Site": "same-origin"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=public), base_url="https://app.test/api",
                                     headers=as_page) as b:
            assert (await b.post(f"/v1/parcours/{pid}/vir-seen", json={})).json()["phase"] == "consent"
            assert (await b.post(f"/v1/parcours/{pid}/consent", json={"accepted": True})).json()["consent"] is True
            s = (await b.post(f"/v1/parcours/{pid}/selection", json={"entry_ids": ["fn_green_lamps"]})).json()
            assert s["phase"] == "confirmation"
            out = (await b.post(f"/v1/parcours/{pid}/confirm",
                                json={"entry_ids": ["fn_green_lamps"], "confirmed": True})).json()
            assert out["phase"] == "restitution" and out["premier_constat"]
            # Same request without the token, or from the plain-http origin: refused.
            del b.headers[CSRF_HEADER]
            assert (await b.post(f"/v1/parcours/{pid}/return", json={})).status_code == 403
            b.headers[CSRF_HEADER] = token
            b.headers["Origin"] = "http://app.test"
            assert (await b.post(f"/v1/parcours/{pid}/return", json={})).status_code == 403
