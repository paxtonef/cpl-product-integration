"""Clôture PGDR V1 — in the assembled product (real PI-05 app, real PostgreSQL, real VIR app on its simulated
fixture, real PGDR app with a FICTIVE notice and the fake sorting transport of the trials).

  1. No notice for the vehicle (none provided, another vehicle's, applicability not confirmed): PGDR's refusal
     is shown with, beside it, its parcours WITHOUT notice -- fixed screen, the colour, the validated safety
     screen -- for the case owner only; never a catalogue; nothing recorded in CPL.
  2. The product never serves the legacy PGDR dialogue (complaint text, questions, garage report): absent from
     the production entry whatever the environment says, absent from any API assembly that does not ask for it.
  3. The V1 parcours, with or without notice, never reaches a dialogue engine (SessionController, DiagnosticLoop,
     ComplaintParser, PI-04's diagnostic orchestration, Photo-First): spies make the test fail.
  4. The photo is not kept: no media file, no media ownership row, no trace in CPL (database dump), in a new
     temporary file or in the logs -- after proposals and after a sorting failure.
"""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from app.db.engine import SessionLocal, engine
from pgdr import v1_parcours as v1

from tests.auth_support import log_in, new_account
from tests.notice_parcours_support import (
    SIMULATED_VEHICLE, fake_sorter, notice_parcours_opened, photo_with_metadata,
)
from tests.test_notice_parcours import (  # noqa: F401  (fixtures)
    PLATE, app, case, open_parcours, page_client, pgdr, propose, started, use_notice, use_sorter, user_a, user_b,
    vir_store,
)

SANS_NOTICE = {
    "vehicle_not_supported": lambda p: use_notice(p, {"manufacturer": "Peugeot", "model": "208", "generation": "II"}),
    "applicability_not_confirmed": lambda p: use_notice(p, SIMULATED_VEHICLE, applicability_established=False),
    "notice_unavailable": lambda p: setattr(v1, "_wiring", v1.V1Wiring(repository=None, tri=v1._wiring.tri)),
}


# -- 1. without a notice ------------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("status", sorted(SANS_NOTICE))
async def test_refusal_leads_to_the_safety_instructions_of_the_owner_only(app, pgdr, user_a, user_b, status):
    SANS_NOTICE[status](pgdr)
    case_id = await case(user_a)
    r = await open_parcours(user_a, case_id)
    assert r["status"] == status and r["page"] is None and r["message"]
    assert notice_parcours_opened() == []
    pid = r["safety_page"].split("p=", 1)[1]
    page = page_client(user_a)
    html = await page.get("/v1", params={"p": pid})
    assert html.status_code == 200 and 'id="screen-sans-notice"' in html.text

    state = (await page.get(f"/v1/parcours/{pid}")).json()
    assert state["phase"] == "sans_notice" and state["sans_notice"]["message"] == r["message"]
    for path in ("/catalogue", "/propositions"):
        assert (await page.get(f"/v1/parcours/{pid}{path}")).status_code == 409
    assert (await page.post(f"/v1/parcours/{pid}/consent", json={"accepted": True})).status_code == 409
    red = (await page.post(f"/v1/parcours/{pid}/colour", json={"colour": "rouge"})).json()["screen"]
    assert red["key"] == "red_or_uncertain" and red["heading"].startswith("Arrêtez-vous en sécurité")
    other = (await page.post(f"/v1/parcours/{pid}/colour", json={"colour": "jaune"})).json()["screen"]
    assert other["key"] == "other_colour"

    # Another account: the same answer as a parcours that does not exist.
    stranger = page_client(user_b)
    assert (await stranger.get(f"/v1/parcours/{pid}")).status_code == 404
    assert (await stranger.post(f"/v1/parcours/{pid}/colour", json={"colour": "rouge"})).status_code == 404
    # Nothing recorded: no result, no summary, no report.
    assert (await user_a.get(f"/cases/{case_id}/notice-results")).json()["results"] == []
    await page.aclose()
    await stranger.aclose()


# -- 2. the legacy dialogue is not served -------------------------------------------------------------

def _paths(routes) -> set[tuple[str, str]]:
    out = set()
    for r in routes:
        if hasattr(r, "original_router"):
            out |= _paths(r.original_router.routes)
        elif hasattr(r, "app") and hasattr(r.app, "routes"):
            out |= {(m, r.path + p) for m, p in _paths(r.app.routes)}
        else:
            out |= {(m, r.path) for m in getattr(r, "methods", None) or ()}
    return out


