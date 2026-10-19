"""Preparation for production, block 4 — the context handed to PGDR is
built from an explicit whitelist of technical characteristics. Vehicle
identifiers (plate, VIN, registration country) and registration-document
data (first registration date) never reach PGDR: PGDR's applicability and
diagnostic logic never reads them (pgdr 7b863c0: the only consumer of a
first registration date, the Peugeot knowledge adapter, is always given
None by VehicleApplicabilityContext.from_pgdr_vehicle_identity_dict).
Objects stay linked through the opaque VIR resolution_id.
"""
from __future__ import annotations

import json
import logging
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.db.engine import SessionLocal
from vir.domain.enums import ResolutionStatus as VIRResolutionStatus
from vir.domain.models import (
    CanonicalVehicleIdentity,
    Contradiction,
    DiagnosticIdentityContext,
    Engine,
    Identifiers,
    Production,
    VehicleIdentityResolution,
)

from product_integration.api.app import create_app
from product_integration.api.deps import get_vir_client
from product_integration.pgdr.handoff_mapper import (
    PGDR_DIAGNOSTIC_CONTEXT_FIELDS,
    PGDR_VEHICLE_IDENTITY_FIELDS,
    map_diagnostic_context,
    map_resolution,
)
from product_integration.vir.client import VIRClient

from tests.auth_support import log_in, new_account

FICTIVE_VIN = "VF3XXXXXXXXXXXXXX"
FICTIVE_PLATE = "ZZ-999-ZZ"
FORBIDDEN_KEYS = {"identifiers", "vin", "registration_number", "registration_country", "first_registration_date"}


def _identity() -> CanonicalVehicleIdentity:
    return CanonicalVehicleIdentity(
        manufacturer="Peugeot", model="308", generation="T9",
        production=Production(year=2016, start_date="2016-01-01"),
        engine=Engine(engine_code="EB2", power_kw=96.0),
        identifiers=Identifiers(vin=FICTIVE_VIN, registration_number=FICTIVE_PLATE, registration_country="FR"),
        first_registration_date="2016-05-17", model_year=2016,
    )


def _keys(node) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {k for v in node.values() for k in _keys(v)}
    return set()


class TestWhitelist:

    def test_richer_path_drops_identifiers_and_registration_data(self):
        resolution = VehicleIdentityResolution(
            request_id="REQ", resolution_id="VIR-RES-W1", resolution_status=VIRResolutionStatus.RESOLVED,
            vehicle_identity=_identity(),
        )
        context = map_resolution(resolution)
        dumped = context.model_dump_json()
        assert FICTIVE_VIN not in dumped and FICTIVE_PLATE not in dumped and "2016-05-17" not in dumped
        assert not (_keys(context.vehicle_identity) & FORBIDDEN_KEYS)
        assert set(context.vehicle_identity) <= set(PGDR_VEHICLE_IDENTITY_FIELDS)
        # technical characteristics, unknowns included, are preserved
        vi = context.vehicle_identity
        assert (vi["manufacturer"], vi["model"], vi["generation"]) == ("Peugeot", "308", "T9")
        assert vi["engine"]["engine_code"] == "EB2" and vi["engine"]["displacement_cc"] is None
        assert vi["production"] == {"year": 2016, "start_date": "2016-01-01", "end_date": None}
        assert vi["model_year"] == 2016 and vi["simulated"] is False
        assert context.resolution_id == "VIR-RES-W1"  # opaque link to the VIR record

    def test_unknowns_and_contradictions_survive(self):
        resolution = VehicleIdentityResolution(
            request_id="REQ", resolution_id="VIR-RES-W2", resolution_status=VIRResolutionStatus.CONTRADICTORY,
            vehicle_identity=_identity(), unresolved_fields=["engine.engine_code"],
            contradictions=[Contradiction(contradiction_id="C1", field_path="model", severity="high")],
        )
        context = map_resolution(resolution)
        assert context.unresolved_fields == ["engine.engine_code"]
        assert context.contradictions == ["model"]

    def test_diagnostic_context_path_drops_registration_data(self):
        context = map_diagnostic_context(DiagnosticIdentityContext(
            resolution_id="VIR-RES-W3", identity_status=VIRResolutionStatus.RESOLVED,
            vehicle={"manufacturer": "Peugeot", "model": "308", "first_registration_date": "2016-05-17",
                     "vin": FICTIVE_VIN, "registration_number": FICTIVE_PLATE, "power_kw": None},
            diagnostic_constraints={}, registration_country="FR",
        ))
        assert context.vehicle_identity == {"manufacturer": "Peugeot", "model": "308", "power_kw": None}
        assert set(context.vehicle_identity) <= set(PGDR_DIAGNOSTIC_CONTEXT_FIELDS)

    def test_whitelists_name_no_identifier(self):
        assert not (set(PGDR_VEHICLE_IDENTITY_FIELDS) & FORBIDDEN_KEYS)
        assert not (set(PGDR_DIAGNOSTIC_CONTEXT_FIELDS) & FORBIDDEN_KEYS)


