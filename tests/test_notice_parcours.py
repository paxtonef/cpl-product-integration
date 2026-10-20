"""PGDR V1 notice parcours in the authenticated product (block 2): the case
owner opens PGDR's /v1 parcours (photo -> 1 to 3 proposed images -> own
selection -> confirmation -> notice and Premier Constat), through PI only.

Real PI-05 app, real PostgreSQL, real VIR app (simulated fixture, or real mode
on fake transports), real PGDR web app reached over HTTP semantics
(ASGI transport) with a FICTIVE notice and the FAKE sorting transport only.
This proves the wiring, the rights and the refusals -- never any recognition
quality.
"""
from __future__ import annotations

import base64
import json
import logging
import uuid
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio

import pgdr.v1_parcours as v1
import pgdr.web_app as pgdr_web
from pgdr import v1_contenu as vc
from pgdr import v1_propositions as vp
from pgdr.adapters.manifest_notice_repository import ManifestNoticeRepository

from product_integration.api import parcours_routes
from product_integration.api.app import create_app
from product_integration.api.deps import get_notice_registry, get_pgdr_http_client, get_vir_client
from product_integration.pgdr.notice_parcours import NoticeParcoursRegistry
from product_integration.vir.client import VIRClient

from tests import vir_real_mode_support as support
from tests.auth_support import CSRF_HEADER, log_in, new_account
from tests.notice_parcours_support import (
    GREEN_MEANING, ORDER, RECIPIENT, SIMULATED_VEHICLE, build_notice, fake_sorter, notice_parcours_opened,
    photo_with_metadata,
)

TOKEN = "fictive-pgdr-handoff-" + uuid.uuid4().hex[:8]
RESOLVED_VIN = "VF3XXXXXXXXXXXXXX"        # VIR simulated fixture: Peugeot 3008 II, resolved
PROVISIONAL_VIN = "VF1XXXXXXXXXXXXXX"     # VIR simulated fixture: provisionally resolved
PLATE = "FICTIVE-PLATE-91"
UNKNOWN = {"detail": "Parcours inconnu ou expiré. Rouvrez la notice depuis votre dossier : un nouveau parcours commencera.",
           "error_category": "NOT_FOUND"}


class RecordingASGITransport(httpx.ASGITransport):
    """Every request PI sends to PGDR (method, path, body)."""

    def __init__(self, app):
        super().__init__(app=app)
        self.calls: list[tuple[str, str, bytes]] = []

    async def handle_async_request(self, request):
        self.calls.append((request.method, request.url.path, request.content))
        return await super().handle_async_request(request)


class DownTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request):
        raise httpx.ConnectError("connection refused to " + str(request.url))


@pytest.fixture
def pgdr(monkeypatch, tmp_path):
    """PGDR's real web app with a FICTIVE notice for VIR's simulated vehicle."""
    seen: list = []
    repo = ManifestNoticeRepository(build_notice(tmp_path / "notice", SIMULATED_VEHICLE))
    monkeypatch.setattr(v1, "_wiring", v1.build_wiring(repo, dev_trial=False,
                                                       tri=fake_sorter(["fn_green_lamps", "fn_red_fluid"], seen=seen)))
    monkeypatch.setattr(v1, "_parcours", {})
    monkeypatch.setenv(pgdr_web.IDENTITY_HANDOFF_TOKEN_ENV, TOKEN)
    monkeypatch.setenv("PI_PGDR_IDENTITY_HANDOFF_TOKEN", TOKEN)
    monkeypatch.setenv("PI_PGDR_BASE_URL", "http://pgdr.test")
    return SimpleNamespace(seen=seen, transport=RecordingASGITransport(pgdr_web.app), tmp=tmp_path)


def use_sorter(transport) -> None:
    v1._wiring.tri = transport


def use_notice(pgdr, vehicle: dict, **kw) -> None:
    v1._wiring = v1.build_wiring(ManifestNoticeRepository(build_notice(pgdr.tmp / uuid.uuid4().hex, vehicle, **kw)),
                                 dev_trial=False, tri=v1._wiring.tri)


