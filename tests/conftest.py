"""PI-01 test configuration.

VIR is exercised through its REAL FastAPI app via httpx's ASGITransport —
the actual HTTP-shaped request/response cycle (headers, status codes, JSON
serialization) runs, in-process, without a live socket. This is exactly
the "VIR's own TestClient... or a live VIR process" arrangement §25 of the
PI-01 instruction permits for the definitive acceptance test; VIR's own
test suite (tests/test_api_persistence.py, read directly) uses the same
isolation pattern (an isolated SQLite store, swapped in via monkeypatch),
reused here rather than reinvented.
"""
from __future__ import annotations

import os
import uuid

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://pi01:pi01@localhost/pi01_test")

import httpx
import pytest
import pytest_asyncio

from app.db.engine import SessionLocal, check_db_connection
from app.cpl.identity.authority import AuthorityContext
from app.cpl.assets.authority import AssetAuthority
from app.cpl.runners.authority import RunnerAuthority
from app.cpl.models.contact import Contact
from app.cpl.models.asset import Asset
from app.cpl.models.case import Case

from product_integration.vir.client import VIRClient
from product_integration.vir.schemas import ConsentInput, VehicleIdentityRequest

pytestmark = pytest.mark.skipif(not check_db_connection(), reason="PostgreSQL not available")


@pytest.fixture(scope="session", autouse=True)
def migrate_cpl():
    """Applies the CPL migration chain (through 027) once per test
    session, exactly as CPL's own conftest.py does — reused, not
    reinvented, per the instruction's "no CPL migration authorized by
    PI-01" rule (this only *applies* CPL's existing chain, it adds
    nothing)."""
    if check_db_connection():
        from sqlalchemy import text
        from alembic.config import Config
        from alembic import command
        from app.db.engine import engine

        with engine.connect() as conn:
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS cpl"))
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS automotive"))
            conn.commit()
        cfg = Config(str(_cpl_alembic_ini()))
        cfg.set_main_option("sqlalchemy.url", str(engine.url))
        cfg.set_main_option("script_location", str(_cpl_alembic_ini().parent / "migrations"))
        command.upgrade(cfg, "head")


def _cpl_alembic_ini():
    import app
    from pathlib import Path
    return Path(app.__file__).resolve().parent.parent / "alembic.ini"


@pytest.fixture
def full_authority() -> AuthorityContext:
    """Every authority grant PI-01's own code paths require, spanning
    both B6's RunnerAuthority and B4's AssetAuthority classes."""
    return AuthorityContext(
        granted=frozenset({
            RunnerAuthority.ADMIT_EXECUTION, RunnerAuthority.TRANSITION_EXECUTION_STATUS,
            RunnerAuthority.REGISTER_ARTIFACT, RunnerAuthority.READ_EXECUTION,
            AssetAuthority.CONSUME_IDENTITY_RESOLUTION, AssetAuthority.CREATE_ASSET, AssetAuthority.READ_ASSET,
        }),
        actor_reference="pi-01-test-suite",
    )