LEGACY = {("POST", "/cases/{case_id}/diagnostics"), ("POST", "/cases/{case_id}/diagnostics/{execution_id}/answers")}
PRODUCT_API = {
    ("GET", "/health"), ("POST", "/auth/login"), ("POST", "/auth/logout"), ("POST", "/auth/password"),
    ("GET", "/auth/session"), ("GET", "/me"), ("GET", "/contacts/{contact_id}"), ("POST", "/vehicles"),
    ("GET", "/cases"), ("POST", "/cases"), ("GET", "/cases/{case_id}"), ("GET", "/cases/{case_id}/history"),
    ("GET", "/cases/{case_id}/vir"), ("POST", "/cases/{case_id}/vir/clarifications"),
    ("POST", "/cases/{case_id}/vir/confirmations"), ("PUT", "/cases/{case_id}/vir/confirmations/{field_path}"),
    ("DELETE", "/cases/{case_id}/vir/confirmations/{field_path}"), ("GET", "/executions/{execution_id}"),
    ("GET", "/executions/{execution_id}/artifact"), ("POST", "/media"),
    ("POST", "/cases/{case_id}/notice-parcours"), ("GET", "/cases/{case_id}/notice-results"),
    ("GET", "/v1"), ("POST", "/v1/parcours/{pid}/record"), ("GET", "/v1/parcours/{pid}{sub_path:path}"),
    ("POST", "/v1/parcours/{pid}{sub_path:path}"),
}


def test_the_production_entry_never_serves_the_legacy_dialogue(monkeypatch, tmp_path):
    from product_integration.api.production import create_production_app
    (tmp_path / "index.html").write_text("<!doctype html><title>app</title>")
    monkeypatch.delenv("PI_COOKIE_SECURE", raising=False)
    monkeypatch.setenv("PI_DIALOGUE_HISTORIQUE", "1")             # even when asked for
    served = _paths(create_production_app(frontend_dist=str(tmp_path)).routes)
    api = {(m, p.removeprefix("/api")) for m, p in served if p.startswith("/api/")}
    assert api == PRODUCT_API and not api & LEGACY


def test_an_api_assembly_serves_the_legacy_dialogue_only_when_asked_for(monkeypatch):
    from product_integration.api.app import create_app
    monkeypatch.delenv("PI_DIALOGUE_HISTORIQUE", raising=False)
    assert not _paths(create_app().routes) & LEGACY
    assert not _paths(create_app(legacy_dialogue=False).routes) & LEGACY
    assert LEGACY <= _paths(create_app(legacy_dialogue=True).routes)


