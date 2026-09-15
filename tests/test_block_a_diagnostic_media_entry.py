"""Block A — Diagnostic Media Entry — acceptance tests.

VIR_PHOTO_PGDR_BUILD_DECOMPOSITION_v1, §A. Verifies only what Block A
itself promises: a primary diagnostic media reference transports through
PI (API -> orchestration -> PI-03 adapter) to the PGDR boundary, without
producing any Observation/Identification/Confidence/Evidence, without
reusing Q-EVI-002, and without regressing the existing text-only path.

Run against a real, running PI-05 server (real PostgreSQL, real VIR) --
matching this project's own established discipline of never accepting a
mocked backend for acceptance evidence.
"""
import uuid

import httpx
import pytest

BASE_URL = "http://127.0.0.1:8000"


def _register_and_resolve() -> str:
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        vehicle = client.post(
            "/vehicles",
            json={
                "contact_idempotency_key": f"blocka-c-{uuid.uuid4().hex[:10]}",
                "asset_idempotency_key": f"blocka-a-{uuid.uuid4().hex[:10]}",
            },
        ).json()
        case = client.post(
            "/cases",
            json={
                "contact_id": vehicle["contact_id"], "asset_id": vehicle["asset_id"],
                "request_id": f"blocka-case-{uuid.uuid4().hex[:10]}",
                "vin": "VF3XXXXXXXXXXXXXX",
                "case_idempotency_key": f"blocka-case-idem-{uuid.uuid4().hex[:10]}",
                "consent": {"external_lookup_allowed": True},
            },
        )
        assert case.status_code == 201, case.text
        return case.json()["case_id"]


class TestBlockAAcceptance:
    def test_1_diagnostic_starts_with_media_reference_only_no_complaint_text(self):
        """AC1: starting a diagnostic with ONLY a primary diagnostic media
        reference (no complaint_text) succeeds at the API level."""
        case_id = _register_and_resolve()
        with httpx.Client(base_url=BASE_URL, timeout=30) as client:
            response = client.post(
                f"/cases/{case_id}/diagnostics",
                json={"primary_diagnostic_media_reference": "media-ref-block-a-001"},
            )
        assert response.status_code in (200, 201), response.text

    def test_2_existing_text_only_path_unchanged(self):
        """AC2: the existing text-only diagnostic path remains unaffected."""
        case_id = _register_and_resolve()
        with httpx.Client(base_url=BASE_URL, timeout=30) as client:
            response = client.post(
                f"/cases/{case_id}/diagnostics",
                json={"complaint_text": "Le moteur fait un bruit étrange."},
            )
        assert response.status_code in (200, 201), response.text

    def test_3_neither_text_nor_media_is_rejected(self):
        """AC3 (validation boundary): omitting both fields is rejected,
        never silently accepted as an empty diagnostic."""
        case_id = _register_and_resolve()
        with httpx.Client(base_url=BASE_URL, timeout=30) as client:
            response = client.post(f"/cases/{case_id}/diagnostics", json={})
        assert response.status_code == 422

    def test_4_media_reference_reaches_pi03_execution_provenance(self):
        """AC4 (the core Block A stop condition): the primary diagnostic
        media reference reaches PI-03's own governed-execution provenance
        (execution_purpose) -- confirmed by direct inspection of the real
        RunnerGovernanceDecision recorded for this execution's admission."""
        from app.db.engine import SessionLocal
        from app.cpl.models.runner_execution import RunnerExecution
        from app.cpl.models.runner_governance_decision import RunnerGovernanceDecision

        case_id = _register_and_resolve()
        ref = f"media-ref-provenance-{uuid.uuid4().hex[:8]}"
        with httpx.Client(base_url=BASE_URL, timeout=30) as client:
            response = client.post(
                f"/cases/{case_id}/diagnostics",
                json={"primary_diagnostic_media_reference": ref},
            )
        assert response.status_code in (200, 201), response.text

        session = SessionLocal()
        try:
            execution = (
                session.query(RunnerExecution)
                .filter(RunnerExecution.case_id == uuid.UUID(case_id), RunnerExecution.runner_type == "PGDR")
                .order_by(RunnerExecution.created_at.desc())
                .first()
            )
            assert execution is not None
            admission_decision = (
                session.query(RunnerGovernanceDecision)
                .filter(
                    RunnerGovernanceDecision.execution_id == execution.execution_id,
                    RunnerGovernanceDecision.decision_type == "EXECUTION_ADMISSION",
                )
                .order_by(RunnerGovernanceDecision.decided_at.asc())
                .first()
            )
            assert admission_decision is not None
            purpose = admission_decision.new_value.get("execution_purpose", "")
            assert f"primary_diagnostic_media_reference={ref}" in purpose
        finally:
            session.close()

    def test_5_no_observation_evidence_synthesized_by_block_a_code(self):
        """AC5: Block A's own new code (session_adapter.py's
        start_pgdr_session) does not construct any Observation or Evidence
        object itself -- the only code this block adds."""
        import inspect
        from product_integration.pgdr import session_adapter
        source = inspect.getsource(session_adapter.start_pgdr_session)
        assert "Observation(" not in source
        assert "Evidence(" not in source

    def test_6_q_evi_002_not_reused_as_foundation(self):
        """AC6: Block A's new code does not invoke the existing Q-EVI-002
        media-answer mechanism (submit_answer / media_upload handling) --
        only mentions it in documentation explaining it is NOT reused."""
        import inspect
        from product_integration.pgdr import session_adapter
        from product_integration.orchestration import case_orchestration
        for module_source in (
            inspect.getsource(session_adapter.start_pgdr_session),
            inspect.getsource(case_orchestration.start_vehicle_diagnostic),
        ):
            assert "submit_answer(" not in module_source
            assert 'answer_type' not in module_source
            assert "media_upload" not in module_source