@pytest.fixture
def vir_store(tmp_path):
    from vir.adapters.sqlite_persistence_adapter import SQLitePersistenceAdapter
    import vir.api.routes as vir_routes
    original = vir_routes.STORE
    vir_routes.STORE = SQLitePersistenceAdapter(str(tmp_path / "notice_parcours_vir.db"))
    yield
    vir_routes.STORE = original


def make_app(pgdr, vir_app, pgdr_transport=None):
    vir_transport = httpx.ASGITransport(app=vir_app)

    async def vir_client():
        async with httpx.AsyncClient(transport=vir_transport, base_url="http://vir.test") as c:
            yield VIRClient(c)

    async def pgdr_client():
        async with httpx.AsyncClient(transport=pgdr_transport or pgdr.transport) as c:
            yield c

    application = create_app()
    application.dependency_overrides[get_vir_client] = vir_client
    application.dependency_overrides[get_pgdr_http_client] = pgdr_client
    registry = NoticeParcoursRegistry()
    application.dependency_overrides[get_notice_registry] = lambda: registry
    application.state.notice_registry = registry
    return application


@pytest.fixture
def app(vir_store, pgdr):
    import vir.api.routes as vir_routes
    return make_app(pgdr, vir_routes.app)


async def user(app, prefix: str) -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test")
    client.login = await log_in(client, *new_account(prefix))
    return client


@pytest_asyncio.fixture
async def user_a(app):
    c = await user(app, "npa")
    yield c
    await c.aclose()


@pytest_asyncio.fixture
async def user_b(app):
    c = await user(app, "npb")
    yield c
    await c.aclose()


def _key(tag: str) -> str:
    return f"{tag}-{uuid.uuid4().hex[:10]}"


async def case(client, **identifiers) -> str:
    r = await client.post("/vehicles", json={"contact_idempotency_key": _key("c"), "asset_idempotency_key": _key("a")})
    assert r.status_code == 201, r.text
    v = r.json()
    body = {"contact_id": v["contact_id"], "asset_id": v["asset_id"], "request_id": _key("vir"),
            "registration_country_code": "FR", "consent": {"external_lookup_allowed": True},
            "case_idempotency_key": _key("case")}
    body.update(identifiers or {"vin": RESOLVED_VIN})
    r = await client.post("/cases", json=body)
    assert r.status_code == 201, r.text
    return r.json()["case_id"]


async def open_parcours(client, case_id: str) -> dict:
    r = await client.post(f"/cases/{case_id}/notice-parcours")
    assert r.status_code == 200, r.text
    return r.json()


def page_client(client: httpx.AsyncClient) -> httpx.AsyncClient:
    """What PGDR's page sends since bloc 3A: the session cookie, PI's CSRF token
    (read from the <meta name="csrf-token"> PI puts in the page) and, being a
    browser, the Origin of the product."""
    return httpx.AsyncClient(transport=client._transport, base_url="http://api.test",
                             headers={"Cookie": client.headers["Cookie"], CSRF_HEADER: client.headers[CSRF_HEADER],
                                      "Origin": "http://api.test"})


async def started(client, case_id: str) -> tuple[str, httpx.AsyncClient]:
    opened = await open_parcours(client, case_id)
    assert opened["status"] == "opened", opened
    pid = opened["page"].split("p=", 1)[1]
    page = page_client(client)
    base = f"/v1/parcours/{pid}"
    assert (await page.post(base + "/vir-seen", json={})).json()["phase"] == "consent"
    assert (await page.post(base + "/consent", json={"accepted": True})).json()["consent"] is True
    return pid, page


async def propose(page, pid: str, photo: bytes, recipient: str = RECIPIENT) -> httpx.Response:
    return await page.post(f"/v1/parcours/{pid}/propositions",
                           json={"recipient_consent": recipient, "photo_base64": base64.b64encode(photo).decode()})


def pgdr_calls(pgdr, suffix: str) -> list[bytes]:
    return [body for m, path, body in pgdr.transport.calls if path.endswith(suffix)]


# -- C: photo -> proposals -> selection -> notice -> Premier Constat ------------------------------

