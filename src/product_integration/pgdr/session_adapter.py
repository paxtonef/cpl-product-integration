"""PI-03 — PGDR Session Adapter (CPL-governed).

Drives PGDR's real, non-interactive `SessionController` programmatically and
represents the resulting multi-turn diagnostic session as one governed CPL
`RunnerExecution`, finalizing with exactly one `pgdr_garage_preparation_report`
`RunnerArtifact` when the session reaches a terminal PGDR state. PGDR itself
persists nothing (confirmed directly: no database, no filesystem state
anywhere in its own source) — this module is the entirety of that
persistence, using CPL's existing, unmodified B6 mechanisms.

SessionState -> CPL execution_status mapping (empirically derived, not
assumed from the Reality Check's own loose "BLOCKED" phrasing — see below):

`pgdr.enums.SessionState` defines a `BLOCKED` member, but reading
`SessionController`'s actual source (`start()`, `submit_answer()`,
`_advance()`, `_finalize()`, pinned baseline 0580b1a5ba5867a607a33197372fca
f4164f0fb6) and then *empirically running real sessions* both confirm
`SessionState.BLOCKED` is never actually assigned anywhere — a genuine,
independently-confirmed non-guess correction to what the Reality Check's own
diagram implied. `SessionController` is synchronous and blocking: every
`start()`/`submit_answer()` call runs straight through to either (a) a real
next question (`session.pending_questions` non-empty, `session.state` left
at whatever intermediate value it was last set to — empirically observed as
`SYMPTOM_COLLECTION` throughout the question-answering phase) or (b) a
terminal state (`COMPLETED` or `ESCALATED`, both of which empirically always
carry a populated `session.result.garage_preparation_report`). The real
signal this adapter uses is therefore:

    session.state in (COMPLETED, ESCALATED)  -> terminal -> CPL COMPLETED
    session.pending_questions (non-empty)     -> CPL BLOCKED
    (anything else)                              -> UnexpectedPGDRSessionStateError
                                                     (the completeness guard, §34)

Per the PI-03 instruction's explicit, deliberate rule: ESCALATED maps to CPL
COMPLETED, never FAILED — a safety escalation is still a successful runner
report (the runner finished and reported something), exactly as B6's own
REQ-B6-007 discipline (execution completion is a representation fact, never
a domain-truth claim) already established for VIR's inconclusive outcomes in
PI-01.

Transaction boundary (§19, unchanged in spirit from PI-01's own pattern):
admit/transition to RUNNING and commit BEFORE calling into PGDR; call PGDR
with no open transaction; persist the result and commit AFTER PGDR returns.
No transaction is ever held open across a human-interaction interval (the
gap between `start_pgdr_session` returning BLOCKED and a later
`continue_pgdr_session` call) — confirmed structurally, since each function
opens and closes its own `session_scope()` blocks independently.

Session-object custody (§32, an explicit, disclosed limitation, not a
defect): PGDR's `SessionController` and `DiagnosticSession` are purely
in-memory — `SessionController` keeps its own authoritative analytical
state in `self._case_states`, keyed by `session.session_id`, with no
persistence path at all. This adapter does NOT invent persistence for
PGDR's internal state (explicitly out of scope, §32/§37) — the caller
(PI-04 or a future product/API layer) must keep the same `SessionController`
instance and the same `DiagnosticSession` object alive (or otherwise
reconstruct-equivalent) across turns of one session. This is a genuine
PRODUCT_GAP for a real multi-request-cycle deployment, not a COMMON_GAP —
nothing about CPL is deficient here; disclosed explicitly in the candidate
evidence, not silently absorbed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

from pgdr.enums import SessionState
from pgdr.models import Answer, DiagnosticSession, GaragePreparationReport, PreGarageDiagnosticRequest
from pgdr.session_controller import SessionController

from app.cpl.identity.authority import AuthorityContext
from app.cpl.runners.execution import admit_execution, transition_status, persist_runner_report
from app.cpl.runners.artifacts import register_artifact
from app.cpl.runners.outcomes import RunnerOutcome
from app.cpl.models.runner_artifact_schema_definition import RunnerArtifactSchemaDefinition
from app.cpl.models.runner_execution import RunnerExecution
from app.db.engine import session_scope

from product_integration.pgdr.adapter_errors import (
    PGDRAdapterError,
    PGDRSessionAlreadyTerminalError,
    UnexpectedPGDRSessionStateError,
)

PGDR_REPORT_SCHEMA_NAME = "pgdr_garage_preparation_report"
PGDR_REPORT_SCHEMA_VERSION = "1"

_TERMINAL_PGDR_STATES = frozenset({SessionState.COMPLETED, SessionState.ESCALATED})


class PGDRSessionOutcome:
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    AUTHORITY_REJECTION = "AUTHORITY_REJECTION"
    CONFLICT = "CONFLICT"
    CPL_PERSISTENCE_FAILURE = "CPL_PERSISTENCE_FAILURE"


@dataclass
class PGDRAdapterResult:
    outcome: str
    execution_id: Optional[UUID] = None
    session: Optional[DiagnosticSession] = None  # caller must retain this for the next turn, if BLOCKED
    pending_questions: list = field(default_factory=list)
    pgdr_session_state: Optional[str] = None
    artifact_id: Optional[UUID] = None
    detail: Optional[str] = None


def ensure_pgdr_report_schema_registered(session) -> None:
    """Idempotent registration of the minimal structural contract for
    'pgdr_garage_preparation_report' artifacts (REQ-B6-089's existing
    mechanism — no new registry). Kept minimal per the same discipline
    PI-01 applied to 'vir_resolution': enough for reproducibility, nothing
    speculative."""
    existing = session.get(
        RunnerArtifactSchemaDefinition, (PGDR_REPORT_SCHEMA_NAME, PGDR_REPORT_SCHEMA_VERSION)
    )
    if existing is not None:
        return
    session.add(RunnerArtifactSchemaDefinition(
        schema_name=PGDR_REPORT_SCHEMA_NAME,
        schema_version=PGDR_REPORT_SCHEMA_VERSION,
        required_fields=["report_id"],
        field_types={"report_id": "string"},
    ))


def _derive_outcome(pgdr_session: DiagnosticSession) -> str:
    """The single implementation of the empirically-derived status rule
    documented in this module's own docstring. Raises
    UnexpectedPGDRSessionStateError (the completeness guard) for anything
    that isn't one of the two real, observed signals."""
    if pgdr_session.state in _TERMINAL_PGDR_STATES:
        return PGDRSessionOutcome.COMPLETED
    if pgdr_session.pending_questions:
        return PGDRSessionOutcome.BLOCKED
    raise UnexpectedPGDRSessionStateError(pgdr_session.state, bool(pgdr_session.pending_questions))


