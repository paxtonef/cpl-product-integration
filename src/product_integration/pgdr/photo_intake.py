"""VIR -> PGDR Photo-First intake handoff (thin PI function).

Takes a VIR VehicleIdentityResolution, translates it with PI-02's existing
map_resolution() -- identity is never rebuilt here -- and hands the result to
PGDR's credentialed POST /api/photo/identity-handoff. Returns the Photo-First
page URL for the intake PGDR created. No PI route, no session correlation:
full PI-fronted orchestration is a separate follow-on.

Configuration (environment):
  PI_PGDR_BASE_URL                 PGDR web base URL, e.g. http://127.0.0.1:8000
  PI_PGDR_IDENTITY_HANDOFF_TOKEN   the PGDR_IDENTITY_HANDOFF_TOKEN shared secret
"""
from __future__ import annotations

import os
from typing import Optional

import httpx
from vir.domain.models import VehicleIdentityResolution as VIRVehicleIdentityResolution

from product_integration.pgdr.handoff_mapper import map_resolution

PGDR_BASE_URL_ENV = "PI_PGDR_BASE_URL"
PGDR_HANDOFF_TOKEN_ENV = "PI_PGDR_IDENTITY_HANDOFF_TOKEN"
PGDR_HANDOFF_TOKEN_HEADER = "X-PGDR-Identity-Handoff-Token"


class PhotoIntakeRefusedError(Exception):
    """PGDR did not create an intake: the handoff was rejected, or PGDR
    reported a governed non-start (e.g. vehicle_identity_insufficient,
    vehicle_not_supported). `status` carries PGDR's own status or HTTP code."""

    def __init__(self, status: str, detail: object):
        super().__init__(f"PGDR created no Photo-First intake ({status}): {detail}")
        self.status = status
        self.detail = detail


async def request_photo_first_intake(
    resolution: VIRVehicleIdentityResolution, *, http_client: Optional[httpx.AsyncClient] = None,
) -> str:
    """Raises VIRPGDRHandoffError (from map_resolution) for a VIR status PGDR
    cannot accept, and PhotoIntakeRefusedError when PGDR creates no intake."""
    base_url = os.environ[PGDR_BASE_URL_ENV].rstrip("/")
    token = os.environ[PGDR_HANDOFF_TOKEN_ENV]
    identity = map_resolution(resolution)

    client = http_client or httpx.AsyncClient()
    try:
        response = await client.post(
            f"{base_url}/api/photo/identity-handoff",
            json=identity.model_dump(mode="json"),
            headers={PGDR_HANDOFF_TOKEN_HEADER: token},
        )
    finally:
        if http_client is None:
            await client.aclose()

    if response.status_code != 200:
        raise PhotoIntakeRefusedError(f"http_{response.status_code}", response.text)
    body = response.json()
    if body.get("status") != "awaiting_consent":
        raise PhotoIntakeRefusedError(body.get("status", "unknown"), body)
    return f"{base_url}/?intake={body['intake_id']}"
