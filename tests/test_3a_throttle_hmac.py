"""Bloc 3A, point 2 — sign-in throttling counters keyed by HMAC with a server
secret given at run time (PI_LOGIN_THROTTLE_SECRET), never a bare SHA-256
of a login or an address.

The secret is in no file of the repository and in no log. Rotation: the
former secret, while still given (PI_LOGIN_THROTTLE_SECRET_PREVIOUS), keeps
its locks in force; it is never written with; once it is withdrawn its
counters no longer apply and are purged when their window and lock are
over. A rotation never locks anyone. Limits per (login, origin), per origin
and per login unchanged; a third party knowing a login does not lock its
owner out from another origin. Real PostgreSQL, fictitious accounts.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import subprocess
import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from app.db.engine import SessionLocal

from product_integration.api.app import create_app
from product_integration.auth import accounts

from tests.auth_support import new_account

REPO = Path(__file__).resolve().parents[1]


def _origin() -> str:
    n = uuid.uuid4().int
    return f"10.{n % 250}.{(n >> 8) % 250}.{(n >> 16) % 250 + 1}"


async def _login(app, login: str, password: str, origin: str) -> int:
    transport = httpx.ASGITransport(app=app, client=(origin, 40000))
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as c:
        return (await c.post("/auth/login", json={"login": login, "password": password})).status_code


def _hmac(secret: str, kind: str, value: str) -> str:
    return hmac.new(secret.encode(), f"pi-throttle-{kind}:{value}".encode(), hashlib.sha256).hexdigest()


def _rows(subject: str) -> list:
    with SessionLocal() as s:
        return s.execute(text("SELECT scope, subject_hash, origin_hash, locked_until FROM pi_auth.login_throttle "
                              "WHERE subject_hash = :h"), {"h": subject}).all()


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def secret(monkeypatch) -> str:
    value = secrets.token_hex(32)
    monkeypatch.setenv("PI_LOGIN_THROTTLE_SECRET", value)
    monkeypatch.delenv("PI_LOGIN_THROTTLE_SECRET_PREVIOUS", raising=False)
    return value


async def test_counters_are_hmac_of_the_runtime_secret_not_bare_sha256(app, secret):
    login, _ = new_account("hmac")
    origin = _origin()
    assert await _login(app, login, "guess-password-123", origin) == 401
    rows = _rows(_hmac(secret, "login", login))
    assert {r.scope for r in rows} == {"login_origin", "login"}
    assert {r.origin_hash for r in rows if r.scope == "login_origin"} == {_hmac(secret, "origin", origin)}
    bare = hashlib.sha256(f"pi-throttle-login:{login}".encode()).hexdigest()
    assert _rows(bare) == []


async def test_without_the_secret_no_counter_is_computed(app, monkeypatch):
    monkeypatch.delenv("PI_LOGIN_THROTTLE_SECRET", raising=False)
    with pytest.raises(accounts.ThrottleSecretMissing):
        accounts.authenticate("anyone-" + uuid.uuid4().hex[:6], "guess-password-123", _origin())
    monkeypatch.setenv("PI_LOGIN_THROTTLE_SECRET", "too-short")
    with pytest.raises(accounts.ThrottleSecretMissing):
        accounts.authenticate("anyone-" + uuid.uuid4().hex[:6], "guess-password-123", _origin())


def test_production_entry_refuses_to_start_without_the_secret(monkeypatch, tmp_path):
    from product_integration.api.production import create_production_app
    (tmp_path / "index.html").write_text("<!doctype html>")
    monkeypatch.delenv("PI_COOKIE_SECURE", raising=False)
    monkeypatch.delenv("PI_LOGIN_THROTTLE_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="PI_LOGIN_THROTTLE_SECRET"):
        create_production_app(frontend_dist=str(tmp_path))


async def test_rotation_keeps_locks_never_locks_anyone_and_old_counters_expire(app, secret, monkeypatch):
    login, password = new_account("rotate")
    attacker = _origin()
    for _ in range(accounts.MAX_FAILED_ATTEMPTS):
        await _login(app, login, "guess-" + uuid.uuid4().hex[:8], attacker)
    assert await _login(app, login, password, attacker) == 401                 # locked for that origin

    new = secrets.token_hex(32)
    monkeypatch.setenv("PI_LOGIN_THROTTLE_SECRET", new)
    monkeypatch.setenv("PI_LOGIN_THROTTLE_SECRET_PREVIOUS", secret)
    assert await _login(app, login, password, attacker) == 401                 # the former lock still holds
    assert await _login(app, login, password, _origin()) == 200                # the owner, elsewhere, is not locked
    other, other_password = new_account("rotate-other")
    assert await _login(app, other, other_password, _origin()) == 200          # nobody is locked by a rotation
    await _login(app, login, "guess-after-rotation", _origin())
    assert _rows(_hmac(new, "login", login)) and _rows(_hmac(secret, "login", login))   # never written with the former

    monkeypatch.delenv("PI_LOGIN_THROTTLE_SECRET_PREVIOUS")
    assert await _login(app, login, password, attacker) == 200                 # former counters no longer apply
    with SessionLocal() as s:                                                  # their window and lock are over ...
        s.execute(text("UPDATE pi_auth.login_throttle SET window_started_at = now() - interval '1 hour', "
                       "locked_until = now() - interval '1 second' WHERE subject_hash = :h"),
                  {"h": _hmac(secret, "login", login)})
        s.commit()
    accounts.purge_expired_sessions()
    assert _rows(_hmac(secret, "login", login)) == []                          # ... so they are purged


async def test_limits_per_login_and_per_origin_hold_under_hmac(app, secret):
    login, password = new_account("limits")
    attacker = _origin()
    for _ in range(accounts.MAX_FAILED_ATTEMPTS + 2):
        await _login(app, login, "guess-" + uuid.uuid4().hex[:8], attacker)
    assert await _login(app, login, password, attacker) == 401                 # per (login, origin)
    assert await _login(app, login, password, _origin()) == 200                # a third party does not lock the owner
    sprayer = _origin()
    for _ in range(accounts.ORIGIN_MAX_FAILURES):
        await _login(app, "nobody-" + uuid.uuid4().hex[:8], "guess-password-123", sprayer)
    other, other_password = new_account("limits-other")
    assert await _login(app, other, other_password, sprayer) == 401            # per origin
    assert await _login(app, other, other_password, _origin()) == 200


async def test_secret_never_logged_and_not_in_the_repository(app, secret, caplog):
    caplog.set_level(logging.DEBUG)
    login, password = new_account("quiet")
    await _login(app, login, "guess-password-123", _origin())
    await _login(app, login, password, _origin())
    assert secret not in caplog.text
    tracked = subprocess.run(["git", "-C", str(REPO), "grep", "-l", secret], capture_output=True, text=True)
    assert tracked.returncode == 1 and tracked.stdout == ""


def test_schema_v3_drops_the_former_sha256_counters():
    from app.db.engine import engine
    from product_integration.auth import schema
    bare = hashlib.sha256(b"pi-throttle-login:former-" + uuid.uuid4().hex.encode()).hexdigest()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM pi_auth.schema_version WHERE version >= 3"))
        conn.execute(text("INSERT INTO pi_auth.login_throttle(scope, subject_hash, origin_hash, failures) "
                          "VALUES ('login', :h, '', 3)"), {"h": bare})
        assert schema.upgrade(conn) == schema.SCHEMA_VERSION >= 3
    assert _rows(bare) == []