@pytest.mark.asyncio
async def test_c_photo_proposals_selection_notice_and_premier_constat(app, pgdr, user_a):
    case_id = await case(user_a)
    opened = await open_parcours(user_a, case_id)
    assert opened["status"] == "opened" and opened["page"].startswith("/v1?p=V1-")
    # PGDR received the whitelisted identity only: no VIN, no plate, no registration data.
    (handoff,) = pgdr_calls(pgdr, "/api/v1/vir-handoff")
    sent = json.loads(handoff)
    assert sent["vehicle_identity"]["manufacturer"] == "Peugeot" and sent["resolution_status"] == "resolved"
    assert RESOLVED_VIN.encode() not in handoff and b"identifiers" not in handoff
    assert b"first_registration_date" not in handoff

    pid, page = await started(user_a, case_id)
    html = await page.get("/v1", params={"p": pid})
    assert html.status_code == 200 and 'id="screen-propositions"' in html.text
    csp = html.headers["content-security-policy"]
    assert "script-src 'sha256-" in csp and "unsafe-inline" not in csp.split("script-src")[1].split(";")[0]
    assert html.headers["cache-control"] == "no-store" and html.headers["referrer-policy"] == "no-referrer"

    state = (await page.get(f"/v1/parcours/{pid}")).json()
    assert state["propositions"]["recipient"] == RECIPIENT and state["propositions"]["fake"] is True
    catalogue = (await page.get(f"/v1/parcours/{pid}/catalogue")).json()
    assert [e["entry_id"] for e in catalogue["entries"]] == ORDER
    image = await page.get(catalogue["entries"][0]["image"].removeprefix("/api"))
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert image.headers["cache-control"] == "no-store"

    photo = photo_with_metadata(PLATE, support.VIN)
    r = (await propose(page, pid, photo)).json()
    assert r["phase"] == "propositions" and r["selection"] == [] and r["confirmed"] is False
    assert [e["entry_id"] for e in r["proposed"]["entries"]] == ["fn_red_fluid", "fn_green_lamps"]  # notice order
    # Metadata removed by PI before PGDR, the sorting context without any vehicle data.
    (relayed,) = pgdr_calls(pgdr, "/propositions")
    relayed_photo = base64.b64decode(json.loads(relayed)["photo_base64"])
    (demande,) = pgdr.seen
    for blob in (relayed, relayed_photo, demande.photo, repr(demande).encode()):
        for marker in (PLATE.encode(), support.VIN.encode(), RESOLVED_VIN.encode(), b"GPS", b"tEXt", b"Peugeot"):
            assert marker not in blob
    assert [c.entry_id for c in demande.candidats] == ORDER

    s = (await page.post(f"/v1/parcours/{pid}/selection", json={"entry_ids": ["fn_green_lamps"]})).json()
    assert s["phase"] == "confirmation"
    out = (await page.post(f"/v1/parcours/{pid}/confirm", json={"entry_ids": ["fn_green_lamps"], "confirmed": True})).json()
    assert out["phase"] == "restitution" and out["premier_constat"]
    assert [x["entry_id"] for x in out["sections"]] == ["fn_green_lamps"]
    assert out["sections"][0]["meaning"] == [{"text": GREEN_MEANING}]
    await page.aclose()


# -- D: proposals not recognised -> complete catalogue -> selection --------------------------------

@pytest.mark.asyncio
async def test_d_proposals_not_recognised_then_catalogue_then_selection(app, pgdr, user_a):
    pid, page = await started(user_a, await case(user_a))
    assert (await propose(page, pid, photo_with_metadata(PLATE, support.VIN))).json()["phase"] == "propositions"
    assert (await page.post(f"/v1/parcours/{pid}/return", json={})).json()["phase"] == "catalogue"
    c = (await page.get(f"/v1/parcours/{pid}/catalogue")).json()
    assert [e["entry_id"] for e in c["entries"]] == ORDER and c["selection"] == []
    await page.post(f"/v1/parcours/{pid}/selection", json={"entry_ids": ["fn_amber_sensor"]})
    out = (await page.post(f"/v1/parcours/{pid}/confirm", json={"entry_ids": ["fn_amber_sensor"], "confirmed": True})).json()
    assert [x["entry_id"] for x in out["sections"]] == ["fn_amber_sensor"]
    await page.aclose()


