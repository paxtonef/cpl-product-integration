"""PI-05 test suite. HTTP ONLY -- no direct Python calls into PI-04 for any
definitive test. Real VIR (ASGI), real PGDR (SessionController), real
PostgreSQL throughout.
"""
from __future__ import annotations

import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.cpl.identity.authority import AuthorityContext, Authority
from app.cpl.assets.authority import AssetAuthority
from app.cpl.cases.authority import CaseAuthority
from app.cpl.runners.authority import RunnerAuthority
from app.cpl.cases.lifecycle import create_case
from app.db.engine import SessionLocal

from vir.domain.models import Confidence as VIRConfidence, VehicleIdentityResolution as VIRRes
from vir.domain.enums import ConfidenceLevel, ResolutionStatus as VIRStatus

from product_integration.cpl_registration import VIRRegistrationOutcome, register_vir_resolution_result
from product_integration.api.app import create_app
from product_integration.api.deps import get_vir_client, get_pgdr_registry
from product_integration.api.registry import PGDRSessionRegistry
from product_integration.vir.client import VIRClient

NOISE_COMPLAINT = "The engine makes a strange noise when accelerating."
SMOKE_COMPLAINT = "There is smoke coming from under the hood and a burning smell."


@pytest.fixture
def vir_isolated_store(tmp_path):
    from vir.adapters.sqlite_persistence_adapter import SQLitePersistenceAdapter
    import vir.api.routes as vir_routes
    store = SQLitePersistenceAdapter(str(tmp_path / "pi05_test_vir.db"))
    original_store = vir_routes.STORE
    vir_routes.STORE = store
    yield store
    vir_routes.STORE = original_store


@pytest_asyncio.fixture
async def api_client(vir_isolated_store):
    import vir.api.routes as vir_routes
    vir_transport = httpx.ASGITransport(app=vir_routes.app)

    async def override_vir_client():
        async with httpx.AsyncClient(transport=vir_transport, base_url="http://vir.test") as c:
            yield VIRClient(c)

    app = create_app()
    app.dependency_overrides[get_vir_client] = override_vir_client
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as client:
        client.app = app  # stash for tests that need to swap dependency overrides
        yield client


async def _register_vehicle(client) -> dict:
    r = await client.post("/vehicles", json={
        "contact_idempotency_key": f"c-{uuid.uuid4().hex[:10]}", "asset_idempotency_key": f"a-{uuid.uuid4().hex[:10]}",
    })
    assert r.status_code == 201
    return r.json()


async def _start_case_vir(client, veh, vin: str = "VF3XXXXXXXXXXXXXX", **overrides) -> dict:
    body = {
        "contact_id": veh["contact_id"], "asset_id": veh["asset_id"], "request_id": f"vir-{uuid.uuid4().hex[:10]}",
        "vin": vin, "consent": {"external_lookup_allowed": True}, "case_idempotency_key": f"case-{uuid.uuid4().hex[:10]}",
    }
    body.update(overrides)
    r = await client.post("/cases", json=body)
    assert r.status_code == 201
    return r.json()


async def _drive_to_completion(client, case_id, diag, max_turns=15):
    turns = 0
    while diag["outcome"] == "BLOCKED" and turns < max_turns:
        turns += 1
        q = diag["pending_questions"][0]
        answer_value = q["choices"][0] if q.get("choices") else "yes"
        r = await client.post(
            f"/cases/{case_id}/diagnostics/{diag['execution_id']}/answers",
            json={"question_id": q["question_id"], "value": answer_value},
        )
        diag = r.json()
    return diag


class TestHTTPHappyPath:

    async def test_full_journey_http_only(self, api_client):
        veh = await _register_vehicle(api_client)
        case = await _start_case_vir(api_client, veh)
        assert case["outcome"] == VIRRegistrationOutcome.SUCCESS

        r = await api_client.get(f"/cases/{case['case_id']}")
        assert r.status_code == 200
        assert r.json()["case_status"] == "IN_PROGRESS"

        r = await api_client.post(f"/cases/{case['case_id']}/diagnostics", json={"complaint_text": NOISE_COMPLAINT})
        assert r.status_code == 201
        diag = r.json()
        assert diag["outcome"] == "BLOCKED"

        final = await _drive_to_completion(api_client, case["case_id"], diag)
        assert final["outcome"] == "COMPLETED"
        assert final["artifact_id"] is not None

        r = await api_client.get(f"/executions/{final['execution_id']}/artifact")
        assert r.status_code == 200
        assert "report_id" in r.json()["payload"]

        r = await api_client.get(f"/executions/{final['execution_id']}")
        assert r.status_code == 200
        assert r.json()["execution_status"] == "COMPLETED"

        r = await api_client.get(f"/cases/{case['case_id']}/history")
        assert r.status_code == 200
        hist = r.json()
        assert len(hist["executions"]) == 2
        assert {e["runner_type"] for e in hist["executions"]} == {"VIR", "PGDR"}

    def test_openapi_schema_generates(self, api_client):
        schema = api_client.app.openapi()
        assert "paths" in schema
        assert "/cases" in schema["paths"]
        assert "/cases/{case_id}/diagnostics" in schema["paths"]


