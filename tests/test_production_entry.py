"""Preparation for production, block 6 — the single public entry point.

One process serves the built frontend (no Vite dev server) and the PI-05
API under /api, with security headers, a public health check and nothing
else: no interactive API documentation, no file outside the build.
"""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

from product_integration.api.production import create_production_app

from tests.auth_support import log_in, new_account


@pytest.fixture
def dist(tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>app</title><div id=root></div>")
    (root / "assets" / "index-abc.js").write_text("console.log('app')")
    (tmp_path / "secret.txt").write_text("outside the build")
    return root


@pytest_asyncio.fixture
async def public(dist, monkeypatch):
    monkeypatch.delenv("PI_COOKIE_SECURE", raising=False)
    app = create_production_app(frontend_dist=str(dist))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://app.test") as client:
        yield client


class TestProductionEntry:

    async def test_frontend_is_served_with_spa_fallback(self, public):
        r = await public.get("/")
        assert r.status_code == 200 and "<div id=root>" in r.text
        r = await public.get("/cases/1234/history")  # a client-side route after a reload
        assert r.status_code == 200 and "<div id=root>" in r.text
        r = await public.get("/assets/index-abc.js")
        assert r.status_code == 200 and "console.log" in r.text

    async def test_missing_asset_is_a_404_not_the_page(self, public):
        assert (await public.get("/assets/missing.js")).status_code == 404

    async def test_nothing_outside_the_build(self, public):
        for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt"):
            r = await public.get(path)
            assert "outside the build" not in r.text

    async def test_api_is_under_api_and_requires_a_session(self, public):
        assert (await public.get("/api/cases")).status_code == 401
        async with httpx.AsyncClient(transport=public._transport, base_url="https://app.test/api") as api:
            await log_in(api, *new_account("prod"))
            assert (await api.get("/cases")).status_code == 200

    async def test_no_interactive_api_documentation(self, public):
        for path in ("/api/docs", "/api/redoc", "/api/openapi.json", "/openapi.json"):
            r = await public.get(path)
            assert "swagger" not in r.text.lower() and '"openapi"' not in r.text

    async def test_public_health_check_reveals_nothing(self, public):
        r = await public.get("/health")
        assert r.status_code == 200 and r.json() == {"status": "ok"}

    async def test_security_headers(self, public):
        r = await public.get("/")
        h = r.headers
        assert "default-src 'self'" in h["content-security-policy"]
        assert "frame-ancestors 'none'" in h["content-security-policy"]
        assert h["x-content-type-options"] == "nosniff"
        assert h["x-frame-options"] == "DENY"
        assert h["referrer-policy"] == "no-referrer"
        assert "max-age=" in h["strict-transport-security"]
        assert (await public.get("/api/cases")).headers["x-frame-options"] == "DENY"

    def test_refuses_to_start_without_secure_cookies(self, dist, monkeypatch):
        monkeypatch.setenv("PI_COOKIE_SECURE", "0")
        with pytest.raises(RuntimeError):
            create_production_app(frontend_dist=str(dist))

    def test_refuses_to_start_without_a_built_frontend(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PI_COOKIE_SECURE", raising=False)
        with pytest.raises(RuntimeError):
            create_production_app(frontend_dist=str(tmp_path / "nowhere"))


async def test_development_app_keeps_a_health_check():
    from product_integration.api.app import create_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://api.test") as client:
        r = await client.get("/health")
        assert r.status_code == 200 and r.json() == {"status": "ok"}
