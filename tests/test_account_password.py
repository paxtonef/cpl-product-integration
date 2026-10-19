"""PI accounts: password change by the signed-in user, operator reset, and
sign-in throttling per account AND per origin. HTTP only for the web paths,
the operator command for the reset; real PostgreSQL, real VIR (ASGI) and
real PGDR behind the product routes; fictitious accounts and vehicles.

Identity must survive a password change or reset: same CPL Account and
Contact ids, account never disabled nor recreated, every object (vehicle,
case, history, media) still reachable. Knowing a login must not be enough to
lock its owner out from another origin; password guessing stays limited.
"""
from __future__ import annotations

import io
import logging
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.db.engine import SessionLocal

from product_integration.api.app import create_app
from product_integration.api.deps import get_media_storage, get_vir_client
from product_integration.auth import accounts, cli
from product_integration.media.storage import LocalMediaStorage
from product_integration.vir.client import VIRClient

from tests.auth_support import CSRF_HEADER, SESSION_COOKIE, log_in, new_account, session_cookie

JPEG = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffdb004300" + "10" * 61 + "ffd9")
NEW_PASSWORD = "fictive-new-password-" + uuid.uuid4().hex[:8]


@pytest.fixture
def vir_isolated_store(tmp_path):
    from vir.adapters.sqlite_persistence_adapter import SQLitePersistenceAdapter
    import vir.api.routes as vir_routes
    store = SQLitePersistenceAdapter(str(tmp_path / "password_test_vir.db"))
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


def _origin() -> str:
    """A fresh private address per call, so tests never share an origin counter."""
    n = uuid.uuid4().int
    return f"10.{n % 250}.{(n >> 8) % 250}.{(n >> 16) % 250 + 1}"


def _client(app, origin: str | None = None) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, client=(origin or _origin(), 40000))
    return httpx.AsyncClient(transport=transport, base_url="http://api.test")


@pytest_asyncio.fixture
async def user(app):
    login, password = new_account("pwd")
    async with _client(app) as client:
        client.identity = await log_in(client, login, password)
        client.login, client.password = login, password
        yield client


async def _change(client, current: str, new: str) -> httpx.Response:
    return await client.post("/auth/password", json={"current_password": current, "new_password": new})


async def _login(app, login: str, password: str, origin: str | None = None) -> httpx.Response:
    async with _client(app, origin) as client:
        return await client.post("/auth/login", json={"login": login, "password": password})


def _identity_rows(account_id: str) -> dict:
    with SessionLocal() as s:
        account = s.execute(text(
            "SELECT account_id, contact_id, auth_provider, provider_subject_id, account_status, disabled_at, created_at "
            "FROM cpl.accounts WHERE account_id = :a"), {"a": account_id}).mappings().one()
        contact = s.execute(text("SELECT contact_id, display_name, created_at FROM cpl.contacts WHERE contact_id = :c"),
                            {"c": account["contact_id"]}).mappings().one()
        relationships = s.execute(text(
            "SELECT relationship_id, asset_id, relationship_status FROM cpl.contact_asset_relationships "
            "WHERE contact_id = :c ORDER BY relationship_id"), {"c": account["contact_id"]}).mappings().all()
        media = s.execute(text("SELECT media_id FROM pi_auth.media_ownership WHERE contact_id = :c ORDER BY media_id"),
                          {"c": account["contact_id"]}).scalars().all()
        credentials = s.execute(text("SELECT count(*) FROM pi_auth.credentials WHERE account_id = :a"),
                                {"a": account_id}).scalar()
    return {"account": dict(account), "contact": dict(contact), "relationships": [dict(r) for r in relationships],
            "media": list(media), "credentials": credentials}


def _password_hash(account_id: str) -> str:
    with SessionLocal() as s:
        return s.execute(text("SELECT password_hash FROM pi_auth.credentials WHERE account_id = :a"),
                         {"a": account_id}).scalar()


def _session_count(account_id: str) -> int:
    with SessionLocal() as s:
        return s.execute(text("SELECT count(*) FROM pi_auth.web_sessions WHERE account_id = :a"),
                         {"a": account_id}).scalar()


