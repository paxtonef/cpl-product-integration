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

from fastapi import Depends
import httpx

from app.cpl.identity.authority import Authority, AuthorityContext
from app.cpl.assets.authority import AssetAuthority
from app.cpl.cases.authority import CaseAuthority
from app.cpl.runners.authority import RunnerAuthority

from product_integration.api.registry import PGDRSessionRegistry, default_registry
from product_integration.vir.client import VIRClient

# No authentication/authorization platform exists in the product baseline
# (§31 -- "not required to invent a complete authentication system unless
# one already exists"), so this API grants every PI-04/CPL authority its
# own routes could ever need, uniformly, to every request. Real
# authorization-by-resource-consistency (§31's actual requirement) is
# enforced separately, per-route, by checking that the resource IDs in the
# request genuinely relate to each other (see routes.py) -- that check is
# independent of, and not weakened by, this broad authority grant.
_FULL_AUTHORITY = AuthorityContext(
    granted=frozenset({
        Authority.CREATE_CONTACT, Authority.READ_IDENTITY,
        AssetAuthority.CREATE_ASSET, AssetAuthority.CONSUME_IDENTITY_RESOLUTION,
        CaseAuthority.CREATE_CASE, CaseAuthority.TRANSITION_CASE_STATUS, CaseAuthority.READ_CASE,
        RunnerAuthority.ADMIT_EXECUTION, RunnerAuthority.TRANSITION_EXECUTION_STATUS,
        RunnerAuthority.REGISTER_ARTIFACT,
    }),
    actor_reference="pi05-product-api",
)


def get_authority() -> AuthorityContext:
    return _FULL_AUTHORITY


# The VIR base URL is a module-level, overridable value rather than a
# hardcoded constant -- production deployment would point this at VIR's
# real service address; tests override get_vir_http_client entirely to use
# an ASGI transport against VIR's own app object (§35 -- real VIR HTTP
# semantics, never a fake response).
VIR_BASE_URL = "http://vir-service.internal"


async def get_vir_http_client() -> httpx.AsyncClient:
    async with httpx.AsyncClient(base_url=VIR_BASE_URL, timeout=10.0) as client:
        yield client


def get_vir_client(http_client: httpx.AsyncClient = Depends(get_vir_http_client)) -> VIRClient:
    return VIRClient(http_client)


def get_pgdr_registry() -> PGDRSessionRegistry:
    return default_registry
