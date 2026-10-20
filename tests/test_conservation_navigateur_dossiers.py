"""Conservation 3/3 — the browser, with the real assembly, after the deletion of an expired case.

scripts/lancer_montage.sh in production mode (HTTPS, built frontend, VIR simulated, PGDR with a FICTIVE notice,
no sorting transport), real Chromium, fictitious accounts. User A has two cases with a confirmed notice result,
user B one case. A backup is taken while A's second case is already past its period (moved 40 days into the
past; test period 30 days, never an approved duration), then the operator purge deletes it. In the browser: the
kept case is A's, with its result; the deleted case cannot be found; B is refused A's case. The same is checked
again after restoring that older backup into a new database (deploy/restaurer.sh, then its purge) and starting
the assembly on it.
"""
from __future__ import annotations

import pytest

from tests import conservation_support as cs
from tests.test_3a_lancement_reel import REPO, Montage
from tests.test_3b_reception_navigateur import (  # noqa: F401  (fixtures)
    GREEN, account, browser, built_frontend, confirmed_results, parcours_to_restitution, register, signed_in,
)
from tests.test_conservation_navigateur import operator_env
from tests.test_conservation_sauvegardes import fresh_database

STATE: dict = {}
POLICY = cs.policy_env(PI_CONSERVATION_DOSSIERS_JOURS=cs.TEST_DAYS)


@pytest.fixture(scope="module")
def montage(tmp_path_factory, built_frontend):
    m = Montage(tmp_path_factory.mktemp("conservation-dossiers"))
    m.env["PI_FRONTEND_DIST"] = str(built_frontend)
    (m.root / "media").mkdir()
    m.start()
    yield m
    if m.proc.poll() is None:
        m.stop()


def not_found(page, case_id: str) -> bool:
    page.goto(f"/cases/{case_id}")
    banner = page.locator("[data-category='NOT_FOUND']")
    banner.wait_for()
    body = page.locator("body").inner_text()
    return (banner.count() == 1 and "Confirmed results" not in body and "Something went wrong" not in body
            and "temporarily unavailable" not in body)


def check_in_browser(browser, montage) -> None:
    context_a, page_a = signed_in(browser, montage, STATE["login_a"], STATE["password_a"])
    assert confirmed_results(page_a, STATE["kept"]) == STATE["kept_results"]          # kept case: its owner's
    assert not_found(page_a, STATE["deleted"])                                         # deleted: not found
    context_b, page_b = signed_in(browser, montage, STATE["login_b"], STATE["password_b"])
    assert not_found(page_b, STATE["kept"]) and not_found(page_b, STATE["deleted"])    # another user: refused
    assert confirmed_results(page_b, STATE["case_b"]) == STATE["case_b_results"]      # B's own case: kept
    context_a.close()
    context_b.close()


def test_kept_case_owner_only_deleted_case_not_found_with_the_real_assembly(browser, montage):
    STATE["login_a"], STATE["password_a"] = account("cons-del-a")
    STATE["login_b"], STATE["password_b"] = account("cons-del-b")
    context, page = signed_in(browser, montage, STATE["login_a"], STATE["password_a"])
    for key in ("kept", "deleted"):
        STATE[key] = register(page)
        parcours_to_restitution(page, GREEN)
    STATE["kept_results"] = confirmed_results(page, STATE["kept"])
    assert "Confirmed results" in STATE["kept_results"]
    context.close()
    context, page = signed_in(browser, montage, STATE["login_b"], STATE["password_b"])
    STATE["case_b"] = register(page)
    parcours_to_restitution(page, GREEN)
    STATE["case_b_results"] = confirmed_results(page, STATE["case_b"])
    context.close()

    cs.backdate_case_creation(STATE["deleted"], 40)
    backup = cs.run(["bash", str(REPO / "deploy" / "sauvegarder.sh")], operator_env(montage))
    assert backup.returncode == 0, backup.stderr                 # the older backup still holds the case
    run = cs.cli("purge", "--executer", env=operator_env(montage, **POLICY))
    assert run.returncode == 0 and "dossier(s) échu(s) supprimé(s)" in run.stdout, run.stdout + run.stderr
    check_in_browser(browser, montage)


def test_after_restoring_the_older_backup_and_its_purge_the_deleted_case_stays_not_found(
        browser, montage, built_frontend):
    montage.stop()
    source = next((montage.root / "sauvegardes").iterdir())
    (montage.root / "restauree").mkdir()
    restored = Montage(montage.root / "restauree")
    url = fresh_database("pi_restore_cons_nav_dossiers")
    restored.env.update({"DATABASE_URL": url, "PI_FRONTEND_DIST": str(built_frontend),
                         "VIR_DATA_ENCRYPTION_KEY": montage.env["VIR_DATA_ENCRYPTION_KEY"],
                         "PI05_MEDIA_STORAGE_DIR": str(restored.root / "media")})
    r = cs.run(["bash", str(REPO / "deploy" / "restaurer.sh")],
               operator_env(montage, **POLICY, DATABASE_URL=url, SOURCE=str(source), MONTAGE_DIR=str(restored.dir),
                            VIR_DATABASE_PATH=restored.env["VIR_DATABASE_PATH"],
                            PI05_MEDIA_STORAGE_DIR=str(restored.root / "media")))
    assert r.returncode == 0 and "Sessions web révoquées" in r.stdout, r.stdout + r.stderr
    assert "1 dossier(s) échu(s) supprimé(s)" in r.stdout, r.stdout
    restored.start()
    try:
        check_in_browser(browser, restored)
    finally:
        restored.stop()
