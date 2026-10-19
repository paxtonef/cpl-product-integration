"""Passe provenance et applicabilité — browser check on the real production launch.

scripts/lancer_montage.sh in production mode (HTTPS entry, VIR simulated, PGDR with a FICTIVE notice whose
applicability is NOT established at notice level, no sorting transport), the REAL built frontend, real
Chromium, fictitious accounts:

  1. the refusal shows PGDR's reasons, the keys compared with their provenance (« fourni par une source,
     non établi »), what remains to be checked and the next action -- never asking to redo validated contents;
  2. a generation the driver confirms in the case page is shown « confirmé par le conducteur » in the
     refusal, never as established;
  3. after a FICTIVE attestation limited to one case's vehicle and to this notice version (and a restart, PGDR
     reading its files once), that case opens the notice; another account's vehicle with the same identity
     stays refused.

No PGDR_V1_DEV_VEHICLE, no development trial. Proves the wiring, never the applicability of a real notice.
"""
from __future__ import annotations

import pytest
import yaml
from sqlalchemy import text

from app.db.engine import SessionLocal
from pgdr import v1_applicabilite as va
from pgdr.adapters.manifest_notice_repository import ManifestNoticeRepository

from tests.notice_parcours_support import SIMULATED_VEHICLE, build_notice
from tests.test_3a_lancement_reel import Montage
from tests.test_3b_reception_navigateur import (  # noqa: F401  (fixtures)
    account, browser, built_frontend, register, signed_in,
)

PROVISIONAL_VIN = "VF1XXXXXXXXXXXXXX"   # VIR simulated fixture: manufacturer deduced, no model, no generation
STATE: dict = {}


@pytest.fixture(scope="module")
def montage(tmp_path_factory, built_frontend):
    root = tmp_path_factory.mktemp("provenance")
    m = Montage(root)
    m.env["PI_FRONTEND_DIST"] = str(built_frontend)
    m.env["PGDR_V1_MANIFEST"] = str(build_notice(root / "notice-not-established", SIMULATED_VEHICLE,
                                                 applicability_established=False))
    m.env["PGDR_V1_APPLICABILITE"] = str(root / "applicabilite.yaml")      # absent until test 3
    m.start()
    yield m
    if m.proc.poll() is None:
        m.stop()


def refusal_text(page, case_id: str) -> str:
    page.goto(f"/cases/{case_id}")
    page.get_by_role("button", name="Open the manufacturer notice").click()
    refusal = page.get_by_test_id("notice-refusal")
    refusal.wait_for()
    assert page.url.endswith(f"/cases/{case_id}")
    return refusal.inner_text()


def test_1_refusal_shows_reasons_provenance_what_to_check_and_next_action(browser, montage):
    login, password = account("prov-a")
    context, page = signed_in(browser, montage, login, password)
    case_id = register(page)
    shown = refusal_text(page, case_id)
    assert "L'applicabilité de la notice à ce véhicule n'est pas confirmée." in shown
    assert "Le modèle : 3008 (fourni par une source, non établi)" in shown
    assert "L'applicabilité de cette notice n'est pas établie par sa revue." in shown
    assert "Aucune attestation d'applicabilité ne couvre ce véhicule" in shown
    assert "Reste à vérifier" in shown and "nom du fichier" in shown
    assert "Prochaine étape" in shown and "n'ont pas à être refaits" in shown
    STATE.update(case_a=case_id, login_a=login, password_a=password)
    context.close()


def test_2_confirmed_generation_is_shown_as_confirmed_by_the_driver(browser, montage):
    context, page = signed_in(browser, montage, *account("prov-b"))
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
    generation = page.locator("fieldset", has=page.locator("legend", has_text="Generation"))
    generation.get_by_label("Your value for Generation").fill("II")
    generation.get_by_role("button", name="Confirm").click()
    generation.get_by_text("Your confirmation: II").wait_for()
    shown = refusal_text(page, case_id)
    assert "L'identité du véhicule n'est pas établie par VIR." in shown
    assert "La génération : II (confirmé par le conducteur, sans vérification indépendante)" in shown
    assert "Le modèle du véhicule n'est pas connu" in shown
    assert "établi (décodage" not in shown
    context.close()


def test_3_attestation_opens_only_the_attested_vehicle(browser, montage):
    with SessionLocal() as s:
        asset = str(s.execute(text("SELECT asset_id FROM cpl.cases WHERE case_id = :c"),
                              {"c": STATE["case_a"]}).scalar())
    catalogue = ManifestNoticeRepository(montage.env["PGDR_V1_MANIFEST"]).catalogue
    criteria = {k: {"value": v, "notice_source": {"kind": "printed_notice", "reference": "couverture fictive"},
                    "vehicle_source": {"kind": "registration_document", "reference": "rubrique fictive"}}
                for k, v in SIMULATED_VEHICLE.items()}
    with open(montage.env["PGDR_V1_APPLICABILITE"], "w", encoding="utf-8") as fh:
        yaml.safe_dump({"format": va.ATTESTATION_FORMAT, "attestations": [{
            "status": "VALIDE", "attested_by": "Fictive Owner", "verified_on": "2026-10-18",
            "document_id": catalogue.document.document_id, "catalogue_content_sha256": catalogue.content_sha256,
            "vehicle_ref": asset, "criteria": criteria}]}, fh, allow_unicode=True)
    montage.stop()
    montage.start()                                   # PGDR reads its files once, at the first parcours

    context, page = signed_in(browser, montage, STATE["login_a"], STATE["password_a"])
    page.goto(f"/cases/{STATE['case_a']}")
    page.get_by_role("button", name="Open the manufacturer notice").click()
    page.wait_for_url("**/api/v1?p=*")
    vehicle = page.locator("#vir-vehicle")
    vehicle.wait_for()
    assert "3008 (fourni par une source, non établi)" in vehicle.inner_text()
    context.close()

    context, page = signed_in(browser, montage, *account("prov-c"))
    other_case = register(page)                       # same fictitious identity, another vehicle
    assert "Aucune attestation d'applicabilité ne couvre ce véhicule" in refusal_text(page, other_case)
    context.close()
    logs = montage.all_output()
    assert "VF3XXXXXXXXXXXXXX" not in logs and PROVISIONAL_VIN not in logs
