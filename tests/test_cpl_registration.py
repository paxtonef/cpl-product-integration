"""Categories C-I (§24) plus the definitive acceptance scenario (§26).

register_vir_execution opens its OWN independently-committing sessions
(session_scope() bound to the real engine) — these tests therefore never
use CPL's rollback-wrapped db_session fixture; they use plain SessionLocal
sessions for setup/verification, exactly matching what the function under
test itself does, and query back through completely fresh sessions to
prove real persistence rather than same-transaction visibility.
"""
from __future__ import annotations

import uuid

import pytest

from app.db.engine import SessionLocal
from app.cpl.runners.authority import AuthorityContext as _AC  # noqa: F401 (type reference only)
from app.cpl.models.runner_execution import RunnerExecution
from app.cpl.models.runner_artifact import RunnerArtifact
from app.cpl.models.runner_governance_decision import RunnerGovernanceDecision
from app.cpl.models.asset_identity_resolution import AssetIdentityResolution
from app.automotive.models.vehicle_detail import VehicleDetail

from product_integration.cpl_registration import VIRRegistrationOutcome, register_vir_execution
from product_integration.vir.client import VIRClient
from tests.conftest import make_vin_request


class TestCPLRegistration:

    # -- C. Execution --------------------------------------------------

    async def test_c01_vir_call_creates_one_governed_runner_execution(self, cpl_case_context, full_authority, vir_client):
        result = await register_vir_execution(
            vir_client=vir_client, case_id=cpl_case_context["case_id"], asset_id=cpl_case_context["asset_id"],
            vir_request=make_vin_request(), authority=full_authority,
        )
        assert result.outcome == VIRRegistrationOutcome.SUCCESS
        session = SessionLocal()
        execution = session.get(RunnerExecution, result.execution_id)
        assert execution is not None
        assert execution.execution_status == "COMPLETED"
        assert execution.runner_type == "VIR"
        session.close()

    async def test_c02_technical_failure_distinguishable_from_governed_non_resolution(
        self, cpl_case_context, full_authority, vir_isolated_store,
    ):
        import httpx

        # A transport-broken client — VIR never actually responds. Distinct
        # from a governed non-resolution (which is a normal SUCCESS outcome
        # carrying an inconclusive resolution_status, tested in E below).
        def _fail(request):
            raise httpx.ConnectError("refused")
        transport = httpx.MockTransport(_fail)
        async with httpx.AsyncClient(transport=transport, base_url="http://vir.test") as http_client:
            broken_client = VIRClient(http_client)
            result = await register_vir_execution(
                vir_client=broken_client, case_id=cpl_case_context["case_id"], asset_id=cpl_case_context["asset_id"],
                vir_request=make_vin_request(), authority=full_authority,
            )
        assert result.outcome == VIRRegistrationOutcome.VIR_TECHNICAL_FAILURE
        session = SessionLocal()
        execution = session.get(RunnerExecution, result.execution_id)
        assert execution.execution_status == "FAILED"
        session.close()

    # -- D. Artifact -----------------------------------------------------

    async def test_d01_schema_registered_and_artifact_produced_and_linked(
        self, cpl_case_context, full_authority, vir_client,
    ):
        result = await register_vir_execution(
            vir_client=vir_client, case_id=cpl_case_context["case_id"], asset_id=cpl_case_context["asset_id"],
            vir_request=make_vin_request(), authority=full_authority,
        )
        assert result.outcome == VIRRegistrationOutcome.SUCCESS
        session = SessionLocal()
        artifact = session.get(RunnerArtifact, result.artifact_id)
        assert artifact is not None
        assert artifact.execution_id == result.execution_id
        assert artifact.artifact_type == "vir_resolution"
        assert artifact.schema_name == "vir_resolution"
        assert artifact.artifact_status == "VALIDATED"  # structural validation passed (REQ-B6-089 mechanism)
        assert artifact.payload["resolution_id"] == result.vir_resolution_id
        session.close()

    async def test_d02_no_duplicate_artifact_on_replayed_admission(self, cpl_case_context, full_authority, vir_client):
        # Reusing the same idempotency_key (request_id) for a second
        # attempt after the first already succeeded must not silently
        # register a second artifact for the same governed execution.
        # A fresh uuid-based key avoids any cross-test-run contamination
        # (a fixed literal key would collide with a stale row from a
        # previous failed run — exactly the bug this suite's own first
        # pass caught).
        request = make_vin_request(request_id=f"PI01-NO-DUP-{uuid.uuid4().hex[:12]}")
        r1 = await register_vir_execution(
            vir_client=vir_client, case_id=cpl_case_context["case_id"], asset_id=cpl_case_context["asset_id"],
            vir_request=request, authority=full_authority,
        )
        assert r1.outcome == VIRRegistrationOutcome.SUCCESS

        r2 = await register_vir_execution(
            vir_client=vir_client, case_id=cpl_case_context["case_id"], asset_id=cpl_case_context["asset_id"],
            vir_request=request, authority=full_authority,
        )
        # REQ-B6-036: same key, same governed operation -> replay, not a
        # second admission — CPL's own existing B6 semantics, reused here,
        # not reimplemented.
        assert r2.execution_id == r1.execution_id

        session = SessionLocal()
        count = session.query(RunnerArtifact).filter(RunnerArtifact.execution_id == r1.execution_id).count()
        assert count == 1
        session.close()

    async def test_d03_conflict_distinguished_from_authority_rejection(self, cpl_case_context, full_authority, vir_client):
        """Same idempotency_key reused against a DIFFERENT Asset (a
        materially different governed operation, REQ-B6-037) must yield
        CONFLICT — a distinct, correctly-labeled outcome, never collapsed
        into AUTHORITY_REJECTION or a generic failure."""
        shared_key = f"PI01-CONFLICT-{uuid.uuid4().hex[:12]}"
        r1 = await register_vir_execution(
            vir_client=vir_client, case_id=cpl_case_context["case_id"], asset_id=cpl_case_context["asset_id"],
            vir_request=make_vin_request(request_id=shared_key), authority=full_authority,
        )
        assert r1.outcome == VIRRegistrationOutcome.SUCCESS

        setup = SessionLocal()
        from app.cpl.models.asset import Asset
        other_asset = Asset(asset_domain="AUTOMOTIVE", asset_type="PASSENGER_CAR", asset_status="ACTIVE")
        setup.add(other_asset)
        setup.commit()
        other_asset_id = other_asset.asset_id
        setup.close()
        try:
            r2 = await register_vir_execution(
                vir_client=vir_client, case_id=cpl_case_context["case_id"], asset_id=other_asset_id,
                vir_request=make_vin_request(request_id=shared_key), authority=full_authority,
            )
            assert r2.outcome == VIRRegistrationOutcome.CONFLICT
        finally:
            cleanup = SessionLocal()
            cleanup.query(Asset).filter(Asset.asset_id == other_asset_id).delete()
            cleanup.commit()
            cleanup.close()

    # -- E. Asset identity resolution ------------------------------------

    async def test_e01_vir_result_feeds_cpl_resolution_with_correct_mapped_status(
        self, cpl_case_context, full_authority, vir_client,
    ):
        result = await register_vir_execution(
            vir_client=vir_client, case_id=cpl_case_context["case_id"], asset_id=cpl_case_context["asset_id"],
            vir_request=make_vin_request(), authority=full_authority,
        )
        assert result.outcome == VIRRegistrationOutcome.SUCCESS
        session = SessionLocal()
        resolution = session.get(AssetIdentityResolution, result.resolution_id)
        assert resolution is not None
        assert resolution.resolver_type == "VIR"
        assert resolution.execution_id == result.execution_id
        assert resolution.resolution_status == result.cpl_resolution_status
        assert resolution.resolution_status in {"RESOLVED", "PARTIALLY_RESOLVED", "AMBIGUOUS", "CONTRADICTORY", "UNRESOLVED", "FAILED"}
        session.close()

    async def test_e02_ambiguous_outcome_does_not_become_accepted_identity(
        self, cpl_case_context, full_authority, vir_client,
    ):
        from product_integration.vir.schemas import VehicleIdentityRequest, ConsentInput
        request = VehicleIdentityRequest(
            request_id=f"PI01-AMBIG-{uuid.uuid4().hex[:8]}",
            registration={"registration_number": "AM-BIG-01", "country_code": "FR"},
            consent=ConsentInput(external_lookup_allowed=True),
        )
        result = await register_vir_execution(
            vir_client=vir_client, case_id=cpl_case_context["case_id"], asset_id=cpl_case_context["asset_id"],
            vir_request=request, authority=full_authority,
        )
        assert result.outcome == VIRRegistrationOutcome.SUCCESS
        assert result.cpl_resolution_status == "AMBIGUOUS"
        session = SessionLocal()
        # §24-E: ambiguous outcomes do not become accepted identity by
        # convenience — VehicleDetail must NOT have been written.
        detail = session.get(VehicleDetail, cpl_case_context["asset_id"])
        assert detail is None
        session.close()

    # -- F. Vehicle detail -------------------------------------------------

    async def test_f01_correct_asset_receives_correct_vehicle_detail(
        self, cpl_case_context, full_authority, vir_client,
    ):
        result = await register_vir_execution(
            vir_client=vir_client, case_id=cpl_case_context["case_id"], asset_id=cpl_case_context["asset_id"],
            vir_request=make_vin_request(), authority=full_authority,
        )
        assert result.outcome == VIRRegistrationOutcome.SUCCESS
        assert result.cpl_resolution_status == "RESOLVED"  # the plain VIN case resolves cleanly
        session = SessionLocal()
        detail = session.get(VehicleDetail, cpl_case_context["asset_id"])
        assert detail is not None
        assert detail.vin_display == "VF3XXXXXXXXXXXXXX"
        assert detail.make is not None
        assert detail.source_resolution_id == result.resolution_id
        session.close()

    async def test_f02_unrelated_asset_never_modified(self, cpl_case_context, full_authority, vir_client):
        # A second, unrelated Asset exists in the DB throughout — confirm
        # it is never touched.
        setup = SessionLocal()
        from app.cpl.models.asset import Asset
        unrelated = Asset(asset_domain="AUTOMOTIVE", asset_type="PASSENGER_CAR", asset_status="ACTIVE")
        setup.add(unrelated)
        setup.commit()
        unrelated_id = unrelated.asset_id
        setup.close()
        try:
            await register_vir_execution(
                vir_client=vir_client, case_id=cpl_case_context["case_id"], asset_id=cpl_case_context["asset_id"],
                vir_request=make_vin_request(), authority=full_authority,
            )
            session = SessionLocal()
            assert session.get(VehicleDetail, unrelated_id) is None
            session.close()
        finally:
            cleanup = SessionLocal()
            cleanup.query(Asset).filter(Asset.asset_id == unrelated_id).delete()
            cleanup.commit()
            cleanup.close()

    # -- H. Failure atomicity ----------------------------------------------

    async def test_h01_persistence_failure_after_vir_success_leaves_no_masquerading_state(
        self, cpl_case_context, full_authority, vir_client, monkeypatch,
    ):
        """Inject a failure inside TX2 (after VIR has already returned
        successfully) and verify no partial state looks like a completed
        registration."""
        import product_integration.cpl_registration as reg_module

        original = reg_module.record_asset_identity_resolution

        def _boom(*args, **kwargs):
            raise RuntimeError("simulated CPL persistence failure")

        monkeypatch.setattr(reg_module, "record_asset_identity_resolution", _boom)

        result = await register_vir_execution(
            vir_client=vir_client, case_id=cpl_case_context["case_id"], asset_id=cpl_case_context["asset_id"],
            vir_request=make_vin_request(), authority=full_authority,
        )
        assert result.outcome == VIRRegistrationOutcome.CPL_PERSISTENCE_FAILURE

        session = SessionLocal()
        execution = session.get(RunnerExecution, result.execution_id)
        assert execution.execution_status == "FAILED"  # never masquerades as COMPLETED
        artifact_count = session.query(RunnerArtifact).filter(RunnerArtifact.execution_id == result.execution_id).count()
        # The artifact insert happened before the injected failure, inside
        # the SAME transaction as the failed resolution recording — since
        # that whole transaction rolled back together, no artifact survives
        # either. This is the "no partial state" proof.
        assert artifact_count == 0
        resolution_count = session.query(AssetIdentityResolution).filter(
            AssetIdentityResolution.asset_id == cpl_case_context["asset_id"]
        ).count()
        assert resolution_count == 0
        session.close()

    # -- G / definitive acceptance (§26) -----------------------------------

    async def test_g_definitive_acceptance_full_linked_state_survives_restart(
        self, cpl_case_context, full_authority, vir_client,
    ):
        """The exact 16-step scenario from the PI-01 instruction §26,
        including step 14-16: recreate the application session and prove
        the linkage survives, i.e. it was genuinely persisted, not merely
        held in the test's own in-memory objects."""
        result = await register_vir_execution(
            vir_client=vir_client, case_id=cpl_case_context["case_id"], asset_id=cpl_case_context["asset_id"],
            vir_request=make_vin_request(), authority=full_authority,
        )
        assert result.outcome == VIRRegistrationOutcome.SUCCESS

        # Steps 14-15: "restart" — brand-new SQLAlchemy session, a fresh
        # connection checked out from the pool, no shared Python object
        # with anything register_vir_execution touched.
        fresh_session = SessionLocal()

        execution = fresh_session.get(RunnerExecution, result.execution_id)
        artifact = fresh_session.get(RunnerArtifact, result.artifact_id)
        resolution = fresh_session.get(AssetIdentityResolution, result.resolution_id)
        detail = fresh_session.get(VehicleDetail, cpl_case_context["asset_id"])
        decision_count = fresh_session.query(RunnerGovernanceDecision).filter(
            RunnerGovernanceDecision.execution_id == result.execution_id
        ).count()

        # Step 16: prove linkage survives.
        assert execution is not None
        assert execution.case_id == cpl_case_context["case_id"]
        assert execution.asset_id == cpl_case_context["asset_id"]
        assert execution.execution_status == "COMPLETED"

        assert artifact is not None
        assert artifact.execution_id == execution.execution_id

        assert resolution is not None
        assert resolution.asset_id == cpl_case_context["asset_id"]
        assert resolution.execution_id == execution.execution_id

        assert detail is not None
        assert detail.asset_id == cpl_case_context["asset_id"]
        assert detail.source_resolution_id == resolution.resolution_id

        assert decision_count >= 2  # at least admission + one artifact-registration decision

        fresh_session.close()