# -- E: sorting absent, failing or invalid -> explained catalogue ---------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("sorter,repli", [
    (None, "non_configure"),
    (fake_sorter(panne=True), "panne"),
    (fake_sorter(raw=json.dumps({"proposed_entry_ids": ["fn_red_fluid"], "score": 0.98})), "reponse_invalide"),
    (fake_sorter(ORDER), "reponse_invalide"),                       # 4 images: never more than 3
    (fake_sorter(["fn_not_in_this_notice"]), "reponse_invalide"),   # outside the applicable catalogue
    (fake_sorter([]), "aucune_proposition"),
])
async def test_e_sorting_absent_failing_or_invalid_gives_the_explained_catalogue(app, pgdr, user_a, sorter, repli):
    use_sorter(sorter)
    pid, page = await started(user_a, await case(user_a))
    r = (await propose(page, pid, photo_with_metadata(PLATE, support.VIN))).json()
    assert (r["phase"], r["proposed"], r["repli"]["key"]) == ("catalogue", None, repli)
    assert r["repli"]["explanation"] == vc.DRAFT_LABELS["propositions.repli." + repli]
    c = (await page.get(f"/v1/parcours/{pid}/catalogue")).json()
    assert [e["entry_id"] for e in c["entries"]] == ORDER and c["repli"]["key"] == repli
    if sorter is None:
        assert pgdr.seen == [] and json.loads(pgdr_calls(pgdr, "/propositions")[0])  # nothing decoded by PGDR
    await page.aclose()


@pytest.mark.asyncio
async def test_e_a_photo_pi_cannot_clean_is_never_forwarded(app, pgdr, user_a):
    pid, page = await started(user_a, await case(user_a))
    gif = b"GIF89a" + PLATE.encode()
    r = (await propose(page, pid, gif)).json()
    assert r["repli"]["key"] == "photo_refusee" and pgdr.seen == []
    (relayed,) = pgdr_calls(pgdr, "/propositions")
    assert json.loads(relayed)["photo_base64"] == "" and PLATE.encode() not in relayed
    await page.aclose()


# -- F: no image recognised -> existing safety outcome ---------------------------------------------

@pytest.mark.asyncio
async def test_f_no_image_recognised_keeps_the_existing_safety_outcome(app, pgdr, user_a):
    pid, page = await started(user_a, await case(user_a))
    await propose(page, pid, photo_with_metadata(PLATE, support.VIN))
    await page.post(f"/v1/parcours/{pid}/return", json={})
    r = (await page.post(f"/v1/parcours/{pid}/no-match", json={"reason": "none_match"})).json()
    assert r["phase"] == "colour"
    red = (await page.post(f"/v1/parcours/{pid}/colour", json={"colour": "rouge"})).json()
    assert red["screen"]["key"] == "red_or_uncertain"
    assert red["screen"]["heading"] == v1.load_fallback_screens()["screens"]["red_or_uncertain"]["heading"]
    await page.aclose()


# -- G: insufficient identity or notice -> appropriate refusal ---------------------------------------

@pytest.mark.asyncio
async def test_g_provisional_identity_is_refused_and_no_notice_is_assumed(app, pgdr, user_a):
    r = await open_parcours(user_a, await case(user_a, vin=PROVISIONAL_VIN))
    assert (r["status"], r["page"], r["message"]) == (
        "vehicle_identity_insufficient", None, "L'identité du véhicule n'est pas établie par VIR.")
    # Passe provenance: PGDR now also says which key is missing and the next useful action.
    assert any("n'est pas connu" in x for x in r["reasons"]) and r["next_action"]
    # Clôture PGDR V1: no notice parcours; only the owner's parcours without notice, for the safety instructions.
    assert notice_parcours_opened() == [] and len(app.state.notice_registry) == 1
    assert r["safety_page"] == f"/v1?p={next(iter(v1._parcours))}"


