"""PI-05 — FastAPI application factory (§7)."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db.engine import engine

from product_integration.api.errors import ProductAPIError, product_api_error_handler
from product_integration.api.auth_routes import router as auth_router
from product_integration.api.routes import router
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


def create_app(*, public_docs: bool = True) -> FastAPI:
    docs = {} if public_docs else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    app = FastAPI(title="CPL Product Integration API", version="0.1.0", **docs)
    app.add_api_route("/health", health_route, methods=["GET"])
    app.include_router(auth_router)
    app.include_router(router)
    app.include_router(notice_router)
    app.include_router(notice_relay_router)
    app.add_exception_handler(ProductAPIError, product_api_error_handler)
    return app


# Canonical app object (repository convention: a module-level `app` for
# ASGI servers/tests to import directly, alongside the factory for tests
# that want a fresh instance per test).
app = create_app()
