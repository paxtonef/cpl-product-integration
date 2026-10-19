"""PGDR V1 notice parcours, reached through the authenticated product.

  POST /cases/{case_id}/notice-parcours   opens a parcours for a case the user
                                          owns (session + CSRF token, like
                                          every other product route)
  GET  /v1?p=<parcours_id>                PGDR's /v1 page, relayed
  GET|POST /v1/parcours/{id}/...          PGDR's parcours requests, relayed for
                                          the parcours' owner only

Under the public /api prefix these are exactly the paths PGDR's page uses
(/api/v1/parcours/...), so the page runs unchanged on the product origin.

The relayed requests come from PGDR's page, which does not send PI's CSRF
header. They are protected instead by: the SameSite=Strict session cookie;
JSON-only POST bodies (a cross-site form cannot send them without a CORS
preflight PI never grants); Sec-Fetch-Site, when the browser sends it, must
be same-origin; and the parcours id in the path, an unguessable PGDR
identifier that is useless to anyone but its owner (checked on every
request; anything else is answered like a missing parcours).
"""
from __future__ import annotations

import base64
import hashlib
import re
from typing import Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from app.db.engine import session_scope
from vir.domain.models import VehicleIdentityResolution as VIRVehicleIdentityResolution

from product_integration.api.deps import SESSION_COOKIE, get_notice_registry, get_pgdr_http_client, get_principal
from product_integration.api.errors import ProductAPIError, ProductAPIErrorCategory
from product_integration.api.routes import _find_vir_execution_and_artifact
from product_integration.auth import accounts
from product_integration.auth.accounts import Principal
from product_integration.auth.ownership import owned_case
from product_integration.pgdr.errors import VIRPGDRHandoffError
from product_integration.pgdr.handoff_mapper import map_resolution
from product_integration.pgdr.notice_parcours import (
    MAX_RELAY_BODY, PGDR_REFUSALS, NoticeParcoursRegistry, ParcoursOwner, allowed, cleaned_propositions_body,
    handoff_headers, pgdr_base_url, valid_parcours_id,
)

router = APIRouter(dependencies=[Depends(get_principal)])
relay_router = APIRouter()

_NO_STORE = {"Cache-Control": "no-store"}
_UNKNOWN = "Parcours inconnu ou expiré."  # PGDR's own answer for an unknown parcours
_RELAYED_TYPES = ("application/json", "image/png", "image/jpeg")


class NoticeParcoursResponse(BaseModel):
    status: str                    # "opened" or PGDR's refusal (pgdr.v1_parcours._open_parcours)
    page: Optional[str] = None     # with "opened": the page path under the API prefix
    message: Optional[str] = None  # with a refusal: PGDR's own explanation


@router.post("/cases/{case_id}/notice-parcours", response_model=NoticeParcoursResponse)
async def open_notice_parcours_route(
    case_id: UUID, principal: Principal = Depends(get_principal),
    http: httpx.AsyncClient = Depends(get_pgdr_http_client),
    registry: NoticeParcoursRegistry = Depends(get_notice_registry),
):
    with session_scope() as session:
        owned_case(session, principal, case_id)
        _, artifact = _find_vir_execution_and_artifact(session, case_id)
        payload = dict(artifact.payload)
    try:
        identity = map_resolution(VIRVehicleIdentityResolution.model_validate(payload))
    except VIRPGDRHandoffError:
        # A VIR result PGDR cannot accept: no notice is ever assumed.
        return NoticeParcoursResponse(status="vehicle_identity_insufficient",
                                      message="L'identité du véhicule n'est pas établie par VIR.")
    try:
        response = await http.post(f"{pgdr_base_url()}/api/v1/vir-handoff", json=identity.model_dump(mode="json"),
                                   headers=handoff_headers())
        body = response.json() if response.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        raise ProductAPIError(ProductAPIErrorCategory.PGDR_TECHNICAL_FAILURE, "PGDR notice service unavailable") from None
    if not isinstance(body, dict):
        raise ProductAPIError(ProductAPIErrorCategory.PGDR_TECHNICAL_FAILURE, "PGDR opened no notice parcours")
    status, pid = body.get("status"), body.get("parcours_id")
    if status == "opened" and isinstance(pid, str) and valid_parcours_id(pid):
        registry.put(pid, ParcoursOwner(case_id=case_id, contact_id=principal.contact_id))
        return NoticeParcoursResponse(status="opened", page=f"/v1?p={pid}")
    if status in PGDR_REFUSALS:
        return NoticeParcoursResponse(status=status, message=body.get("message"))
    raise ProductAPIError(ProductAPIErrorCategory.PGDR_TECHNICAL_FAILURE, "PGDR opened no notice parcours")


