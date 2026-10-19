"""Bloc 3B — browser acceptance of the kept results on the real production launch.

scripts/lancer_montage.sh in production mode (HTTPS entry, VIR simulated,
PGDR with a FICTIVE notice and no sorting transport), serving the REAL built
frontend (vite build of this repository, into a temporary directory), real
Chromium, two fictitious accounts:

  point 3  CPL refuses the record (a temporary PostgreSQL trigger on
           cpl.runner_artifacts makes the database reject it): the driver
           sees the manufacturer's texts and « Résultat non enregistré »;
           the retry, once CPL accepts again, records it once, with no new
           request to PGDR; « Résultat enregistré » appears only then
  point 1  « Confirmed results » on the case page shows each kept result;
           after a complete restart of the assembly it is the same, for its
           owner; another account is refused the case and its results
"""
from __future__ import annotations

import secrets
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from app.db.engine import SessionLocal
from product_integration.auth import accounts

from tests.notice_parcours_support import GREEN_MEANING
from tests.test_3a_lancement_reel import REPO, VIN, Montage

FRONTEND = REPO / "frontend"
AMBER = "fn_amber_sensor"
GREEN = "fn_green_lamps"
STATE: dict = {}

REFUSE = """
CREATE OR REPLACE FUNCTION public.essai_3b_refus() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.schema_name = 'pgdr_v1_premier_constat' THEN RAISE EXCEPTION 'essai 3B : enregistrement refusé'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER essai_3b_refus BEFORE INSERT ON cpl.runner_artifacts FOR EACH ROW EXECUTE FUNCTION public.essai_3b_refus();
"""
ACCEPT = "DROP TRIGGER IF EXISTS essai_3b_refus ON cpl.runner_artifacts; DROP FUNCTION IF EXISTS public.essai_3b_refus();"


def sql(statement: str) -> None:
    with SessionLocal() as s:
        s.execute(text(statement))
        s.commit()


def kept_rows(case_id: str) -> int:
    with SessionLocal() as s:
        return s.execute(text(
            "SELECT count(*) FROM cpl.runner_executions e JOIN cpl.runner_artifacts a ON a.execution_id = e.execution_id "
            "WHERE e.case_id = :c AND e.runner_type = 'PGDR_V1_NOTICE'"), {"c": case_id}).scalar()


@pytest.fixture(scope="module")
def built_frontend(tmp_path_factory) -> Path:
    if shutil.which("npx") is None or not (FRONTEND / "node_modules").is_dir():
        raise AssertionError("frontend dependencies missing: run `npm ci` in frontend/ first")
    out = tmp_path_factory.mktemp("frontend") / "dist"
    subprocess.run(["npx", "vite", "build", "--outDir", str(out), "--emptyOutDir", "--logLevel", "error"],
                   cwd=FRONTEND, check=True, capture_output=True, timeout=300)
    assert (out / "index.html").is_file()
    return out


@pytest.fixture(scope="module")
def montage(tmp_path_factory, built_frontend):
    m = Montage(tmp_path_factory.mktemp("reception"))
    m.env["PI_FRONTEND_DIST"] = str(built_frontend)
    m.start()
    yield m
    sql(ACCEPT)
    if m.proc.poll() is None:
        m.stop()


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    b = pw.chromium.launch(headless=True)
    yield b
    b.close()
    pw.stop()


def account(prefix: str) -> tuple[str, str]:
    login, password = f"{prefix}-{uuid.uuid4().hex[:8]}", "fictive-" + secrets.token_urlsafe(12)
    accounts.create_account(login, password)
    return login, password


def signed_in(browser, montage, login: str, password: str):
    context = browser.new_context(ignore_https_errors=True, base_url=montage.base)
    page = context.new_page()
    page.goto("/")
    page.get_by_label("Login").fill(login)
    page.get_by_label("Password").fill(password)
    page.get_by_role("button", name="Sign in").click()
    page.get_by_role("heading", name="Vehicle diagnostic").wait_for()
    return context, page


def register(page) -> str:
    page.goto("/register")
    page.get_by_role("button", name="Register").click()
    page.get_by_label("VIN", exact=True).fill(VIN)
    page.get_by_label("Registration country").select_option("FR")
    page.get_by_label("I agree that my VIN or registration number is sent to the vehicle-data providers to identify "
                      "my vehicle").check()
    page.get_by_role("button", name="Continue").click()
    page.get_by_role("button", name="Continue").click()
    page.wait_for_url("**/cases/*")
    return page.url.rsplit("/", 1)[1]