async def _objects(client) -> dict:
    """A vehicle, a VIR case, a media and a diagnostic using that media."""
    r = await client.post("/vehicles", json={"contact_idempotency_key": f"c-{uuid.uuid4().hex[:10]}",
                                             "asset_idempotency_key": f"a-{uuid.uuid4().hex[:10]}"})
    assert r.status_code == 201, r.text
    vehicle = r.json()
    r = await client.post("/cases", json={
        "contact_id": vehicle["contact_id"], "asset_id": vehicle["asset_id"], "request_id": f"vir-{uuid.uuid4().hex[:10]}",
        "vin": "VF3XXXXXXXXXXXXXX", "registration_country_code": "FR", "consent": {"external_lookup_allowed": True},
        "case_idempotency_key": f"case-{uuid.uuid4().hex[:10]}",
    })
    assert r.status_code == 201, r.text
    case = r.json()
    r = await client.post("/media", files={"file": ("dashboard.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 201, r.text
    return {"vehicle": vehicle, "case": case, "media_id": r.json()["media_id"]}


# -- change by the signed-in user ----------------------------------------------------

class TestPasswordChange:

    async def test_identity_and_objects_survive_and_every_session_is_revoked(self, app, user):
        account_id = user.identity["account_id"]
        objects = await _objects(user)
        before = _identity_rows(account_id)
        async with _client(app) as second:          # another session of the same user
            await log_in(second, user.login, user.password)
            assert _session_count(account_id) == 2

            r = await _change(user, user.password, NEW_PASSWORD)
            assert r.status_code == 204, r.text
            assert session_cookie(r) is None
            assert any(h.startswith(f"{SESSION_COOKIE}=") and "max-age=0" in h.lower()
                       for h in r.headers.get_list("set-cookie"))

            assert _session_count(account_id) == 0
            assert (await user.get("/cases")).status_code == 401
            assert (await second.get("/cases")).status_code == 401

        assert (await _login(app, user.login, user.password)).status_code == 401      # old password refused
        async with _client(app) as again:
            identity = await log_in(again, user.login, NEW_PASSWORD)
            assert (identity["account_id"], identity["contact_id"]) == (account_id, user.identity["contact_id"])
            assert _identity_rows(account_id) == before   # same Account, Contact, relationships, media, one credential
            case_id = objects["case"]["case_id"]
            listed = (await again.get("/cases")).json()["cases"]
            assert [c["case_id"] for c in listed] == [case_id]
            assert (await again.get(f"/cases/{case_id}")).status_code == 200
            history = await again.get(f"/cases/{case_id}/history")
            assert history.status_code == 200 and history.json()["executions"]
            r = await again.post(f"/cases/{case_id}/diagnostics", json={
                "primary_diagnostic_media_reference": objects["media_id"],
                "consent_media_analysis_allowed": True})
            assert r.status_code in (200, 201), r.text   # the uploaded media is still this user's

    async def test_wrong_current_password_changes_nothing(self, app, user):
        account_id = user.identity["account_id"]
        stored = _password_hash(account_id)
        r = await _change(user, "not-the-current-password", NEW_PASSWORD)
        assert r.status_code == 400
        assert r.json()["error_category"] == "PASSWORD_CHANGE_REFUSED"
        assert NEW_PASSWORD not in r.text and "not-the-current-password" not in r.text
        assert _password_hash(account_id) == stored
        assert (await user.get("/cases")).status_code == 200        # session kept
        assert (await _login(app, user.login, user.password)).status_code == 200

    async def test_new_password_must_satisfy_the_policy(self, app, user):
        account_id = user.identity["account_id"]
        stored = _password_hash(account_id)
        for new in ("short", user.login, user.password):
            r = await _change(user, user.password, new)
            assert r.status_code == 422, r.text
            assert r.json()["error_category"] == "PASSWORD_POLICY"
            assert new not in r.text
        assert _password_hash(account_id) == stored
        assert (await user.get("/cases")).status_code == 200

    async def test_session_and_csrf_are_required(self, app, user):
        async with _client(app) as anonymous:
            r = await _change(anonymous, user.password, NEW_PASSWORD)
            assert r.status_code == 401
        csrf = user.headers.pop(CSRF_HEADER)
        r = await _change(user, user.password, NEW_PASSWORD)
        assert r.status_code == 403 and r.json()["error_category"] == "CSRF_REJECTED"
        user.headers[CSRF_HEADER] = csrf
        assert (await _login(app, user.login, user.password)).status_code == 200

    async def test_other_user_is_not_affected(self, app, user):
        other_login, other_password = new_account("other")
        async with _client(app) as other:
            other_identity = await log_in(other, other_login, other_password)
            other_hash = _password_hash(other_identity["account_id"])
            assert (await _change(user, user.password, NEW_PASSWORD)).status_code == 204
            assert (await other.get("/cases")).status_code == 200
            assert _password_hash(other_identity["account_id"]) == other_hash
        assert (await _login(app, other_login, other_password)).status_code == 200

    async def test_a_failure_during_the_change_leaves_everything_as_it_was(self, app, user, monkeypatch):
        account_id = user.identity["account_id"]
        stored = _password_hash(account_id)

        def broken(session, account_id):
            raise RuntimeError("fictitious failure after the password update")

        monkeypatch.setattr(accounts, "_revoke_all_sessions", broken)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False,
                                                                   client=(_origin(), 40000)),
                                     base_url="http://api.test", headers=dict(user.headers)) as client:
            r = await _change(client, user.password, NEW_PASSWORD)
        assert r.status_code == 500
        assert _password_hash(account_id) == stored
        assert _session_count(account_id) == 1
        monkeypatch.undo()
        assert (await user.get("/cases")).status_code == 200
        assert (await _login(app, user.login, NEW_PASSWORD)).status_code == 401

    async def test_no_secret_nor_login_in_logs_or_answers(self, app, user, caplog):
        caplog.set_level(logging.DEBUG)
        bad = await _change(user, "wrong-current-password", NEW_PASSWORD)
        ok = await _change(user, user.password, NEW_PASSWORD)
        assert ok.status_code == 204
        logged = "\n".join(record.getMessage() for record in caplog.records)
        for secret in (user.password, NEW_PASSWORD, "wrong-current-password", user.login):
            assert secret not in logged and secret not in bad.text and secret not in ok.text
        assert "password changed" in logged


# -- operator reset ------------------------------------------------------------------

class TestOperatorReset:

    def _reset(self, monkeypatch, login: str, password: str, *, stdin: bool) -> int:
        if stdin:
            monkeypatch.setattr("sys.stdin", io.StringIO(password + "\n"))
            return cli.main(["reset-password", "--login", login, "--password-stdin"])
        typed = iter([password, password])
        prompts = []

        def fake_getpass(prompt=""):
            prompts.append(prompt)
            return next(typed)

        monkeypatch.setattr(cli.getpass, "getpass", fake_getpass)
        code = cli.main(["reset-password", "--login", login])
        assert len(prompts) == 2       # typed twice, masked
        return code

    @pytest.mark.parametrize("stdin", [False, True])
    async def test_reset_keeps_identity_and_revokes_sessions(self, app, user, monkeypatch, caplog, stdin):
        caplog.set_level(logging.DEBUG)
        account_id = user.identity["account_id"]
        objects = await _objects(user)
        before = _identity_rows(account_id)
        assert self._reset(monkeypatch, user.login, NEW_PASSWORD, stdin=stdin) == 0
        assert _session_count(account_id) == 0
        assert (await user.get("/cases")).status_code == 401
        assert (await _login(app, user.login, user.password)).status_code == 401
        async with _client(app) as again:
            identity = await log_in(again, user.login, NEW_PASSWORD)
            assert identity["account_id"] == account_id and identity["contact_id"] == user.identity["contact_id"]
            assert (await again.get(f"/cases/{objects['case']['case_id']}")).status_code == 200
        assert _identity_rows(account_id) == before
        logged = "\n".join(record.getMessage() for record in caplog.records)
        assert "password reset" in logged
        assert NEW_PASSWORD not in logged and user.password not in logged and user.login not in logged

    def test_the_command_writes_its_audit_line_without_any_secret(self):
        """The command run as the operator runs it (its own process): the
        reset leaves an audit line on standard error, with the account id
        only -- no password, no login."""
        import os
        import subprocess
        import sys
        login, password = new_account("audit")
        done = subprocess.run([sys.executable, "-m", "product_integration.auth.cli", "reset-password", "--login", login,
                               "--password-stdin"], input=NEW_PASSWORD + "\n", capture_output=True, text=True,
                              env=dict(os.environ), timeout=120)
        assert done.returncode == 0, done.stderr
        assert "password reset by the operator account_id=" in done.stderr
        for secret in (NEW_PASSWORD, password, login):
            assert secret not in done.stderr and secret not in done.stdout

    def test_password_is_never_a_command_line_argument(self, monkeypatch):
        with pytest.raises(SystemExit):
            cli.main(["reset-password", "--login", "someone", "--password", "fictive-arg-password"])

    def test_reset_of_unknown_login_or_bad_password_changes_nothing(self, monkeypatch, capsys):
        login, password = new_account("reset")
        with SessionLocal() as s:
            account_id = s.execute(text("SELECT account_id FROM pi_auth.credentials WHERE login = :l"),
                                   {"l": login}).scalar()
        stored = _password_hash(account_id)
        assert self._reset(monkeypatch, "nobody-" + uuid.uuid4().hex[:8], NEW_PASSWORD, stdin=True) == 2
        assert self._reset(monkeypatch, login, "short", stdin=True) == 2
        assert _password_hash(account_id) == stored
        err = capsys.readouterr().err
        assert "short" not in err and NEW_PASSWORD not in err


# -- throttling per account and per origin -----------------------------------------------

class TestSignInThrottling:

    async def test_failures_from_one_origin_do_not_lock_the_owner_elsewhere(self, app):
        login, password = new_account("victim")
        attacker = _origin()
        for _ in range(accounts.MAX_FAILED_ATTEMPTS + 3):
            assert (await _login(app, login, "guess-" + uuid.uuid4().hex[:8], attacker)).status_code == 401
        # the guessing origin is stopped, even with the right password ...
        assert (await _login(app, login, password, attacker)).status_code == 401
        # ... the owner, from their own origin, is not
        assert (await _login(app, login, password, _origin())).status_code == 200

    async def test_one_origin_guessing_many_logins_is_stopped(self, app):
        login, password = new_account("spray")
        sprayer = _origin()
        for _ in range(accounts.ORIGIN_MAX_FAILURES):
            await _login(app, f"nobody-{uuid.uuid4().hex[:8]}", "guess-password-123", sprayer)
        assert (await _login(app, login, password, sprayer)).status_code == 401
        assert (await _login(app, login, password, _origin())).status_code == 200

    async def test_distributed_guessing_of_one_account_is_still_limited(self, app):
        login, password = new_account("distributed")
        per_origin = accounts.MAX_FAILED_ATTEMPTS - 1          # never enough to lock any single origin
        origins = -(-accounts.ACCOUNT_MAX_FAILURES // per_origin)
        for _ in range(origins):
            origin = _origin()
            for _ in range(per_origin):
                await _login(app, login, "guess-" + uuid.uuid4().hex[:8], origin)
        assert (await _login(app, login, password, _origin())).status_code == 401
        # temporary only: once the lock has elapsed, the owner signs in again
        with SessionLocal() as s:
            s.execute(text("UPDATE pi_auth.login_throttle SET locked_until = now() - interval '1 second', "
                           "window_started_at = now() - interval '1 day'"))
            s.commit()
        assert (await _login(app, login, password, _origin())).status_code == 200

    async def test_unknown_and_known_logins_still_answer_identically(self, app):
        login, _ = new_account("same")
        origin = _origin()
        wrong = await _login(app, login, "not-the-password-123", origin)
        unknown = await _login(app, f"nobody-{uuid.uuid4().hex[:8]}", "not-the-password-123", origin)
        assert wrong.status_code == unknown.status_code == 401 and wrong.json() == unknown.json()

    async def test_wrong_current_passwords_are_throttled_too(self, app, user):
        for _ in range(accounts.MAX_FAILED_ATTEMPTS):
            await _change(user, "guess-" + uuid.uuid4().hex[:8], NEW_PASSWORD)
        r = await _change(user, user.password, NEW_PASSWORD)
        assert r.status_code == 400 and r.json()["error_category"] == "PASSWORD_CHANGE_REFUSED"
        assert (await _login(app, user.login, user.password)).status_code == 200   # another origin: unaffected

    async def test_successful_sign_in_from_an_origin_clears_its_own_failures(self, app):
        login, password = new_account("clear")
        origin = _origin()
        for _ in range(accounts.MAX_FAILED_ATTEMPTS - 1):
            await _login(app, login, "guess-" + uuid.uuid4().hex[:8], origin)
        assert (await _login(app, login, password, origin)).status_code == 200
        for _ in range(accounts.MAX_FAILED_ATTEMPTS - 1):
            await _login(app, login, "guess-" + uuid.uuid4().hex[:8], origin)
        assert (await _login(app, login, password, origin)).status_code == 200

    async def test_throttle_rows_hold_no_login_nor_address(self, app):
        login, _ = new_account("stored")
        origin = _origin()
        await _login(app, login, "guess-password-123", origin)
        with SessionLocal() as s:
            rows = s.execute(text("SELECT scope, subject_hash, origin_hash FROM pi_auth.login_throttle")).all()
        assert rows
        dumped = repr(rows)
        assert login not in dumped and origin not in dumped
        assert all(len(h) in (0, 64) for row in rows for h in (row.subject_hash, row.origin_hash))