@pytest.mark.asyncio
@pytest.mark.parametrize("setup,status", [
    (lambda p: use_notice(p, {"manufacturer": "Peugeot", "model": "208", "generation": "II"}), "vehicle_not_supported"),
    (lambda p: use_notice(p, SIMULATED_VEHICLE, applicability_established=False), "applicability_not_confirmed"),
    (lambda p: setattr(v1, "_wiring", v1.V1Wiring(repository=None, tri=v1._wiring.tri)), "notice_unavailable"),
])
async def test_g_notice_insufficient_is_refused(app, pgdr, user_a, setup, status):
    setup(pgdr)
    r = await open_parcours(user_a, await case(user_a))
    assert r["status"] == status and r["page"] is None and r["message"]
    # Clôture PGDR V1: no notice parcours; only the owner's parcours without notice, for the safety instructions.
    assert notice_parcours_opened() == [] and len(app.state.notice_registry) == 1
    assert r["safety_page"] == f"/v1?p={next(iter(v1._parcours))}"


@pytest.mark.asyncio
async def test_g_a_driver_confirmed_value_is_never_promoted_to_a_decode(monkeypatch, vir_store, pgdr, tmp_path):
    """Real VIR (fake provider transports) leaves the generation unknown; the
    driver confirms one that matches a notice exactly. PGDR receives it as a
    confirmed value (field_provenance, user_confirmed), never among the known
    values, and opens nothing: no notice is chosen on a confirmation alone.
    Passe provenance: refused as applicability_not_confirmed with its reason
    (bloc 3A: vehicle_identity_insufficient, the value being withheld)."""
    from vir.adapters.sqlite_persistence_adapter import SQLitePersistenceAdapter
    import vir.api.routes as vir_routes
    for name, value in support.FICTIVE_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(vir_routes, "STORE", SQLitePersistenceAdapter(str(tmp_path / "vir_real.db")))
    support.permit_real_adapters(monkeypatch.setattr)
    monkeypatch.setattr(vir_routes, "_DEFAULT_PROVIDERS", support.real_mode_providers(
        support.FakeRegCheckTransport(), support.FakeVincarioTransport()))
    application = make_app(pgdr, vir_routes.create_app(provider_mode="real"))
    use_notice(pgdr, {"manufacturer": "MARQUE-FICTIVE", "model": "MODELE-FICTIF", "generation": "G-FICTIVE"})
    client = await user(application, "npg")
    case_id = await case(client, vin=support.VIN)
    r = await client.post(f"/cases/{case_id}/vir/confirmations", json={"field_path": "generation", "value": "G-FICTIVE"})
    assert r.status_code == 200, r.text
    r = await open_parcours(client, case_id)
    assert r["status"] == "applicability_not_confirmed" and r["page"] is None
    assert any("seule confirmation du conducteur" in x for x in r["reasons"])
    (handoff,) = pgdr_calls(pgdr, "/api/v1/vir-handoff")
    sent = json.loads(handoff)
    assert sent["vehicle_identity"]["generation"] is None and "generation" in sent["unresolved_fields"]
    assert sent["field_provenance"]["generation"]["status"] == "user_confirmed"
    assert support.VIN.encode() not in handoff
    assert notice_parcours_opened() == []
    await client.aclose()


# -- rights: two users, unauthenticated, CSRF, allow-list ------------------------------------------

