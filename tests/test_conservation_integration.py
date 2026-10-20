"""Conservation 3/3 — the operator purge as a whole, backups, restoration and copies set aside.

2. One purge, in its documented order: vir_resolution artifacts past their period expurgated by CPL's
   operation (REQ-B6-091), cases past their period deleted (REQ-B5-116), identifier copies emptied, media, logs.
3. A backup made after the purge holds neither the identifiers removed nor the cases deleted; the copy VIR sets
   aside on restore is recognised by the manifest deploy/restaurer.sh writes, cleaned with the backups' period,
   and a copy without it is reported, never deleted.
4. An old backup (CPL schema 030, before REQ-B5-116) restored: the service stays closed until, in order, the
   migrations (031), the expurgation, the deletion of expired cases and the identifiers' purge have succeeded;
   every restored session is revoked; without a policy the lock stays with a clear message.

Real delivery scripts with a test $PREFIX, temporary PostgreSQL databases of the test cluster, fictitious data;
30 days is a test value, never an approved period.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.cpl.models.runner_artifact import RunnerArtifact
from app.cpl.runners import redaction
from app.db.engine import SessionLocal

from product_integration.conservation import purge

from tests import conservation_support as cs
from tests.test_conservation_sauvegardes import (
    PG_BIN, REPO, age_manifest, base_env, fresh_database, media, query, vir_db,
)
from tests.test_notice_parcours import RESOLVED_VIN, app, case, pgdr, user, user_a, vir_store  # noqa: F401

CPL_ROOT = Path(__import__("app").__file__).resolve().parents[1]


def _env(**overrides) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PI_CONSERVATION_")}
    env.update(cs.policy_env(**{"PI_CONSERVATION_DOSSIERS_JOURS": cs.TEST_DAYS, **overrides}))
    return env


def _legacy_case(monkeypatch_context, client):
    """A case whose vir_resolution artifact was registered as before REQ-B6-091 (plate and VIN inside)."""
    import product_integration.cpl_registration as registration
    monkeypatch_context.setattr(registration, "redact_vehicle_identifiers", lambda payload: (payload, []))
    return case(client)


def _vir_artifacts(case_id: str) -> list:
    with SessionLocal() as s:
        return s.execute(text(
            "SELECT a.artifact_id, a.payload, a.redaction_status FROM cpl.runner_artifacts a "
            "JOIN cpl.runner_executions e USING (execution_id) WHERE e.case_id = :c "
            "AND a.artifact_type = 'vir_resolution'"), {"c": case_id}).all()


# -- 2. one purge, every category, in order ------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_purge_expurgates_expired_artifacts_through_cpl_then_deletes_cases_then_empties_copies(
        app, user_a, monkeypatch):
    purge.execute(environ=_env())                       # a clean start for the counts below
    with monkeypatch.context() as m:
        kept_case = await _legacy_case(m, user_a)        # identifiers past their period, case within it
        gone_case = await _legacy_case(m, user_a)        # case past its period
    cs.backdate_case(kept_case, 40)
    cs.backdate_case_creation(gone_case, 40)
    [kept_art] = _vir_artifacts(kept_case)
    gone_exec = [r[0] for r in SessionLocal().execute(text(
        "SELECT execution_id FROM cpl.runner_executions WHERE case_id = :c"), {"c": gone_case})]
    assert RESOLVED_VIN in json.dumps(kept_art.payload)

    snap = cs.snapshot()
    sim = cs.cli("purge", env=_env())
    assert sim.returncode == 0 and cs.snapshot() == snap, sim.stderr
    lines = [l for l in sim.stdout.splitlines() if l.startswith("- ")]
    assert [l.split(" ")[1] for l in lines[:5]] == ["artefacts", "dossiers", "identifiants", "medias", "journaux"]
    assert "2 artefact(s) vir_resolution échu(s) seraient expurgés" in sim.stdout, sim.stdout
    assert "1 dossier(s) échu(s) seraient supprimés" in sim.stdout
    assert "aucun média n'est rattaché à un dossier" in sim.stdout and "copie de la base VIR" in sim.stdout
    assert RESOLVED_VIN not in sim.stdout + sim.stderr

    run = cs.cli("purge", "--executer", env=_env())
    assert run.returncode == 0, run.stdout + run.stderr
    assert "2 artefact(s) vir_resolution échu(s) expurgé(s)" in run.stdout, run.stdout
    assert "1 dossier(s) échu(s) supprimé(s)" in run.stdout
    assert "0 copie(s) échue(s) restante(s), artefacts compris" in run.stdout
    assert RESOLVED_VIN not in run.stdout + run.stderr

    # the case within its period: artifact expurgated by CPL's operation (authorised, traced), case kept
    [now] = _vir_artifacts(kept_case)
    assert now.redaction_status == "REDACTED" and RESOLVED_VIN not in json.dumps(now.payload)
    with SessionLocal() as s:
        artifact = s.get(RunnerArtifact, now.artifact_id)
        assert redaction.classify_integrity(s, artifact) == redaction.IntegrityClass.REDACTED_AUTHORIZED
        trace = s.execute(text("SELECT reason, operator_reference FROM cpl.runner_artifact_redactions "
                               "WHERE artifact_id = :a"), {"a": now.artifact_id}).one()
        op = s.execute(text("SELECT counts FROM pi_auth.conservation_operations ORDER BY started_at DESC "
                            "LIMIT 1")).scalar()
    assert trace.reason == "RETENTION_POLICY" and trace.operator_reference.startswith("pi-purge:")
    assert op["artifacts"] == 2 and op["cases"] == 1 and op["artifacts_refused"] == 0
    assert (await user_a.get(f"/cases/{kept_case}")).status_code == 200
    # the expired case: deleted with its (expurgated) artifact
    assert (await user_a.get(f"/cases/{gone_case}")).status_code == 404
    with SessionLocal() as s:
        assert s.execute(text("SELECT count(*) FROM cpl.runner_artifacts WHERE execution_id = ANY(:x)"),
                         {"x": gone_exec}).scalar() == 0
    assert set(cs.scan(RESOLVED_VIN)) - {"cpl.asset_identity_resolutions.canonical_identity_payload",
                                         "automotive.vehicle_details.vin_display"} == set()

    again = cs.cli("purge", "--executer", env=_env())
    assert "0 artefact(s) vir_resolution échu(s) expurgé(s)" in again.stdout and "0 dossier(s)" in again.stdout


@pytest.mark.asyncio
async def test_an_altered_artifact_is_refused_by_cpl_counted_and_left_as_it_is(app, user_a, monkeypatch):
    purge.execute(environ=_env())
    with monkeypatch.context() as m:
        c = await _legacy_case(m, user_a)
    cs.backdate_case(c, 40)
    [art] = _vir_artifacts(c)
    with SessionLocal() as s:                 # test database only: an alteration outside any governed path
        s.execute(text("UPDATE cpl.runner_artifacts SET payload = jsonb_set(payload, '{note}', '\"x\"') "
                       "WHERE artifact_id = :a"), {"a": art.artifact_id})
        s.commit()
    run = cs.cli("purge", "--executer", env=_env())
    assert run.returncode == 0 and "1 refusé(s) par CPL" in run.stdout, run.stdout + run.stderr
    [after] = _vir_artifacts(c)
    assert after.redaction_status is None and RESOLVED_VIN in json.dumps(after.payload)
    with SessionLocal() as s:
        assert redaction.classify_integrity(s, s.get(RunnerArtifact, art.artifact_id)) == \
            redaction.IntegrityClass.UNAUTHORIZED_ALTERATION
    cs.backdate_case_creation(c, 40)           # deleted by the next clean start (deletion checks no hash)


# -- 3. backups ---------------------------------------------------------------------------------------------

def _blocks_naming(dump_text: str, value: str) -> set[str]:
    """The tables whose COPY data in a plain-text dump contain the value."""
    found, table = set(), None
    for line in dump_text.splitlines():
        if line.startswith("COPY "):
            table = line.split()[1]
        elif line == "\\.":
            table = None
        elif table and value in line:
            found.add(table)
    return found


def _dump_text(dump: Path) -> str:
    os.chmod(dump, 0o600)
    out = subprocess.run([f"{PG_BIN}/pg_restore", "-f", "-", str(dump)], capture_output=True, text=True, check=True)
    os.chmod(dump, 0o400)
    return out.stdout


@pytest.mark.asyncio
async def test_a_backup_made_after_the_purge_holds_neither_removed_identifiers_nor_deleted_cases(
        app, user_a, full_authority, monkeypatch, tmp_path):
    purge.execute(environ=_env())
    vin, plate = cs.fictive_identifiers()
    with monkeypatch.context() as m:
        gone = await _legacy_case(m, user_a)
        kept = await _legacy_case(m, user_a)
    from tests.test_conservation_purge import _case_ids
    cs.register_handmade(kept, _case_ids(kept)["asset_id"], vin, plate, full_authority)
    cs.backdate_case_creation(gone, 40)
    cs.backdate_case(kept, 40)
    vir_db(tmp_path / "vir.db")
    media(tmp_path / "media")
    env = {**base_env(tmp_path), **cs.policy_env(PI_CONSERVATION_DOSSIERS_JOURS=cs.TEST_DAYS)}
    before = cs.run(["bash", str(REPO / "deploy" / "sauvegarder.sh")], env)
    assert before.returncode == 0, before.stderr
    old_backup = next((tmp_path / "sauvegardes").iterdir())
    old_text = _dump_text(old_backup / "postgresql.dump")
    assert gone in old_text and vin in old_text            # the earlier backup keeps them until it expires

    assert cs.cli("purge", "--executer", env=_env()).returncode == 0
    import time
    time.sleep(1.1)
    after = cs.run(["bash", str(REPO / "deploy" / "sauvegarder.sh")], env)
    assert after.returncode == 0, after.stderr
    new_backup = max((tmp_path / "sauvegardes").iterdir())
    new_text = _dump_text(new_backup / "postgresql.dump")
    assert _blocks_naming(new_text, gone) == {"cpl.case_deletions"}       # only the deletion trace names it
    assert vin not in new_text and plate not in new_text

    # the earlier backup stays protected until its period is over, then the cleaning deletes it (and only it)
    clean = ["bash", str(REPO / "deploy" / "nettoyer_sauvegardes.sh")]
    r = cs.run([*clean, "--executer"], env)
    assert r.returncode == 0 and "échues supprimées : 0" in r.stdout and old_backup.exists(), r.stdout + r.stderr
    age_manifest(old_backup, 40)
    r = cs.run([*clean, "--executer"], env)
    assert r.returncode == 0 and "échues supprimées : 1" in r.stdout and not old_backup.exists()
    assert new_backup.exists()


# -- 4 and 5. restoring an old backup; copies set aside ---------------------------------------------------

VIN_OLD, PLATE_OLD = "FAUXRESTO0000OLD1", "FICTIVE-RESTO-OLD"
VIN_FRESH = "FAUXRESTO000FRSH1"


def _database_at_030(name: str) -> str:
    """A database as an installation before REQ-B5-116 left it (CPL 030, pi_auth 4), with fictitious data:
    an expired case, a case within its period whose identification is expired (artifact still holding the
    plate and the VIN, as registered before REQ-B6-091), a recent identification, an account and a session."""
    url = fresh_database(name)
    env = {**os.environ, "DATABASE_URL": url}
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS cpl"))
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS automotive"))
    subprocess.run([sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "030"], cwd=CPL_ROOT, env=env,
                   check=True, capture_output=True)
    subprocess.run([sys.executable, "-m", "product_integration.auth.cli", "migrate"], env=env, check=True,
                   capture_output=True)

    from app.cpl.identity.authority import AuthorityContext
    from app.cpl.models.asset import Asset
    from app.cpl.models.asset_identity_resolution import AssetIdentityResolution
    from app.cpl.models.case import Case
    from app.cpl.models.contact import Contact
    from app.cpl.models.runner_artifact_schema_definition import RunnerArtifactSchemaDefinition
    from app.cpl.runners.artifacts import register_artifact
    from app.cpl.runners.authority import RunnerAuthority
    from app.cpl.runners.execution import admit_execution
    authority = AuthorityContext(granted=frozenset({RunnerAuthority.ADMIT_EXECUTION, RunnerAuthority.REGISTER_ARTIFACT}),
                                 actor_reference="test-suite-0001")
    now = datetime.now(timezone.utc)
    ids = {}
    session = sessionmaker(bind=engine)()
    contact = Contact(contact_type="PERSON", display_name="Restauration fictive")
    asset = Asset(asset_domain="AUTOMOTIVE", asset_type="PASSENGER_CAR", asset_status="ACTIVE")
    session.add_all([contact, asset])
    session.add(RunnerArtifactSchemaDefinition(schema_name="vir_resolution", schema_version="1",
                                               required_fields=["resolution_id"], field_types={}))
    session.flush()
    for key, case_age, ident_age, vin, plate in (("expired", 40, 40, VIN_OLD, PLATE_OLD),
                                                 ("kept", 1, 40, VIN_OLD, PLATE_OLD),
                                                 ("fresh", 1, 1, VIN_FRESH, None)):
        c = Case(primary_contact_id=contact.contact_id, asset_id=asset.asset_id, domain="AUTOMOTIVE",
                 case_type="DIAGNOSTIC", created_at=now - timedelta(days=case_age))
        session.add(c)
        session.flush()
        x = admit_execution(session, case_id=c.case_id, asset_id=asset.asset_id, runner_type="VIR",
                            runner_version="1.0", authority=authority).object_id
        identifiers = {"vin": vin, "registration_number": plate, "registration_country": "FR"}
        session.add(AssetIdentityResolution(asset_id=asset.asset_id, resolver_type="VIR", resolver_version="1.0",
                                            execution_id=x, resolution_status="RESOLVED",
                                            canonical_identity_payload={"identifiers": identifiers},
                                            created_at=now - timedelta(days=ident_age)))
        a = register_artifact(session, execution_id=x, artifact_type="vir_resolution", schema_name="vir_resolution",
                              schema_version="1", payload={"resolution_id": f"R-{key}", "resolution_status": "resolved",
                                                           "vehicle_identity": {"identifiers": identifiers}},
                              semantic_function="DOMAIN_ASSERTION_CARRIER", lifecycle_role="FINAL",
                              presentation_role="INTERNAL", authority=authority).object_id
        ids[key] = (str(c.case_id), str(a))
    account_id = uuid.uuid4()
    session.execute(text("INSERT INTO cpl.accounts(account_id, contact_id, auth_provider, provider_subject_id, "
                         "account_status, created_at) VALUES (:a, :c, 'pi-password', :s, 'ACTIVE', now())"),
                    {"a": account_id, "c": contact.contact_id, "s": f"fictif-{account_id}"})
    session.execute(text("INSERT INTO pi_auth.credentials(account_id, login, password_hash) "
                         "VALUES (:a, :l, 'scrypt$fictif')"), {"a": account_id, "l": f"resto-{account_id.hex[:8]}"})
    session.execute(text("INSERT INTO pi_auth.web_sessions(session_hash, account_id, expires_at) "
                         "VALUES (:h, :a, now() + interval '1 day')"), {"h": uuid.uuid4().hex, "a": account_id})
    session.commit()
    session.close()
    engine.dispose()
    return url, ids


def test_an_old_backup_restored_stays_closed_until_migrations_and_conservation_have_succeeded(tmp_path):
    url_old, ids = _database_at_030("pi_cons3_ancienne")
    assert query(url_old, "SELECT version_num FROM public.alembic_version")[0][0] == "030"
    vir_db(tmp_path / "vir.db")
    media(tmp_path / "media")
    env = base_env(tmp_path, VIR_RETENTION_DAYS=cs.TEST_DAYS, DATABASE_URL=url_old)
    backup = cs.run(["bash", str(REPO / "deploy" / "sauvegarder.sh")], env)
    assert backup.returncode == 0, backup.stderr
    source = next((tmp_path / "sauvegardes").iterdir())
    restore = ["bash", str(REPO / "deploy" / "restaurer.sh")]
    lock = tmp_path / "montage" / "RESTAURATION_A_PURGER"
    launch = ["bash", str(REPO / "scripts" / "lancer_montage.sh")]
    launch_extra = {"VIR_SERVICE_TOKEN": "fictive", "PGDR_IDENTITY_HANDOFF_TOKEN": "fictive",
                    "PI_LOGIN_THROTTLE_SECRET": "fictive-throttle-" + "x" * 32}

    # without a policy: migrated, sessions revoked, nothing deleted, the lock stays, the launch is refused
    url_a = fresh_database("pi_cons3_resto_a")
    r = cs.run(restore, {**env, "DATABASE_URL": url_a, "SOURCE": str(source)})
    assert r.returncode == 1 and lock.exists(), r.stdout + r.stderr
    assert "politique de conservation NON appliquée" in r.stderr and "PI_CONSERVATION_" in r.stderr
    assert "relancer deploy/finir_restauration.sh" in r.stderr
    assert query(url_a, "SELECT version_num FROM public.alembic_version")[0][0] == "031"
    assert query(url_a, "SELECT count(*) FROM pi_auth.web_sessions")[0][0] == 0
    assert query(url_a, "SELECT count(*) FROM cpl.cases")[0][0] == 3
    assert VIN_OLD not in r.stdout + r.stderr
    r = cs.run(launch, {**env, "DATABASE_URL": url_a, **launch_extra}, timeout=30)
    assert r.returncode == 2 and "démarrage refusé" in r.stderr, r.stderr
    # the policy defined afterwards: finishing alone completes it and lifts the lock
    finish = cs.run(["bash", str(REPO / "deploy" / "finir_restauration.sh")],
                    {**env, **cs.policy_env(PI_CONSERVATION_DOSSIERS_JOURS=cs.TEST_DAYS), "DATABASE_URL": url_a})
    assert finish.returncode == 0 and not lock.exists(), finish.stdout + finish.stderr

    # with a policy: one run; the VIR database in place is copied aside by VIR, with PI's manifest
    url_b = fresh_database("pi_cons3_resto_b")
    r = cs.run(restore, {**env, **cs.policy_env(PI_CONSERVATION_DOSSIERS_JOURS=cs.TEST_DAYS), "DATABASE_URL": url_b,
                         "SOURCE": str(source)})
    assert r.returncode == 0 and not lock.exists(), r.stdout + r.stderr
    assert "n'est pas relancé" in r.stdout and "Sessions web révoquées : 1" in r.stdout
    assert VIN_OLD not in r.stdout + r.stderr and PLATE_OLD not in r.stdout + r.stderr
    for url in (url_a, url_b):
        assert query(url, "SELECT version_num FROM public.alembic_version")[0][0] == "031"
        assert query(url, "SELECT count(*) FROM pi_auth.web_sessions")[0][0] == 0
        cases = {str(row[0]) for row in query(url, "SELECT case_id FROM cpl.cases")}
        assert ids["expired"][0] not in cases and {ids["kept"][0], ids["fresh"][0]} <= cases
        assert query(url, "SELECT count(*) FROM cpl.case_deletions WHERE case_id = :c", c=ids["expired"][0])[0][0] == 1
        kept_art = query(url, "SELECT payload, redaction_status FROM cpl.runner_artifacts WHERE artifact_id = :a",
                         a=ids["kept"][1])[0]
        assert kept_art.redaction_status == "REDACTED" and VIN_OLD not in json.dumps(kept_art.payload)
        assert set(cs.scan(VIN_OLD, PLATE_OLD, database_url=url)) == set()     # expired: nowhere any more
        assert cs.scan(VIN_FRESH, database_url=url)                             # within its period: kept
        op = query(url, "SELECT trigger, outcome, counts FROM pi_auth.conservation_operations "
                        "ORDER BY started_at DESC LIMIT 1")[0]
        assert (op.trigger, op.outcome) == ("after_restore", "completed")
        assert op.counts["artifacts"] == 2 and op.counts["cases"] == 1

    # 5. copies set aside: VIR's copy (0600) and its manifest, the media directory (0700 with its manifest)
    copies = sorted(p for p in tmp_path.iterdir() if p.name.startswith("vir.db.avant-restauration-")
                    and not p.name.endswith(".MANIFESTE"))
    assert len(copies) == 2
    for copy in copies:
        assert oct(copy.stat().st_mode & 0o777) == "0o600"
        manifest = Path(str(copy) + ".MANIFESTE").read_text()
        assert "format=pi-copie-vir-1" in manifest and f"fichier={copy.name}" in manifest
    asides = [p for p in tmp_path.iterdir() if p.name.startswith("media.avant-restauration-")]
    assert asides and all(oct(p.stat().st_mode & 0o777) == "0o700" for p in asides)
    foreign = tmp_path / "vir.db.avant-restauration-20200101T000000Z"         # set aside by a bare `vir restore`
    foreign.write_bytes(copies[0].read_bytes())
    altered = copies[1]
    os.chmod(altered, 0o600)
    with open(altered, "ab") as fh:
        fh.write(b"\0")

    clean = ["bash", str(REPO / "deploy" / "nettoyer_sauvegardes.sh")]
    policy = {**env, **cs.policy_env()}
    r = cs.run(clean, policy)
    assert "copie de la base VIR mise de côté par une restauration : 1 reconnue(s), 2 non reconnue(s)" in r.stdout, \
        r.stdout + r.stderr
    sim = cs.cli("purge", env={**policy, "DATABASE_URL": url_b})
    assert "copie de la base VIR mise de côté par une restauration) — politique : 30 jour(s)" in sim.stdout
    assert "1 reconnue(s), 2 non reconnue(s) (jamais supprimées" in sim.stdout, sim.stdout
    age_manifest_file(Path(str(copies[0]) + ".MANIFESTE"), 40)
    for p in asides:
        age_manifest(p, 40)
    r = cs.run([*clean, "--executer"], policy)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not copies[0].exists() and not Path(str(copies[0]) + ".MANIFESTE").exists()
    assert foreign.exists() and altered.exists()                     # not recognised: never deleted
    assert not any(p.exists() for p in asides) and source.exists()   # the backup itself: within its period


def age_manifest_file(manifest: Path, days: int) -> None:
    os.chmod(manifest, 0o600)
    created = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [f"creee_le={created}" if l.startswith("creee_le=") else l for l in manifest.read_text().splitlines()]
    manifest.write_text("\n".join(lines) + "\n")
    os.chmod(manifest, 0o400)