def parcours_to_restitution(page, entry_id: str) -> None:
    page.get_by_role("button", name="Open the manufacturer notice").click()
    page.wait_for_url("**/api/v1?p=*")
    page.click("#vir-continue")
    page.check("#consent-box")
    page.click("#consent-continue")
    page.click("#photo-continue")
    page.click(f'#catalogue-grid .tile[data-entry-id="{entry_id}"]')
    page.click("#selection-continue")
    page.click("#confirm")
    page.wait_for_selector("#screen-restitution:not([hidden])")


def confirmed_results(page, case_id: str) -> str:
    page.goto(f"/cases/{case_id}")
    region = page.get_by_role("region", name="Confirmed results")
    region.wait_for()
    return region.inner_text()


def test_point1_a_confirmed_result_is_announced_recorded_and_shown_with_the_case(browser, montage):
    login, password = account("rec-a")
    context, page = signed_in(browser, montage, login, password)
    case_id = register(page)
    parcours_to_restitution(page, GREEN)
    box = page.locator("#product-record")
    assert box.get_attribute("data-status") == "recorded" and "Résultat enregistré" in box.inner_text()
    assert kept_rows(case_id) == 1
    shown = confirmed_results(page, case_id)
    assert GREEN_MEANING in shown and "Your selection, not a recognition" in shown
    assert page.locator("article[data-testid^='notice-result-']").count() == 1
    STATE.update(case_id=case_id, login=login, password=password)
    context.close()


def test_point3_cpl_refuses_then_the_retry_records_it_once_without_pgdr(browser, montage):
    context, page = signed_in(browser, montage, STATE["login"], STATE["password"])
    page.goto(f"/cases/{STATE['case_id']}")
    sql(REFUSE)
    try:
        parcours_to_restitution(page, AMBER)
        box = page.locator("#product-record")
        assert box.get_attribute("data-status") == "not_recorded" and box.get_attribute("role") == "alert"
        assert "Résultat non enregistré" in box.inner_text()
        assert page.locator(f'article.restitution[data-entry-id="{AMBER}"]').count() == 1     # texts still shown
        assert "fictive sensor fault" in page.locator("#restitution").inner_text()
        assert kept_rows(STATE["case_id"]) == 1
        other = context.new_page()
        assert "fictive sensor fault" not in confirmed_results(other, STATE["case_id"])   # not announced as kept
        other.close()
        page.click("#record-retry")                     # CPL still refuses: still not recorded, nothing written
        page.locator("#record-retry:enabled").wait_for()
        assert box.get_attribute("data-status") == "not_recorded" and kept_rows(STATE["case_id"]) == 1
    finally:
        sql(ACCEPT)
    pgdr_before = montage.logs()["pgdr.log"].count("/api/v1/parcours/")
    page.click("#record-retry")
    page.wait_for_selector('#product-record[data-status="recorded"]')
    assert "Résultat enregistré" in page.locator("#product-record").inner_text()
    assert page.locator("#record-retry").count() == 0
    assert kept_rows(STATE["case_id"]) == 2
    assert montage.logs()["pgdr.log"].count("/api/v1/parcours/") == pgdr_before     # no PGDR request for the retry
    assert "POST /api/v1/parcours/{pid}/record 200" in montage.logs()["pi05.log"]
    shown = confirmed_results(page, STATE["case_id"])
    assert "fictive sensor fault" in shown and GREEN_MEANING in shown
    assert page.locator("article[data-testid^='notice-result-']").count() == 2
    STATE["shown"] = shown
    context.close()


def test_point1_after_a_complete_restart_the_owner_sees_the_same_and_another_account_is_refused(browser, montage):
    montage.stop()
    montage.start()
    context, page = signed_in(browser, montage, STATE["login"], STATE["password"])
    assert confirmed_results(page, STATE["case_id"]) == STATE["shown"]
    assert page.locator("article[data-testid^='notice-result-']").count() == 2
    context.close()

    login_b, password_b = account("rec-b")
    context, page = signed_in(browser, montage, login_b, password_b)
    page.goto(f"/cases/{STATE['case_id']}")
    page.get_by_role("alert").wait_for()
    assert page.get_by_role("region", name="Confirmed results").count() == 0
    body = page.locator("body").inner_text()
    assert "fictive sensor fault" not in body and GREEN_MEANING not in body
    answer = page.request.get(f"/api/cases/{STATE['case_id']}/notice-results")
    assert answer.status == 404 and "fn_" not in answer.text()
    context.close()
    assert kept_rows(STATE["case_id"]) == 2