def _admit_and_prepare(
    *, case_id: UUID, asset_id: UUID, idempotency_key: str, execution_purpose: str,
    resolver_version: str, authority: AuthorityContext,
) -> tuple[UUID, bool]:
    """Shared TX1: admit_execution + (if genuinely new) transition to
    RUNNING, committed together — the "required pre-call state" pattern
    PI-01 already established for exactly this reason (REQ-B6-009's
    transition table requires CREATED -> RUNNING before RUNNING ->
    COMPLETED/BLOCKED)."""
    with session_scope() as session:
        admission = admit_execution(
            session, case_id=case_id, asset_id=asset_id, runner_type="PGDR",
            runner_version=resolver_version, execution_purpose=execution_purpose,
            idempotency_key=idempotency_key, authority=authority,
        )
        if admission.outcome != RunnerOutcome.SUCCESS:
            session.commit()
            raise _AdmissionRejected(admission.outcome, admission.detail)
        execution_id = admission.object_id
        was_replay = bool(admission.payload.get("replay"))
        if not was_replay:
            transition_status(session, execution_id=execution_id, new_status="RUNNING", authority=authority)
        session.commit()
        return execution_id, was_replay


class _AdmissionRejected(Exception):
    def __init__(self, outcome: str, detail: Optional[str]):
        super().__init__(detail)
        self.outcome = outcome
        self.detail = detail


