"""Async VIR HTTP client — the PI-01 integration boundary.

Wraps exactly the four endpoints the Reality Check (§6) confirmed by
reading vir/api/routes.py directly at baseline a342aba7cc2fc517621f4fc79c
3191bdfdc9e10b:

  POST /v1/vehicle-identities/resolve
  POST /v1/vehicle-identities/{resolution_id}/clarifications
  GET  /v1/vehicle-identities/{resolution_id}
  GET  /v1/vehicle-identities/{resolution_id}/handoff/diagnostic

No fifth endpoint is invented. No VIR internals are imported — this module
talks to VIR only via HTTP (an httpx.AsyncClient, which may be bound to a
real network transport or, for testing, an ASGI transport wrapping VIR's
own FastAPI app in-process — either way, the actual HTTP-shaped request/
response cycle is exercised, never VIR's Python functions directly).

No hidden retry policy, no infinite retry: exactly one attempt per call.
Retry, if ever wanted, is the caller's decision, not this client's.
"""
from __future__ import annotations

from typing import Optional

import httpx
from pydantic import ValidationError

from product_integration.vir.errors import (
    VIRClientError,
    VIRInvalidResponseError,
    VIRResolutionNotFoundError,
    VIRTechnicalFailureError,
    VIRTimeoutError,
    VIRTransportError,
)
from product_integration.vir.schemas import (
    ClarificationRequest,
    DiagnosticIdentityContext,
    VehicleIdentityRequest,
    VehicleIdentityResolution,
    VIRErrorResponse,
)

DEFAULT_TIMEOUT_SECONDS = 10.0


class VIRClient:
    """One instance wraps one httpx.AsyncClient (caller-supplied, so tests
    can bind it to VIR's ASGI app in-process instead of a real socket)."""

    def __init__(self, http_client: httpx.AsyncClient, *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS):
        self._http = http_client
        self._timeout = timeout_seconds

    async def resolve(self, request: VehicleIdentityRequest) -> VehicleIdentityResolution:
        """POST /v1/vehicle-identities/resolve. Returns normally for every
        governed outcome, including ambiguous/contradictory/insufficient-
        data — those are successful VIR responses carrying a
        resolution_status, not client-raised errors (see vir/errors.py's
        module docstring)."""
        response = await self._request("POST", "/v1/vehicle-identities/resolve", json=request.model_dump(mode="json"))
        return self._parse(response, VehicleIdentityResolution)

    async def submit_clarification(self, resolution_id: str, request: ClarificationRequest) -> VehicleIdentityResolution:
        """POST /v1/vehicle-identities/{resolution_id}/clarifications."""
        response = await self._request(
            "POST", f"/v1/vehicle-identities/{resolution_id}/clarifications", json=request.model_dump(mode="json")
        )
        return self._parse(response, VehicleIdentityResolution)

    async def get_resolution(self, resolution_id: str) -> VehicleIdentityResolution:
        """GET /v1/vehicle-identities/{resolution_id}."""
        response = await self._request("GET", f"/v1/vehicle-identities/{resolution_id}")
        return self._parse(response, VehicleIdentityResolution)

    async def get_diagnostic_handoff(self, resolution_id: str) -> DiagnosticIdentityContext:
        """GET /v1/vehicle-identities/{resolution_id}/handoff/diagnostic.
        PI-01 may retrieve this (it belongs to VIR's real, confirmed
        interface) but does NOT transform it into PGDR input — that is
        PI-02's explicit scope, not this one's (Reality Check §20)."""
        response = await self._request("GET", f"/v1/vehicle-identities/{resolution_id}/handoff/diagnostic")
        return self._parse(response, DiagnosticIdentityContext)

    # -- internal ------------------------------------------------------

    async def _request(self, method: str, path: str, *, json: Optional[dict] = None) -> httpx.Response:
        try:
            response = await self._http.request(method, path, json=json, timeout=self._timeout)
        except httpx.TimeoutException as exc:
            raise VIRTimeoutError(f"VIR request timed out after {self._timeout}s: {method} {path}") from exc
        except httpx.TransportError as exc:
            raise VIRTransportError(f"VIR transport failure: {method} {path}: {exc}") from exc

        if response.status_code == 404:
            raise VIRResolutionNotFoundError(f"VIR resolution not found: {method} {path}")

        if response.status_code >= 400:
            try:
                error_body = VIRErrorResponse.model_validate(response.json())
            except (ValueError, ValidationError) as exc:
                raise VIRInvalidResponseError(
                    f"VIR returned {response.status_code} with an unparseable error body",
                    status_code=response.status_code, body=response.text,
                ) from exc
            raise VIRTechnicalFailureError(
                error_body.error_code, error_body.message,
                http_status=response.status_code, recoverable=error_body.recoverable,
            )

        return response

    @staticmethod
    def _parse(response: httpx.Response, model: type):
        try:
            return model.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise VIRInvalidResponseError(
                f"VIR returned {response.status_code} but the body did not match the expected schema",
                status_code=response.status_code, body=response.text,
            ) from exc
