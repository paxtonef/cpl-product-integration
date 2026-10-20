"""Conservation — backups of the delivery scripts and restoration.

The real deploy/sauvegarder.sh, deploy/nettoyer_sauvegardes.sh,
deploy/restaurer.sh and scripts/lancer_montage.sh, run as the operator would
(a test $PREFIX whose python and vir are this environment), on temporary
PostgreSQL databases of the test cluster, temporary directories and
fictitious data; the periods are test values (30 days), never approved.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.db.engine import SessionLocal

from product_integration.conservation import purge

from tests import conservation_support as cs
from tests.test_notice_parcours import app, case, pgdr, user, user_a, vir_store  # noqa: F401  (fixtures)
from tests.test_conservation_purge import _case_ids

REPO = Path(__file__).resolve().parents[1]
PG_BIN = "/opt/homebrew/opt/postgresql@16/bin"


def tree(root: Path) -> dict[str, str]:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            p_mode = p.stat().st_mode
            os.chmod(p, p_mode | stat.S_IRUSR)
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
            os.chmod(p, p_mode)
    return out


def base_env(tmp: Path, **extra) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PI_CONSERVATION_")}
    env.update({"PREFIX": str(cs.make_prefix(tmp)) if not (tmp / "prefix").exists() else str(tmp / "prefix"),
                "PATH": f"{PG_BIN}:{env['PATH']}", "VIR_DATABASE_PATH": str(tmp / "vir.db"),
                "PI05_MEDIA_STORAGE_DIR": str(tmp / "media"), "SAUVEGARDES_DIR": str(tmp / "sauvegardes"),
                "MONTAGE_DIR": str(tmp / "montage")})
    env.update(extra)
    return env


def vir_db(path: Path) -> None:
    from vir.adapters.sqlite_persistence_adapter import SQLitePersistenceAdapter
    SQLitePersistenceAdapter(str(path))


def media(dirpath: Path) -> None:
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / ("ab" * 16 + ".png")).write_bytes(b"\x89PNG fictive")
    (dirpath / ("ab" * 16 + ".contenttype")).write_text("image/png")


def age_manifest(directory: Path, days: int) -> None:
    manifest = directory / "MANIFESTE"
    os.chmod(manifest, 0o600)
    created = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [f"creee_le={created}" if l.startswith("creee_le=") else l for l in manifest.read_text().splitlines()]
    manifest.write_text("\n".join(lines) + "\n")
    os.chmod(manifest, 0o400)


def fresh_database(name: str) -> str:
    url = make_url(os.environ["DATABASE_URL"])
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    return url.set(database=name).render_as_string(hide_password=False)


def query(database_url: str, sql: str, **params):
    engine = create_engine(database_url)
    try:
        with engine.connect() as conn:
            return conn.execute(text(sql), params).all()
    finally:
        engine.dispose()


def test_backups_carry_a_manifest_and_only_expired_recognised_ones_are_deleted(tmp_path):
    vir_db(tmp_path / "vir.db")
    media(tmp_path / "media")
    env = base_env(tmp_path)
    first = cs.run(["bash", str(REPO / "deploy" / "sauvegarder.sh")], env)
    assert first.returncode == 0, first.stderr
    time.sleep(1.1)
    second = cs.run(["bash", str(REPO / "deploy" / "sauvegarder.sh")], env)
    assert second.returncode == 0, second.stderr
    old_b, new_b = sorted((tmp_path / "sauvegardes").iterdir())

    # protections: directory 0700, files read-only, manifest listing exactly the files, no key inside
    assert stat.S_IMODE(old_b.stat().st_mode) == 0o700
    assert {stat.S_IMODE(p.stat().st_mode) for p in old_b.iterdir()} == {0o400}
    manifest = (old_b / "MANIFESTE").read_text()
    assert "format=pi-sauvegarde-1" in manifest and "creee_par=deploy/sauvegarder.sh" in manifest
    assert set(manifest.split("fichiers=")[1].split()) | {"MANIFESTE"} == {p.name for p in old_b.iterdir()}
    key = os.environ["VIR_DATA_ENCRYPTION_KEY"].encode()
    for p in old_b.iterdir():
        os.chmod(p, 0o600)
        assert key not in p.read_bytes()
        os.chmod(p, 0o400)
    age_manifest(old_b, 40)

    # around them: an unrecognised backup (extra key file), other entries, a backup outside the root,
    # media directories set aside by a restoration (one recognised, one with a foreign file)
    odd = tmp_path / "sauvegardes" / "pi-sauvegarde-20200101T000000Z"
    shutil.copytree(old_b, odd)
    os.chmod(odd, 0o700)
    (odd / "cle.key").write_text("fictive")
    (tmp_path / "sauvegardes" / "autre").mkdir()
    (tmp_path / "sauvegardes" / "pi-sauvegarde-20200101T000001Z").write_text("a file, not a backup")
    outside = cs.run(["bash", str(REPO / "deploy" / "sauvegarder.sh")], {**env, "DEST": str(tmp_path / "hors")})
    assert outside.returncode == 0
    aside_ok = tmp_path / "media.avant-restauration-20200101T000000Z"
    aside_odd = tmp_path / "media.avant-restauration-20200101T000001Z"
    for d in (aside_ok, aside_odd):
        media(d)
        (d / "MANIFESTE").write_text("format=pi-avant-restauration-1\ncreee_le=2020-01-01T00:00:00Z\n"
                                     "creee_par=deploy/restaurer.sh\n")
    (aside_odd / "notes.txt").write_text("not a medium")

    clean = ["bash", str(REPO / "deploy" / "nettoyer_sauvegardes.sh")]
    before = tree(tmp_path)
    r = cs.run(clean, env)                                       # no policy: simulation says so
    assert r.returncode == 0 and purge.NO_POLICY in r.stdout, r.stdout + r.stderr
    r = cs.run([*clean, "--executer"], env)                      # no policy: refused
    assert r.returncode == 2 and "refusée" in r.stderr
    policy = {**env, **cs.policy_env()}
    r = cs.run(clean, policy)                                    # simulation with a policy
    assert r.returncode == 0 and "échues : 2 seraient supprimées" in r.stdout, r.stdout
    assert "non reconnues (jamais supprimées) : 2" in r.stdout
    assert tree(tmp_path) == before

    r = cs.run([*clean, "--executer"], policy)
    assert r.returncode == 0 and "échues supprimées : 2" in r.stdout, r.stdout + r.stderr
    assert not old_b.exists() and not aside_ok.exists()
    after = tree(tmp_path)
    kept = {k: v for k, v in before.items() if not k.startswith((old_b.relative_to(tmp_path).as_posix() + "/",
                                                                  aside_ok.name + "/"))}
    assert after == kept                                         # everything else intact, byte for byte
    r = cs.run([*clean, "--executer"], policy)
    assert r.returncode == 0 and "échues supprimées : 0" in r.stdout and tree(tmp_path) == after


@pytest.mark.asyncio
async def test_an_old_backup_restored_is_purged_before_the_service_reopens(app, user_a, full_authority, tmp_path):
    purge.execute(environ={**os.environ, **cs.policy_env()})      # a clean start for the counts below
    vin, plate = cs.fictive_identifiers()
    case_id = await case(user_a)
    cs.register_handmade(case_id, _case_ids(case_id)["asset_id"], vin, plate, full_authority)
    cs.backdate_case(case_id, 40)
    with SessionLocal() as s:
        assert s.execute(text("SELECT count(*) FROM pi_auth.web_sessions")).scalar() >= 1
    vir_db(tmp_path / "vir.db")
    media(tmp_path / "media")
    env = base_env(tmp_path, VIR_RETENTION_DAYS=cs.TEST_DAYS)
    backup = cs.run(["bash", str(REPO / "deploy" / "sauvegarder.sh")], env)
    assert backup.returncode == 0, backup.stderr
    source = next((tmp_path / "sauvegardes").iterdir())
    live = cs.cli("purge", "--executer", env={**env, **cs.policy_env()})   # purged since the backup was made
    assert live.returncode == 0 and "0 copie(s) échue(s) restante(s)" in live.stdout
    assert set(cs.scan(vin, plate)) == set()        # the vir_resolution artifact never held them (REQ-B6-091)

    restore = ["bash", str(REPO / "deploy" / "restaurer.sh")]
    lock = tmp_path / "montage" / "RESTAURATION_A_PURGER"

    # without a policy: restored, NOT reopened: the lock stays and the launch is refused
    url_a = fresh_database("pi_restore_cons_a")
    r = cs.run(restore, {**env, "DATABASE_URL": url_a, "SOURCE": str(source)})
    assert r.returncode == 1 and "NON appliquée" in r.stderr and lock.exists(), r.stdout + r.stderr
    assert vin not in r.stdout + r.stderr and plate not in r.stdout + r.stderr
    restored_scan = cs.scan(vin, plate, database_url=url_a)
    assert "cpl.asset_identity_resolutions.canonical_identity_payload" in restored_scan     # back from the backup
    launch_env = {**env, "DATABASE_URL": url_a, "VIR_SERVICE_TOKEN": "fictive", "PGDR_IDENTITY_HANDOFF_TOKEN": "fictive",
                  "PI_LOGIN_THROTTLE_SECRET": "fictive-throttle-" + "x" * 32}
    r = cs.run(["bash", str(REPO / "scripts" / "lancer_montage.sh")], launch_env, timeout=30)
    assert r.returncode == 2 and "démarrage refusé" in r.stderr, r.stderr
    lock.unlink()

    # with a policy: purge applied before reopening, sessions revoked, lock removed, nothing started
    url_b = fresh_database("pi_restore_cons_b")
    vir_restored = tmp_path / "vir-b.db"
    r = cs.run(restore, {**env, **cs.policy_env(), "DATABASE_URL": url_b, "SOURCE": str(source),
                         "VIR_DATABASE_PATH": str(vir_restored)})
    assert r.returncode == 0, r.stdout + r.stderr
    assert not lock.exists() and "n'est pas relancé" in r.stdout and "Sessions web révoquées" in r.stdout
    assert vin not in r.stdout + r.stderr and plate not in r.stdout + r.stderr
    assert set(cs.scan(vin, plate, database_url=url_b)) == set()
    assert query(url_b, "SELECT count(*) FROM pi_auth.web_sessions")[0][0] == 0
    op = query(url_b, "SELECT trigger, outcome FROM pi_auth.conservation_operations ORDER BY started_at DESC LIMIT 1")
    assert tuple(op[0]) == ("after_restore", "completed")
    asides = [p for p in tmp_path.iterdir() if p.name.startswith("media.avant-restauration-")]
    assert asides and all("format=pi-avant-restauration-1" in (p / "MANIFESTE").read_text() for p in asides)
    # the case and its access rights came back intact
    owner = query(url_b, "SELECT primary_contact_id FROM cpl.cases WHERE case_id = :c", c=case_id)
    with SessionLocal() as s:
        assert owner[0][0] == s.execute(text("SELECT primary_contact_id FROM cpl.cases WHERE case_id = :c"),
                                        {"c": case_id}).scalar()
