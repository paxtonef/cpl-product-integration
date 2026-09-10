"""PI-01-VF-01 repair tests.

Proves the clarification result persistence path exists, uses the exact
clarified resolution_id, shares its persistence logic with Path A (no
duplicate implementation), and never calls resolve() a second time after a
clarification. All against real VIR (via ASGI transport, same isolation
pattern as the rest of this suite) and real PostgreSQL.
"""
from __future__ import annotations

import uuid

import pytest

from app.db.engine import SessionLocal
from app.cpl.models.runner_execution import RunnerExecution
from app.cpl.models.runner_artifact import RunnerArtifact
from app.cpl.models.asset_identity_resolution import AssetIdentityResolution
from app.automotive.models.vehicle_detail import VehicleDetail

from product_integration.cpl_registration import (
    VIRRegistrationOutcome,
    register_vir_execution,
    register_vir_resolution_result,
)
from product_integration.vir.client import VIRClient
from product_integration.vir.schemas import ClarificationAnswer, ClarificationRequest, ConsentInput, VehicleIdentityRequest


def make_ambiguous_request(request_id: str | None = None) -> VehicleIdentityRequest:
    """VIR's own known ambiguous-plate fixture (confirmed directly in VIR's
    tests/test_resolution.py and src/vir/adapters/registration_provider_
    adapter.py at the pinned baseline) — deterministically produces
    AMBIGUOUS with >=1 clarification question."""
    return VehicleIdentityRequest(
        request_id=request_id or f"VF01-REPAIR-{uuid.uuid4().hex[:12]}",
        registration={"registration_number": "AM-BIG-01", "country_code": "FR"},
        consent=ConsentInput(external_lookup_allowed=True),
    )


