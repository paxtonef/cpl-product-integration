"""PI-05 — FastAPI application factory (§7)."""
from __future__ import annotations

from fastapi import FastAPI

from product_integration.api.errors import ProductAPIError, product_api_error_handler
from product_integration.api.routes import router


def create_app() -> FastAPI:
    app = FastAPI(title="CPL Product Integration API", version="0.1.0")
    app.include_router(router)
    app.add_exception_handler(ProductAPIError, product_api_error_handler)
    return app


# Canonical app object (repository convention: a module-level `app` for
# ASGI servers/tests to import directly, alongside the factory for tests
# that want a fresh instance per test).
app = create_app()
