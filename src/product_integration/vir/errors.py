"""VIR client error taxonomy.

Distinguishes exactly the categories §18 of the PI-01 instruction requires
kept separate. Note what is deliberately NOT an error here: a resolution
with resolution_status='ambiguous'/'contradictory'/'insufficient_data' is
a SUCCESSFUL HTTP 200 response carrying a governed non-resolution outcome
— confirmed directly from VIR's own resolve_vehicle.py (ResolveVehicleUseCase
always returns a VehicleIdentityResolution, never raises for these cases).
Such a resolution is returned normally by VIRClient.resolve(); it is not
raised as an exception. Only genuine transport/protocol/technical failures
raise below.
"""
from __future__ import annotations


class VIRClientError(Exception):
    """Base for all PI-01 VIR-client-raised errors."""


class VIRTransportError(VIRClientError):
    """HTTP transport failure — connection refused, DNS failure, etc. No
    HTTP response was received at all."""


class VIRTimeoutError(VIRClientError):
    """The bounded request timeout elapsed before VIR responded."""


class VIRInvalidResponseError(VIRClientError):
    """VIR returned an HTTP response, but its body did not parse against
    the expected schema — a contract violation, never silently accepted."""

    def __init__(self, message: str, *, status_code: int, body: str):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class VIRTechnicalFailureError(VIRClientError):
    """VIR returned a structured VIRBaseError response (its own error_code/
    message/recoverable body) — a genuine technical/input failure, always
    distinguishable from a governed non-resolution outcome (which is a 200
    with a resolution_status field, not this)."""

    def __init__(self, error_code: str, message: str, *, http_status: int, recoverable: bool):
        super().__init__(f"{error_code}: {message}")
        self.error_code = error_code
        self.http_status = http_status
        self.recoverable = recoverable


class VIRResolutionNotFoundError(VIRClientError):
    """VIR returned 404 for a resolution_id that does not exist in VIR's
    own store."""
