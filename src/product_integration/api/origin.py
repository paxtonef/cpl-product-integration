"""The origin of a write request (bloc 3A for the relay; bloc 3B for every write).

A browser sends Origin on every POST, PUT, PATCH and DELETE fetch, and
Sec-Fetch-Site when it supports it. A write the browser says comes from
elsewhere -- an Origin other than the product's, or a Sec-Fetch-Site other
than same-origin -- is refused before anything else, sign-in included (it
has no CSRF token). The product's origin is PI_PUBLIC_ORIGIN when given,
else the scheme and Host this server sees (uvicorn rewrites the scheme from
X-Forwarded-Proto only for the proxies given to --forwarded-allow-ips; PI
never reads X-Forwarded-Host).

A request without Origin is not a browser's cross-site write (operator
tools, tests): the product's routes then rely on the session's CSRF token,
as before; the relay of PGDR's page, written for a browser only, requires
the Origin as well (`origin_required`).
"""
from __future__ import annotations

import os

from fastapi import Request

from product_integration.api.errors import ProductAPIError, ProductAPIErrorCategory

PUBLIC_ORIGIN_ENV = "PI_PUBLIC_ORIGIN"
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def product_origin(request: Request) -> str:
    """PI_PUBLIC_ORIGIN when given, else the scheme and Host of the request as this server sees them."""
    configured = os.environ.get(PUBLIC_ORIGIN_ENV, "").strip().rstrip("/")
    return configured or f"{request.url.scheme}://{request.headers.get('host', '')}"


def cross_site(request: Request, *, origin_required: bool = False) -> bool:
    """True when the browser says the request comes from elsewhere (or, with `origin_required`, says nothing)."""
    origin = request.headers.get("origin")
    if origin is None:
        if origin_required:
            return True
    elif origin != product_origin(request):
        return True
    return request.headers.get("sec-fetch-site", "same-origin") != "same-origin"


def same_origin_write(request: Request) -> None:
    """Dependency of the writes that have no session yet (sign-in)."""
    if request.method in WRITE_METHODS and cross_site(request):
        raise ProductAPIError(ProductAPIErrorCategory.CSRF_REJECTED, "cross-site request refused")