class TestHTTPClarification:

    async def test_clarification_path_http_only(self, api_client):
        veh = await _register_vehicle(api_client)
        case = await _start_case_vir(
            api_client, veh, vin=None, registration_number="AM-BIG-01", registration_country_code="FR",
        )
        assert case["vir_resolution_status"] == "AMBIGUOUS"

        r = await api_client.get(f"/executions/{case['vir_execution_id']}/artifact")
        questions = r.json()["payload"].get("clarification_questions", [])
        assert questions, "fixture must produce real clarification_questions"
        q = questions[0]
        answer_value = q["choices"][0]["value"] if q.get("choices") else "some-answer"

        r = await api_client.post(f"/cases/{case['case_id']}/vir/clarifications", json={
            "answers": [{"question_id": q["question_id"], "value": answer_value}],
        })
        assert r.status_code == 200
        clarified = r.json()
        assert clarified["outcome"] == VIRRegistrationOutcome.SUCCESS
        assert clarified["vir_execution_id"] != case["vir_execution_id"]

        r = await api_client.get(f"/cases/{case['case_id']}/history")
        vir_execs = [e for e in r.json()["executions"] if e["runner_type"] == "VIR"]
        assert len(vir_execs) == 2  # original + clarified, no duplicate fresh resolve


class TestHTTPBlockedContinuation:

    async def test_blocked_continue_separate_requests(self, api_client):
        """§39: end the HTTP request completely, make a later independent
        HTTP request to continue -- proves the SAME process, DIFFERENT
        request, can resume via the registry."""
        veh = await _register_vehicle(api_client)
        case = await _start_case_vir(api_client, veh)
        r = await api_client.post(f"/cases/{case['case_id']}/diagnostics", json={"complaint_text": NOISE_COMPLAINT})
        diag = r.json()
        assert diag["outcome"] == "BLOCKED"
        execution_id = diag["execution_id"]

        q = diag["pending_questions"][0]
        answer_value = q["choices"][0] if q.get("choices") else "yes"
        r2 = await api_client.post(
            f"/cases/{case['case_id']}/diagnostics/{execution_id}/answers",
            json={"question_id": q["question_id"], "value": answer_value},
        )
        assert r2.status_code == 200
        assert r2.json()["execution_id"] == execution_id  # same execution, not a new one

        r3 = await api_client.get(f"/cases/{case['case_id']}")
        assert r3.json()["current_execution_id"] == execution_id

    async def test_no_open_transaction_across_blocked_wait(self, api_client):
        veh = await _register_vehicle(api_client)
        case = await _start_case_vir(api_client, veh)
        r = await api_client.post(f"/cases/{case['case_id']}/diagnostics", json={"complaint_text": NOISE_COMPLAINT})
        assert r.json()["outcome"] == "BLOCKED"

        check = SessionLocal()
        rows = check.execute(text(
            "SELECT pid FROM pg_stat_activity WHERE datname = current_database() "
            "AND state IN ('idle in transaction', 'active') AND pid != pg_backend_pid()"
        )).fetchall()
        assert len(rows) == 0
        check.close()

    async def test_cross_resource_mismatch_rejected(self, api_client):
        """§31: wrong case/execution pairing must be rejected, not silently accepted."""
        veh = await _register_vehicle(api_client)
        case_a = await _start_case_vir(api_client, veh)
        case_b = await _start_case_vir(api_client, veh)
        r = await api_client.post(f"/cases/{case_a['case_id']}/diagnostics", json={"complaint_text": NOISE_COMPLAINT})
        diag_a = r.json()
        assert diag_a["outcome"] == "BLOCKED"

        # attempt to answer diag_a's execution but scoped under case_b
        r = await api_client.post(
            f"/cases/{case_b['case_id']}/diagnostics/{diag_a['execution_id']}/answers",
            json={"question_id": "x", "value": "y"},
        )
        assert r.status_code == 404
        assert r.json()["error_category"] == "CROSS_RESOURCE_MISMATCH"


