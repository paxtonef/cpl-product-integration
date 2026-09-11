"""PI-05 — product API error model and HTTP status mapping.

§21/§22 of the PI-05 instruction: a narrow, explicit product-facing error
representation, preserving the distinctions PI-01/PI-02/PI-03/PI-04 already
established — never collapsed into a single generic 500.

Documented HTTP status mapping (actual mapping used by this module, not a
generic example table):

  validation error (malformed request body)          -> 422 (FastAPI's own
                                                           default for
                                                           Pydantic
                                                           validation
                                                           failures)
  resource not found (contact/asset/case/execution)       -> 404
  cross-resource mismatch (§31 — e.g. execution does           -> 404 (treated
    not belong to the given case)                               as "not
                                                                   found in
                                                                   this
                                                                   context",
                                                                   not 403,
                                                                   since this
                                                                   API has no
                                                                   real
                                                                   authentication
                                                                   layer to
                                                                   make a 403
                                                                   meaningful
                                                                   — see
                                                                   §31 note
                                                                   below)
  PI-02 handoff refusal (VIR result not admissible for PGDR)  -> 200,
                                                                   status=
                                                                   "PI02_
                                                                   HANDOFF_
                                                                   REFUSED"
                                                                   (§25 — a
                                                                   valid,
                                                                   informative
                                                                   product
                                                                   outcome,
                                                                   never an
                                                                   error)
  PGDR BLOCKED (awaiting user answer)                              -> 200,
                                                                       status=
                                                                       "BLOCKED"
                                                                       (§23 —
                                                                       explicitly
                                                                       NOT a
                                                                       failure)
  PGDR ESCALATED                                                       -> 200,
                                                                           status=
                                                                           "COMPLETED",
                                                                           domain_
                                                                           result=
                                                                           "escalated"
                                                                           (§24)
  conflict / invalid continuation state (e.g. continuing                -> 409
    an already-terminal execution)
  VIR technical failure / PGDR technical failure /                          -> 502
    CPL persistence failure / Case orchestration failure                       (upstream/
    (all genuine integration-layer failures, distinguished                      integration
    from each other in the response body's `error_category`,                     failure,
    never collapsed together)                                                     not the
                                                                                     client's
                                                                                      fault)
  authority rejection                                                                   -> 403
  truly unexpected/unclassified exception                                                   -> 500
                                                                                                (last
                                                                                                 resort
                                                                                                 only)

§31 note on the 404-not-403 choice for cross-resource mismatches: this API
does not implement a real authentication/session system (none exists in the
product baseline, and building one is explicitly out of PI-05's scope). A
403 implies "we know who you are and you're not allowed"; without real
authentication this API cannot honestly make that claim. Returning 404 for
"this execution does not belong to this case" is the same answer a genuine
authorization boundary would give an attacker probing for resources they
have no relationship to (don't confirm the resource exists at all) --
consistent with the resource-consistency check itself (§31), not a weaker
substitute for it.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException
from fastapi.responses import JSONResponse


class ProductAPIErrorCategory:
    NOT_FOUND = "NOT_FOUND"
    CROSS_RESOURCE_MISMATCH = "CROSS_RESOURCE_MISMATCH"
    AUTHORITY_REJECTION = "AUTHORITY_REJECTION"
    CONFLICT = "CONFLICT"
    VIR_TECHNICAL_FAILURE = "VIR_TECHNICAL_FAILURE"
    VIR_NON_RESOLUTION = "VIR_NON_RESOLUTION"
    PGDR_TECHNICAL_FAILURE = "PGDR_TECHNICAL_FAILURE"
    CPL_PERSISTENCE_FAILURE = "CPL_PERSISTENCE_FAILURE"
    CASE_ORCHESTRATION_FAILURE = "CASE_ORCHESTRATION_FAILURE"
    PROCESS_LOCAL_STATE_UNAVAILABLE = "PROCESS_LOCAL_STATE_UNAVAILABLE"
    UNEXPECTED = "UNEXPECTED"


_CATEGORY_TO_STATUS: dict[str, int] = {
    ProductAPIErrorCategory.NOT_FOUND: 404,
    ProductAPIErrorCategory.CROSS_RESOURCE_MISMATCH: 404,
    ProductAPIErrorCategory.AUTHORITY_REJECTION: 403,
    ProductAPIErrorCategory.CONFLICT: 409,
    ProductAPIErrorCategory.VIR_TECHNICAL_FAILURE: 502,
    ProductAPIErrorCategory.VIR_NON_RESOLUTION: 502,
    ProductAPIErrorCategory.PGDR_TECHNICAL_FAILURE: 502,
    ProductAPIErrorCategory.CPL_PERSISTENCE_FAILURE: 502,
    ProductAPIErrorCategory.CASE_ORCHESTRATION_FAILURE: 502,
    ProductAPIErrorCategory.PROCESS_LOCAL_STATE_UNAVAILABLE: 409,
    ProductAPIErrorCategory.UNEXPECTED: 500,
}


class ProductAPIError(HTTPException):
    """The one typed error this API layer raises. Carries an explicit
    `error_category` (one of `ProductAPIErrorCategory`'s values) the
    response body exposes, plus only stable, product-safe identifiers --
    never a raw underlying exception, ORM object, or DB-internal detail
    (§26)."""

    def __init__(self, category: str, message: str, *, extra: Optional[dict[str, Any]] = None):
        status_code = _CATEGORY_TO_STATUS.get(category, 500)
        detail = {"error_category": category, "message": message}
        if extra:
            detail.update(extra)
        super().__init__(status_code=status_code, detail=detail)
        self.category = category


async def product_api_error_handler(request, exc: ProductAPIError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.detail)
