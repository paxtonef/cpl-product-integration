"""PGDR V1 notice parcours, reached through the authenticated product.

  POST /cases/{case_id}/notice-parcours   opens a parcours for a case the user
                                          owns (session + CSRF token, like
                                          every other product route)
  GET  /v1?p=<parcours_id>                PGDR's /v1 page, relayed
  GET|POST /v1/parcours/{id}/...          PGDR's parcours requests, relayed for
                                          the parcours' owner only
  POST /v1/parcours/{id}/record           PI alone (bloc 3B): records again a
                                          confirmed result CPL did not record

Under the public /api prefix these are exactly the paths PGDR's page uses
(/api/v1/parcours/...), so the page runs unchanged on the product origin.

The relayed writes carry PI's own CSRF token (bloc 3A): PI places the
session's token in the page it relays (<meta name="csrf-token">), PGDR's page
sends it as X-CSRF-Token (PGDR 48d5da4), and PI compares it with the
session's own, as for every product route. On top of it, each relayed write
needs: an Origin equal to the product's origin (api.origin; required here,
the page being a browser's only), Sec-Fetch-Site same-origin when the
browser sends it, and a JSON body. The parcours owner is checked on every
request; anything else is answered like a missing parcours. The SameSite
cookie and Sec-Fetch-Site are kept but never relied on alone. No service
token ever reaches the browser.
"""
from __future__ import annotations

import base64
import hashlib
import html as html_lib
import json
import re
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.db.engine import session_scope
from vir.domain.models import VehicleIdentityResolution as VIRVehicleIdentityResolution

from product_integration.api.deps import (
    CSRF_HEADER, SESSION_COOKIE, get_notice_registry, get_pgdr_http_client, get_principal,
)
from product_integration.api.errors import ProductAPIError, ProductAPIErrorCategory
from product_integration.api.origin import cross_site
from product_integration.api.routes import _find_vir_execution_and_artifact
from product_integration.auth import accounts
from product_integration.auth.accounts import Principal
from product_integration.auth.ownership import owned_case
from product_integration.pgdr import notice_results
from product_integration.pgdr.errors import VIRPGDRHandoffError
from product_integration.pgdr.handoff_mapper import map_resolution
from product_integration.stderr_log import stderr_logger
from product_integration.pgdr.notice_parcours import (
    MAX_RELAY_BODY, PGDR_REFUSALS, NoticeParcoursRegistry, ParcoursOwner, allowed, cleaned_propositions_body,
    handoff_headers, pgdr_base_url, valid_parcours_id,
)

router = APIRouter(dependencies=[Depends(get_principal)])
relay_router = APIRouter()

_NO_STORE = {"Cache-Control": "no-store"}
# An unknown parcours, another user's, or one lost at a restart: one answer, which never offers to resume.
_UNKNOWN = "Parcours inconnu ou expiré. Rouvrez la notice depuis votre dossier : un nouveau parcours commencera."
_RESTITUTION_STEPS = ("/confirm", "/clarify", "/condition")  # PGDR answers them with the restitution
logger = stderr_logger("product_integration.notice_parcours")
_RELAYED_TYPES = ("application/json", "image/png", "image/jpeg")

# The product's own record status, added to a restitution PGDR answered after an explicit confirmation (shown by
# PGDR's page, which says nothing about a record without it). « Enregistré » only once CPL has committed it.
_RECORDED = {"status": "recorded", "retry": False,
             "message": "Résultat enregistré dans votre dossier : vous le retrouverez dans « Confirmed results »."}
_NOT_RECORDED = {"status": "not_recorded", "retry": True, "retry_label": "Réessayer l'enregistrement",
                 "message": "Résultat non enregistré : votre dossier n'a pas conservé ce résultat. Les textes de la "
                            "notice affichés sur cette page restent ceux du constructeur. Vous pouvez réessayer "
                            "l'enregistrement sans refaire le parcours."}


class NoticeResultsResponse(BaseModel):
    case_id: UUID
    results: list[dict]   # product_integration.pgdr.notice_results.build_record, plus record_id and recorded_at


class NoticeIdentityKey(BaseModel):
    """One identity key as PGDR compared it, with VIR's provenance label (« confirmé par le conducteur »...)."""
    key: str
    label: str
    value: Optional[str] = None
    provenance: str
    provenance_label: str