def _persist_current_state(
    *, execution_id: UUID, pgdr_session: DiagnosticSession, authority: AuthorityContext,
) -> PGDRAdapterResult:
    """Shared TX2 (§9/§19): persists whatever the PGDR session's current
    state actually is — either a BLOCKED transition (awaiting an answer) or
    a terminal COMPLETED finalization with its GaragePreparationReport
    artifact. Used identically after both start_pgdr_session's initial
    SessionController.start() call and continue_pgdr_session's
    submit_answer() call — one canonical persistence path, no duplicate
    logic."""
    outcome = _derive_outcome(pgdr_session)

    try:
        with session_scope() as session:
            if outcome == PGDRSessionOutcome.BLOCKED:
                result = transition_status(session, execution_id=execution_id, new_status="BLOCKED", authority=authority)
                if result.outcome != RunnerOutcome.SUCCESS:
                    session.rollback()
                    return _mark_failed(execution_id, detail=f"BLOCKED transition outcome {result.outcome!r}", authority=authority)
                session.commit()
                return PGDRAdapterResult(
                    outcome=PGDRSessionOutcome.BLOCKED, execution_id=execution_id, session=pgdr_session,
                    pending_questions=list(pgdr_session.pending_questions), pgdr_session_state=pgdr_session.state.value,
                )

            # terminal — §26: ESCALATED maps to COMPLETED, exactly like COMPLETED itself.
            ensure_pgdr_report_schema_registered(session)
            report: Optional[GaragePreparationReport] = (
                pgdr_session.result.garage_preparation_report if pgdr_session.result is not None else None
            )
            if report is None:
                session.rollback()
                return _mark_failed(
                    execution_id, detail="terminal PGDR session produced no garage_preparation_report", authority=authority,
                )

            artifact_result = register_artifact(
                session, execution_id=execution_id, artifact_type=PGDR_REPORT_SCHEMA_NAME,
                schema_name=PGDR_REPORT_SCHEMA_NAME, schema_version=PGDR_REPORT_SCHEMA_VERSION,
                payload=report.model_dump(mode="json"),
                semantic_function="DOMAIN_DETERMINATION_CARRIER", lifecycle_role="FINAL",
                presentation_role="INTERNAL", authority=authority,
            )
            if artifact_result.outcome != RunnerOutcome.SUCCESS:
                session.rollback()
                return _mark_failed(execution_id, detail=f"artifact registration outcome {artifact_result.outcome!r}", authority=authority)

            report_result = persist_runner_report(session, execution_id=execution_id, new_status="COMPLETED", authority=authority)
            if report_result.outcome != RunnerOutcome.SUCCESS:
                session.rollback()
                return _mark_failed(execution_id, detail=f"final report outcome {report_result.outcome!r}", authority=authority)

            session.commit()
            return PGDRAdapterResult(
                outcome=PGDRSessionOutcome.COMPLETED, execution_id=execution_id, session=pgdr_session,
                pending_questions=[], pgdr_session_state=pgdr_session.state.value,
                artifact_id=artifact_result.object_id,
            )
    except Exception as exc:  # noqa: BLE001 — genuine CPL persistence failure
        return _mark_failed(execution_id, detail=f"CPL persistence failure: {exc}", authority=authority)


def start_pgdr_session(
    *,
    session_controller: SessionController,
    request: PreGarageDiagnosticRequest,
    case_id: UUID,
    asset_id: UUID,
    vir_artifact_id: Optional[UUID],
    authority: AuthorityContext,
    resolver_version: str = "unknown",
) -> PGDRAdapterResult:
    """Admits one governed CPL RunnerExecution for the whole bounded PGDR
    session (§12 — never one per question/answer turn) and drives the
    real, non-interactive `SessionController.start()`.

    `vir_artifact_id`, when supplied, is recorded as VIR-artifact
    provenance for this execution's own admission (Reality Check §15's
    exact mechanism: the EXECUTION_ADMISSION RunnerGovernanceDecision's
    `new_value` JSONB already includes `execution_purpose` verbatim,
    confirmed by direct source read of `admit_execution` — no new CPL
    column, table, or schema element is introduced; `execution_purpose`
    is simply given a structured, parseable value)."""
    execution_purpose = "pgdr_diagnostic_session"
    if vir_artifact_id is not None:
        execution_purpose = f"pgdr_diagnostic_session:vir_artifact_id={vir_artifact_id}"

    try:
        execution_id, was_replay = _admit_and_prepare(
            case_id=case_id, asset_id=asset_id, idempotency_key=request.request_id,
            execution_purpose=execution_purpose, resolver_version=resolver_version, authority=authority,
        )
    except _AdmissionRejected as rejected:
        mapped_outcome = (
            PGDRSessionOutcome.CONFLICT if rejected.outcome == RunnerOutcome.CONFLICT
            else PGDRSessionOutcome.AUTHORITY_REJECTION
        )
        return PGDRAdapterResult(outcome=mapped_outcome, detail=f"admission outcome was {rejected.outcome!r}: {rejected.detail}")

    if was_replay:
        return _existing_terminal_or_blocked_result(execution_id)

    # No open DB transaction during this call — SessionController.start()
    # is a pure in-process, synchronous computation (confirmed: no I/O in
    # PGDR's own source), but the discipline is identical in spirit to
    # PI-01's "no transaction held open across an external wait" rule.
    try:
        pgdr_session = session_controller.start(request)
    except Exception as exc:  # noqa: BLE001 — a genuine PGDR-side failure
        return _mark_failed(execution_id, detail=f"PGDR start() failed: {exc}", authority=authority)

    return _persist_current_state(execution_id=execution_id, pgdr_session=pgdr_session, authority=authority)


