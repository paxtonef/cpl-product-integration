"""VIR resolution_status -> CPL AssetIdentityResolution.resolution_status.

VIR's 8 values (vir.domain.enums.ResolutionStatus, read directly at the
pinned baseline) map onto CPL's 6 admissible values
(app.cpl.models.asset_identity_resolution's CHECK constraint:
'RESOLVED','PARTIALLY_RESOLVED','AMBIGUOUS','CONTRADICTORY','UNRESOLVED',
'FAILED'). This mapping is authored here, in the product-integration
layer, per the Reality Check's own instruction that CPL's status
vocabulary is not modified and VIR's is not modified — the transform is a
product-integration responsibility.

Reasoning per value (not arbitrary):
  RESOLVED                -> RESOLVED               identical concept
  PROVISIONALLY_RESOLVED  -> PARTIALLY_RESOLVED      a resolution that still
                                                        needs more information
                                                        is CPL's "partial" case
  AMBIGUOUS               -> AMBIGUOUS               identical concept
  INSUFFICIENT_DATA       -> UNRESOLVED              VIR could not resolve for
                                                        lack of data -> CPL's
                                                        generic "unresolved"
  CONTRADICTORY           -> CONTRADICTORY           identical concept
  UNSUPPORTED_COUNTRY     -> FAILED                  an environmental/
                                                        capability limitation,
                                                        not a data-quality
                                                        resolution state
  PROVIDER_UNAVAILABLE    -> FAILED                  a technical failure of
                                                        VIR's own execution,
                                                        not an identity-quality
                                                        outcome
  INVALID_IDENTIFIER      -> FAILED                  an input-validation
                                                        failure, not a
                                                        resolution-quality
                                                        outcome

Every one of VIR's 8 values has a deterministic target. No 7th CPL value is
introduced. An unrecognized VIR status string raises rather than silently
defaulting — REQ-B6-090's "no silent acceptance of the unclassified" spirit
applied here at the product-integration layer.
"""
from __future__ import annotations

VIR_TO_CPL_RESOLUTION_STATUS: dict[str, str] = {
    "resolved": "RESOLVED",
    "provisionally_resolved": "PARTIALLY_RESOLVED",
    "ambiguous": "AMBIGUOUS",
    "insufficient_data": "UNRESOLVED",
    "contradictory": "CONTRADICTORY",
    "unsupported_country": "FAILED",
    "provider_unavailable": "FAILED",
    "invalid_identifier": "FAILED",
}

# The 3 VIR statuses that map to FAILED represent VIR being unable to even
# attempt a resolution, as opposed to attempting one and reaching an
# inconclusive result. Kept as a named set so callers (e.g. PI-01's
# orchestration function, and later PI-02) can distinguish "VIR tried and
# got an inconclusive answer" from "VIR could not try at all" without
# re-deriving this classification.
VIR_STATUSES_REPRESENTING_NO_ATTEMPT = frozenset({
    "unsupported_country", "provider_unavailable", "invalid_identifier",
})


class UnknownVIRStatusError(ValueError):
    """Raised when a VIR resolution_status string is not one of the 8
    known values. This should be structurally unreachable if VIR's own
    enum validation ran first (Pydantic validates the wire value against
    no fixed choice set here, since PI-01 does not import VIR's enum
    class — see vir/schemas.py's module docstring) — this function is the
    explicit, testable belt-and-suspenders check for that boundary."""


def map_vir_status_to_cpl(vir_status: str) -> str:
    try:
        return VIR_TO_CPL_RESOLUTION_STATUS[vir_status]
    except KeyError:
        raise UnknownVIRStatusError(
            f"{vir_status!r} is not one of VIR's 8 known resolution_status values: "
            f"{sorted(VIR_TO_CPL_RESOLUTION_STATUS)}"
        ) from None
