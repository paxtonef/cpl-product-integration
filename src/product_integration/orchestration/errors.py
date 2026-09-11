"""PI-04 orchestration error taxonomy.

Distinct types per §21's required failure-boundary categories that aren't
already covered by PI-01/PI-02/PI-03's own outcome vocabularies (which are
reused/passed through directly, not re-wrapped, wherever they already exist).
"""
from __future__ import annotations

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
