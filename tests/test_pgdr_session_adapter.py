"""PI-03 test suite.

Real, non-interactive PGDR SessionController, real PostgreSQL. No mock-only
persistence verification anywhere in this file.
"""
from __future__ import annotations

import uuid

import pytest

from app.db.engine import SessionLocal
from app.cpl.models.runner_execution import RunnerExecution
from app.cpl.models.runner_artifact import RunnerArtifact
from app.cpl.models.runner_governance_decision import RunnerGovernanceDecision

from pgdr.session_controller import SessionController
from pgdr.enums import SessionState
from pgdr.models import Answer, Consent, InitialComplaint, PreGarageDiagnosticRequest, UserContext, VehicleIdentityContext
from pgdr.enums import ResolutionStatus as PGDRResolutionStatus

from product_integration.pgdr.adapter_errors import (
    PGDRAdapterError,
    PGDRSessionAlreadyTerminalError,
    UnexpectedPGDRSessionStateError,
)
from product_integration.pgdr.session_adapter import (
    PGDRSessionOutcome,
    continue_pgdr_session,
    start_pgdr_session,
)


def make_request(complaint: str, request_id: str | None = None, **overrides) -> PreGarageDiagnosticRequest:
    defaults = dict(
        request_id=request_id or f"PI03-TEST-{uuid.uuid4().hex[:12]}",
        vehicle_identity_context=VehicleIdentityContext(
            resolution_id=f"VIR-RES-{uuid.uuid4().hex[:8]}", resolution_status=PGDRResolutionStatus.RESOLVED,
        ),
        initial_complaint=InitialComplaint(free_text=complaint),
        user_context=UserContext(),
        consent=Consent(report_storage_allowed=True),
    )
    defaults.update(overrides)
    return PreGarageDiagnosticRequest(**defaults)


NOISE_COMPLAINT = "The engine makes a strange noise when accelerating."
SMOKE_COMPLAINT = "There is smoke coming from under the hood and a burning smell."


def drive_to_completion(sc: SessionController, result, authority, max_turns: int = 15):
    """Test helper: answers every pending question with its first offered
    choice (or a literal 'yes') until the session terminates. Test-only —
    production code never fabricates an answer (§23)."""
    turns = 0
    while result.outcome == PGDRSessionOutcome.BLOCKED and turns < max_turns:
        turns += 1
        q = result.pending_questions[0]
        answer_value = q.choices[0] if q.choices else "yes"
        result = continue_pgdr_session(
            session_controller=sc, pgdr_session=result.session,
            answer=Answer(question_id=q.question_id, value=answer_value),
            execution_id=result.execution_id, authority=authority,
        )
    return result


