"""PI-02 mapper error taxonomy.

A single, specific exception type distinguishing "this VIR result cannot be
handed off to PGDR at all" from a programming error. Never a bare Exception,
per the PI-02 instruction's own convention requirement.
"""
from __future__ import annotations


class VIRPGDRHandoffError(Exception):
    """Raised when a VIR resolution_status is not one of PGDR's admissible
    values — i.e. VIR could not actually attempt identity resolution
    (unsupported_country / provider_unavailable / invalid_identifier).

    This is never raised for an ordinary inconclusive-but-attempted result
    (ambiguous, contradictory, insufficient_data, provisionally_resolved are
    all admissible and pass through normally) — only for the three states
    representing no genuine attempt at all."""

    def __init__(self, vir_status: str, *, admissible_statuses: frozenset[str]):
        super().__init__(
            f"VIR resolution_status {vir_status!r} is not admissible for PGDR handoff "
            f"(admissible: {sorted(admissible_statuses)}) — VIR did not actually attempt "
            f"identity resolution for this input; refusing rather than guessing a PGDR state."
        )
        self.vir_status = vir_status
        self.admissible_statuses = admissible_statuses