@pytest.mark.asyncio
async def test_cross_user_refusals_match_a_missing_parcours(app, pgdr, user_a, user_b):
    case_a = await case(user_a)
    pid, page_a = await started(user_a, case_a)
    await propose(page_a, pid, photo_with_metadata(PLATE, support.VIN))
    catalogue = (await page_a.get(f"/v1/parcours/{pid}/catalogue")).json()
    asset = catalogue["entries"][0]["image"].removeprefix("/api")
    page_b = page_client(user_b)
    missing = "V1-" + "0" * 32
    for method, path, body in [("GET", "", None), ("GET", "/catalogue", None), ("GET", "/propositions", None),
                               ("GET", asset.split(pid, 1)[1], None),
                               ("POST", "/selection", {"entry_ids": ["fn_red_fluid"]}),
                               ("POST", "/propositions", {"recipient_consent": RECIPIENT, "photo_base64": ""}),
                               ("POST", "/confirm", {"entry_ids": ["fn_red_fluid"], "confirmed": True})]:
        for target in (pid, missing):
            r = await page_b.request(method, f"/v1/parcours/{target}{path}", json=body)
            assert (r.status_code, r.json()) == (404, UNKNOWN), (method, path, target)
            assert pid not in r.text
    # B cannot open a parcours on A's case either.
    r = await user_b.post(f"/cases/{case_a}/notice-parcours")
    assert r.status_code == 404 and "Peugeot" not in r.text
    # A's parcours is untouched by B's attempts.
    state = (await page_a.get(f"/v1/parcours/{pid}")).json()
    assert state["selection"] == [] and state["phase"] == "propositions"
    # And B's own parcours is B's alone.
    pid_b, page_b2 = await started(user_b, await case(user_b))
    assert (await page_a.get(f"/v1/parcours/{pid_b}")).status_code == 404
    for c in (page_a, page_b, page_b2):
        await c.aclose()


