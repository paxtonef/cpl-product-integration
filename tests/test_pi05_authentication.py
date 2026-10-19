"""PI-05 end-user authentication and per-owner isolation (preparation for
production, block 3). HTTP only, real VIR (ASGI), real PGDR, real
PostgreSQL; fictitious accounts, plates and VINs.

Two users, A and B. Every object type A can reach (contact, vehicle, case,
history, execution, artifact, diagnostic, clarification, media) is probed
by B, and B's answer must be byte-identical to the answer for an object
that does not exist.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.db.engine import SessionLocal

from product_integration.api.app import create_app
from product_integration.api.deps import get_media_storage, get_vir_client
from product_integration.auth import accounts
from product_integration.auth.passwords import PasswordPolicyError
from product_integration.media.storage import LocalMediaStorage
from product_integration.vir.client import VIRClient

from tests.auth_support import CSRF_HEADER, SESSION_COOKIE, log_in, new_account, session_cookie

NOISE_COMPLAINT = "The engine makes a strange noise when accelerating."
JPEG = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffdb004300" + "10" * 61 + "ffd9")
MISSING = "00000000-0000-4000-8000-000000000000"


@pytest.fixture
def vir_isolated_store(tmp_path):
    from vir.adapters.sqlite_persistence_adapter import SQLitePersistenceAdapter
    import vir.api.routes as vir_routes
    store = SQLitePersistenceAdapter(str(tmp_path / "auth_test_vir.db"))
    original = vir_routes.STORE
    vir_routes.STORE = store
    yield store
    vir_routes.STORE = original


@pytest.fixture
def app(vir_isolated_store, tmp_path):
    import vir.api.routes as vir_routes
    vir_transport = httpx.ASGITransport(app=vir_routes.app)

    async def override_vir_client():
        async with httpx.AsyncClient(transport=vir_transport, base_url="http://vir.test") as c:
            yield VIRClient(c)

    application = create_app()
    application.dependency_overrides[get_vir_client] = override_vir_client
    storage = LocalMediaStorage(tmp_path / "media")
    application.dependency_overrides[get_media_storage] = lambda: storage
    return application


@pytest_asyncio.fixture
async def anonymous(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test") as client:
        yield client


@pytest_asyncio.fixture
async def user_a(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test") as client:
        client.identity = await log_in(client, *new_account("alice"))
        yield client


@pytest_asyncio.fixture
async def user_b(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test") as client:
        client.identity = await log_in(client, *new_account("bob"))
        yield client


def _key(tag: str) -> str:
    return f"{tag}-{uuid.uuid4().hex[:10]}"


async def _vehicle(client) -> dict:
    r = await client.post("/vehicles", json={"contact_idempotency_key": _key("c"), "asset_idempotency_key": _key("a")})
    assert r.status_code == 201, r.text
    return r.json()


async def _case(client, veh, **overrides) -> dict:
    body = {
        "contact_id": veh["contact_id"], "asset_id": veh["asset_id"], "request_id": _key("vir"),
        "vin": "VF3XXXXXXXXXXXXXX", "registration_country_code": "FR",
        "consent": {"external_lookup_allowed": True}, "case_idempotency_key": _key("case"),
    }
    body.update(overrides)
    r = await client.post("/cases", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def _diagnostic(client, case_id) -> dict:
    r = await client.post(f"/cases/{case_id}/diagnostics", json={"complaint_text": NOISE_COMPLAINT})
    assert r.status_code == 201, r.text
    return r.json()


# -- authentication -----------------------------------------------------------

ALL_ROUTES = [
    ("GET", "/auth/session"), ("GET", "/me"), ("GET", "/cases"),
    ("GET", f"/contacts/{MISSING}"), ("POST", "/vehicles"), ("POST", "/cases"),
    ("POST", f"/cases/{MISSING}/vir/clarifications"), ("GET", f"/cases/{MISSING}"),
    ("GET", f"/cases/{MISSING}/history"), ("GET", f"/executions/{MISSING}"),
    ("GET", f"/executions/{MISSING}/artifact"), ("POST", "/media"),
    ("POST", f"/cases/{MISSING}/diagnostics"), ("POST", f"/cases/{MISSING}/diagnostics/{MISSING}/answers"),
    ("POST", "/auth/logout"),
]


class TestAuthentication:

    @pytest.mark.parametrize("method,path", ALL_ROUTES)
    async def test_every_route_refuses_without_session(self, anonymous, method, path):
        r = await anonymous.request(method, path, json={} if method == "POST" and path != "/media" else None)
        assert r.status_code == 401, (method, path, r.text)
        assert r.json()["error_category"] == "AUTHENTICATION_REQUIRED"

    async def test_forged_session_cookie_is_refused(self, anonymous):
        anonymous.headers["Cookie"] = f"{SESSION_COOKIE}=forged-{uuid.uuid4().hex}"
        r = await anonymous.get("/cases")
        assert r.status_code == 401

    async def test_login_sets_hardened_cookie_and_returns_only_csrf(self, anonymous):
        login, password = new_account("cookie")
        r = await anonymous.post("/auth/login", json={"login": login, "password": password})
        assert r.status_code == 200
        header = next(h for h in r.headers.get_list("set-cookie") if h.startswith(SESSION_COOKIE + "="))
        lowered = header.lower()
        assert "httponly" in lowered and "secure" in lowered and "samesite=strict" in lowered and "path=/" in lowered
        token = session_cookie(r)
        body = r.json()
        assert set(body) == {"csrf_token", "contact_id", "account_id"}
        assert token not in r.text  # the session token never reaches JavaScript
        assert r.headers.get("cache-control") == "no-store"

    async def test_wrong_password_and_unknown_login_answer_identically(self, anonymous):
        login, _ = new_account("probe")
        wrong = await anonymous.post("/auth/login", json={"login": login, "password": "not-the-password-123"})
        unknown = await anonymous.post("/auth/login", json={"login": f"nobody-{uuid.uuid4().hex[:8]}", "password": "not-the-password-123"})
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json() == unknown.json()
        assert session_cookie(wrong) is None and session_cookie(unknown) is None

    async def test_lockout_after_repeated_failures(self, anonymous):
        login, password = new_account("lock")
        for _ in range(accounts.MAX_FAILED_ATTEMPTS):
            await anonymous.post("/auth/login", json={"login": login, "password": "wrong-password-xyz"})
        r = await anonymous.post("/auth/login", json={"login": login, "password": password})
        assert r.status_code == 401

    async def test_logout_ends_the_session_server_side(self, user_a):
        cookie = user_a.headers["Cookie"]
        r = await user_a.post("/auth/logout")
        assert r.status_code == 204
        assert any("max-age=0" in h.lower() or "expires=" in h.lower() for h in r.headers.get_list("set-cookie"))
        user_a.headers["Cookie"] = cookie  # replaying the old cookie
        assert (await user_a.get("/cases")).status_code == 401

    async def test_expired_session_is_refused(self, user_a):
        with SessionLocal() as s:
            s.execute(text("UPDATE pi_auth.web_sessions SET expires_at = :t WHERE account_id = :a"),
                      {"t": datetime.now(timezone.utc) - timedelta(seconds=1), "a": user_a.identity["account_id"]})
            s.commit()
        assert (await user_a.get("/cases")).status_code == 401

    async def test_disabled_account_loses_its_sessions(self, user_a):
        with SessionLocal() as s:
            login = s.execute(text("SELECT login FROM pi_auth.credentials WHERE account_id = :a"),
                              {"a": user_a.identity["account_id"]}).scalar()
        accounts.set_account_status(login, "DISABLED")
        assert (await user_a.get("/cases")).status_code == 401

    async def test_unsafe_request_without_or_with_wrong_csrf_is_refused(self, user_a):
        csrf = user_a.headers.pop(CSRF_HEADER)
        r = await user_a.post("/vehicles", json={"contact_idempotency_key": _key("c"), "asset_idempotency_key": _key("a")})
        assert r.status_code == 403 and r.json()["error_category"] == "CSRF_REJECTED"
        user_a.headers[CSRF_HEADER] = csrf[:-1] + ("0" if csrf[-1] != "0" else "1")
        r = await user_a.post("/vehicles", json={"contact_idempotency_key": _key("c"), "asset_idempotency_key": _key("a")})
        assert r.status_code == 403
        user_a.headers[CSRF_HEADER] = csrf
        assert (await user_a.get("/auth/session")).json()["csrf_token"] == csrf  # re-served after a reload

    def test_password_policy_and_no_default_account(self):
        with pytest.raises(PasswordPolicyError):
            accounts.create_account(f"short-{uuid.uuid4().hex[:6]}", "short")
        login = f"same-{uuid.uuid4().hex[:6]}"
        with pytest.raises(PasswordPolicyError):
            accounts.create_account(login, login.upper())
        for default in ("admin", "root", "test", "demo", "user"):
            assert accounts.authenticate(default, default) is None
            assert accounts.authenticate(default, "admin") is None


# -- isolation per owner --------------------------------------------------------

class TestOwnerIsolation:

    async def test_identity_comes_from_the_session_not_the_body(self, user_a, user_b):
        veh = await _vehicle(user_a)
        assert veh["contact_id"] == user_a.identity["contact_id"]
        # B names A's contact in the body: refused like a missing contact.
        r = await user_b.post("/vehicles", json={
            "existing_contact_id": user_a.identity["contact_id"],
            "contact_idempotency_key": _key("c"), "asset_idempotency_key": _key("a"),
        })
        missing = await user_b.post("/vehicles", json={
            "existing_contact_id": MISSING, "contact_idempotency_key": _key("c"), "asset_idempotency_key": _key("a"),
        })
        assert r.status_code == missing.status_code == 404
        assert r.json() == missing.json()

    async def test_authority_headers_and_admin_name_grant_nothing(self, app, user_a):
        veh = await _vehicle(user_a)
        case = await _case(user_a, veh)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test") as admin:
            await log_in(admin, *_admin_account())
            admin.headers["X-Authority"] = "ALL"
            admin.headers["X-Actor"] = "pi05-product-api"
            r = await admin.get(f"/cases/{case['case_id']}")
            assert r.status_code == 404
            assert (await admin.get("/cases")).json()["cases"] == []

    async def test_contact_creation_is_not_a_web_operation(self, user_a):
        r = await user_a.post("/contacts", json={"idempotency_key": _key("c")})
        assert r.status_code in (404, 405)

    async def test_case_list_contains_only_own_cases(self, user_a, user_b):
        case_a = await _case(user_a, await _vehicle(user_a))
        case_b = await _case(user_b, await _vehicle(user_b))
        ids_a = {c["case_id"] for c in (await user_a.get("/cases")).json()["cases"]}
        ids_b = {c["case_id"] for c in (await user_b.get("/cases")).json()["cases"]}
        assert case_a["case_id"] in ids_a and case_a["case_id"] not in ids_b
        assert case_b["case_id"] in ids_b and case_b["case_id"] not in ids_a

    async def test_cross_user_refusals_are_indistinguishable_from_missing(self, user_a, user_b):
        veh = await _vehicle(user_a)
        case = await _case(user_a, veh)
        diag = await _diagnostic(user_a, case["case_id"])
        assert diag["outcome"] == "BLOCKED"
        c, x, a = case["case_id"], diag["execution_id"], veh["asset_id"]
        question = diag["pending_questions"][0]
        answer = {"question_id": question["question_id"], "value": (question.get("choices") or ["yes"])[0]}
        probes = [
            ("GET", "/contacts/{contact}", None),
            ("GET", "/cases/{case}", None),
            ("GET", "/cases/{case}/history", None),
            ("GET", "/executions/{execution}", None),
            ("GET", "/executions/{vir_execution}/artifact", None),
            ("GET", "/executions/{execution}/artifact", None),
            ("POST", "/cases/{case}/diagnostics", {"complaint_text": NOISE_COMPLAINT}),
            ("POST", "/cases/{case}/diagnostics/{execution}/answers", answer),
            ("POST", "/cases/{case}/vir/clarifications", {"answers": [{"question_id": "q", "value": "v"}]}),
        ]
        real = {"contact": user_a.identity["contact_id"], "case": c, "execution": x, "vir_execution": case["vir_execution_id"]}
        fake = {k: MISSING for k in real}
        for method, template, body in probes:
            foreign = await user_b.request(method, template.format(**real), json=body)
            missing = await user_b.request(method, template.format(**fake), json=body)
            assert foreign.status_code == missing.status_code == 404, (template, foreign.text)
            assert foreign.content == missing.content, template
        # starting a case on A's vehicle
        foreign = await user_b.post("/cases", json={
            "contact_id": user_b.identity["contact_id"], "asset_id": a, "request_id": _key("vir"), "vin": "VF3XXXXXXXXXXXXXX",
            "registration_country_code": "FR", "consent": {"external_lookup_allowed": True}, "case_idempotency_key": _key("case"),
        })
        missing = await user_b.post("/cases", json={
            "contact_id": user_b.identity["contact_id"], "asset_id": MISSING, "request_id": _key("vir"), "vin": "VF3XXXXXXXXXXXXXX",
            "registration_country_code": "FR", "consent": {"external_lookup_allowed": True}, "case_idempotency_key": _key("case"),
        })
        assert foreign.status_code == missing.status_code == 404
        assert foreign.content == missing.content
        # A's own objects stay reachable by A, and A's diagnostic is intact.
        assert (await user_a.get(f"/cases/{c}")).status_code == 200
        r = await user_a.post(f"/cases/{c}/diagnostics/{x}/answers", json=answer)
        assert r.status_code == 200, r.text

    async def test_media_belongs_to_its_uploader(self, user_a, user_b):
        uploaded = await user_a.post("/media", files={"file": ("dash.jpg", JPEG, "image/jpeg")})
        assert uploaded.status_code == 201
        media_id = uploaded.json()["media_id"]
        case_b = await _case(user_b, await _vehicle(user_b))
        body = lambda ref: {"primary_diagnostic_media_reference": ref, "consent_media_analysis_allowed": True}  # noqa: E731
        foreign = await user_b.post(f"/cases/{case_b['case_id']}/diagnostics", json=body(media_id))
        missing = await user_b.post(f"/cases/{case_b['case_id']}/diagnostics", json=body(uuid.uuid4().hex))
        assert foreign.status_code == missing.status_code == 404
        assert foreign.content == missing.content
        case_a = await _case(user_a, await _vehicle(user_a))
        own = await user_a.post(f"/cases/{case_a['case_id']}/diagnostics", json=body(media_id))
        assert own.status_code != 404, own.text

    async def test_client_idempotency_keys_are_scoped_per_user(self, user_a, user_b):
        """Reusing another user's idempotency keys must never replay (and so
        reveal) that user's objects."""
        keys = {"contact_idempotency_key": _key("c"), "asset_idempotency_key": _key("a")}
        veh_a = (await user_a.post("/vehicles", json=keys)).json()
        r = await user_b.post("/vehicles", json=keys)
        assert r.status_code == 201
        assert r.json()["asset_id"] != veh_a["asset_id"]
        shared = {"request_id": _key("vir"), "case_idempotency_key": _key("case")}
        case_a = await _case(user_a, veh_a, **shared)
        case_b = await _case(user_b, r.json(), **shared)
        assert case_b["case_id"] != case_a["case_id"]
        assert case_b["vir_execution_id"] != case_a["vir_execution_id"]

    async def test_cpl_records_the_authenticated_actor(self, user_a):
        case = await _case(user_a, await _vehicle(user_a))
        with SessionLocal() as s:
            actors = set(s.execute(text(
                "SELECT authority_context->>'actor_reference' FROM cpl.runner_governance_decisions WHERE execution_id = :x"
            ), {"x": case["vir_execution_id"]}).scalars())
        assert actors == {f"pi-account:{user_a.identity['account_id']}"}


def _admin_account() -> tuple[str, str]:
    login = "admin"
    password = "fictive-admin-" + uuid.uuid4().hex
    with SessionLocal() as s:
        exists = s.execute(text("SELECT 1 FROM pi_auth.credentials WHERE login = 'admin'")).first()
    if exists:
        login = f"admin-{uuid.uuid4().hex[:6]}"
    accounts.create_account(login, password)
    return login, password