def _refused(status: int, category: str, detail: str) -> JSONResponse:
    # « detail » is what PGDR's page shows; the category is PI's own.
    return JSONResponse({"detail": detail, "error_category": category}, status_code=status, headers=_NO_STORE)


def _session(request: Request) -> Optional[Principal]:
    return accounts.resolve_session(request.cookies.get(SESSION_COOKIE))


def _page_csp(html: str) -> str:
    scripts = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    hashes = " ".join("'sha256-" + base64.b64encode(hashlib.sha256(s.encode("utf-8")).digest()).decode() + "'"
                      for s in scripts)
    return ("default-src 'none'; script-src " + (hashes or "'none'") + "; style-src 'unsafe-inline'; "
            "img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
            "form-action 'none'; object-src 'none'")


@relay_router.get("/v1", include_in_schema=False)
async def notice_page_route(request: Request, http: httpx.AsyncClient = Depends(get_pgdr_http_client)):
    if _session(request) is None:
        return _refused(401, ProductAPIErrorCategory.AUTHENTICATION_REQUIRED, "Session expirée : reconnectez-vous.")
    try:
        response = await http.get(f"{pgdr_base_url()}/v1")
    except httpx.HTTPError:
        return _refused(502, ProductAPIErrorCategory.PGDR_TECHNICAL_FAILURE, "Service des notices indisponible.")
    if response.status_code != 200:
        return _refused(502, ProductAPIErrorCategory.PGDR_TECHNICAL_FAILURE, "Service des notices indisponible.")
    html = response.text
    return HTMLResponse(html, headers={**_NO_STORE, "Content-Security-Policy": _page_csp(html),
                                       "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
                                       "X-Content-Type-Options": "nosniff"})


async def _bounded_body(request: Request) -> Optional[bytes]:
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > MAX_RELAY_BODY):
        return None
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_RELAY_BODY:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


@relay_router.api_route("/v1/parcours/{pid}{sub_path:path}", methods=["GET", "POST"], include_in_schema=False)
async def notice_relay_route(
    pid: str, sub_path: str, request: Request, http: httpx.AsyncClient = Depends(get_pgdr_http_client),
    registry: NoticeParcoursRegistry = Depends(get_notice_registry),
):
    principal = _session(request)
    if principal is None:
        return _refused(401, ProductAPIErrorCategory.AUTHENTICATION_REQUIRED, "Session expirée : reconnectez-vous.")
    method = request.method
    if method == "POST":
        if request.headers.get("sec-fetch-site", "same-origin") != "same-origin":
            return _refused(403, ProductAPIErrorCategory.CSRF_REJECTED, "Requête refusée.")
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            return _refused(415, ProductAPIErrorCategory.INVALID_REQUEST, "Requête refusée.")
    owner = registry.owner(pid) if valid_parcours_id(pid) else None
    if owner is None or owner.contact_id != principal.contact_id or not allowed(method, sub_path):
        return _refused(404, ProductAPIErrorCategory.NOT_FOUND, _UNKNOWN)
    content = None
    if method == "POST":
        content = await _bounded_body(request)
        if content is None:
            return _refused(413, ProductAPIErrorCategory.INVALID_REQUEST, "Photo trop volumineuse.")
        if sub_path == "/propositions":
            try:
                content = cleaned_propositions_body(content)
            except ValueError:
                return _refused(422, ProductAPIErrorCategory.INVALID_REQUEST, "Requête refusée.")
    try:
        response = await http.request(method, f"{pgdr_base_url()}/api/v1/parcours/{pid}{sub_path}", content=content,
                                      headers={"Content-Type": "application/json"} if method == "POST" else None)
    except httpx.HTTPError:
        return _refused(502, ProductAPIErrorCategory.PGDR_TECHNICAL_FAILURE, "Service des notices indisponible.")
    media = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if media not in _RELAYED_TYPES:
        return _refused(502, ProductAPIErrorCategory.PGDR_TECHNICAL_FAILURE, "Service des notices indisponible.")
    return Response(content=response.content, status_code=response.status_code, media_type=media, headers=_NO_STORE)
