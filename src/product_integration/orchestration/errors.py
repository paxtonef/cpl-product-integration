"""PI-04 orchestration error taxonomy.

Distinct types per §21's required failure-boundary categories that aren't
already covered by PI-01/PI-02/PI-03's own outcome vocabularies (which are
reused/passed through directly, not re-wrapped, wherever they already exist).
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID


class CaseOrchestrationError(Exception):
    """Base for all PI-04-raised errors."""


class VIRArtifactNotFoundError(CaseOrchestrationError):
    """start_vehicle_diagnostic could not find a VIR RunnerExecution/
    RunnerArtifact for the given case_id — the caller attempted to start
    a diagnostic before (or without ever) resolving vehicle identity."""

    def __init__(self, case_id: UUID):
        super().__init__(f"no VIR resolution found for case {case_id} — call resolve_vehicle_identity first")
        self.case_id = case_id


class CaseNotFoundError(CaseOrchestrationError):
    def __init__(self, case_id: UUID):
        super().__init__(f"case {case_id} not found")
        self.case_id = case_id


class CaseOrchestrationTransitionError(CaseOrchestrationError):
    """PI-04-VF-01 repair: raised (never silently swallowed, never let to
    propagate as a raw underlying exception) when a PGDR domain result has
    already been correctly and durably persisted by PI-03, but the
    subsequent Case-side synchronization (current_execution_id + status
    transition) could not be completed.

    This is NOT a PGDR failure and NOT a generic CPL persistence failure —
    the PGDR RunnerExecution itself is valid and untouched; only the
    Case's own summary of that fact failed to update. Carries everything
    needed to safely reconcile later via `reconcile_case_orchestration`,
    using the already-persisted PGDR execution as the source of truth —
    never by re-invoking PGDR, never by creating a new Case or execution."""

    def __init__(
        self, *, case_id: UUID, pgdr_execution_id: Optional[UUID], observed_pgdr_status: str,
        intended_case_status: str, underlying_error: str,
    ):
        super().__init__(
            f"PGDR outcome {observed_pgdr_status!r} was persisted correctly for execution "
            f"{pgdr_execution_id}, but Case {case_id}'s synchronization to {intended_case_status!r} failed: "
            f"{underlying_error}"
        )
        self.case_id = case_id
        self.pgdr_execution_id = pgdr_execution_id
        self.observed_pgdr_status = observed_pgdr_status
        self.intended_case_status = intended_case_status
        self.underlying_error = underlying_error
