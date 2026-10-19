"""Conservation — a case in the browser after the purge and after a restoration.

scripts/lancer_montage.sh in production mode (HTTPS, built frontend, VIR
simulated, PGDR with a FICTIVE notice, no sorting transport), real Chromium,
a fictitious account. The case is identified and its notice result
confirmed; a backup is taken; the identification is made due (moved 40 days
into the past; test period 30 days, never an approved duration) and purged
by the operator command. Then the assembly is stopped, the backup restored
into a new database by deploy/restaurer.sh, and the assembly started on it.
"""
from __future__ import annotations

import os

import pytest

from tests import conservation_support as cs
from tests.notice_parcours_support import GREEN_MEANING
from tests.test_3a_lancement_reel import REPO, Montage
from tests.test_3b_reception_navigateur import (  # noqa: F401  (fixtures)
    GREEN, account, browser, built_frontend, confirmed_results, parcours_to_restitution, register, signed_in,
)
from tests.test_conservation_sauvegardes import PG_BIN, fresh_database

NOT_KEPT = "no longer kept"
STATE: dict = {}


@pytest.fixture(scope="module")
def montage(tmp_path_factory, built_frontend):
    m = Montage(tmp_path_factory.mktemp("conservation"))
    m.env["PI_FRONTEND_DIST"] = str(built_frontend)
    (m.root / "media").mkdir()
    m.start()
    yield m
    if m.proc.poll() is None:
        m.stop()


def operator_env(m: Montage, **extra) -> dict:
    env = {k: v for k, v in m.env.items() if not k.startswith("PI_CONSERVATION_")}
    prefix = m.root / "prefix"
    env.update({"PREFIX": str(prefix if prefix.exists() else cs.make_prefix(m.root)),
                "PATH": f"{PG_BIN}:{env['PATH']}", "SAUVEGARDES_DIR": str(m.root / "sauvegardes"),
                "VIR_RETENTION_DAYS": cs.TEST_DAYS})
    env.update(extra)
    return env


def identity_region(page, case_id: str):
    page.goto(f"/cases/{case_id}")
    page.get_by_role("region", name="Confirmed results").wait_for()
    page.locator("[aria-label='Vehicle identity details'], [data-category]").first.wait_for()
    return page


def test_after_the_purge_the_case_says_the_identification_is_no_longer_kept(browser, montage):
    login, password = account("cons-nav")
    context, page = signed_in(browser, montage, login, password)
    case_id = register(page)
    parcours_to_restitution(page, GREEN)
    identity_region(page, case_id)
    assert page.get_by_role("region", name="Vehicle identity details").count() == 1        # before: shown
    shown = confirmed_results(page, case_id)

    cs.backdate_case(case_id, 40)              # past its period, not yet purged: the backup keeps it so
    backup = cs.run(["bash", str(REPO / "deploy" / "sauvegarder.sh")], operator_env(montage))
    assert backup.returncode == 0, backup.stderr
    run = cs.cli("purge", "--executer", env=operator_env(montage, **cs.policy_env()))
    assert run.returncode == 0, run.stderr

    identity_region(page, case_id)
    alert = page.locator("[data-category='VIR_RESULT_NOT_KEPT']")
    assert alert.count() == 1 and NOT_KEPT in alert.inner_text()
    body = page.locator("body").inner_text()
    assert "temporarily unavailable" not in body and "Something went wrong" not in body
    assert page.get_by_role("region", name="Vehicle identity details").count() == 0
    assert confirmed_results(page, case_id) == shown                                       # results intact
    STATE.update(case_id=case_id, login=login, password=password, shown=shown, context=context)


def test_after_restoring_the_older_backup_the_identification_stays_not_kept_and_sessions_are_not_restored(
        browser, montage, built_frontend):
    montage.stop()
    source = next((montage.root / "sauvegardes").iterdir())
    (montage.root / "restauree").mkdir()
    restored = Montage(montage.root / "restauree")
    url = fresh_database("pi_restore_cons_nav")
    restored.env.update({"DATABASE_URL": url, "PI_FRONTEND_DIST": str(built_frontend),
                         "VIR_DATA_ENCRYPTION_KEY": montage.env["VIR_DATA_ENCRYPTION_KEY"],
                         "PI05_MEDIA_STORAGE_DIR": str(restored.root / "media")})
    r = cs.run(["bash", str(REPO / "deploy" / "restaurer.sh")],
               operator_env(montage, **cs.policy_env(), DATABASE_URL=url, SOURCE=str(source),
                            MONTAGE_DIR=str(restored.dir), VIR_DATABASE_PATH=restored.env["VIR_DATABASE_PATH"],
                            PI05_MEDIA_STORAGE_DIR=str(restored.root / "media")))
    assert r.returncode == 0, r.stdout + r.stderr
    restored.start()
    try:
        page = STATE["context"].new_page()          # the browser still holds its session cookie
        page.goto(restored.base + "/")
        page.get_by_label("Login").wait_for()       # the restored session is not accepted: sign in again
        STATE["context"].close()
        context, page = signed_in(browser, restored, STATE["login"], STATE["password"])
        identity_region(page, STATE["case_id"])
        alert = page.locator("[data-category='VIR_RESULT_NOT_KEPT']")
        assert alert.count() == 1 and NOT_KEPT in alert.inner_text()
        assert confirmed_results(page, STATE["case_id"]) == STATE["shown"]
        context.close()
    finally:
        restored.stop()
    logs = restored.all_output() + montage.all_output()
    assert "VF3XXXXXXXXXXXXXX" not in logs