class TestHTTPPI02Refusal:

    async def test_refusal_via_http(self, api_client):
        veh = await _register_vehicle(api_client)
        auth = AuthorityContext(granted=frozenset({
            Authority.CREATE_CONTACT, Authority.READ_IDENTITY, AssetAuthority.CREATE_ASSET, AssetAuthority.CONSUME_IDENTITY_RESOLUTION,
            CaseAuthority.CREATE_CASE, CaseAuthority.TRANSITION_CASE_STATUS,
            RunnerAuthority.ADMIT_EXECUTION, RunnerAuthority.TRANSITION_EXECUTION_STATUS, RunnerAuthority.REGISTER_ARTIFACT,
        }), actor_reference="pi05-test-refusal-setup")
        s = SessionLocal()
        case_result = create_case(
            s, primary_contact_id=uuid.UUID(veh["contact_id"]), asset_id=uuid.UUID(veh["asset_id"]),
            domain="AUTOMOTIVE", case_type="VEHICLE_DIAGNOSTIC", authority=auth, idempotency_key=f"case-{uuid.uuid4().hex[:10]}",
        )
        s.commit()
        case_id = case_result.object_id
        s.close()
        refused = VIRRes(
            request_id="PI05-TEST-REFUSAL", resolution_id=f"VIR-RES-{uuid.uuid4().hex[:12].upper()}",
            resolution_status=VIRStatus.PROVIDER_UNAVAILABLE, confidence=VIRConfidence(score=0.0, level=ConfidenceLevel.UNRESOLVED),
        )
        vir_result = register_vir_resolution_result(vir_resolution=refused, case_id=case_id, asset_id=uuid.UUID(veh["asset_id"]), authority=auth)
        assert vir_result.outcome == VIRRegistrationOutcome.SUCCESS

        r = await api_client.post(f"/cases/{case_id}/diagnostics", json={"complaint_text": "noise"})
        assert r.status_code == 200  # nothing created
        assert r.json()["outcome"] == "PI02_HANDOFF_REFUSED"

        r = await api_client.get(f"/cases/{case_id}/history")
        pgdr_execs = [e for e in r.json()["executions"] if e["runner_type"] == "PGDR"]
        assert len(pgdr_execs) == 0


class TestHTTPEscalated:

    async def test_escalated_via_http(self, api_client):
        veh = await _register_vehicle(api_client)
        case = await _start_case_vir(api_client, veh)
        r = await api_client.post(f"/cases/{case['case_id']}/diagnostics", json={"complaint_text": SMOKE_COMPLAINT})
        assert r.status_code == 201
        diag = r.json()
        assert diag["outcome"] == "COMPLETED"
        assert diag["artifact_id"] is not None

        r = await api_client.get(f"/executions/{diag['execution_id']}")
        assert r.json()["execution_status"] == "COMPLETED"  # never FAILED

        r = await api_client.get(f"/cases/{case['case_id']}")
        assert r.json()["case_status"] == "RESOLVED"


class TestHTTPCaseOrchestrationFailure:

    async def test_case_orchestration_failure_mapped_correctly(self, api_client):
        veh = await _register_vehicle(api_client)
        case = await _start_case_vir(api_client, veh)

        import product_integration.orchestration.case_orchestration as orch_module
        original = orch_module.transition_case_status
        orch_module.transition_case_status = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("test-injected"))
        try:
            r = await api_client.post(f"/cases/{case['case_id']}/diagnostics", json={"complaint_text": NOISE_COMPLAINT})
        finally:
            orch_module.transition_case_status = original

        assert r.status_code == 502
        body = r.json()
        assert body["error_category"] == "CASE_ORCHESTRATION_FAILURE"
        assert "case_id" in body
        assert "execution_id" in body
        # no raw exception text/type leaked
        assert "RuntimeError" not in str(body)
        assert "Traceback" not in str(body)