@pytest.mark.asyncio
async def test_unauthenticated_and_cross_site_requests_are_refused(app, pgdr, user_a):
    pid, page = await started(user_a, await case(user_a))
    anonymous = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test")
    for method, path in (("GET", "/v1"), ("GET", f"/v1/parcours/{pid}"), ("POST", f"/v1/parcours/{pid}/selection")):
        r = await anonymous.request(method, path, json={"entry_ids": ["fn_red_fluid"]} if method == "POST" else None)
        assert r.status_code == 401 and pid not in r.text
    r = await anonymous.post("/cases/" + str(uuid.uuid4()) + "/notice-parcours")
    assert r.status_code == 401
    # Opening needs PI's CSRF token like every product route.
    no_csrf = httpx.AsyncClient(transport=user_a._transport, base_url="http://api.test",
                                headers={"Cookie": user_a.headers["Cookie"]})
    assert (await no_csrf.post(f"/cases/{uuid.uuid4()}/notice-parcours")).status_code == 403
    # Relayed POSTs: PI's token and origin (tests/test_3a_csrf_relais.py), JSON only, same-origin only.
    sel = f"/v1/parcours/{pid}/selection"
    r = await page.post(sel, content=b"entry_ids=fn_red_fluid", headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 415
    r = await page.post(sel, json={"entry_ids": ["fn_red_fluid"]}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    assert (await page.get(f"/v1/parcours/{pid}")).json()["selection"] == []
    r = await page.post(sel, json={"entry_ids": ["fn_red_fluid"]}, headers={"Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200
    await anonymous.aclose()
    await no_csrf.aclose()
    await page.aclose()


@pytest.mark.asyncio
async def test_only_the_parcours_requests_of_the_page_are_relayed(app, pgdr, user_a):
    pid, page = await started(user_a, await case(user_a))
    before = len(pgdr.transport.calls)
    for method, path in (("GET", "/asset/not-a-digest"), ("POST", "/photo"), ("POST", "/media"), ("GET", "/selection"),
                         ("GET", "/catalogue/extra"), ("POST", "/asset/" + "a" * 64), ("POST", "/%2e%2e/%2e%2e/vir-handoff")):
        r = await page.request(method, f"/v1/parcours/{pid}{path}", json={} if method == "POST" else None)
        assert (r.status_code, r.json()) == (404, UNKNOWN), path
    # A dot-segment path is resolved before PI: it is no relay route at all.
    assert (await page.post(f"/v1/parcours/{pid}/../../vir-handoff", json={})).status_code == 404
    assert len(pgdr.transport.calls) == before   # nothing reached PGDR
    assert (await page.get("/v1/essai-dev")).status_code in (404, 405)
    await page.aclose()


@pytest.mark.asyncio
async def test_oversized_relayed_body_is_refused_before_pgdr(monkeypatch, app, pgdr, user_a):
    monkeypatch.setattr(parcours_routes, "MAX_RELAY_BODY", 1000)
    pid, page = await started(user_a, await case(user_a))
    before = len(pgdr.transport.calls)
    r = await propose(page, pid, bytes(2000))
    assert r.status_code == 413 and len(pgdr.transport.calls) == before
    await page.aclose()


# -- PGDR unavailable, logs and errors ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_pgdr_unavailable_is_a_plain_technical_failure(vir_store, pgdr):
    import vir.api.routes as vir_routes
    application = make_app(pgdr, vir_routes.app, pgdr_transport=DownTransport())
    client = await user(application, "npd")
    case_id = await case(client)
    r = await client.post(f"/cases/{case_id}/notice-parcours")
    assert r.status_code == 502 and r.json() == {"error_category": "PGDR_TECHNICAL_FAILURE",
                                                 "message": "PGDR notice service unavailable"}
    application.state.notice_registry.put("V1-" + "1" * 32, parcours_routes.ParcoursOwner(
        case_id=uuid.UUID(case_id), contact_id=uuid.UUID(client.login["contact_id"])))
    page = page_client(client)
    for path in ("/v1", "/v1/parcours/V1-" + "1" * 32):
        r = await page.get(path)
        assert r.status_code == 502 and r.json()["detail"] == "Service des notices indisponible."
        assert "pgdr.test" not in r.text and TOKEN not in r.text
    await page.aclose()
    await client.aclose()


@pytest.mark.asyncio
async def test_no_photo_identifier_token_or_password_in_logs_or_errors(app, pgdr, user_a, user_b, caplog):
    caplog.set_level(logging.DEBUG)
    photo = photo_with_metadata(PLATE, support.VIN)
    pid, page = await started(user_a, await case(user_a))
    bodies = [(await propose(page, pid, photo)).text]
    use_sorter(fake_sorter(panne=True))
    bodies.append((await propose(page, pid, photo)).text)
    bodies.append((await propose(page, pid, photo, recipient="other")).text)
    bodies.append((await page_client(user_b).get(f"/v1/parcours/{pid}/catalogue")).text)
    text = caplog.text + "".join(bodies)
    for secret in (PLATE, support.VIN, RESOLVED_VIN, TOKEN, base64.b64encode(photo).decode()[:40], "GPS",
                   "panne simulée", user_a.headers[CSRF_HEADER], user_a.headers["Cookie"].split("=", 1)[1]):
        assert secret not in text, secret
    await page.aclose()


# -- single public entry point (production) ----------------------------------------------------------

@pytest.mark.asyncio
async def test_production_entry_serves_the_page_under_api_with_its_own_script_hash_csp(monkeypatch, app, pgdr, tmp_path):
    from starlette.routing import Mount
    from product_integration.api.production import create_production_app
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><div id=root></div>")
    monkeypatch.delenv("PI_COOKIE_SECURE", raising=False)
    public = create_production_app(frontend_dist=str(dist))
    inner = next(r.app for r in public.routes if isinstance(r, Mount) and r.path == "/api")
    inner.dependency_overrides.update(app.dependency_overrides)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=public), base_url="https://app.test/api") as api:
        await log_in(api, *new_account("npprod"))
        case_id = await case(api)
        opened = await open_parcours(api, case_id)
        page = await api.get(opened["page"])
        assert page.status_code == 200 and 'id="screen-propositions"' in page.text
        csp = page.headers["content-security-policy"]
        assert "script-src 'sha256-" in csp and "script-src 'self'" not in csp
        assert page.headers["x-frame-options"] == "DENY"
        pid = opened["page"].split("p=", 1)[1]
        assert (await api.get(f"/v1/parcours/{pid}/catalogue")).status_code == 403   # PGDR: consent first
        api.headers["Origin"] = "https://app.test"   # the page's writes: PI's token and the product origin
        await api.post(f"/v1/parcours/{pid}/vir-seen", json={})
        await api.post(f"/v1/parcours/{pid}/consent", json={"accepted": True})
        r = await api.get(f"/v1/parcours/{pid}/catalogue")   # what the page calls: /api/v1/parcours/...
        assert r.status_code == 200 and r.json()["entries"][0]["image"].startswith(f"/api/v1/parcours/{pid}/asset/")
