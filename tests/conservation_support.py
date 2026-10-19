"""Shared helpers of the conservation tests: fictitious identifiers only,
temporary databases only, durations that are test values (never approved).
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app.db.engine import SessionLocal

TEST_DAYS = "30"                     # test value only, not a decided duration
SCHEMAS = ("cpl", "automotive", "pi_auth")
WATCHED_TABLES = ("cpl.asset_identity_resolutions", "automotive.vehicle_details", "cpl.runner_artifacts",
                  "cpl.runner_executions", "cpl.cases", "pi_auth.media_ownership",
                  "pi_auth.identifier_expunctions", "pi_auth.conservation_operations")


def fictive_identifiers() -> tuple[str, str]:
    """A VIN-shaped and a plate-shaped value that exist in no other test."""
    tag = uuid.uuid4().hex[:8].upper()
    return f"FAUXCNSRV{tag}"[:17].ljust(17, "Z"), f"FICTIVE-CONS-{tag}"


def policy_env(**overrides) -> dict[str, str]:
    env = {"PI_CONSERVATION_IDENTIFIANTS_JOURS": TEST_DAYS, "PI_CONSERVATION_DOSSIERS_JOURS": "illimitee",
           "PI_CONSERVATION_MEDIAS_JOURS": TEST_DAYS, "PI_CONSERVATION_JOURNAUX_JOURS": TEST_DAYS,
           "PI_CONSERVATION_SAUVEGARDES_JOURS": TEST_DAYS}
    env.update(overrides)
    return {k: v for k, v in env.items() if v is not None}


def clear_policy(monkeypatch) -> None:
    for name in ("PI_CONSERVATION_IDENTIFIANTS_JOURS", "PI_CONSERVATION_DOSSIERS_JOURS", "PI_CONSERVATION_MEDIAS_JOURS",
                 "PI_CONSERVATION_JOURNAUX_JOURS", "PI_CONSERVATION_SAUVEGARDES_JOURS"):
        monkeypatch.delenv(name, raising=False)


def scan(*values: str, database_url: str | None = None) -> dict[str, int]:
    """Every text, JSON or array column of the CPL and PI schemas holding one
    of the values: {"schema.table.column": number of rows}."""
    from sqlalchemy import create_engine
    engine = create_engine(database_url) if database_url else None
    session = SessionLocal(bind=engine) if engine else SessionLocal()
    try:
        columns = session.execute(text(
            "SELECT c.table_schema, c.table_name, c.column_name FROM information_schema.columns c "
            "JOIN information_schema.tables t ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
            "WHERE c.table_schema = ANY(:s) AND t.table_type = 'BASE TABLE' "
            "AND (c.data_type IN ('text', 'character varying', 'json', 'jsonb') OR c.data_type = 'ARRAY')"),
            {"s": list(SCHEMAS)}).all()
        found = {}
        params = {f"v{i}": f"%{value}%" for i, value in enumerate(values)}
        for schema, table, column in columns:
            where = " OR ".join(f'"{column}"::text LIKE :{name}' for name in params)
            n = session.execute(text(f'SELECT count(*) FROM "{schema}"."{table}" WHERE {where}'), params).scalar()
            if n:
                found[f"{schema}.{table}.{column}"] = n
        return found
    finally:
        session.close()
        if engine:
            engine.dispose()


def snapshot() -> dict[str, str]:
    with SessionLocal() as s:
        return {t: s.execute(text(f"SELECT md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) FROM {t} x"))
                .scalar() for t in WATCHED_TABLES}


def backdate_case(case_id, days: int) -> None:
    """Moves the case's identification records (and its vehicle detail row)
    `days` into the past: the test's way of being after the deadline."""
    with SessionLocal() as s:
        s.execute(text(
            "UPDATE cpl.asset_identity_resolutions SET created_at = created_at - make_interval(days => :d) "
            "WHERE execution_id IN (SELECT execution_id FROM cpl.runner_executions WHERE case_id = :c)"),
            {"d": days, "c": str(case_id)})
        s.execute(text(
            "UPDATE automotive.vehicle_details SET updated_at = updated_at - make_interval(days => :d), "
            "created_at = created_at - make_interval(days => :d) "
            "WHERE asset_id = (SELECT asset_id FROM cpl.cases WHERE case_id = :c)"), {"d": days, "c": str(case_id)})
        s.commit()


def backdate_media(media_id: str, days: int) -> None:
    with SessionLocal() as s:
        s.execute(text("UPDATE pi_auth.media_ownership SET created_at = created_at - make_interval(days => :d) "
                       "WHERE media_id = :m"), {"d": days, "m": media_id})
        s.commit()


def register_handmade(case_id, asset_id, vin: str, plate: str, authority, driver_confirmation=None):
    """A VIR result carrying the plate and the VIN in every place VIR puts
    them (identity, a candidate, evidence), registered through PI's real
    persistence path (artifact + identity resolution + vehicle detail)."""
    from product_integration.cpl_registration import register_vir_resolution_result
    from product_integration.vir.schemas import (
        CanonicalVehicleIdentity, FieldEvidence, SourceEvidence, VehicleCandidate, VehicleIdentityResolution,
    )
    identity = CanonicalVehicleIdentity(manufacturer="MARQUE-FICTIVE", model="MODELE-FICTIF", simulated=True,
                                        identifiers={"vin": vin, "registration_number": plate,
                                                     "registration_country": "FR"})
    resolution = VehicleIdentityResolution(
        request_id=f"cons-{uuid.uuid4().hex[:8]}", resolution_id=f"cons-res-{uuid.uuid4().hex[:8]}",
        created_at=datetime.now(timezone.utc), resolution_status="resolved", vehicle_identity=identity,
        alternative_candidates=[VehicleCandidate(candidate_id="c1", identity=identity)],
        field_evidence=[FieldEvidence(field_path="identifiers.vin", resolved_value=vin, sources=[
            SourceEvidence(source_id="fictive", reported_value=vin, reliability="high", source_value=vin)])],
        registration_country="FR", simulated=True)
    result = register_vir_resolution_result(vir_resolution=resolution, case_id=case_id, asset_id=asset_id,
                                            authority=authority, driver_confirmation=driver_confirmation)
    assert result.outcome == "SUCCESS", result.detail
    return result


def make_prefix(root: Path) -> Path:
    """A $PREFIX for the delivery scripts whose venv/bin/python and vir run
    this test environment (same interpreter, same PYTHONPATH)."""
    bindir = root / "prefix" / "venv" / "bin"
    bindir.mkdir(parents=True)
    (bindir / "python").write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    (bindir / "vir").write_text(f'#!/bin/sh\nexec "{sys.executable}" -m vir.cli.main "$@"\n')
    for f in bindir.iterdir():
        f.chmod(0o755)
    return root / "prefix"


def run(args, env: dict, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(args, env=env, capture_output=True, text=True, timeout=timeout)


def cli(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return run([sys.executable, "-m", "product_integration.conservation.cli", *args], env or dict(os.environ))
