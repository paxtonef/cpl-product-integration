"""Conservation 1/3 — plate and VIN in the vir_resolution artifacts (PI side of REQ-B6-091).

A. New writes: the artifact is registered without the plate and the VIN, everything else kept; the identity
   resolution and the vehicle detail keep them (their own conservation, unchanged); every reading works.
B. Artifacts registered before: counted by the purge, expurgated only by CPL's operator command (simulation by
   default), never by SQL from PI; after it, every reading still works and the integrity check says
   "expurgated by the authorized operation".

Real PI app, real VIR app (simulated fixture), real PGDR with a FICTIVE notice, temporary test database,
fictitious identifiers only.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from sqlalchemy import text

from app.cpl.models.runner_artifact import RunnerArtifact
from app.cpl.runners import redaction
from app.db.engine import SessionLocal

from product_integration.conservation import identifiants

from tests import conservation_support as cs
from tests.test_3a_persistance_parcours import confirmed
from tests.test_notice_parcours import (  # noqa: F401  (fixtures)
    RESOLVED_VIN, app, case, open_parcours, pgdr, user, user_a, vir_store,
)

pytestmark = pytest.mark.asyncio


def vir_artifacts(case_id: str) -> list[RunnerArtifact]:
    with SessionLocal() as s:
        ids = [r[0] for r in s.execute(text(
            "SELECT a.artifact_id FROM cpl.runner_artifacts a JOIN cpl.runner_executions e USING (execution_id) "
            "WHERE e.case_id = :c AND a.artifact_type = 'vir_resolution' ORDER BY a.created_at"), {"c": case_id})]
        out = [s.get(RunnerArtifact, i) for i in ids]
        s.expunge_all()
        return out


def integrity(artifact_id) -> str:
    with SessionLocal() as s:
        return redaction.classify_integrity(s, s.get(RunnerArtifact, artifact_id))


def identity_copies(case_id: str) -> tuple[list, object]:
    with SessionLocal() as s:
        resolutions = [r[0] for r in s.execute(text(
            "SELECT r.canonical_identity_payload FROM cpl.asset_identity_resolutions r JOIN cpl.runner_executions e "
            "USING (execution_id) WHERE e.case_id = :c"), {"c": case_id})]
        detail = s.execute(text("SELECT d.vin_display, d.registration_display FROM automotive.vehicle_details d "
                                "JOIN cpl.cases c ON c.asset_id = d.asset_id WHERE c.case_id = :c"), {"c": case_id}).first()
    return resolutions, detail


async def readings_work(client, case_id: str) -> None:
    """Everything the product reads from a vir_resolution artifact, unaffected by the identifiers' absence."""
    r = await client.get(f"/cases/{case_id}/vir")
    assert r.status_code == 200, r.text
    artifact = vir_artifacts(case_id)[-1]
    r = await client.get(f"/executions/{artifact.execution_id}/artifact")
    assert r.status_code == 200 and r.json()["payload"]["resolution_id"] == artifact.payload["resolution_id"], r.text
    assert (await open_parcours(client, case_id))["status"] == "opened"     # VIR -> PGDR handoff from the payload
    _, out = await confirmed(client, case_id)
    assert out["phase"] == "restitution"


# -- A. new writes ----------------------------------------------------------------------------------

async def test_new_vir_resolution_artifacts_are_written_without_plate_and_vin(app, pgdr, user_a, full_authority):
    case_id = await case(user_a)
    [artifact] = vir_artifacts(case_id)
    dumped = json.dumps(artifact.payload)
    assert RESOLVED_VIN not in dumped and not redaction.holds_vehicle_identifier(artifact.payload)
    assert artifact.payload["vehicle_identity"]["identifiers"]["vin"] is None
    assert artifact.payload["vehicle_identity"]["model"] and artifact.payload["resolution_id"]
    assert [fe["field_path"] for fe in artifact.payload["field_evidence"]]          # provenance kept
    assert artifact.artifact_status == "VALIDATED" and artifact.redaction_status is None
    assert integrity(artifact.artifact_id) == redaction.IntegrityClass.ORIGINAL_INTACT
    # asset_identity_resolutions and vehicle_details: unchanged treatment, they keep the identifiers.
    resolutions, detail = identity_copies(case_id)
    assert resolutions[0]["identifiers"]["vin"] == RESOLVED_VIN and detail.vin_display == RESOLVED_VIN

    # Every location VIR uses, through PI's real persistence path: none reaches the artifact.
    vin, plate = cs.fictive_identifiers()
    hand = await case(user_a)
    with SessionLocal() as s:
        asset_id = s.execute(text("SELECT asset_id FROM cpl.cases WHERE case_id = :c"), {"c": hand}).scalar()
    cs.register_handmade(hand, asset_id, vin, plate, full_authority)
    assert "cpl.runner_artifacts.payload" not in cs.scan(vin, plate)
    assert {"cpl.asset_identity_resolutions.canonical_identity_payload",
            "automotive.vehicle_details.vin_display"} <= set(cs.scan(vin, plate))
    await readings_work(user_a, case_id)


