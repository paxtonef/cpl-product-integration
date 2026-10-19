"""Request log without request data (bloc 3A, point 5).

uvicorn's own access log writes each request's path and query string: in
the product they carry case, execution and parcours identifiers
(``/api/v1?p=V1-…``, ``/api/v1/parcours/V1-…/selection``). PI and the
public entry are therefore launched with ``--no-access-log`` and log through
this middleware instead: one line per request with the method, the matched
route TEMPLATE under its mount (e.g. ``/api/v1/parcours/{pid}{sub_path:path}``)
or a fixed label, the status and the duration -- never the path, the query,
a header, a cookie, a body, a photo or an address.

An exception escaping a route is logged as one fixed line naming its class
only (its message and traceback may carry request data) and answered with a
plain 500; nothing reaches uvicorn's error log.
"""
from __future__ import annotations

import time

from product_integration.stderr_log import stderr_logger

logger = stderr_logger("product_integration.access")

NO_ROUTE = "(aucune route)"
_ERROR_BODY = b'{"error_category":"INTERNAL_ERROR","message":"internal error"}'


def route_label(scope) -> str:
    """The matched route's template under its mount, a mount's fixed label, or NO_ROUTE."""
    route = scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str):
        return scope.get("root_path", "") + template
    endpoint = scope.get("endpoint")
    if endpoint is not None:
        return "montage:" + type(endpoint).__name__
    return NO_ROUTE


class AccessLogMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started, status = time.monotonic(), []

        async def send_and_note(message):
            if message["type"] == "http.response.start":
                status.append(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_and_note)
        except Exception as exc:  # noqa: BLE001 -- logged by class only, answered with a plain 500
            logger.error("%s %s exception %s", scope.get("method"), route_label(scope), type(exc).__name__)
            if not status:
                status.append(500)
                await send({"type": "http.response.start", "status": 500,
                            "headers": [(b"content-type", b"application/json"), (b"cache-control", b"no-store")]})
                await send({"type": "http.response.body", "body": _ERROR_BODY})
        logger.info("%s %s %s %dms", scope.get("method"), route_label(scope), status[0] if status else "-",
                    int((time.monotonic() - started) * 1000))
