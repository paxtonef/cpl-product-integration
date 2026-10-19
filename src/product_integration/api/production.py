"""The single public entry point (preparation for production, block 6).

One process serves the built frontend (``vite build`` output, no Vite dev
server) at ``/`` and the PI-05 API at ``/api``, adds security headers, and
exposes ``/health``. VIR, PGDR and PostgreSQL stay on the loopback, reached
only by this process. TLS is terminated by uvicorn itself
(``--ssl-certfile/--ssl-keyfile``) or by a TLS proxy in front of it; the
session cookie is always ``Secure`` here.

  uvicorn --factory product_integration.api.production:create_production_app \\
      --host 0.0.0.0 --port 443 --ssl-certfile … --ssl-keyfile … --workers 1 \\
      --no-access-log --no-proxy-headers

``--no-access-log``: uvicorn's access log would write request paths and
queries (identifiers); api.access_log writes route templates instead.
``--no-proxy-headers`` unless a TLS proxy is in front, and then
``--proxy-headers --forwarded-allow-ips <that proxy only>``: X-Forwarded-*
is believed from configured proxies only (client address for throttling,
scheme for the origin check). PI_LOGIN_THROTTLE_SECRET is required.

``--workers 1`` is required: PGDR's diagnostic sessions live in this
process's memory (PI-05 registry) and are lost on restart.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.staticfiles import StaticFiles

from product_integration.api.access_log import AccessLogMiddleware
from product_integration.api.app import create_app, health_route
from product_integration.auth import accounts

_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=31536000",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


class _SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response


class _SinglePageApp(StaticFiles):
    """Files of the build only; a path without a file extension (a
    client-side route, e.g. /cases/<id> after a reload) gets index.html. A
    missing asset stays a 404."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or "." in Path(path).name:
                raise
            return await super().get_response("index.html", scope)


def create_production_app(frontend_dist: Optional[str] = None) -> FastAPI:
    if os.environ.get("PI_COOKIE_SECURE", "1") == "0":
        raise RuntimeError("PI_COOKIE_SECURE=0 is for local plain-http tests only; production cookies are Secure")
    try:
        accounts.throttle_secrets()
    except accounts.ThrottleSecretMissing as exc:
        raise RuntimeError(str(exc)) from None
    dist = Path(frontend_dist or os.environ.get("PI_FRONTEND_DIST", "")).resolve()
    if not (dist / "index.html").is_file():
        raise RuntimeError(f"built frontend not found (index.html) in PI_FRONTEND_DIST={dist}")

    app = FastAPI(title="CPL product", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(AccessLogMiddleware)   # inside the security headers: a 500 it writes gets them too
    app.add_middleware(_SecurityHeaders)
    app.add_api_route("/health", health_route, methods=["GET"])
    app.mount("/api", create_app(public_docs=False, access_log=False))
    app.mount("/", _SinglePageApp(directory=str(dist), html=True), name="frontend")
    return app