# -- B. artifacts registered before -------------------------------------------------------------------

def command(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "app.cpl.runners.redaction_command", *args],
                          capture_output=True, text=True, env=dict(os.environ), timeout=120)


async def test_older_artifacts_are_expurgated_only_by_the_cpl_command(app, pgdr, user_a, monkeypatch):
    # An artifact as written before REQ-B6-091: the same path without the removal.
    import product_integration.cpl_registration as registration
    with monkeypatch.context() as m:              # only this patch: the fixtures' own stay in place
        m.setattr(registration, "redact_vehicle_identifiers", lambda payload: (payload, []))
        case_id = await case(user_a)
    [old] = vir_artifacts(case_id)
    assert RESOLVED_VIN in json.dumps(old.payload) and redaction.holds_vehicle_identifier(old.payload)
    registered_hash = old.content_hash
    cs.backdate_case(case_id, 40)
    try:
        with SessionLocal() as s:
            assert identifiants.plan(s, identifiants_cutoff()).artifacts_blocked >= 1     # counted by the purge

        # Simulation by default: nothing written, no value printed.
        sim = command("--motif", "RETENTION_POLICY", "--operateur", "op-cons-0001", "--artefact", str(old.artifact_id))
        assert sim.returncode == 0, sim.stdout + sim.stderr
        assert "simulation" in sim.stdout and f"à expurger {old.artifact_id}" in sim.stdout
        assert RESOLVED_VIN not in sim.stdout + sim.stderr
        assert vir_artifacts(case_id)[0].payload == old.payload

        run = command("--motif", "RETENTION_POLICY", "--operateur", "op-cons-0001", "--artefact", str(old.artifact_id),
                      "--executer")
        assert run.returncode == 0 and "1 artefact(s) expurgé(s)" in run.stdout, run.stdout + run.stderr
        assert RESOLVED_VIN not in run.stdout + run.stderr
        [now] = vir_artifacts(case_id)
        assert RESOLVED_VIN not in json.dumps(now.payload) and now.redaction_status == "REDACTED"
        assert now.artifact_id == old.artifact_id and now.execution_id == old.execution_id
        assert now.payload["resolution_id"] == old.payload["resolution_id"]
        assert integrity(now.artifact_id) == redaction.IntegrityClass.REDACTED_AUTHORIZED
        with SessionLocal() as s:
            trace = s.execute(text("SELECT original_content_hash, operator_reference, redacted_locations "
                                   "FROM cpl.runner_artifact_redactions WHERE artifact_id = :a"),
                              {"a": now.artifact_id}).one()
            assert identifiants.plan(s, identifiants_cutoff()).artifacts_blocked == 0
        assert trace.original_content_hash == registered_hash and trace.operator_reference == "op-cons-0001"
        assert RESOLVED_VIN not in json.dumps(trace.redacted_locations)
        # The identity resolution and the vehicle detail are not this command's: untouched.
        resolutions, detail = identity_copies(case_id)
        assert resolutions[0]["identifiers"]["vin"] == RESOLVED_VIN and detail.vin_display == RESOLVED_VIN

        again = command("--motif", "RETENTION_POLICY", "--operateur", "op-cons-0001", "--artefact",
                        str(old.artifact_id), "--executer")
        assert again.returncode == 0 and "déjà expurgés : 1" in again.stdout     # idempotent
        await readings_work(user_a, case_id)
    finally:
        cs.backdate_case(case_id, -40)


def identifiants_cutoff():
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone.utc) - timedelta(days=int(cs.TEST_DAYS))