class NoticeParcoursResponse(BaseModel):
    status: str                    # "opened" or PGDR's refusal (pgdr.v1_parcours._open_parcours)
    page: Optional[str] = None     # with "opened": the page path under the API prefix
    message: Optional[str] = None  # with a refusal: PGDR's own explanation
    # With a refusal (pgdr.v1_applicabilite): PGDR's precise reasons, what remains to be checked, the next
    # useful action, and the identity keys compared with their provenance. Relayed as PGDR wrote them.
    reasons: list[str] = Field(default_factory=list)
    to_verify: list[str] = Field(default_factory=list)
    next_action: Optional[str] = None
    identity: list[NoticeIdentityKey] = Field(default_factory=list)


_MAX_RELAYED_LINES, _MAX_LINE = 12, 600


def _lines(value) -> list[str]:
    return [x[:_MAX_LINE] for x in value[:_MAX_RELAYED_LINES] if isinstance(x, str)] if isinstance(value, list) else []


def _refusal(status: str, body: dict) -> NoticeParcoursResponse:
    identity = []
    for k in body.get("identity") or []:
        try:
            identity.append(NoticeIdentityKey.model_validate(k))
        except ValueError:
            continue
    next_action = body.get("next_action")
    return NoticeParcoursResponse(status=status, message=body.get("message"), reasons=_lines(body.get("reasons")),
                                  to_verify=_lines(body.get("to_verify")), identity=identity[:_MAX_RELAYED_LINES],
                                  next_action=next_action[:_MAX_LINE] if isinstance(next_action, str) else None)


@router.post("/cases/{case_id}/notice-parcours", response_model=NoticeParcoursResponse)
async def open_notice_parcours_route(
    case_id: UUID, principal: Principal = Depends(get_principal),
    http: httpx.AsyncClient = Depends(get_pgdr_http_client),
    registry: NoticeParcoursRegistry = Depends(get_notice_registry),
):
    with session_scope() as session:
        case = owned_case(session, principal, case_id)
        vehicle_ref = str(case.asset_id) if case.asset_id is not None else None   # opaque: never a VIN nor a plate
        execution, artifact = _find_vir_execution_and_artifact(session, case_id)
        payload = dict(artifact.payload)
        vir = {"vir_execution_id": execution.execution_id, "vir_artifact_id": artifact.artifact_id,
               "vir_resolution_id": payload.get("resolution_id")}
    try:
        identity = map_resolution(VIRVehicleIdentityResolution.model_validate(payload), vehicle_ref=vehicle_ref)
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
        registry.put(pid, ParcoursOwner(case_id=case_id, contact_id=principal.contact_id, **vir))
        return NoticeParcoursResponse(status="opened", page=f"/v1?p={pid}")
    if status in PGDR_REFUSALS:
        return _refusal(status, body)
    raise ProductAPIError(ProductAPIErrorCategory.PGDR_TECHNICAL_FAILURE, "PGDR opened no notice parcours")


def _refused(status: int, category: str, detail: str) -> JSONResponse:
    # « detail » is what PGDR's page shows; the category is PI's own.
    return JSONResponse({"detail": detail, "error_category": category}, status_code=status, headers=_NO_STORE)


def _session(request: Request) -> Optional[Principal]:
    return accounts.resolve_session(request.cookies.get(SESSION_COOKIE))


def _write_refusal(request: Request, principal: Principal) -> Optional[JSONResponse]:
    """Why a relayed write is refused, or None. Each condition is required; none is enough alone."""
    if cross_site(request, origin_required=True):
        return _refused(403, ProductAPIErrorCategory.CSRF_REJECTED, "Requête refusée.")
    if not accounts.csrf_matches(principal, request.headers.get(CSRF_HEADER)):
        return _refused(403, ProductAPIErrorCategory.CSRF_REJECTED, "Requête refusée.")
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        return _refused(415, ProductAPIErrorCategory.INVALID_REQUEST, "Requête refusée.")
    return None


def _with_csrf_meta(page: str, principal: Principal) -> Optional[str]:
    """The page with the session's CSRF token for its writes (PGDR reads <meta name="csrf-token">)."""
    if "<head>" not in page:
        return None
    meta = f'<meta name="csrf-token" content="{html_lib.escape(principal.csrf_token, quote=True)}">'
    return page.replace("<head>", "<head>\n" + meta, 1)


def _page_csp(html: str) -> str:
    scripts = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    hashes = " ".join("'sha256-" + base64.b64encode(hashlib.sha256(s.encode("utf-8")).digest()).decode() + "'"
                      for s in scripts)
    return ("default-src 'none'; script-src " + (hashes or "'none'") + "; style-src 'unsafe-inline'; "
            "img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
            "form-action 'none'; object-src 'none'")