@pytest.fixture
def cpl_case_context():
    """Creates a real, committed Contact/Asset/Case triple using a plain
    committing session (not the rollback-wrapped pattern CPL's own unit
    tests use) — required because register_vir_execution opens its own
    independently-committing sessions and must see this data. Cleans up
    explicitly afterward, mirroring B6's own test_b6_concurrency.py
    live-session pattern."""
    session = SessionLocal()
    contact = Contact(contact_type="PERSON", display_name="PI-01 Test Contact")
    session.add(contact)
    session.flush()
    asset = Asset(asset_domain="AUTOMOTIVE", asset_type="PASSENGER_CAR", asset_status="ACTIVE")
    session.add(asset)
    session.flush()
    case = Case(primary_contact_id=contact.contact_id, asset_id=asset.asset_id, domain="AUTOMOTIVE", case_type="VEHICLE_IDENTIFICATION")
    session.add(case)
    session.flush()
    session.commit()
    ids = {"contact_id": contact.contact_id, "asset_id": asset.asset_id, "case_id": case.case_id}
    session.close()

    yield ids

    cleanup = SessionLocal()
    from app.cpl.models.runner_governance_decision import RunnerGovernanceDecision
    from app.cpl.models.runner_artifact import RunnerArtifact
    from app.cpl.models.runner_execution import RunnerExecution
    from app.cpl.models.asset_identity_resolution import AssetIdentityResolution
    from app.automotive.models.vehicle_detail import VehicleDetail
    from sqlalchemy import text as sa_text

    cleanup.execute(sa_text("DELETE FROM automotive.vehicle_details WHERE asset_id = :a"), {"a": str(ids["asset_id"])})
    # RunnerGovernanceDecision rows from ARTIFACT_REGISTRATION/SUPERSESSION
    # set artifact_id, not execution_id (confirmed directly in
    # app/cpl/runners/artifacts.py) — deleting by execution_id alone
    # misses them and leaves a dangling FK to runner_artifacts. Delete by
    # BOTH execution_id and artifact_id before touching runner_artifacts.
    cleanup.execute(sa_text(
        "DELETE FROM cpl.runner_governance_decisions WHERE execution_id IN "
        "(SELECT execution_id FROM cpl.runner_executions WHERE case_id = :c) "
        "OR artifact_id IN (SELECT artifact_id FROM cpl.runner_artifacts WHERE execution_id IN "
        "(SELECT execution_id FROM cpl.runner_executions WHERE case_id = :c))"
    ), {"c": str(ids["case_id"])})
    cleanup.execute(sa_text("DELETE FROM cpl.runner_artifacts WHERE execution_id IN "
                             "(SELECT execution_id FROM cpl.runner_executions WHERE case_id = :c)"), {"c": str(ids["case_id"])})
    cleanup.execute(sa_text("DELETE FROM cpl.asset_identity_resolutions WHERE asset_id = :a"), {"a": str(ids["asset_id"])})
    cleanup.execute(sa_text("DELETE FROM cpl.runner_executions WHERE case_id = :c"), {"c": str(ids["case_id"])})
    cleanup.execute(sa_text("DELETE FROM cpl.cases WHERE case_id = :c"), {"c": str(ids["case_id"])})
    cleanup.execute(sa_text("DELETE FROM cpl.assets WHERE asset_id = :a"), {"a": str(ids["asset_id"])})
    cleanup.execute(sa_text("DELETE FROM cpl.contacts WHERE contact_id = :ct"), {"ct": str(ids["contact_id"])})
    cleanup.commit()
    cleanup.close()


@pytest.fixture
def vir_isolated_store(tmp_path):
    """VIR's own isolation pattern, reused verbatim: an isolated SQLite
    store swapped onto VIR's real app via monkeypatch, so PI-01's tests
    never touch a real vir_data.db and can't interfere with each other."""
    from vir.adapters.sqlite_persistence_adapter import SQLitePersistenceAdapter
    import vir.api.routes as vir_routes

    store = SQLitePersistenceAdapter(str(tmp_path / "pi01_test_vir.db"))
    original_store = vir_routes.STORE
    vir_routes.STORE = store
    yield store
    vir_routes.STORE = original_store


@pytest_asyncio.fixture
async def vir_client(vir_isolated_store) -> VIRClient:
    """A real VIRClient bound to VIR's actual FastAPI app via ASGI
    transport — no network socket, but the genuine HTTP-shaped path."""
    import vir.api.routes as vir_routes

    transport = httpx.ASGITransport(app=vir_routes.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://vir.test") as http_client:
        yield VIRClient(http_client)


def make_vin_request(vin: str = "VF3XXXXXXXXXXXXXX", request_id: str | None = None) -> VehicleIdentityRequest:
    """VF3XXXXXXXXXXXXXX is VIR's own known-good stub VIN (confirmed in
    VIR's own tests/test_persistence.py and tests/test_api_persistence.py,
    read directly at the pinned baseline) — resolves deterministically to
    a Peugeot via the in-memory VIN decoder stub adapter."""
    return VehicleIdentityRequest(
        request_id=request_id or f"PI01-TEST-{uuid.uuid4().hex[:12]}",
        vin=vin, consent=ConsentInput(external_lookup_allowed=True),
    )
