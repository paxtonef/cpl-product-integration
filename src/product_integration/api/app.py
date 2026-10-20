"""PI-05 — FastAPI application factory (§7)."""
from __future__ import annotations

import os
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db.engine import engine

from product_integration.api.access_log import AccessLogMiddleware
from product_integration.api.errors import ProductAPIError, product_api_error_handler
from product_integration.api.auth_routes import router as auth_router
from product_integration.api.routes import legacy_dialogue_router, router
from product_integration.api.parcours_routes import relay_router as notice_relay_router
from product_integration.api.parcours_routes import router as notice_router


def health_route() -> JSONResponse:
    """Public readiness check: the process answers and its database is
    reachable. Says nothing else."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 -- any failure simply means "not ready"
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ok"})


LEGACY_DIALOGUE_ENV = "PI_DIALOGUE_HISTORIQUE"


def create_app(*, public_docs: bool = True, access_log: bool = True, legacy_dialogue: Optional[bool] = None) -> FastAPI:
    """`access_log`: one line per request with its route template (api.access_log); the production entry logs
    at its own level instead. `legacy_dialogue`: the legacy PGDR dialogue routes (routes.legacy_dialogue_router),
    absent unless asked for (default: PI_DIALOGUE_HISTORIQUE=1); the production entry never includes them."""
    if legacy_dialogue is None:
        legacy_dialogue = os.environ.get(LEGACY_DIALOGUE_ENV) == "1"
    docs = {} if public_docs else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    app = FastAPI(title="CPL Product Integration API", version="0.1.0", **docs)
    if access_log:
        app.add_middleware(AccessLogMiddleware)
    app.add_api_route("/health", health_route, methods=["GET"])
    app.include_router(auth_router)
    app.include_router(router)
    if legacy_dialogue:
        app.include_router(legacy_dialogue_router)
    app.include_router(notice_router)
    app.include_router(notice_relay_router)
    app.add_exception_handler(ProductAPIError, product_api_error_handler)
    return app


# Canonical app object (repository convention: a module-level `app` for
# ASGI servers/tests to import directly, alongside the factory for tests
# that want a fresh instance per test).
app = create_app()