class TestPGDRSessionAdapter:

    # -- Core lifecycle: BLOCKED path is mandatory (§27) --------------------

    def test_blocked_path_full_multiturn_cycle(self, cpl_case_context, full_authority):
        sc = SessionController()
        request = make_request(NOISE_COMPLAINT)
        result = start_pgdr_session(
            session_controller=sc, request=request, case_id=cpl_case_context["case_id"],
            asset_id=cpl_case_context["asset_id"], vir_artifact_id=None, authority=full_authority,
        )
        assert result.outcome == PGDRSessionOutcome.BLOCKED
        assert len(result.pending_questions) >= 1

        session = SessionLocal()
        execution = session.get(RunnerExecution, result.execution_id)
        assert execution.execution_status == "BLOCKED"
        session.close()

        # At least one real submit_answer() (§27's explicit requirement).
        q = result.pending_questions[0]
        answer_value = q.choices[0] if q.choices else "yes"
        result = continue_pgdr_session(
            session_controller=sc, pgdr_session=result.session, answer=Answer(question_id=q.question_id, value=answer_value),
            execution_id=result.execution_id, authority=full_authority,
        )
        session = SessionLocal()
        execution = session.get(RunnerExecution, result.execution_id)
        assert execution.execution_status in ("BLOCKED", "COMPLETED")  # RUNNING was transient, already past it
        session.close()

        final = drive_to_completion(sc, result, full_authority)
        assert final.outcome == PGDRSessionOutcome.COMPLETED
        assert final.artifact_id is not None

        session = SessionLocal()
        execution = session.get(RunnerExecution, final.execution_id)
        artifact = session.get(RunnerArtifact, final.artifact_id)
        assert execution.execution_status == "COMPLETED"
        assert artifact is not None
        assert artifact.execution_id == final.execution_id
        assert artifact.artifact_type == "pgdr_garage_preparation_report"
        session.close()

    # -- ESCALATED path is mandatory (§26) -----------------------------------

    def test_escalated_path_maps_to_cpl_completed_never_failed(self, cpl_case_context, full_authority):
        sc = SessionController()
        request = make_request(SMOKE_COMPLAINT)
        result = start_pgdr_session(
            session_controller=sc, request=request, case_id=cpl_case_context["case_id"],
            asset_id=cpl_case_context["asset_id"], vir_artifact_id=None, authority=full_authority,
        )
        assert result.outcome == PGDRSessionOutcome.COMPLETED
        assert result.pgdr_session_state == "escalated"
        assert result.artifact_id is not None

        session = SessionLocal()
        execution = session.get(RunnerExecution, result.execution_id)
        artifact = session.get(RunnerArtifact, result.artifact_id)
        assert execution.execution_status == "COMPLETED"  # never FAILED
        assert artifact is not None
        assert artifact.artifact_type == "pgdr_garage_preparation_report"
        session.close()

    def test_escalated_reachable_via_safety_engine_real_rules(self, cpl_case_context, full_authority):
        """Confirms the ESCALATED path is reached through PGDR's REAL
        SafetyEngine rule evaluation (config-driven keyword match), not a
        contrived shortcut."""
        sc = SessionController()
        request = make_request(SMOKE_COMPLAINT)
        result = start_pgdr_session(
            session_controller=sc, request=request, case_id=cpl_case_context["case_id"],
            asset_id=cpl_case_context["asset_id"], vir_artifact_id=None, authority=full_authority,
        )
        assert result.session.safety_triage is not None
        assert result.session.safety_triage.level.value == "emergency_stop"
        assert "PGDR-SAF-004" in result.session.safety_triage.triggered_rules

    # -- SessionState -> CPL mapping completeness guard (§34) ----------------

    def test_unexpected_pgdr_state_raises_completeness_guard(self):
        from product_integration.pgdr.session_adapter import _derive_outcome
        from pgdr.models import DiagnosticSession

        fake_session = DiagnosticSession(request=make_request(NOISE_COMPLAINT))
        fake_session.state = SessionState.REASONING  # a real enum value, but neither terminal nor pending
        with pytest.raises(UnexpectedPGDRSessionStateError):
            _derive_outcome(fake_session)

    def test_all_reachable_states_covered(self):
        """Documents, exhaustively, every SessionState this adapter's
        signal derivation actually classifies, matching PI-02's own
        completeness-guard pattern."""
        from product_integration.pgdr.session_adapter import _TERMINAL_PGDR_STATES
        assert _TERMINAL_PGDR_STATES == {SessionState.COMPLETED, SessionState.ESCALATED}
        # SessionState.BLOCKED is a real enum member but empirically never
        # assigned by SessionController (confirmed directly against source
        # and by live execution) -- not part of the terminal set, and the
        # adapter's own "needs an answer" signal is pending_questions, not
        # this value.
        assert SessionState.BLOCKED not in _TERMINAL_PGDR_STATES

    # -- VIR artifact provenance (§16/§17) ------------------------------------

    def test_vir_artifact_provenance_recorded_in_admission_decision(self, cpl_case_context, full_authority):
        sc = SessionController()
        vir_artifact_id = uuid.uuid4()
        request = make_request(NOISE_COMPLAINT)
        result = start_pgdr_session(
            session_controller=sc, request=request, case_id=cpl_case_context["case_id"],
            asset_id=cpl_case_context["asset_id"], vir_artifact_id=vir_artifact_id, authority=full_authority,
        )
        session = SessionLocal()
        decision = (
            session.query(RunnerGovernanceDecision)
            .filter(RunnerGovernanceDecision.execution_id == result.execution_id,
                     RunnerGovernanceDecision.decision_type == "EXECUTION_ADMISSION")
            .first()
        )
        assert decision is not None
        assert str(vir_artifact_id) in decision.new_value["execution_purpose"]
        session.close()

    def test_no_vir_artifact_provenance_when_not_supplied(self, cpl_case_context, full_authority):
        sc = SessionController()
        result = start_pgdr_session(
            session_controller=sc, request=make_request(NOISE_COMPLAINT), case_id=cpl_case_context["case_id"],
            asset_id=cpl_case_context["asset_id"], vir_artifact_id=None, authority=full_authority,
        )
        session = SessionLocal()
        execution = session.get(RunnerExecution, result.execution_id)
        assert execution.execution_purpose == "pgdr_diagnostic_session"
        assert "vir_artifact_id" not in execution.execution_purpose
        session.close()

    # -- No open transaction across a BLOCKED wait (§33, mandatory) ---------

    def test_no_open_transaction_across_blocked_wait(self, cpl_case_context, full_authority):
        """Independently confirms each adapter call opens/closes its own
        transaction: querying from a completely SEPARATE connection while
        the 'session' is conceptually paused (between start_pgdr_session
        returning BLOCKED and the test's own next continue_pgdr_session
        call) must see the committed BLOCKED state -- impossible if a
        transaction were still open on the original connection."""
        sc = SessionController()
        result = start_pgdr_session(
            session_controller=sc, request=make_request(NOISE_COMPLAINT), case_id=cpl_case_context["case_id"],
            asset_id=cpl_case_context["asset_id"], vir_artifact_id=None, authority=full_authority,
        )
        assert result.outcome == PGDRSessionOutcome.BLOCKED

        # A brand-new, independent connection/session -- if a transaction
        # were still open elsewhere, this would either block or see stale
        # (pre-BLOCKED) state depending on isolation level; it sees neither.
        independent_session = SessionLocal()
        execution = independent_session.get(RunnerExecution, result.execution_id)
        assert execution.execution_status == "BLOCKED"
        independent_session.close()

    # -- Exactly-once terminal artifact (§30, mandatory) ---------------------

    def test_exactly_once_terminal_artifact_on_repeated_continue_after_terminal(self, cpl_case_context, full_authority):
        sc = SessionController()
        result = start_pgdr_session(
            session_controller=sc, request=make_request(SMOKE_COMPLAINT), case_id=cpl_case_context["case_id"],
            asset_id=cpl_case_context["asset_id"], vir_artifact_id=None, authority=full_authority,
        )
        assert result.outcome == PGDRSessionOutcome.COMPLETED  # SMOKE_COMPLAINT escalates immediately

        # Accidentally calling continue_pgdr_session again on an
        # already-terminal execution must be refused BEFORE PGDR is
        # touched again, not silently produce a second artifact.
        with pytest.raises(PGDRSessionAlreadyTerminalError):
            continue_pgdr_session(
                session_controller=sc, pgdr_session=result.session,
                answer=Answer(question_id="irrelevant", value="x"),
                execution_id=result.execution_id, authority=full_authority,
            )

        session = SessionLocal()
        artifact_count = session.query(RunnerArtifact).filter(RunnerArtifact.execution_id == result.execution_id).count()
        assert artifact_count == 1
        session.close()

    def test_exactly_once_on_replayed_start(self, cpl_case_context, full_authority):
        sc = SessionController()
        request = make_request(SMOKE_COMPLAINT, request_id=f"PI03-REPLAY-{uuid.uuid4().hex[:8]}")
        r1 = start_pgdr_session(
            session_controller=sc, request=request, case_id=cpl_case_context["case_id"],
            asset_id=cpl_case_context["asset_id"], vir_artifact_id=None, authority=full_authority,
        )
        assert r1.outcome == PGDRSessionOutcome.COMPLETED

        r2 = start_pgdr_session(
            session_controller=sc, request=request, case_id=cpl_case_context["case_id"],
            asset_id=cpl_case_context["asset_id"], vir_artifact_id=None, authority=full_authority,
        )
        assert r2.execution_id == r1.execution_id  # replay, not a new admission

        session = SessionLocal()
        artifact_count = session.query(RunnerArtifact).filter(RunnerArtifact.execution_id == r1.execution_id).count()
        assert artifact_count == 1
        session.close()

    # -- Failure atomicity (mandatory) ---------------------------------------

    def test_failure_atomicity_terminal_persistence_failure_leaves_no_masquerading_state(self, cpl_case_context, full_authority, monkeypatch):
        sc = SessionController()
        result = start_pgdr_session(
            session_controller=sc, request=make_request(SMOKE_COMPLAINT), case_id=cpl_case_context["case_id"],
            asset_id=cpl_case_context["asset_id"], vir_artifact_id=None, authority=full_authority,
        )
        # This particular request already terminated inside start(); use a
        # fresh one and inject the failure at the terminal registration step.
        import product_integration.pgdr.session_adapter as adapter_module
        original_register_artifact = adapter_module.register_artifact
        def _boom(*a, **k):
            raise RuntimeError("PI-03 injected terminal persistence failure")
        adapter_module.register_artifact = _boom
        try:
            sc2 = SessionController()
            result2 = start_pgdr_session(
                session_controller=sc2, request=make_request(SMOKE_COMPLAINT, request_id=f"PI03-FAIL-{uuid.uuid4().hex[:8]}"),
                case_id=cpl_case_context["case_id"], asset_id=cpl_case_context["asset_id"],
                vir_artifact_id=None, authority=full_authority,
            )
        finally:
            adapter_module.register_artifact = original_register_artifact

        assert result2.outcome == PGDRSessionOutcome.CPL_PERSISTENCE_FAILURE
        session = SessionLocal()
        execution = session.get(RunnerExecution, result2.execution_id)
        assert execution.execution_status == "FAILED"  # never masquerades as COMPLETED
        artifact_count = session.query(RunnerArtifact).filter(RunnerArtifact.execution_id == result2.execution_id).count()
        assert artifact_count == 0
        session.close()

    # -- Restart durability (mandatory) --------------------------------------

    def test_restart_durability_full_linked_state_survives(self, cpl_case_context, full_authority):
        sc = SessionController()
        vir_artifact_id = uuid.uuid4()
        result = start_pgdr_session(
            session_controller=sc, request=make_request(SMOKE_COMPLAINT), case_id=cpl_case_context["case_id"],
            asset_id=cpl_case_context["asset_id"], vir_artifact_id=vir_artifact_id, authority=full_authority,
        )
        assert result.outcome == PGDRSessionOutcome.COMPLETED

        fresh_session = SessionLocal()
        execution = fresh_session.get(RunnerExecution, result.execution_id)
        artifact = fresh_session.get(RunnerArtifact, result.artifact_id)
        decision = (
            fresh_session.query(RunnerGovernanceDecision)
            .filter(RunnerGovernanceDecision.execution_id == result.execution_id,
                     RunnerGovernanceDecision.decision_type == "EXECUTION_ADMISSION")
            .first()
        )
        assert execution is not None and execution.execution_status == "COMPLETED"
        assert execution.case_id == cpl_case_context["case_id"]
        assert artifact is not None and artifact.execution_id == execution.execution_id
        assert decision is not None
        assert str(vir_artifact_id) in decision.new_value["execution_purpose"]
        fresh_session.close()

    # -- Adapter input errors (§25) -------------------------------------------

    def test_continue_on_nonexistent_execution_raises_adapter_error(self, full_authority):
        sc = SessionController()
        with pytest.raises(PGDRAdapterError):
            continue_pgdr_session(
                session_controller=sc, pgdr_session=None, answer=Answer(question_id="x", value="y"),
                execution_id=uuid.uuid4(), authority=full_authority,
            )

    # -- Regression: one execution per session, not per turn (§12) -----------

    def test_one_execution_for_entire_multiturn_session(self, cpl_case_context, full_authority):
        sc = SessionController()
        result = start_pgdr_session(
            session_controller=sc, request=make_request(NOISE_COMPLAINT), case_id=cpl_case_context["case_id"],
            asset_id=cpl_case_context["asset_id"], vir_artifact_id=None, authority=full_authority,
        )
        execution_id = result.execution_id
        final = drive_to_completion(sc, result, full_authority)
        assert final.execution_id == execution_id  # same execution throughout, never a new one per turn

        session = SessionLocal()
        count = session.query(RunnerExecution).filter(RunnerExecution.execution_id == execution_id).count()
        assert count == 1
        session.close()


