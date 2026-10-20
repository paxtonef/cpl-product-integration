"""Cases past their period: deleted by CPL's governed operation (REQ-B5-116).

PI never deletes a CPL row itself: it asks CPL for the plan
(app.cpl.cases.deletion.plan_expired_cases, reads only) and calls
delete_expired_case once per case, each case in its own transaction. CPL
deletes the case and what exists only because of it -- executions, every
artifact version (VIR resolutions, Premiers Constats), identity resolutions,
decisions, events, participants -- and keeps the account, the vehicle, other
cases, knowledge and notices; it refuses a case another row still depends on
(reported, not deleted). In the same transaction PI removes its own trace
rows that named the case's identity resolutions
(pi_auth.identifier_expunctions): they would name rows that no longer exist.

Media: no persisted reference links a medium to a case (the product's photo
is not stored; an uploaded medium belongs to its contact only), so deleting a
case deletes no file; media follow their own period (medias.py).

A case still within its period is never touched. A failure rolls back the
current case only; the cases deleted before stay deleted, and a new run takes
up the rest (a deleted case is no longer due, a second run changes nothing).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.cpl.cases.authority import AuthorityContext, CaseAuthority
from app.cpl.cases.deletion import CaseDeletionPlan, case_footprint, delete_expired_case, plan_expired_cases
from app.cpl.cases.outcomes import CaseOutcome


def plan(session: Session, cutoff: datetime) -> CaseDeletionPlan:
    return plan_expired_cases(session, created_before=cutoff)


def authority_for(operation_id: UUID) -> AuthorityContext:
    """The operator purge's authority; its reference is the purge operation's opaque identifier."""
    return AuthorityContext(granted=frozenset({CaseAuthority.DELETE_EXPIRED_CASE}),
                            actor_reference=f"pi-purge:{operation_id}")


@dataclass
class Outcome:
    deleted: bool
    blocked: bool
    counts: dict


def delete_one(session: Session, case_id: UUID, cutoff: datetime, days: int, operation_id: UUID) -> Outcome:
    """In the caller's transaction (committed by the caller)."""
    resolutions = case_footprint(session, case_id).resolutions
    result = delete_expired_case(session, case_id=case_id, created_before=cutoff, retention_days=days,
                                 authority=authority_for(operation_id), operation_id=operation_id)
    if result.outcome == CaseOutcome.SUCCESS:
        if resolutions:
            session.execute(text(
                "DELETE FROM pi_auth.identifier_expunctions WHERE target_kind = 'asset_identity_resolution' "
                "AND target_id = ANY(CAST(:ids AS uuid[]))"), {"ids": [str(r) for r in resolutions]})
        return Outcome(True, False, result.payload["counts"])
    if result.outcome == CaseOutcome.CONFLICT:
        return Outcome(False, True, {})
    if result.outcome in (CaseOutcome.NO_CHANGE, CaseOutcome.NOT_FOUND):
        return Outcome(False, False, {})            # already deleted (a resumed run)
    raise RuntimeError(f"case deletion refused: {result.outcome}")
