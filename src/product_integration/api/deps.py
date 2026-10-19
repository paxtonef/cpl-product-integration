"""PI-05 — dependency injection wiring (§29).

Infrastructure (DB session scope, the PI-04 authority context, the VIR HTTP
client, the process-local PGDR registry) is wired through FastAPI's own
dependency system rather than global mutable state, and every one of these
is overridable in tests (`app.dependency_overrides`) without bypassing real
integration — tests override only the VIR transport (to point at VIR's own
ASGI app instead of a live network address) and, where explicitly testing
the process-restart scenario, the registry (a fresh, empty one) -- never
PI-04, CPL, or PGDR themselves.
"""
from __future__ import annotations

from fastapi import Depends, Request
import httpx

from app.cpl.identity.authority import Authority, AuthorityContext
from app.cpl.assets.authority import AssetAuthority
from app.cpl.cases.authority import CaseAuthority
from app.cpl.runners.authority import RunnerAuthority

from product_integration.api.errors import ProductAPIError, ProductAPIErrorCategory
from product_integration.api.origin import cross_site
from product_integration.api.registry import PGDRSessionRegistry, default_registry
from product_integration.auth import accounts
from product_integration.auth.accounts import Principal
from product_integration.media.storage import LocalMediaStorage
from product_integration.pgdr.notice_parcours import NoticeParcoursRegistry, default_notice_registry
from product_integration.vir.client import VIRClient

# End users authenticate with a PI account (product_integration.auth): the
# session cookie fixes the Principal server-side, and the CPL authority is
# built from it for that one request. The operations granted are the ones
# the product journey performs; *which* rows they may touch is enforced by
# the per-owner checks in product_integration.auth.ownership, derived from
# CPL's own records (case primary contact, contact-asset relationships).
# No contact creation (accounts are made by the operator command), no
# authority taken from a header, a body or a login name.
SESSION_COOKIE = "pi_session"
CSRF_HEADER = "X-CSRF-Token"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

END_USER_GRANTS = frozenset({
    Authority.READ_IDENTITY,
    AssetAuthority.CREATE_ASSET, AssetAuthority.MANAGE_RELATIONSHIP, AssetAuthority.CONSUME_IDENTITY_RESOLUTION,
    CaseAuthority.CREATE_CASE, CaseAuthority.TRANSITION_CASE_STATUS, CaseAuthority.READ_CASE,
    RunnerAuthority.ADMIT_EXECUTION, RunnerAuthority.TRANSITION_EXECUTION_STATUS,
    RunnerAuthority.REGISTER_ARTIFACT,
})


def get_principal(request: Request) -> Principal:
    principal = accounts.resolve_session(request.cookies.get(SESSION_COOKIE))
    if principal is None:
        raise ProductAPIError(ProductAPIErrorCategory.AUTHENTICATION_REQUIRED, "authentication required")
    if request.method not in _SAFE_METHODS:
        # Bloc 3B: a write the browser says comes from elsewhere is refused whatever its token (api.origin).
        if cross_site(request):
            raise ProductAPIError(ProductAPIErrorCategory.CSRF_REJECTED, "cross-site request refused")
        if not accounts.csrf_matches(principal, request.headers.get(CSRF_HEADER)):
            raise ProductAPIError(ProductAPIErrorCategory.CSRF_REJECTED, "missing or invalid CSRF token")
    return principal


def get_authority(principal: Principal = Depends(get_principal)) -> AuthorityContext:
    return AuthorityContext(granted=END_USER_GRANTS, actor_reference=principal.actor_reference)


# The VIR base URL is a module-level, overridable value rather than a
# hardcoded constant -- production deployment would point this at VIR's
# real service address; tests override get_vir_http_client entirely to use
# an ASGI transport against VIR's own app object (§35 -- real VIR HTTP
# semantics, never a fake response). PI_VIR_BASE_URL, when set, gives that
# address at process start (scripts/lancer_montage.sh); the default is unchanged.
import os as _os
VIR_BASE_URL = _os.environ.get("PI_VIR_BASE_URL") or "http://vir-service.internal"


async def get_vir_http_client() -> httpx.AsyncClient:
    async with httpx.AsyncClient(base_url=VIR_BASE_URL, timeout=10.0) as client:
        yield client


def get_vir_client(http_client: httpx.AsyncClient = Depends(get_vir_http_client)) -> VIRClient:
    return VIRClient(http_client)


def get_pgdr_registry() -> PGDRSessionRegistry:
    return default_registry


# Block B1.5 -- a single, process-local, fixed base directory. Overridable
# in tests (app.dependency_overrides) the same way VIR's transport is, but
# never per-request or per-caller -- the directory itself is a deployment
# detail, not something any request body ever influences.
import os as _os
_MEDIA_STORAGE_DIR = _os.environ.get("PI05_MEDIA_STORAGE_DIR", "/tmp/pi05-media-storage")
_default_media_storage = LocalMediaStorage(_MEDIA_STORAGE_DIR)


def get_media_storage() -> LocalMediaStorage:
    return _default_media_storage


# PGDR's V1 notice parcours (product_integration.pgdr.notice_parcours): PGDR on
# the loopback at PI_PGDR_BASE_URL. trust_env=False: no proxy taken from the
# environment ever sees a photo or a notice. Tests override this client with
# an ASGI transport against PGDR's own app, as for VIR.
async def get_pgdr_http_client() -> httpx.AsyncClient:
    async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
        yield client


def get_notice_registry() -> NoticeParcoursRegistry:
    return default_notice_registry