class TestProcessRestartContinuation:

    async def test_process_restart_continuation_surfaces_limitation_honestly(self, api_client, vir_isolated_store):
        """§46: the critical PI-05 frontier test. A fresh, empty registry
        simulates process restart. Required: typed 409, no raw exception,
        the underlying BLOCKED execution remains valid and queryable."""
        veh = await _register_vehicle(api_client)
        case = await _start_case_vir(api_client, veh)
        r = await api_client.post(f"/cases/{case['case_id']}/diagnostics", json={"complaint_text": NOISE_COMPLAINT})
        diag = r.json()
        assert diag["outcome"] == "BLOCKED"

        import vir.api.routes as vir_routes
        vir_transport = httpx.ASGITransport(app=vir_routes.app)

        async def override_vir_client():
            async with httpx.AsyncClient(transport=vir_transport, base_url="http://vir.test") as c:
                yield VIRClient(c)

        fresh_registry = PGDRSessionRegistry()
        restarted_app = create_app()
        restarted_app.dependency_overrides[get_vir_client] = override_vir_client
        restarted_app.dependency_overrides[get_pgdr_registry] = lambda: fresh_registry
        restarted_transport = httpx.ASGITransport(app=restarted_app)
        async with httpx.AsyncClient(transport=restarted_transport, base_url="http://api.test") as restarted_client:
            q = diag["pending_questions"][0]
            answer_value = q["choices"][0] if q.get("choices") else "yes"
            r2 = await restarted_client.post(
                f"/cases/{case['case_id']}/diagnostics/{diag['execution_id']}/answers",
                json={"question_id": q["question_id"], "value": answer_value},
            )
            assert r2.status_code == 409
            assert r2.json()["error_category"] == "PROCESS_LOCAL_STATE_UNAVAILABLE"

            r3 = await restarted_client.get(f"/executions/{diag['execution_id']}")
            assert r3.status_code == 200
            assert r3.json()["execution_status"] == "BLOCKED"  # still valid, not corrupted


class TestRestartDurability:

    async def test_full_journey_retrievable_after_fresh_session(self, api_client):
        veh = await _register_vehicle(api_client)
        case = await _start_case_vir(api_client, veh)
        r = await api_client.post(f"/cases/{case['case_id']}/diagnostics", json={"complaint_text": SMOKE_COMPLAINT})
        diag = r.json()
        assert diag["outcome"] == "COMPLETED"

        fresh = SessionLocal()
        fresh.close()  # dispose, then query fresh via a brand-new HTTP client / app instance

        import vir.api.routes as vir_routes
        vir_transport = httpx.ASGITransport(app=vir_routes.app)

        async def override_vir_client():
            async with httpx.AsyncClient(transport=vir_transport, base_url="http://vir.test") as c:
                yield VIRClient(c)

        new_app = create_app()
        new_app.dependency_overrides[get_vir_client] = override_vir_client
        new_transport = httpx.ASGITransport(app=new_app)
        async with httpx.AsyncClient(transport=new_transport, base_url="http://api.test") as new_client:
            r = await new_client.get(f"/cases/{case['case_id']}")
            assert r.status_code == 200
            assert r.json()["case_status"] == "RESOLVED"
            r = await new_client.get(f"/cases/{case['case_id']}/history")
            assert len(r.json()["executions"]) == 2
            r = await new_client.get(f"/executions/{diag['execution_id']}/artifact")
            assert r.status_code == 200


class TestRepeatedCalls:

    async def test_repeated_vehicle_registration(self, api_client):
        key_c, key_a = f"c-{uuid.uuid4().hex[:10]}", f"a-{uuid.uuid4().hex[:10]}"
        body = {"contact_idempotency_key": key_c, "asset_idempotency_key": key_a}
        r1 = await api_client.post("/vehicles", json=body)
        r2 = await api_client.post("/vehicles", json=body)
        assert r1.json()["contact_id"] == r2.json()["contact_id"]
        assert r1.json()["asset_id"] == r2.json()["asset_id"]

    async def test_repeated_diagnostic_start_no_duplicate(self, api_client):
        veh = await _register_vehicle(api_client)
        case = await _start_case_vir(api_client, veh)
        r1 = await api_client.post(f"/cases/{case['case_id']}/diagnostics", json={"complaint_text": NOISE_COMPLAINT})
        r2 = await api_client.post(f"/cases/{case['case_id']}/diagnostics", json={"complaint_text": NOISE_COMPLAINT})
        assert r1.json()["execution_id"] == r2.json()["execution_id"]

        r = await api_client.get(f"/cases/{case['case_id']}/history")
        pgdr_execs = [e for e in r.json()["executions"] if e["runner_type"] == "PGDR"]
        assert len(pgdr_execs) == 1
