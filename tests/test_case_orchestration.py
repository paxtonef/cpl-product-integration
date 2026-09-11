"""PI-04 test suite. Real VIR (ASGI), real PGDR (SessionController), real
PostgreSQL throughout. No mock-only persistence verification.
"""
from __future__ import annotations

import uuid

import httpx
import pytest
import pytest_asyncio

from app.cpl.identity.authority import Authority, AuthorityContext
from app.cpl.assets.authority import AssetAuthority
from app.cpl.cases.authority import CaseAuthority
from app.cpl.runners.authority import RunnerAuthority
from app.cpl.models.case import Case
from app.cpl.models.runner_execution import RunnerExecution
from app.cpl.models.runner_artifact import RunnerArtifact
from app.db.engine import SessionLocal

from pgdr.session_controller import SessionController
from pgdr.models import Answer, Consent, InitialComplaint, UserContext
from vir.domain.models import (
    Confidence as VIRConfidence,
    VehicleIdentityResolution as VIRVehicleIdentityResolution,
)
from vir.domain.enums import ConfidenceLevel, ResolutionStatus as VIRResolutionStatus

from product_integration.vir.client import VIRClient
from product_integration.vir.schemas import ConsentInput, VehicleIdentityRequest
from product_integration.cpl_registration import VIRRegistrationOutcome, register_vir_resolution_result
from product_integration.pgdr.session_adapter import PGDRSessionOutcome
from product_integration.orchestration.case_orchestration import (
    DiagnosticStartOutcome,
    RegistrationOutcome,
    continue_vehicle_diagnostic,
    register_vehicle_for_contact,
    resolve_vehicle_identity,
    start_vehicle_diagnostic,
)

NOISE_COMPLAINT = InitialComplaint(free_text="The engine makes a strange noise when accelerating.")
SMOKE_COMPLAINT = InitialComplaint(free_text="There is smoke coming from under the hood and a burning smell.")


@pytest.fixture
def full_authority() -> AuthorityContext:
    return AuthorityContext(
        granted=frozenset({
            Authority.CREATE_CONTACT, Authority.READ_IDENTITY,
            AssetAuthority.CREATE_ASSET, AssetAuthority.CONSUME_IDENTITY_RESOLUTION,
            CaseAuthority.CREATE_CASE, CaseAuthority.TRANSITION_CASE_STATUS,
            RunnerAuthority.ADMIT_EXECUTION, RunnerAuthority.TRANSITION_EXECUTION_STATUS,
            RunnerAuthority.REGISTER_ARTIFACT,
        }),
        actor_reference="pi04-test-suite",
    )


@pytest.fixture
def vir_isolated_store(tmp_path):
    from vir.adapters.sqlite_persistence_adapter import SQLitePersistenceAdapter
    import vir.api.routes as vir_routes

    store = SQLitePersistenceAdapter(str(tmp_path / "pi04_test_vir.db"))
    original_store = vir_routes.STORE
    vir_routes.STORE = store
    yield store
    vir_routes.STORE = original_store


