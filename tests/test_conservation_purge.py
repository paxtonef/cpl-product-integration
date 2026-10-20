"""Conservation — policy, simulation, execution of the purge (PI).

Real PI-05 app, real PostgreSQL (temporary test database), real VIR app
(simulated fixture), real PGDR app with a FICTIVE notice. Identifiers are
fictitious and unique to these tests; the periods are test values (30 days),
never approved durations. "After the deadline" = records moved 40 days into
the past; "before" = records of now.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.db.engine import SessionLocal
from app.cpl.models.runner_artifact import RunnerArtifact
from app.cpl.runners.artifacts import IntegrityCheckOutcome, verify_content_integrity

from product_integration.conservation import policy, purge
from product_integration.conservation.cli import readiness

from tests import conservation_support as cs
from tests.auth_support import new_account
from tests.test_3a_persistance_parcours import confirmed
from tests.test_notice_parcours import app, case, pgdr, user, user_a, user_b, vir_store  # noqa: F401  (fixtures)

pytestmark = pytest.mark.asyncio


def _env(**overrides) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PI_CONSERVATION_")}
    env.update(cs.policy_env(**overrides))
    return env


def _case_ids(case_id: str) -> dict:
    with SessionLocal() as s:
        row = s.execute(text("SELECT asset_id FROM cpl.cases WHERE case_id = :c"), {"c": case_id}).one()
        resolutions = s.execute(text(
            "SELECT r.resolution_id, r.canonical_identity_payload, r.provenance_payload, r.execution_id "
            "FROM cpl.asset_identity_resolutions r JOIN cpl.runner_executions e ON e.execution_id = r.execution_id "
            "WHERE e.case_id = :c ORDER BY r.created_at"), {"c": case_id}).all()
        detail = s.execute(text("SELECT vin_display, registration_display, registration_country, make, model, "
                                "source_resolution_id FROM automotive.vehicle_details WHERE asset_id = :a"),
                           {"a": row.asset_id}).first()
    return {"asset_id": row.asset_id, "resolutions": resolutions, "detail": detail}


def _premier_constat(case_id: str) -> list:
    with SessionLocal() as s:
        return s.execute(text(
            "SELECT a.artifact_id, a.payload, a.content_hash FROM cpl.runner_artifacts a JOIN cpl.runner_executions e "
            "ON e.execution_id = a.execution_id WHERE e.case_id = :c AND a.schema_name = 'pgdr_v1_premier_constat' "
            "ORDER BY a.created_at"), {"c": case_id}).all()


# -- policy ---------------------------------------------------------------------------------------

async def test_policy_is_explicit_per_category_and_never_taken_from_vir(monkeypatch):
    cs.clear_policy(monkeypatch)
    monkeypatch.setenv("VIR_RETENTION_DAYS", "30")
    settings = policy.read_policy()
    assert all(not s.defined for s in settings.values())            # VIR's setting is not assimilated
    assert {c.env for c in policy.ALL} == {
        "PI_CONSERVATION_IDENTIFIANTS_JOURS", "PI_CONSERVATION_DOSSIERS_JOURS", "PI_CONSERVATION_MEDIAS_JOURS",
        "PI_CONSERVATION_JOURNAUX_JOURS", "PI_CONSERVATION_SAUVEGARDES_JOURS"}
    assert policy.read_setting(policy.MEDIA, {"PI_CONSERVATION_MEDIAS_JOURS": "illimitee"}).unlimited
    assert policy.read_setting(policy.MEDIA, {"PI_CONSERVATION_MEDIAS_JOURS": "12"}).days == 12
    for bad in ("0", "-3", "30j", "1.5", "unlimited"):
        with pytest.raises(policy.PolicyError):
            policy.read_setting(policy.MEDIA, {"PI_CONSERVATION_MEDIAS_JOURS": bad})


async def test_readiness_reports_an_incomplete_production_configuration(monkeypatch, tmp_path):
    complete, lines = readiness({"MONTAGE_DIR": str(tmp_path)})
    assert not complete and sum("non définie" in l for l in lines) == 5 and any("VIR_RETENTION_DAYS" in l for l in lines)
    env = {**cs.policy_env(), "VIR_RETENTION_DAYS": "30", "MONTAGE_DIR": str(tmp_path)}
    complete, lines = readiness(env)
    assert complete and any("artefacts vir_resolution" in l for l in lines)       # the known limit is stated
    assert not readiness({**env, "PI_CONSERVATION_DOSSIERS_JOURS": "30"})[0]     # not applicable to cases
    (tmp_path / "RESTAURATION_A_PURGER").write_text("x")
    assert not readiness(env)[0]
    r = cs.cli("controle", env={**os.environ, **{k: "" for k in cs.policy_env()}, "VIR_RETENTION_DAYS": ""})
    assert r.returncode == 1 and "INCOMPLET" in r.stdout


# -- simulation and refusal without policy --------------------------------------------------------

async def test_without_policy_simulation_says_nothing_would_be_deleted_and_execution_refuses(app, user_a, monkeypatch):
    case_id = await case(user_a)
    cs.backdate_case(case_id, 40)
    before = cs.snapshot()
    env = {k: v for k, v in os.environ.items() if not k.startswith("PI_CONSERVATION_")}
    r = cs.cli("purge", env=env)
    assert r.returncode == 0 and r.stdout.count(purge.NO_POLICY) == 4, r.stdout
    r = cs.cli("purge", "--executer", env=env)
    assert r.returncode == 2 and "Exécution refusée, rien n'est supprimé" in r.stderr
    r = cs.cli("purge", "--executer", env=_env(PI_CONSERVATION_DOSSIERS_JOURS="30"))
    assert r.returncode == 2 and "aucune suppression de dossier" in r.stderr
    r = cs.cli("purge", "--executer", env=_env(PI_CONSERVATION_MEDIAS_JOURS=None))
    assert r.returncode == 2 and "PI_CONSERVATION_MEDIAS_JOURS" in r.stderr
    assert cs.snapshot() == before                                     # nothing written, no operation recorded
    cs.backdate_case(case_id, -40)                                     # back to now: not due for the next tests


# -- execution --------------------------------------------------------------------------------------

async def test_purge_empties_due_identifiers_everywhere_allowed_and_keeps_cases_results_and_rights(
        app, pgdr, user_a, user_b, full_authority, tmp_path, monkeypatch):
    purge.execute(environ=_env())     # records left due by an earlier run of these tests: a clean start
    # A case past its period: VIN identification, a driver confirmation (second version), a confirmed
    # notice result (Premier Constat); a second case past its period carrying a unique plate and VIN
    # in every place VIR puts them, in two versions; a third, recent case with the same unique values.
    old = await case(user_a)
    assert (await user_a.post(f"/cases/{old}/vir/confirmations",
                              json={"field_path": "drivetrain", "value": "front_wheel_drive"})).status_code == 200
    await confirmed(user_a, old)
    vin, plate = cs.fictive_identifiers()
    hand = await case(user_a)
    hand_ids = _case_ids(hand)
    cs.register_handmade(hand, hand_ids["asset_id"], vin, plate, full_authority)
    cs.register_handmade(hand, hand_ids["asset_id"], vin, plate, full_authority,
                         driver_confirmation={"operation": "confirm", "field_path": "model", "updates_execution_id": "x"})
    recent = await case(user_a)
    cs.register_handmade(recent, _case_ids(recent)["asset_id"], vin, plate, full_authority)
    for c in (old, hand):
        cs.backdate_case(c, 40)

    # media: one past its period, one recent; logs: rotated old/new, active
    storage = tmp_path / "media"
    monkeypatch.setenv("PI05_MEDIA_STORAGE_DIR", str(storage))
    from product_integration.api.deps import get_media_storage
    from product_integration.media.storage import LocalMediaStorage
    app.dependency_overrides[get_media_storage] = lambda: LocalMediaStorage(storage)
    png = b"\x89PNG\r\n\x1a\nfictive"
    m_old = (await user_a.post("/media", files={"file": ("a.png", png, "image/png")})).json()["media_id"]
    m_new = (await user_a.post("/media", files={"file": ("b.png", png, "image/png")})).json()["media_id"]
    cs.backdate_media(m_old, 40)
    montage = tmp_path / "montage"
    montage.mkdir()
    for name in ("pi05.log", "pi05.log.1", "pgdr.log-20260101.gz", "vir.log.2.gz", "notes.txt"):
        (montage / name).write_text("fictive log line\n")
    forty = (datetime.now(timezone.utc) - timedelta(days=40)).timestamp()
    for name in ("pi05.log", "pgdr.log-20260101.gz", "vir.log.2.gz", "notes.txt"):
        os.utime(montage / name, (forty, forty))

    env = _env(MONTAGE_DIR=str(montage), PI05_MEDIA_STORAGE_DIR=str(storage))
    constat_before = _premier_constat(old)
    assert len(constat_before) == 1
    before_scan = cs.scan(vin, plate)
    # REQ-B6-091: the vir_resolution artifacts are registered without the plate and the VIN.
    assert set(before_scan) == {"cpl.asset_identity_resolutions.canonical_identity_payload",
                                "automotive.vehicle_details.vin_display", "automotive.vehicle_details.registration_display"}

    # simulation: counts, nothing written
    before = cs.snapshot()
    sim = cs.cli("purge", env=env)
    assert sim.returncode == 0 and cs.snapshot() == before, sim.stderr
    assert "5 résolution(s) d'identité et 2 fiche(s) véhicule seraient vidées" in sim.stdout, sim.stdout
    assert "1 média(s) seraient supprimés" in sim.stdout and "2 journal(aux) tourné(s)" in sim.stdout
    assert vin not in sim.stdout + sim.stderr and plate not in sim.stdout + sim.stderr

    # execution
    run1 = cs.cli("purge", "--executer", env=env)
    assert run1.returncode == 0, run1.stderr
    assert "5 résolution(s) d'identité et 2 fiche(s) véhicule vidées" in run1.stdout
    assert "0 copie(s) échue(s) restante(s) hors artefacts" in run1.stdout
    assert "1 média(s) supprimé(s)" in run1.stdout and "2 journal(aux) supprimé(s)" in run1.stdout
    for out in (run1.stdout, run1.stderr):
        assert vin not in out and plate not in out and "VF3XXXXXXXXXXXXXX" not in out

    # identifiers: gone from the resolutions and the vehicle details past their period ...
    after_scan = cs.scan(vin, plate)
    assert after_scan["cpl.asset_identity_resolutions.canonical_identity_payload"] == 1          # the recent case
    assert after_scan["automotive.vehicle_details.vin_display"] == 1                              # the recent case
    # ... and never in the vir_resolution artifacts, registered without them (REQ-B6-091; older artifacts:
    # tests/test_conservation_artefacts.py)
    assert "cpl.runner_artifacts.payload" not in after_scan
    assert not any(k.startswith("pi_auth.") for k in after_scan)                                  # no value in the trace
    for c in (old, hand):
        ids = _case_ids(c)
        for r in ids["resolutions"]:
            identity = r.canonical_identity_payload
            assert identity["identifiers"].get("vin") is None and identity["identifiers"].get("registration_number") is None
            if r.canonical_identity_payload["identifiers_not_kept"] == ["registration_number", "vin"]:
                assert identity["identifiers"]["registration_country"] == "FR"         # kept: not an identifier
            assert "vin" in identity["identifiers_not_kept"] and identity["manufacturer"]   # marked, rest intact
            assert r.provenance_payload.get("vir_resolution_id")                            # provenance kept
        assert ids["detail"].vin_display is None and ids["detail"].registration_display is None
        assert ids["detail"].make and ids["detail"].source_resolution_id is not None       # link kept
    assert _case_ids(recent)["detail"].vin_display == vin                                  # before its deadline: kept

    # every artifact intact (content hash), the Premier Constat unchanged
    with SessionLocal() as s:
        for a in s.query(RunnerArtifact).all():
            assert verify_content_integrity(a) != IntegrityCheckOutcome.MISMATCH
    assert _premier_constat(old) == constat_before

    # trace of the operation, without any value
    with SessionLocal() as s:
        op = s.execute(text("SELECT outcome, counts, policy, trigger FROM pi_auth.conservation_operations "
                            "ORDER BY started_at DESC LIMIT 1")).one()
        marks = s.execute(text("SELECT target_kind, fields FROM pi_auth.identifier_expunctions e "
                               "JOIN pi_auth.conservation_operations o USING (operation_id) "
                               "WHERE o.started_at = (SELECT max(started_at) FROM pi_auth.conservation_operations)")).all()
    assert op.outcome == "completed" and op.trigger == "operator"
    assert op.counts["resolutions"] == 5 and op.counts["vehicle_details"] == 2 and op.counts["media"] == 1
    assert op.counts["artifacts_blocked"] == 0 and op.policy["identifiants"]["days"] == 30
    assert sorted(m.target_kind for m in marks).count("asset_identity_resolution") == 5

    # reading after the purge: understandable, rights kept
    r = await user_a.get(f"/cases/{old}/vir")
    assert r.status_code == 410 and r.json()["error_category"] == "VIR_RESULT_NOT_KEPT", r.text
    with SessionLocal() as s:
        n = s.execute(text("SELECT count(*) FROM cpl.runner_executions WHERE case_id = :c"), {"c": old}).scalar()
    c = await user_a.post(f"/cases/{old}/vir/confirmations", json={"field_path": "drivetrain", "value": "front_wheel_drive"})
    assert c.status_code == 410
    with SessionLocal() as s:
        assert s.execute(text("SELECT count(*) FROM cpl.runner_executions WHERE case_id = :c"), {"c": old}).scalar() == n
    assert (await user_a.get(f"/cases/{old}")).status_code == 200
    assert (await user_a.get(f"/cases/{old}/history")).status_code == 200
    results = (await user_a.get(f"/cases/{old}/notice-results")).json()["results"]
    assert len(results) == 1
    assert (await user_b.get(f"/cases/{old}")).status_code == 404
    assert (await user_b.get(f"/cases/{old}/notice-results")).status_code == 404
    hist = (await user_a.get(f"/cases/{hand}/history")).json()
    for entry in hist["executions"]:
        if entry["runner_type"] == "VIR":
            art = await user_a.get(f"/executions/{entry['execution_id']}/artifact")
            assert art.status_code == 200 and vin not in art.text and plate not in art.text

    # media: past its period gone (files), reference answered "no longer kept"; recent kept
    assert not list(storage.glob(f"{m_old}.*")) and len(list(storage.glob(f"{m_new}.*"))) == 2
    d = await user_a.post(f"/cases/{recent}/diagnostics", json={"primary_diagnostic_media_reference": m_old})
    assert d.status_code == 410 and d.json()["error_category"] == "MEDIA_NOT_KEPT", d.text
    # logs: rotated and past the period deleted; the active log and other files kept
    assert sorted(p.name for p in montage.iterdir()) == ["notes.txt", "pi05.log", "pi05.log.1"]

    # second execution: nothing more, nothing changed
    before = cs.snapshot()
    run2 = cs.cli("purge", "--executer", env=env)
    assert run2.returncode == 0 and "0 résolution(s) d'identité et 0 fiche(s) véhicule vidées" in run2.stdout
    assert "0 média(s) supprimé(s)" in run2.stdout
    after = cs.snapshot()
    assert {t: after[t] for t in after if t != "pi_auth.conservation_operations"} == \
        {t: before[t] for t in before if t != "pi_auth.conservation_operations"}


async def test_an_error_during_the_purge_stops_cleanly_and_a_new_run_finishes(app, user_a, full_authority):
    cases = []
    for _ in range(3):
        c = await case(user_a)
        vin, plate = cs.fictive_identifiers()
        cs.register_handmade(c, _case_ids(c)["asset_id"], vin, plate, full_authority)
        cs.backdate_case(c, 40)
        cases.append((c, vin, plate))
    failing = _case_ids(cases[1][0])["resolutions"][-1].resolution_id
    with SessionLocal() as s:          # test database only: the database refuses one of the updates
        s.execute(text(f"""
            CREATE OR REPLACE FUNCTION public.essai_conservation_refus() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.resolution_id = '{failing}' THEN RAISE EXCEPTION 'essai : refus'; END IF; RETURN NEW; END $$;
            CREATE TRIGGER essai_conservation_refus BEFORE UPDATE ON cpl.asset_identity_resolutions
              FOR EACH ROW EXECUTE FUNCTION public.essai_conservation_refus();"""))
        s.commit()
    try:
        r = cs.cli("purge", "--executer", "--lot", "1", env=_env())
        assert r.returncode == 1 and "Purge interrompue (" in r.stderr and "relancer" in r.stderr, r.stderr
        assert "essai : refus" not in r.stderr and all(v not in r.stderr + r.stdout for _, v, p in cases)
        with SessionLocal() as s:
            op = s.execute(text("SELECT outcome, error_class FROM pi_auth.conservation_operations "
                                "ORDER BY started_at DESC LIMIT 1")).one()
        assert op.outcome == "interrupted" and op.error_class
        failing_identity = [r.canonical_identity_payload for r in _case_ids(cases[1][0])["resolutions"]][-1]
        assert failing_identity["identifiers"]["vin"] == cases[1][1]               # its batch rolled back
    finally:
        with SessionLocal() as s:
            s.execute(text("DROP TRIGGER IF EXISTS essai_conservation_refus ON cpl.asset_identity_resolutions; "
                           "DROP FUNCTION IF EXISTS public.essai_conservation_refus();"))
            s.commit()
    r = cs.cli("purge", "--executer", "--lot", "1", env=_env())
    assert r.returncode == 0 and "0 copie(s) échue(s) restante(s) hors artefacts" in r.stdout, r.stdout + r.stderr
    for c, vin, plate in cases:
        assert all(r.canonical_identity_payload["identifiers"].get("vin") is None for r in _case_ids(c)["resolutions"])
        assert _case_ids(c)["detail"].vin_display is None