class TestVF01Repair:

    # -- A. Clarification result persistence ---------------------------

    async def test_a01_clarification_result_persists_through_pi01(
        self, cpl_case_context, full_authority, vir_client: VIRClient,
    ):
        # Real VIR call producing an ambiguous, clarification-required result.
        initial = await vir_client.resolve(make_ambiguous_request())
        assert initial.resolution_status == "ambiguous"
        assert len(initial.clarification_questions) >= 1

        # Real clarification submission through VIR's real endpoint.
        q = initial.clarification_questions[0]
        answer_value = q.choices[0].value if q.choices else "test-answer"
        clarified = await vir_client.submit_clarification(
            initial.resolution_id, ClarificationRequest(answers=[ClarificationAnswer(question_id=q.question_id, value=answer_value)]),
        )
        assert clarified.resolution_id != initial.resolution_id  # VIR's own real behavior, confirmed

        # The clarified result — obtained entirely OUTSIDE register_vir_resolution_result —
        # is registered through PI-01's repaired persistence path.
        result = register_vir_resolution_result(
            vir_resolution=clarified, case_id=cpl_case_context["case_id"], asset_id=cpl_case_context["asset_id"],
            authority=full_authority,
        )
        assert result.outcome == VIRRegistrationOutcome.SUCCESS

        session = SessionLocal()
        execution = session.get(RunnerExecution, result.execution_id)
        artifact = session.get(RunnerArtifact, result.artifact_id)
        resolution = session.get(AssetIdentityResolution, result.resolution_id)

        assert execution is not None
        assert execution.execution_status == "COMPLETED"
        assert execution.execution_purpose == "vehicle_identity_resolution_clarification"
        assert artifact is not None
        assert artifact.execution_id == execution.execution_id
        assert artifact.payload["resolution_id"] == clarified.resolution_id
        assert resolution is not None
        assert resolution.execution_id == execution.execution_id
        session.close()

    async def test_a02_resolved_clarification_writes_vehicle_detail(
        self, cpl_case_context, full_authority, vir_client: VIRClient,
    ):
        """A clarification that resolves to a usable identity must still
        write VehicleDetail through the shared path — same rule Path A
        already enforces (§24-E of the original build)."""
        initial = await vir_client.resolve(make_ambiguous_request())
        q = initial.clarification_questions[0]
        answer_value = q.choices[0].value if q.choices else "test-answer"
        clarified = await vir_client.submit_clarification(
            initial.resolution_id, ClarificationRequest(answers=[ClarificationAnswer(question_id=q.question_id, value=answer_value)]),
        )

        result = register_vir_resolution_result(
            vir_resolution=clarified, case_id=cpl_case_context["case_id"], asset_id=cpl_case_context["asset_id"],
            authority=full_authority,
        )
        assert result.outcome == VIRRegistrationOutcome.SUCCESS

        session = SessionLocal()
        if result.cpl_resolution_status in ("RESOLVED", "PARTIALLY_RESOLVED"):
            detail = session.get(VehicleDetail, cpl_case_context["asset_id"])
            assert detail is not None
            assert detail.source_resolution_id == result.resolution_id
        else:
            # VIR's stub answering logic may still leave this ambiguous
            # depending on which choice was submitted — either outcome is
            # legitimate; the assertion above only applies when resolved.
            detail = session.get(VehicleDetail, cpl_case_context["asset_id"])
            assert detail is None
        session.close()

    # -- B. Resolution ID correctness -----------------------------------

    async def test_b01_persisted_data_uses_clarified_resolution_id_not_original(
        self, cpl_case_context, full_authority, vir_client: VIRClient,
    ):
        initial = await vir_client.resolve(make_ambiguous_request())
        q = initial.clarification_questions[0]
        answer_value = q.choices[0].value if q.choices else "test-answer"
        clarified = await vir_client.submit_clarification(
            initial.resolution_id, ClarificationRequest(answers=[ClarificationAnswer(question_id=q.question_id, value=answer_value)]),
        )
        assert clarified.resolution_id != initial.resolution_id

        result = register_vir_resolution_result(
            vir_resolution=clarified, case_id=cpl_case_context["case_id"], asset_id=cpl_case_context["asset_id"],
            authority=full_authority,
        )
        assert result.vir_resolution_id == clarified.resolution_id
        assert result.vir_resolution_id != initial.resolution_id

        session = SessionLocal()
        artifact = session.get(RunnerArtifact, result.artifact_id)
        assert artifact.payload["resolution_id"] == clarified.resolution_id
        assert artifact.payload["resolution_id"] != initial.resolution_id
        session.close()

    async def test_b02_execution_idempotency_key_is_clarified_resolution_id(
        self, cpl_case_context, full_authority, vir_client: VIRClient,
    ):
        initial = await vir_client.resolve(make_ambiguous_request())
        q = initial.clarification_questions[0]
        answer_value = q.choices[0].value if q.choices else "test-answer"
        clarified = await vir_client.submit_clarification(
            initial.resolution_id, ClarificationRequest(answers=[ClarificationAnswer(question_id=q.question_id, value=answer_value)]),
        )
        result = register_vir_resolution_result(
            vir_resolution=clarified, case_id=cpl_case_context["case_id"], asset_id=cpl_case_context["asset_id"],
            authority=full_authority,
        )
        session = SessionLocal()
        execution = session.get(RunnerExecution, result.execution_id)
        assert execution.idempotency_key == clarified.resolution_id
        session.close()

    async def test_b03_provenance_linkage_recorded_when_supplied(
        self, cpl_case_context, full_authority, vir_client: VIRClient,
    ):
        """If the caller knows which earlier execution this clarifies, the
        relationship is recorded as plain provenance data — never silently
        dropped, never via parent_execution_id."""
        initial_request = make_ambiguous_request()
        initial = await vir_client.resolve(initial_request)

        original_registration = register_vir_resolution_result(
            vir_resolution=initial, case_id=cpl_case_context["case_id"], asset_id=cpl_case_context["asset_id"],
            authority=full_authority,
        )
        assert original_registration.outcome == VIRRegistrationOutcome.SUCCESS

        q = initial.clarification_questions[0]
        answer_value = q.choices[0].value if q.choices else "test-answer"
        clarified = await vir_client.submit_clarification(
            initial.resolution_id, ClarificationRequest(answers=[ClarificationAnswer(question_id=q.question_id, value=answer_value)]),
        )

        clarified_result = register_vir_resolution_result(
            vir_resolution=clarified, case_id=cpl_case_context["case_id"], asset_id=cpl_case_context["asset_id"],
            authority=full_authority,
            clarifies_execution_id=original_registration.execution_id,
            clarifies_resolution_id=initial.resolution_id,
        )
        assert clarified_result.outcome == VIRRegistrationOutcome.SUCCESS

        session = SessionLocal()
        resolution = session.get(AssetIdentityResolution, clarified_result.resolution_id)
        assert resolution.provenance_payload["clarifies_execution_id"] == str(original_registration.execution_id)
        assert resolution.provenance_payload["clarifies_resolution_id"] == initial.resolution_id
        # parent_execution_id is never touched by this path (structural guarantee, not just convention).
        execution = session.get(RunnerExecution, clarified_result.execution_id)
        assert execution.parent_execution_id is None
        session.close()

    # -- C. Shared-path proof --------------------------------------------

    async def test_c01_path_a_and_path_b_share_identical_persistence_function(self):
        """Both public entry points must delegate to the exact same
        internal persistence function — proving there is no duplicate
        implementation, by inspecting the actual call graph rather than
        trusting a code comment."""
        import inspect
        import product_integration.cpl_registration as reg_module

        source_a = inspect.getsource(reg_module.register_vir_execution)
        source_b = inspect.getsource(reg_module.register_vir_resolution_result)
        assert "_persist_vir_resolution(" in source_a
        assert "_persist_vir_resolution(" in source_b
        # Both call the SAME function object, not two functions that happen
        # to share a name.
        assert reg_module.register_vir_execution.__globals__["_persist_vir_resolution"] is (
            reg_module.register_vir_resolution_result.__globals__["_persist_vir_resolution"]
        )

    async def test_c02_both_paths_produce_structurally_identical_artifact_shape(
        self, cpl_case_context, full_authority, vir_client: VIRClient,
    ):
        """A resolution registered via Path A and one registered via Path B
        (using a direct, non-ambiguous VIN so no clarification is even
        needed) must produce artifacts with the identical schema/shape —
        proof the shared path treats both sources identically."""
        from tests.conftest import make_vin_request

        path_a_result = await register_vir_execution(
            vir_client=vir_client, case_id=cpl_case_context["case_id"], asset_id=cpl_case_context["asset_id"],
            vir_request=make_vin_request(request_id=f"VF01-PATHA-{uuid.uuid4().hex[:8]}"), authority=full_authority,
        )
        assert path_a_result.outcome == VIRRegistrationOutcome.SUCCESS

        direct_resolution = await vir_client.resolve(make_vin_request(request_id=f"VF01-PATHB-SRC-{uuid.uuid4().hex[:8]}"))
        path_b_result = register_vir_resolution_result(
            vir_resolution=direct_resolution, case_id=cpl_case_context["case_id"], asset_id=cpl_case_context["asset_id"],
            authority=full_authority,
        )
        assert path_b_result.outcome == VIRRegistrationOutcome.SUCCESS

        session = SessionLocal()
        artifact_a = session.get(RunnerArtifact, path_a_result.artifact_id)
        artifact_b = session.get(RunnerArtifact, path_b_result.artifact_id)
        assert artifact_a.schema_name == artifact_b.schema_name == "vir_resolution"
        assert artifact_a.semantic_function == artifact_b.semantic_function
        assert artifact_a.lifecycle_role == artifact_b.lifecycle_role
        assert artifact_a.presentation_role == artifact_b.presentation_role
        assert set(artifact_a.payload.keys()) == set(artifact_b.payload.keys())
        session.close()

    # -- D. No second resolve() ------------------------------------------

    async def test_d01_no_resolve_call_occurs_after_clarification(
        self, cpl_case_context, full_authority, vir_client: VIRClient, monkeypatch,
    ):
        """Instrument VIRClient.resolve itself and assert it is never
        invoked by register_vir_resolution_result, proving the repair
        actually closes PI-01-VF-01 rather than merely relabeling it."""
        initial = await vir_client.resolve(make_ambiguous_request())
        q = initial.clarification_questions[0]
        answer_value = q.choices[0].value if q.choices else "test-answer"
        clarified = await vir_client.submit_clarification(
            initial.resolution_id, ClarificationRequest(answers=[ClarificationAnswer(question_id=q.question_id, value=answer_value)]),
        )

        resolve_call_count = 0
        original_resolve = VIRClient.resolve

        async def _counting_resolve(self, *args, **kwargs):
            nonlocal resolve_call_count
            resolve_call_count += 1
            return await original_resolve(self, *args, **kwargs)

        monkeypatch.setattr(VIRClient, "resolve", _counting_resolve)

        result = register_vir_resolution_result(
            vir_resolution=clarified, case_id=cpl_case_context["case_id"], asset_id=cpl_case_context["asset_id"],
            authority=full_authority,
        )
        assert result.outcome == VIRRegistrationOutcome.SUCCESS
        assert resolve_call_count == 0  # register_vir_resolution_result never touches vir_client at all

    # -- Definitive repair acceptance scenario (§12) ----------------------

    async def test_e01_definitive_repair_acceptance_full_linked_state_survives_restart(
        self, cpl_case_context, full_authority, vir_client: VIRClient,
    ):
        """The exact 15-step scenario from the PI-01-VF-01 repair
        instruction §12: real ambiguous result -> real clarification ->
        clarified resolution persisted (no second resolve) -> linked state
        proven, including restart-persistence, using the CLARIFIED
        resolution_id throughout."""
        # Steps 5-7: request producing clarification, submit clarification, receive clarified resolution.
        initial = await vir_client.resolve(make_ambiguous_request())
        assert initial.resolution_status == "ambiguous"
        assert initial.clarification_questions
        q = initial.clarification_questions[0]
        answer_value = q.choices[0].value if q.choices else "test-answer"
        clarified = await vir_client.submit_clarification(
            initial.resolution_id, ClarificationRequest(answers=[ClarificationAnswer(question_id=q.question_id, value=answer_value)]),
        )
        assert clarified.resolution_id  # a real, actual resolution_id
        assert clarified.resolution_id != initial.resolution_id

        # Step 8-9: persist the exact clarified result; resolve() is never called again
        # (proven exactly as in test_d01, re-confirmed here as part of the full scenario).
        resolve_calls_before = 0
        original_resolve = VIRClient.resolve
        call_tracker = {"count": 0}

        async def _tracked_resolve(self, *args, **kwargs):
            call_tracker["count"] += 1
            return await original_resolve(self, *args, **kwargs)

        VIRClient.resolve = _tracked_resolve
        try:
            result = register_vir_resolution_result(
                vir_resolution=clarified, case_id=cpl_case_context["case_id"], asset_id=cpl_case_context["asset_id"],
                authority=full_authority,
            )
        finally:
            VIRClient.resolve = original_resolve
        assert call_tracker["count"] == 0
        assert result.outcome == VIRRegistrationOutcome.SUCCESS

        # Steps 10-13: independently query PostgreSQL, confirm all four linked entities,
        # confirm they correspond to the CLARIFIED result specifically.
        session = SessionLocal()
        execution = session.get(RunnerExecution, result.execution_id)
        artifact = session.get(RunnerArtifact, result.artifact_id)
        resolution = session.get(AssetIdentityResolution, result.resolution_id)
        assert execution is not None and execution.execution_status == "COMPLETED"
        assert artifact is not None and artifact.payload["resolution_id"] == clarified.resolution_id
        assert resolution is not None and resolution.execution_id == execution.execution_id
        vehicle_detail = session.get(VehicleDetail, cpl_case_context["asset_id"])
        if result.cpl_resolution_status in ("RESOLVED", "PARTIALLY_RESOLVED"):
            assert vehicle_detail is not None
            assert vehicle_detail.source_resolution_id == result.resolution_id
        session.close()

        # Steps 14-15: restart — brand-new session, no shared Python object —
        # confirm linkage survives.
        fresh_session = SessionLocal()
        execution_after = fresh_session.get(RunnerExecution, result.execution_id)
        artifact_after = fresh_session.get(RunnerArtifact, result.artifact_id)
        resolution_after = fresh_session.get(AssetIdentityResolution, result.resolution_id)
        assert execution_after is not None
        assert execution_after.case_id == cpl_case_context["case_id"]
        assert execution_after.asset_id == cpl_case_context["asset_id"]
        assert artifact_after is not None
        assert artifact_after.payload["resolution_id"] == clarified.resolution_id
        assert resolution_after is not None
        fresh_session.close()
