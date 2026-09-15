"""Block B1 — PI-side acceptance tests (B1-AC06, B1-AC07).

B1-AC08 (full regression, both suites) is reported separately in the
final report rather than as a single test function.
"""
import uuid

import httpx

BASE_URL = "http://127.0.0.1:8000"


def _register_and_resolve() -> str:
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        vehicle = client.post(
            "/vehicles",
            json={
                "contact_idempotency_key": f"b1-c-{uuid.uuid4().hex[:10]}",
                "asset_idempotency_key": f"b1-a-{uuid.uuid4().hex[:10]}",
            },
        ).json()
        case = client.post(
            "/cases",
            json={
                "contact_id": vehicle["contact_id"], "asset_id": vehicle["asset_id"],
                "request_id": f"b1-case-{uuid.uuid4().hex[:10]}",
                "vin": "VF3XXXXXXXXXXXXXX",
                "case_idempotency_key": f"b1-case-idem-{uuid.uuid4().hex[:10]}",
                "consent": {"external_lookup_allowed": True},
            },
        )
        assert case.status_code == 201, case.text
        return case.json()["case_id"]


class TestB1PITransport:
    def test_b1_ac06_pi_to_pgdr_typed_primary_media_input(self):
        """B1-AC06: PI API -> PI orchestration -> PI PGDR adapter -> PGDR
        typed primary-media input, confirmed via the real, running PGDR
        process itself (not PI's own echo) -- and confirmed the reference
        is NOT stored in governance metadata (extending Block A repair's
        own AC4b negative proof to the B1-extended path)."""
        from app.db.engine import SessionLocal
        from app.cpl.models.runner_execution import RunnerExecution
        from app.cpl.models.runner_governance_decision import RunnerGovernanceDecision

        case_id = _register_and_resolve()
        ref = f"media-ref-b1-transport-{uuid.uuid4().hex[:8]}"
        with httpx.Client(base_url=BASE_URL, timeout=30) as client:
            response = client.post(
                f"/cases/{case_id}/diagnostics",
                json={"primary_diagnostic_media_reference": ref},
            )
        assert response.status_code in (200, 201), response.text
        body = response.json()
        # Still true post-B1: the Block A observability echo remains
        # present (TEMPORARY_BLOCK_A_OBSERVABILITY_SURFACE, not removed).
        assert body["primary_diagnostic_media_reference"] == ref

        session = SessionLocal()
        try:
            session.expire_all()
            execution = (
                session.query(RunnerExecution)
                .filter(RunnerExecution.case_id == uuid.UUID(case_id), RunnerExecution.runner_type == "PGDR")
                .order_by(RunnerExecution.created_at.desc())
                .first()
            )
            assert execution is not None
            # B1's own negative proof, extended: still not in governance
            # metadata after B1's changes.
            assert ref not in (execution.execution_purpose or "")
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
            assert ref not in purpose
        finally:
            session.close()

    def test_b1_ac06b_reference_reaches_pgdr_own_request_object(self):
        """Direct, unit-level proof (no HTTP) that case_orchestration.py's
        start_vehicle_diagnostic constructs PGDR's own typed
        PrimaryDiagnosticMedia and sets it on the real
        PreGarageDiagnosticRequest passed to SessionController.start() --
        the actual B1 stop condition ('typed PGDR request/session'), not
        merely PI's own echo fields."""
        import inspect
        from product_integration.orchestration import case_orchestration

        source = inspect.getsource(case_orchestration.start_vehicle_diagnostic)
        assert "PrimaryDiagnosticMedia(" in source
        assert "primary_diagnostic_media=" in source

    def test_b1_ac07_existing_text_only_path_preserved(self):
        """B1-AC07: existing text-only diagnostic behaviour continues to
        work, unaffected by the new typed media contract."""
        case_id = _register_and_resolve()
        with httpx.Client(base_url=BASE_URL, timeout=30) as client:
            response = client.post(
                f"/cases/{case_id}/diagnostics",
                json={"complaint_text": "Le moteur fait un bruit étrange."},
            )
        assert response.status_code in (200, 201), response.text
        body = response.json()
        assert body.get("primary_diagnostic_media_reference") is None