class TestPI03VF01Repair:
    """PI-03-VF-01 repair tests (docs/build/PI_03_VF_01_REPAIR_EVIDENCE_v0.md).

    Independent verification (docs/build/PI_03_INDEPENDENT_VERIFICATION_v0.md)
    found that a PGDR-side/session-continuity failure -- specifically, the
    real KeyError SessionController.submit_answer() raises when a session
    started by one controller instance is resumed through a genuinely
    different instance -- was reported through the adapter's public API as
    outcome=CPL_PERSISTENCE_FAILURE, indistinguishable from an actual CPL
    database failure. These tests prove the two are now distinguishable,
    per the repair instruction's own §12/§13/§14 mandatory tests."""

    # -- §12: cross-controller resume classification -------------------------

    def test_cross_controller_resume_failure_is_not_cpl_persistence_failure(self, cpl_case_context, full_authority):
        controller_a = SessionController()
        result = start_pgdr_session(
            session_controller=controller_a, request=make_request(NOISE_COMPLAINT),
            case_id=cpl_case_context["case_id"], asset_id=cpl_case_context["asset_id"],
            vir_artifact_id=None, authority=full_authority,
        )
        assert result.outcome == PGDRSessionOutcome.BLOCKED

        controller_b = SessionController()
        assert controller_b is not controller_a  # genuinely distinct instance, not a reused reference

        q = result.pending_questions[0]
        answer_value = q.choices[0] if q.choices else "yes"
        resumed = continue_pgdr_session(
            session_controller=controller_b, pgdr_session=result.session,
            answer=Answer(question_id=q.question_id, value=answer_value),
            execution_id=result.execution_id, authority=full_authority,
        )

        assert resumed.outcome != PGDRSessionOutcome.CPL_PERSISTENCE_FAILURE
        assert resumed.outcome == PGDRSessionOutcome.PGDR_TECHNICAL_FAILURE

        session = SessionLocal()
        execution = session.get(RunnerExecution, result.execution_id)
        assert execution.execution_status == "FAILED"  # still correctly terminalized at the CPL layer
        session.close()

    # -- §13: genuine CPL persistence failure classification -----------------

    def test_genuine_cpl_persistence_failure_still_classified_correctly(self, cpl_case_context, full_authority, monkeypatch):
        import product_integration.pgdr.session_adapter as adapter_module

        original_register_artifact = adapter_module.register_artifact
        def _boom(*a, **k):
            raise RuntimeError("genuine injected CPL persistence failure")
        adapter_module.register_artifact = _boom
        try:
            sc = SessionController()
            result = start_pgdr_session(
                session_controller=sc, request=make_request(SMOKE_COMPLAINT), case_id=cpl_case_context["case_id"],
                asset_id=cpl_case_context["asset_id"], vir_artifact_id=None, authority=full_authority,
            )
        finally:
            adapter_module.register_artifact = original_register_artifact

        assert result.outcome == PGDRSessionOutcome.CPL_PERSISTENCE_FAILURE

        session = SessionLocal()
        execution = session.get(RunnerExecution, result.execution_id)
        assert execution.execution_status == "FAILED"
        artifact_count = session.query(RunnerArtifact).filter(RunnerArtifact.execution_id == result.execution_id).count()
        assert artifact_count == 0
        session.close()

    # -- §14: explicit semantic pair test -------------------------------------

    def test_pgdr_technical_failure_and_cpl_persistence_failure_are_distinct_values(self):
        assert PGDRSessionOutcome.PGDR_TECHNICAL_FAILURE != PGDRSessionOutcome.CPL_PERSISTENCE_FAILURE
        all_outcomes = {
            PGDRSessionOutcome.BLOCKED, PGDRSessionOutcome.COMPLETED, PGDRSessionOutcome.AUTHORITY_REJECTION,
            PGDRSessionOutcome.CONFLICT, PGDRSessionOutcome.CPL_PERSISTENCE_FAILURE,
            PGDRSessionOutcome.PGDR_TECHNICAL_FAILURE,
        }
        assert len(all_outcomes) == 6  # all six values genuinely distinct strings

    # -- §16: preserve ESCALATED semantics (regression, re-run explicitly) ----

    def test_escalated_still_maps_to_completed_after_repair(self, cpl_case_context, full_authority):
        sc = SessionController()
        result = start_pgdr_session(
            session_controller=sc, request=make_request(SMOKE_COMPLAINT), case_id=cpl_case_context["case_id"],
            asset_id=cpl_case_context["asset_id"], vir_artifact_id=None, authority=full_authority,
        )
        assert result.outcome == PGDRSessionOutcome.COMPLETED
        assert result.pgdr_session_state == "escalated"

    # -- §7/§25: repair must not solve the underlying PGDR limitation --------

    def test_underlying_pgdr_limitation_remains_unchanged(self, cpl_case_context, full_authority):
        """The repair does not (and must not) make cross-controller resume
        actually work -- only its reported classification changed. This
        documents that the KeyError itself is still real, unmodified PGDR
        behavior, not silently papered over."""
        controller_a = SessionController()
        result = start_pgdr_session(
            session_controller=controller_a, request=make_request(NOISE_COMPLAINT),
            case_id=cpl_case_context["case_id"], asset_id=cpl_case_context["asset_id"],
            vir_artifact_id=None, authority=full_authority,
        )
        controller_b = SessionController()
        q = result.pending_questions[0]
        with pytest.raises(KeyError):
            controller_b.submit_answer(result.session, Answer(question_id=q.question_id, value="yes"))
