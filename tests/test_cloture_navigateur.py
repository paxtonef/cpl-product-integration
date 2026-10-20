"""Clôture PGDR V1 — reception in the browser on the real production launch.

scripts/lancer_montage.sh in production mode (HTTPS entry, the REAL built frontend, VIR simulated, PGDR with a
FICTIVE notice, no sorting transport -- the V1 behaviour accepted in its absence), real Chromium, fictitious
accounts, the real PI -> PGDR -> CPL wiring, no direct injection:

  A/C/F  consent refused then given; the photo stays on the device; the complete catalogue explains why there
         are no proposed images; the driver's own selection and confirmation; the notice's exact passage with
         its page, then the Premier Constat; the result kept with the case (J);
  E      no image recognised: closed commands, colour, the validated safety screen;
  G      identity not established -> PGDR's refusal and, beside it, the safety instructions without notice;
         no notice provided at all (second launch without PGDR_V1_MANIFEST) -> the same, nothing invented;
  H      no dialogue: no link to the legacy diagnostic, no free text field on any screen of the parcours, the
         legacy routes not served by the product API;
  I      the photo is not kept, no identifier in the logs.

Proves the V1 parcours on fictive data; never a real notice, never a real sorting component.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from app.db.engine import SessionLocal

from tests.notice_parcours_support import GREEN_MEANING, png
from tests.test_3a_lancement_reel import VIN, Montage
from tests.test_3b_reception_navigateur import (  # noqa: F401  (fixtures)
    account, browser, built_frontend, register, signed_in,
)

PROVISIONAL_VIN = "VF1XXXXXXXXXXXXXX"   # VIR simulated fixture: no model, no generation
GREEN, AMBER = "fn_green_lamps", "fn_amber_sensor"
FREE_TEXT = "input[type=text]:visible, input:not([type]):visible, textarea, [contenteditable]"
STATE: dict = {}


@pytest.fixture(scope="module")
def montage(tmp_path_factory, built_frontend):
    m = Montage(tmp_path_factory.mktemp("cloture"))
    m.env["PI_FRONTEND_DIST"] = str(built_frontend)
    m.start()
    yield m
    if m.proc.poll() is None:
        m.stop()


def no_free_text(page) -> None:
    assert page.locator(FREE_TEXT).count() == 0, page.url


def executions(case_id: str) -> list[str]:
    with SessionLocal() as s:
        return [r[0] for r in s.execute(text("SELECT runner_type FROM cpl.runner_executions WHERE case_id = :c "
                                             "ORDER BY created_at"), {"c": case_id})]


def test_h_the_case_page_offers_no_legacy_dialogue(browser, montage):
    login, password = account("clo-h")
    context, page = signed_in(browser, montage, login, password)
    case_id = register(page)
    page.get_by_role("button", name="Open the manufacturer notice").wait_for()
    assert page.get_by_role("link", name="Start a diagnostic").count() == 0
    assert page.get_by_text("Tell us what's wrong").count() == 0
    page.goto(f"/cases/{case_id}/diagnostic")                 # typed by hand: no complaint form either
    page.wait_for_load_state("networkidle")
    assert page.locator("textarea").count() == 0 and page.get_by_text("Tell us what's wrong").count() == 0
    r = page.request.post(f"/api/cases/{case_id}/diagnostics", data={"complaint_text": "texte libre fictif"},
                          headers={"Origin": montage.base})
    assert r.status in (404, 405) and "PGDR" not in executions(case_id), r.status   # not a route of the product
    STATE.update(login=login, password=password, case_id=case_id)
    context.close()


def test_a_c_f_e_j_consent_catalogue_selection_exact_passage_then_safety(browser, montage, tmp_path):
    context, page = signed_in(browser, montage, STATE["login"], STATE["password"])
    sent = []
    page.on("request", lambda r: sent.append((r.method, r.url, r.post_data_buffer or b"")))
    case_id = STATE["case_id"]
    page.goto(f"/cases/{case_id}")
    page.get_by_role("button", name="Open the manufacturer notice").click()
    page.wait_for_url("**/api/v1?p=*")
    page.click("#vir-continue")
    no_free_text(page)
    # A: consent refused -> nothing processed, the parcours stays here.
    page.click("#consent-continue")
    page.locator("#consent-message").filter(has_text="Sans votre accord").wait_for()
    assert page.locator("#screen-consent").is_visible()
    page.check("#consent-box")
    page.click("#consent-continue")
    page.locator("#screen-photo").wait_for()
    photo = tmp_path / "tableau.png"
    photo.write_bytes(png((200, 40, 40), 16))
    page.set_input_files("#photo-input", str(photo))
    assert page.locator("#propose-offer").is_hidden()          # no sorting component: no proposal offered
    no_free_text(page)
    # C: complete catalogue, explained.
    page.click("#photo-continue")
    page.locator("#screen-catalogue").wait_for()
    assert page.locator("#catalogue-repli").is_visible()
    assert page.locator("#catalogue-grid .tile[aria-pressed=true]").count() == 0   # nothing preselected
    no_free_text(page)
    # F: the driver's own selection, explicit confirmation, exact passage and page, then the Premier Constat.
    page.click(f'#catalogue-grid .tile[data-entry-id="{GREEN}"]')
    page.click("#selection-continue")
    page.locator("#screen-confirmation").wait_for()
    page.click("#confirm")
    page.locator("#screen-restitution").wait_for()
    article = page.locator(f'article.restitution[data-entry-id="{GREEN}"]')
    assert GREEN_MEANING in article.locator(".meaning").inner_text()
    assert "Page de la notice :" in article.inner_text() and "page PDF" in article.inner_text()
    assert page.locator("#premier-constat").is_visible()
    page.locator('#product-record[data-status="recorded"]').wait_for()
    no_free_text(page)
    # E: no image recognised -> closed commands, colour, validated safety screen.
    page.click("#screen-restitution button.return")
    page.locator("#screen-catalogue").wait_for()
    page.click("#none-match")
    page.locator("#screen-colour").wait_for()
    no_free_text(page)
    page.get_by_role("button", name="Je ne sais pas / incertain").click()
    page.locator("#fallback-content h1").filter(has_text="Arrêtez-vous en sécurité").wait_for()
    no_free_text(page)
    # I: the photo never left the device.
    raw = photo.read_bytes()
    assert not [u for _, u, body in sent if raw[16:48] in body or b"photo_base64" in body]
    # J: the confirmed result is kept with the case; no legacy execution, no report.
    page.goto(f"/cases/{case_id}")
    page.get_by_role("heading", name="Confirmed results").wait_for()
    assert executions(case_id) == ["VIR", "PGDR_V1_NOTICE"]
    context.close()


def test_g_identity_not_established_gives_the_safety_instructions_without_notice(browser, montage):
    context, page = signed_in(browser, montage, *account("clo-g"))
    page.goto("/register")
    page.get_by_role("button", name="Register").click()
    page.get_by_label("VIN", exact=True).fill(PROVISIONAL_VIN)
    page.get_by_label("Registration country").select_option("FR")
    page.get_by_label("I agree that my VIN or registration number is sent to the vehicle-data providers to identify "
                      "my vehicle").check()
    page.get_by_role("button", name="Continue").click()
    page.get_by_role("button", name="Continue").click()
    page.wait_for_url("**/cases/*")
    case_id = page.url.rsplit("/", 1)[1]
    page.get_by_role("button", name="Open the manufacturer notice").click()
    refusal = page.get_by_test_id("notice-refusal")
    refusal.wait_for()
    assert "L'identité du véhicule n'est pas établie par VIR." in refusal.inner_text()
    page.get_by_role("button", name="Voir les consignes de sécurité").click()
    page.wait_for_url("**/api/v1?p=*")
    page.locator("#screen-sans-notice").wait_for()
    assert page.locator("#sans-notice-message").inner_text() == "L'identité du véhicule n'est pas établie par VIR."
    assert page.locator("img:visible, .tile").count() == 0
    no_free_text(page)
    page.get_by_role("button", name="Rouge").click()
    page.locator("#sans-notice-screen h2").filter(has_text="Arrêtez-vous en sécurité").wait_for()
    assert executions(case_id) == ["VIR"]                      # nothing recorded, no summary, no report
    context.close()


def test_i_logs_hold_no_identifier_and_no_photo(montage):
    logs = montage.all_output()
    for marker in (VIN, PROVISIONAL_VIN, "photo_base64", "Traceback"):
        assert marker not in logs, marker
    media = Path(montage.env["PI05_MEDIA_STORAGE_DIR"])
    assert not media.exists() or not [p for p in media.rglob("*") if p.is_file()]


def test_g_no_notice_provided_at_all_gives_the_same_safety_instructions(browser, tmp_path_factory, built_frontend):
    m = Montage(tmp_path_factory.mktemp("cloture-sans-notice"))
    m.env["PI_FRONTEND_DIST"] = str(built_frontend)
    del m.env["PGDR_V1_MANIFEST"]
    m.start()
    try:
        context, page = signed_in(browser, m, *account("clo-n"))
        register(page)
        page.get_by_role("button", name="Open the manufacturer notice").click()
        page.get_by_test_id("notice-refusal").wait_for()
        page.get_by_role("button", name="Voir les consignes de sécurité").click()
        page.locator("#screen-sans-notice").wait_for()
        assert page.locator("#sans-notice-titre").inner_text() == "Aucune notice du constructeur pour ce véhicule"
        no_free_text(page)
        page.get_by_role("button", name="Vert").click()
        page.locator("#sans-notice-screen h2").filter(has_text="Voyant non identifié").wait_for()
        context.close()
    finally:
        m.stop()