def continue_pgdr_session(
    *,
    session_controller: SessionController,
    pgdr_session: DiagnosticSession,
    answer: Answer,
    execution_id: UUID,
    authority: AuthorityContext,
) -> PGDRAdapterResult:
    """Resumes an existing governed PGDR RunnerExecution with a real,
    caller-supplied answer (§23 — never a fabricated one). Refuses
    immediately, without calling PGDR at all, if the execution is already
    terminal (§30's exactly-once guarantee, checked before any PGDR call,
    not only relied upon via CPL's own terminal-transition rejection)."""
    with session_scope() as session:
        execution = session.get(RunnerExecution, execution_id)
        if execution is None or execution.execution_status not in ("BLOCKED",):
            if execution is not None and execution.execution_status == "COMPLETED":
                raise PGDRSessionAlreadyTerminalError(execution_id)
            # Any other unexpected prior state is a genuine adapter-input
            # problem, not a PGDR or CPL failure — surfaced distinctly.
            raise PGDRAdapterError(
                f"continue_pgdr_session requires a BLOCKED execution; "
                f"{execution_id} is {execution.execution_status if execution else 'not found'}"
            )
        transition_status(session, execution_id=execution_id, new_status="RUNNING", authority=authority)
        session.commit()

    try:
        resumed_session = session_controller.submit_answer(pgdr_session, answer)
    except Exception as exc:  # noqa: BLE001
        return _mark_failed(execution_id, detail=f"PGDR submit_answer() failed: {exc}", authority=authority)

    return _persist_current_state(execution_id=execution_id, pgdr_session=resumed_session, authority=authority)


def _existing_terminal_or_blocked_result(execution_id: UUID) -> PGDRAdapterResult:
    """REQ-B6-036 replay (same idempotency_key re-submitted): reconstructs
    the result from already-persisted CPL state, exactly as PI-01's own
    replay handling does. The PGDR DiagnosticSession object itself cannot
    be reconstructed (§32 — no PGDR-side persistence exists), so a replay
    can only report CPL-side state, never re-hand back a live session
    object; this is disclosed explicitly, not silently degraded."""
    with session_scope() as session:
        execution = session.get(RunnerExecution, execution_id)
        status = execution.execution_status if execution is not None else None
        outcome = PGDRSessionOutcome.COMPLETED if status == "COMPLETED" else PGDRSessionOutcome.BLOCKED
        return PGDRAdapterResult(
            outcome=outcome, execution_id=execution_id, session=None,
            detail="replay: returned existing CPL execution state; the PGDR session object itself is not "
                   "reconstructable (PGDR has no persistence) and is not returned on replay",
        )


def _mark_failed(execution_id: UUID, *, detail: str, authority: AuthorityContext) -> PGDRAdapterResult:
    """Best-effort: mark the already-admitted execution FAILED in its own
    short transaction — never masks the original failure if this itself
    fails. Unchanged pattern from PI-01."""
    try:
        with session_scope() as session:
            persist_runner_report(session, execution_id=execution_id, new_status="FAILED", authority=authority)
            session.commit()
    except Exception:  # noqa: BLE001
        pass
    return PGDRAdapterResult(outcome=PGDRSessionOutcome.CPL_PERSISTENCE_FAILURE, execution_id=execution_id, detail=detail)