@relay_router.get("/v1", include_in_schema=False)
async def notice_page_route(request: Request, http: httpx.AsyncClient = Depends(get_pgdr_http_client)):
    principal = _session(request)
    if principal is None:
        return _refused(401, ProductAPIErrorCategory.AUTHENTICATION_REQUIRED, "Session expirée : reconnectez-vous.")
    try:
        response = await http.get(f"{pgdr_base_url()}/v1")
    except httpx.HTTPError:
        return _refused(502, ProductAPIErrorCategory.PGDR_TECHNICAL_FAILURE, "Service des notices indisponible.")
    html = _with_csrf_meta(response.text, principal) if response.status_code == 200 else None
    if html is None:
        return _refused(502, ProductAPIErrorCategory.PGDR_TECHNICAL_FAILURE, "Service des notices indisponible.")
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


@relay_router.post("/v1/parcours/{pid}/record", include_in_schema=False)
async def notice_record_retry_route(pid: str, request: Request,
                                    registry: NoticeParcoursRegistry = Depends(get_notice_registry)):
    """Records again the last confirmed result of the parcours, as it was confirmed: PI alone -- no request to
    PGDR, no sorting, no VIR. Same conditions as a relayed write; owner only."""
    principal = _session(request)
    if principal is None:
        return _refused(401, ProductAPIErrorCategory.AUTHENTICATION_REQUIRED, "Session expirée : reconnectez-vous.")
    refusal = _write_refusal(request, principal)
    if refusal is not None:
        return refusal
    owner = registry.owner(pid) if valid_parcours_id(pid) else None
    if owner is None or owner.contact_id != principal.contact_id:
        return _refused(404, ProductAPIErrorCategory.NOT_FOUND, _UNKNOWN)
    kept = registry.last_record(pid)
    if kept is None:
        return _refused(409, ProductAPIErrorCategory.CONFLICT, "Aucun résultat confirmé à enregistrer.")
    status = await _record(pid, owner, principal, kept[0], registry)
    return JSONResponse({"product_record": status}, headers=_NO_STORE)


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
        refusal = _write_refusal(request, principal)
        if refusal is not None:
            return refusal
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
    if response.status_code == 404:
        return _refused(404, ProductAPIErrorCategory.NOT_FOUND, _UNKNOWN)
    content = response.content
    if method == "POST" and response.status_code == 200 and sub_path in _RESTITUTION_STEPS:
        if sub_path == "/confirm":
            registry.note_confirmation(pid, datetime.now(timezone.utc))
        content = await _keep_result(pid, owner, principal, content, registry)
    return Response(content=content, status_code=response.status_code, media_type=media, headers=_NO_STORE)


async def _record(pid: str, owner: ParcoursOwner, principal: Principal, record: dict,
                  registry: NoticeParcoursRegistry) -> dict:
    """Writes the record in CPL (idempotent: the same record is never written twice) and returns the product's
    record status. If CPL refuses, nothing is written; the record stays with the parcours for a retry."""
    try:
        await run_in_threadpool(notice_results.persist, record, case_id=owner.case_id, contact_id=owner.contact_id,
                                actor_reference=principal.actor_reference)
    except Exception as exc:  # noqa: BLE001 -- the restitution is still shown; logged by class only
        logger.error("notice parcours result not recorded (%s)", type(exc).__name__)
        registry.note_record(pid, record, recorded=False)
        return dict(_NOT_RECORDED)
    registry.note_record(pid, record, recorded=True)
    return dict(_RECORDED)


async def _keep_result(pid: str, owner: ParcoursOwner, principal: Principal, content: bytes,
                       registry: NoticeParcoursRegistry) -> bytes:
    """Keeps in CPL a restitution PGDR produced after an explicit confirmation, and adds the record status to it.
    If CPL refuses, the driver still gets the manufacturer's texts (never withheld for want of a record), told
    that the result is not recorded, with a retry; one fixed log line says so."""
    try:
        state = json.loads(content)
    except ValueError:
        return content
    record = notice_results.build_record(
        pid=pid, case_id=owner.case_id, owner_contact_id=owner.contact_id, vir=owner.vir_reference(), state=state,
        confirmed_at=registry.confirmation(pid) or datetime.now(timezone.utc))
    if record is None:
        return content
    state["product_record"] = await _record(pid, owner, principal, record, registry)
    return json.dumps(state, ensure_ascii=False).encode("utf-8")


@router.get("/cases/{case_id}/notice-results", response_model=NoticeResultsResponse)
def notice_results_route(case_id: UUID, principal: Principal = Depends(get_principal)):
    """The kept results of the case, as confirmed (CPL only: no PGDR, no sorting). Owner only."""
    with session_scope() as session:
        owned_case(session, principal, case_id)
        return NoticeResultsResponse(case_id=case_id, results=notice_results.results(session, case_id))