@pytest_asyncio.fixture
async def vir_client(vir_isolated_store) -> VIRClient:
    import vir.api.routes as vir_routes

    transport = httpx.ASGITransport(app=vir_routes.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://vir.test") as http_client:
        yield VIRClient(http_client)


def make_vin_request(request_id: str | None = None, vin: str = "VF3XXXXXXXXXXXXXX") -> VehicleIdentityRequest:
    return VehicleIdentityRequest(
        request_id=request_id or f"PI04-VIR-{uuid.uuid4().hex[:12]}", vin=vin,
        consent=ConsentInput(external_lookup_allowed=True),
    )


def register(full_authority) -> tuple:
    result = register_vehicle_for_contact(
        asset_domain="AUTOMOTIVE", asset_type="PASSENGER_CAR", authority=full_authority,
        contact_idempotency_key=f"contact-{uuid.uuid4().hex[:10]}", asset_idempotency_key=f"asset-{uuid.uuid4().hex[:10]}",
    )
    assert result.outcome == RegistrationOutcome.SUCCESS
    return result.contact_id, result.asset_id


async def drive_to_completion(case_id, sc, result, full_authority, max_turns: int = 15):
    turns = 0
    while result.outcome == PGDRSessionOutcome.BLOCKED and turns < max_turns:
        turns += 1
        q = result.pending_questions[0]
        answer_value = q.choices[0] if q.choices else "yes"
        result = await continue_vehicle_diagnostic(
            case_id=case_id, execution_id=result.pgdr_execution_id, session_controller=sc,
            pgdr_session=result.pgdr_session, answer=Answer(question_id=q.question_id, value=answer_value),
            authority=full_authority,
        )
    return result


class TestRegisterVehicleForContact:

    def test_creates_contact_and_asset(self, full_authority):
        contact_id, asset_id = register(full_authority)
        assert contact_id is not None
        assert asset_id is not None

    def test_reuses_existing_contact(self, full_authority):
        contact_id, _ = register(full_authority)
        result2 = register_vehicle_for_contact(
            existing_contact_id=contact_id, asset_domain="AUTOMOTIVE", asset_type="PASSENGER_CAR",
            authority=full_authority, contact_idempotency_key="unused", asset_idempotency_key=f"asset-{uuid.uuid4().hex[:10]}",
        )
        assert result2.outcome == RegistrationOutcome.SUCCESS
        assert result2.contact_id == contact_id

    def test_repeated_call_same_idempotency_key_replays(self, full_authority):
        key_c, key_a = f"contact-{uuid.uuid4().hex[:10]}", f"asset-{uuid.uuid4().hex[:10]}"
        r1 = register_vehicle_for_contact(
            asset_domain="AUTOMOTIVE", asset_type="PASSENGER_CAR", authority=full_authority,
            contact_idempotency_key=key_c, asset_idempotency_key=key_a,
        )
        r2 = register_vehicle_for_contact(
            asset_domain="AUTOMOTIVE", asset_type="PASSENGER_CAR", authority=full_authority,
            contact_idempotency_key=key_c, asset_idempotency_key=key_a,
        )
        assert r1.contact_id == r2.contact_id
        assert r1.asset_id == r2.asset_id


class TestFullJourney:

    async def test_happy_path_end_to_end(self, full_authority, vir_client):
        contact_id, asset_id = register(full_authority)
        resolution = await resolve_vehicle_identity(
            contact_id=contact_id, asset_id=asset_id, vir_client=vir_client, vir_request=make_vin_request(),
            authority=full_authority, case_idempotency_key=f"case-{uuid.uuid4().hex[:10]}",
        )
        assert resolution.outcome == VIRRegistrationOutcome.SUCCESS
        assert resolution.cpl_resolution_status == "RESOLVED"

        session = SessionLocal()
        case = session.get(Case, resolution.case_id)
        assert case.case_status == "IN_PROGRESS"
        assert case.current_execution_id == resolution.vir_execution_id
        session.close()

        sc = SessionController()
        start = await start_vehicle_diagnostic(
            case_id=resolution.case_id, session_controller=sc, initial_complaint=NOISE_COMPLAINT,
            user_context=UserContext(), consent=Consent(), authority=full_authority,
        )
        assert start.outcome == PGDRSessionOutcome.BLOCKED

        session = SessionLocal()
        case = session.get(Case, resolution.case_id)
        assert case.case_status == "WAITING_FOR_USER"
        assert case.current_execution_id == start.pgdr_execution_id
        session.close()

        final = await drive_to_completion(resolution.case_id, sc, start, full_authority)
        assert final.outcome == PGDRSessionOutcome.COMPLETED
        assert final.pgdr_artifact_id is not None

        session = SessionLocal()
        case = session.get(Case, resolution.case_id)
        assert case.case_status == "RESOLVED"

        vir_count = session.query(RunnerExecution).filter(
            RunnerExecution.case_id == resolution.case_id, RunnerExecution.runner_type == "VIR").count()
        pgdr_count = session.query(RunnerExecution).filter(
            RunnerExecution.case_id == resolution.case_id, RunnerExecution.runner_type == "PGDR").count()
        assert vir_count == 1
        assert pgdr_count == 1

        pgdr_execution = session.query(RunnerExecution).filter(
            RunnerExecution.case_id == resolution.case_id, RunnerExecution.runner_type == "PGDR").first()
        artifact_count = session.query(RunnerArtifact).filter(
            RunnerArtifact.execution_id == pgdr_execution.execution_id).count()
        assert artifact_count == 1
        session.close()

    async def test_blocked_then_continue_new_caller_context(self, full_authority, vir_client):
        """§27: simulate a later caller invocation -- fresh local variables,
        nothing held across a Python stack frame except what a real caller
        would persist (case_id, execution_id) plus PI-03's own required
        session_controller/pgdr_session objects."""
        contact_id, asset_id = register(full_authority)
        resolution = await resolve_vehicle_identity(
            contact_id=contact_id, asset_id=asset_id, vir_client=vir_client, vir_request=make_vin_request(),
            authority=full_authority, case_idempotency_key=f"case-{uuid.uuid4().hex[:10]}",
        )
        sc = SessionController()
        start = await start_vehicle_diagnostic(
            case_id=resolution.case_id, session_controller=sc, initial_complaint=NOISE_COMPLAINT,
            user_context=UserContext(), consent=Consent(), authority=full_authority,
        )
        assert start.outcome == PGDRSessionOutcome.BLOCKED
        saved_case_id = resolution.case_id
        saved_execution_id = start.pgdr_execution_id
        saved_session = start.pgdr_session
        saved_controller = sc
        del resolution, start  # simulate "returned from start_vehicle_diagnostic" -- nothing else survives

        q = saved_session.pending_questions[0]
        answer_value = q.choices[0] if q.choices else "yes"
        resumed = await continue_vehicle_diagnostic(
            case_id=saved_case_id, execution_id=saved_execution_id, session_controller=saved_controller,
            pgdr_session=saved_session, answer=Answer(question_id=q.question_id, value=answer_value),
            authority=full_authority,
        )
        assert resumed.outcome in (PGDRSessionOutcome.BLOCKED, PGDRSessionOutcome.COMPLETED)
        assert resumed.pgdr_execution_id == saved_execution_id

        session = SessionLocal()
        count = session.query(RunnerExecution).filter(RunnerExecution.execution_id == saved_execution_id).count()
        assert count == 1  # same execution, not a new one
        session.close()

    async def test_no_open_transaction_across_blocked_wait(self, full_authority, vir_client):
        from sqlalchemy import text
        contact_id, asset_id = register(full_authority)
        resolution = await resolve_vehicle_identity(
            contact_id=contact_id, asset_id=asset_id, vir_client=vir_client, vir_request=make_vin_request(),
            authority=full_authority, case_idempotency_key=f"case-{uuid.uuid4().hex[:10]}",
        )
        sc = SessionController()
        start = await start_vehicle_diagnostic(
            case_id=resolution.case_id, session_controller=sc, initial_complaint=NOISE_COMPLAINT,
            user_context=UserContext(), consent=Consent(), authority=full_authority,
        )
        assert start.outcome == PGDRSessionOutcome.BLOCKED

        check = SessionLocal()
        rows = check.execute(text(
            "SELECT pid FROM pg_stat_activity WHERE datname = current_database() "
            "AND state IN ('idle in transaction', 'active') AND pid != pg_backend_pid()"
        )).fetchall()
        assert len(rows) == 0
        check.close()


class TestPI02Refusal:

    async def test_refused_vir_status_prevents_pgdr_start(self, full_authority):
        """Uses PI-01's own Path B (register_vir_resolution_result) to
        register a real VIR VehicleIdentityResolution carrying
        provider_unavailable -- one of PI-02's 3 refused statuses,
        confirmed structurally unreachable through the live stub
        resolve() engine's current provider configuration (independently
        verified: only insufficient_data/contradictory/ambiguous/resolved/
        provisionally_resolved/provider_unavailable are ever actually
        returned by vir.domain.resolution.ResolutionEngine at the pinned
        baseline -- invalid_identifier and unsupported_country are dead
        code, and provider_unavailable itself requires a genuinely empty
        records list the live stub providers do not currently produce).
        This is still a real, genuine VIR domain object -- not fabricated
        data -- exercised through PI-01's real, already-verified Path B
        entry point."""
        contact_id, asset_id = register(full_authority)

        session = SessionLocal()
        from app.cpl.cases.lifecycle import create_case
        case_result = create_case(
            session, primary_contact_id=contact_id, asset_id=asset_id, domain="AUTOMOTIVE",
            case_type="VEHICLE_DIAGNOSTIC", authority=full_authority, idempotency_key=f"case-{uuid.uuid4().hex[:10]}",
        )
        session.commit()
        case_id = case_result.object_id
        session.close()

        refused_resolution = VIRVehicleIdentityResolution(
            request_id="PI04-REFUSAL-TEST", resolution_id=f"VIR-RES-{uuid.uuid4().hex[:12].upper()}",
            resolution_status=VIRResolutionStatus.PROVIDER_UNAVAILABLE,
            confidence=VIRConfidence(score=0.0, level=ConfidenceLevel.UNRESOLVED),
        )
        vir_result = register_vir_resolution_result(
            vir_resolution=refused_resolution, case_id=case_id, asset_id=asset_id, authority=full_authority,
        )
        assert vir_result.outcome == VIRRegistrationOutcome.SUCCESS
        assert vir_result.cpl_resolution_status == "FAILED"  # provider_unavailable -> CPL FAILED, per PI-01's own table

        sc = SessionController()
        start = await start_vehicle_diagnostic(
            case_id=case_id, session_controller=sc, initial_complaint=NOISE_COMPLAINT,
            user_context=UserContext(), consent=Consent(), authority=full_authority,
        )
        assert start.outcome == DiagnosticStartOutcome.PI02_HANDOFF_REFUSED

        session = SessionLocal()
        case = session.get(Case, case_id)
        assert case.case_status == "WAITING_FOR_EXTERNAL_INFORMATION"
        pgdr_count = session.query(RunnerExecution).filter(
            RunnerExecution.case_id == case_id, RunnerExecution.runner_type == "PGDR").count()
        assert pgdr_count == 0
        session.close()


class TestEscalated:

    async def test_escalated_reaches_resolved_case_with_artifact(self, full_authority, vir_client):
        contact_id, asset_id = register(full_authority)
        resolution = await resolve_vehicle_identity(
            contact_id=contact_id, asset_id=asset_id, vir_client=vir_client, vir_request=make_vin_request(),
            authority=full_authority, case_idempotency_key=f"case-{uuid.uuid4().hex[:10]}",
        )
        assert resolution.outcome == VIRRegistrationOutcome.SUCCESS

        sc = SessionController()
        start = await start_vehicle_diagnostic(
            case_id=resolution.case_id, session_controller=sc, initial_complaint=SMOKE_COMPLAINT,
            user_context=UserContext(), consent=Consent(), authority=full_authority,
        )
        assert start.outcome == PGDRSessionOutcome.COMPLETED  # escalates immediately
        assert start.pgdr_artifact_id is not None

        session = SessionLocal()
        case = session.get(Case, resolution.case_id)
        assert case.case_status == "RESOLVED"
        pgdr_execution = session.query(RunnerExecution).filter(RunnerExecution.execution_id == start.pgdr_execution_id).first()
        assert pgdr_execution.execution_status == "COMPLETED"  # never FAILED
        session.close()


class TestPersistenceFailure:

    async def test_cpl_persistence_failure_during_pgdr_finalization(self, full_authority, vir_client, monkeypatch):
        contact_id, asset_id = register(full_authority)
        resolution = await resolve_vehicle_identity(
            contact_id=contact_id, asset_id=asset_id, vir_client=vir_client, vir_request=make_vin_request(),
            authority=full_authority, case_idempotency_key=f"case-{uuid.uuid4().hex[:10]}",
        )
        assert resolution.outcome == VIRRegistrationOutcome.SUCCESS

        import product_integration.pgdr.session_adapter as pgdr_adapter_module
        original = pgdr_adapter_module.register_artifact
        def _boom(*a, **k):
            raise RuntimeError("PI-04 injected CPL persistence failure")
        pgdr_adapter_module.register_artifact = _boom
        try:
            sc = SessionController()
            start = await start_vehicle_diagnostic(
                case_id=resolution.case_id, session_controller=sc, initial_complaint=SMOKE_COMPLAINT,
                user_context=UserContext(), consent=Consent(), authority=full_authority,
            )
        finally:
            pgdr_adapter_module.register_artifact = original

        assert start.outcome == PGDRSessionOutcome.CPL_PERSISTENCE_FAILURE

        session = SessionLocal()
        case = session.get(Case, resolution.case_id)
        # No false success: Case must NOT have been transitioned to RESOLVED.
        assert case.case_status != "RESOLVED"
        if start.pgdr_execution_id is not None:
            artifact_count = session.query(RunnerArtifact).filter(
                RunnerArtifact.execution_id == start.pgdr_execution_id).count()
            assert artifact_count == 0
        session.close()


class TestRestartDurability:

    async def test_journey_retrievable_from_fresh_session(self, full_authority, vir_client):
        contact_id, asset_id = register(full_authority)
        resolution = await resolve_vehicle_identity(
            contact_id=contact_id, asset_id=asset_id, vir_client=vir_client, vir_request=make_vin_request(),
            authority=full_authority, case_idempotency_key=f"case-{uuid.uuid4().hex[:10]}",
        )
        sc = SessionController()
        start = await start_vehicle_diagnostic(
            case_id=resolution.case_id, session_controller=sc, initial_complaint=SMOKE_COMPLAINT,
            user_context=UserContext(), consent=Consent(), authority=full_authority,
        )
        assert start.outcome == PGDRSessionOutcome.COMPLETED

        fresh = SessionLocal()
        case = fresh.get(Case, resolution.case_id)
        assert case is not None
        assert case.case_status == "RESOLVED"
        assert case.current_execution_id == start.pgdr_execution_id

        vir_execution = fresh.query(RunnerExecution).filter(
            RunnerExecution.case_id == resolution.case_id, RunnerExecution.runner_type == "VIR").first()
        pgdr_execution = fresh.query(RunnerExecution).filter(
            RunnerExecution.case_id == resolution.case_id, RunnerExecution.runner_type == "PGDR").first()
        assert vir_execution is not None
        assert pgdr_execution is not None
        vir_artifact = fresh.query(RunnerArtifact).filter(RunnerArtifact.execution_id == vir_execution.execution_id).first()
        pgdr_artifact = fresh.query(RunnerArtifact).filter(RunnerArtifact.execution_id == pgdr_execution.execution_id).first()
        assert vir_artifact is not None
        assert pgdr_artifact is not None
        fresh.close()