@pytest.mark.asyncio
async def test_starting_a_legacy_diagnostic_is_not_found_in_the_product(monkeypatch, vir_store, pgdr):
    import vir.api.routes as vir_routes
    from tests.test_notice_parcours import make_app
    monkeypatch.delenv("PI_DIALOGUE_HISTORIQUE", raising=False)
    application = make_app(pgdr, vir_routes.app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://api.test") as c:
        c.login = await log_in(c, *new_account("clo"))
        case_id = await case(c)
        r = await c.post(f"/cases/{case_id}/diagnostics", json={"complaint_text": "un texte libre fictif"})
        assert r.status_code in (404, 405)
        with SessionLocal() as s:
            assert s.execute(text("SELECT count(*) FROM cpl.runner_executions WHERE case_id = :c AND runner_type = "
                                  "'PGDR'"), {"c": case_id}).scalar() == 0


# -- 3. no dialogue engine is reached -------------------------------------------------------------------

@pytest.fixture
def forbidden(monkeypatch):
    import product_integration.api.routes as pi_routes
    import product_integration.pgdr.photo_intake as photo_intake
    from pgdr.application.diagnostic_loop import DiagnosticLoop
    from pgdr.complaint_parser import ComplaintParser
    from pgdr.session_controller import SessionController
    calls = []

    def trap(name):
        def refuse(*args, **kwargs):
            calls.append(name)
            raise AssertionError(f"{name} reached from the V1 parcours")
        return refuse

    for cls in (SessionController, DiagnosticLoop, ComplaintParser):
        for attr in [a for a, v in vars(cls).items() if callable(v) and (a == "__init__" or not a.startswith("_"))]:
            monkeypatch.setattr(cls, attr, trap(f"{cls.__name__}.{attr}"))
    for name in ("SessionController", "start_vehicle_diagnostic", "continue_vehicle_diagnostic"):
        monkeypatch.setattr(pi_routes, name, trap(f"routes.{name}"))
    monkeypatch.setattr(photo_intake, "request_photo_first_intake", trap("photo_intake.request_photo_first_intake"))
    for spy in (SessionController, DiagnosticLoop, ComplaintParser, pi_routes.SessionController,
                pi_routes.start_vehicle_diagnostic, photo_intake.request_photo_first_intake):   # the spies do fire
        with pytest.raises(AssertionError):
            spy()
    calls.clear()
    return calls


@pytest.mark.asyncio
async def test_the_v1_parcours_never_reaches_a_dialogue_engine(app, pgdr, user_a, forbidden):
    case_id = await case(user_a)
    pid, page = await started(user_a, case_id)
    base = f"/v1/parcours/{pid}"
    assert (await propose(page, pid, photo_with_metadata(PLATE, "VF1FICTIVE0000002"))).json()["phase"] == "propositions"
    assert (await page.get(base + "/catalogue")).status_code == 200
    await page.post(base + "/selection", json={"entry_ids": ["fn_green_lamps"]})
    out = (await page.post(base + "/confirm", json={"entry_ids": ["fn_green_lamps"], "confirmed": True})).json()
    assert out["phase"] == "restitution"
    for path, body in (("/return", {}), ("/no-match", {"reason": "none_match", "entry_ids": []}),
                       ("/colour", {"colour": "incertain"})):
        assert (await page.post(base + path, json=body)).status_code == 200, path
    SANS_NOTICE["notice_unavailable"](pgdr)
    refusal = await open_parcours(user_a, await case(user_a))
    sans = refusal["safety_page"].split("p=", 1)[1]
    assert (await page.post(f"/v1/parcours/{sans}/colour", json={"colour": "rouge"})).status_code == 200
    await page.aclose()
    assert forbidden == []


# -- 4. the photo is not kept -----------------------------------------------------------------------------

def _dump() -> bytes:
    pg_dump = shutil.which("pg_dump") or "/opt/homebrew/opt/postgresql@16/bin/pg_dump"
    url = engine.url
    env = {**os.environ, "PGPASSWORD": url.password or ""}
    return subprocess.run([pg_dump, "-h", url.host, "-p", str(url.port), "-U", url.username, "-d", url.database,
                           "--data-only"], env=env, capture_output=True, check=True).stdout


def _new_files(root: Path, before: set) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file() and p not in before]


@pytest.mark.asyncio
async def test_the_photo_is_kept_nowhere_after_proposals_or_a_sorting_failure(app, pgdr, user_a, caplog, monkeypatch):
    media = Path(os.environ.get("PI05_MEDIA_STORAGE_DIR") or tempfile.mkdtemp())
    tmp = Path(tempfile.gettempdir())
    media_before = set(p for p in media.rglob("*") if p.is_file())
    tmp_before = set(p for p in tmp.glob("*") if p.is_file())
    with SessionLocal() as s:
        owned_before = s.execute(text("SELECT count(*) FROM pi_auth.media_ownership")).scalar()

    photos = []
    for i, sorter in enumerate((None, fake_sorter(panne=True))):
        if sorter is not None:
            use_sorter(sorter)
        photo = photo_with_metadata(PLATE, f"VF1FICTIVE000000{i + 3}")
        photos.append(photo)
        case_id = await case(user_a)
        pid, page = await started(user_a, case_id)
        r = await propose(page, pid, photo)
        assert r.status_code == 200 and r.json()["phase"] == ("propositions" if sorter is None else "catalogue")
        await page.aclose()

    assert _new_files(media, media_before) == []
    with SessionLocal() as s:
        assert s.execute(text("SELECT count(*) FROM pi_auth.media_ownership")).scalar() == owned_before
    dump = _dump()
    logs = caplog.text.encode()
    new_tmp = [p.read_bytes() for p in tmp.glob("*") if p.is_file() and p not in tmp_before and p.stat().st_size < 50_000_000]
    for photo in photos:
        for trace in (photo[16:48], base64.b64encode(photo)[:40], PLATE.encode()):
            assert trace not in dump and trace not in logs
            assert not any(trace in blob for blob in new_tmp)