# -- end to end: real VIR (ASGI), real PGDR, real PostgreSQL ----------------

@pytest.fixture
def vir_isolated_store(tmp_path):
    from vir.adapters.sqlite_persistence_adapter import SQLitePersistenceAdapter
    import vir.api.routes as vir_routes
    store = SQLitePersistenceAdapter(str(tmp_path / "whitelist_vir.db"))
    original = vir_routes.STORE
    vir_routes.STORE = store
    yield store
    vir_routes.STORE = original


@pytest_asyncio.fixture
async def api_client(vir_isolated_store):
    import vir.api.routes as vir_routes
    vir_transport = httpx.ASGITransport(app=vir_routes.app)

    async def override_vir_client():
        async with httpx.AsyncClient(transport=vir_transport, base_url="http://vir.test") as c:
            yield VIRClient(c)

    app = create_app()
    app.dependency_overrides[get_vir_client] = override_vir_client
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test") as client:
        await log_in(client, *new_account("whitelist"))
        yield client


class TestEndToEnd:

    async def test_pgdr_context_report_logs_and_errors_carry_no_identifier(self, api_client, monkeypatch, caplog):
        import pgdr.session_controller as pgdr_sc
        seen: list[str] = []
        original_start = pgdr_sc.SessionController.start

        def spy_start(self, request, *args, **kwargs):
            seen.append(request.model_dump_json())
            return original_start(self, request, *args, **kwargs)

        monkeypatch.setattr(pgdr_sc.SessionController, "start", spy_start)
        caplog.set_level(logging.DEBUG)

        veh = (await api_client.post("/vehicles", json={"contact_idempotency_key": uuid.uuid4().hex,
                                                         "asset_idempotency_key": uuid.uuid4().hex})).json()
        r = await api_client.post("/cases", json={
            "contact_id": veh["contact_id"], "asset_id": veh["asset_id"], "request_id": uuid.uuid4().hex,
            "vin": FICTIVE_VIN, "registration_number": FICTIVE_PLATE, "registration_country_code": "FR",
            "consent": {"external_lookup_allowed": True}, "case_idempotency_key": uuid.uuid4().hex,
        })
        assert r.status_code == 201, r.text
        case = r.json()
        r = await api_client.post(f"/cases/{case['case_id']}/diagnostics",
                                  json={"complaint_text": "There is smoke coming from under the hood and a burning smell."})
        assert r.status_code in (200, 201), r.text
        diag = r.json()

        assert seen, "PGDR was started"
        for request_json in seen:
            assert FICTIVE_VIN not in request_json and FICTIVE_PLATE not in request_json
            assert '"identifiers"' not in request_json and "first_registration_date" not in request_json

        # what PGDR produced and CPL stored for it
        with SessionLocal() as s:
            payloads = s.execute(text(
                "SELECT a.payload FROM cpl.runner_artifacts a JOIN cpl.runner_executions x ON x.execution_id = a.execution_id "
                "WHERE x.case_id = :c AND x.runner_type = 'PGDR'"), {"c": case["case_id"]}).scalars().all()
        assert payloads
        for payload in payloads:
            dumped = json.dumps(payload)
            assert FICTIVE_VIN not in dumped and FICTIVE_PLATE not in dumped

        # the PGDR result as served to the user
        r = await api_client.get(f"/executions/{diag['execution_id']}/artifact")
        assert FICTIVE_VIN not in r.text and FICTIVE_PLATE not in r.text

        # an error path: an unknown clarification answer is refused by VIR
        r = await api_client.post(f"/cases/{case['case_id']}/vir/clarifications",
                                  json={"answers": [{"question_id": "no-such-question", "value": FICTIVE_PLATE + "?"}]})
        assert FICTIVE_VIN not in r.text

        logged = "\n".join(record.getMessage() for record in caplog.records)
        assert FICTIVE_VIN not in logged and FICTIVE_PLATE not in logged
