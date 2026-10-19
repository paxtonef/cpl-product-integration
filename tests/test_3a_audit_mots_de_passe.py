"""Bloc 3A, point 3 — password audit lines that are actually written.

Under uvicorn nothing configures the root logger, so an INFO record of
product_integration was dropped. The audit now has its own handler on
standard error (product_integration.audit): one line per password change by
its owner and per operator reset, success AND failure, with the date, the
operation, the result, an opaque actor and target (account id or a fixed
label) -- never a password, a token, a cookie, a login or an address.

Here: in process (records) and through the operator command (its own
process). The production launch itself is checked in
tests/test_3a_lancement_reel.py. Identity, objects, refusal of the former
password, revocation and the all-or-nothing transaction stay as tested in
tests/test_account_password.py.
"""
from __future__ import annotations

import io
import logging
import os
import re
import subprocess
import sys
import uuid

import httpx
import pytest

from product_integration.api.app import create_app
from product_integration.auth import cli

from tests.auth_support import log_in, new_account

NEW = "fictive-new-password-" + uuid.uuid4().hex[:8]
LINE = re.compile(r"audit date=\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ operation=(\S+) result=(\S+) actor=(\S+) target=(\S+)")


def audit_lines(text: str) -> list[tuple[str, str, str, str]]:
    return LINE.findall(text)


@pytest.fixture
def app():
    return create_app()


async def _user(app):
    login, password = new_account("audit")
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("10.9.8.7", 4000)), base_url="http://api.test")
    identity = await log_in(client, login, password)
    return client, login, password, identity


async def test_change_success_and_failures_are_audited_without_secrets(app, caplog):
    caplog.set_level(logging.INFO)
    client, login, password, identity = await _user(app)
    account = f"account:{identity['account_id']}"
    assert (await client.post("/auth/password", json={"current_password": "wrong-current-pw", "new_password": NEW})).status_code == 400
    assert (await client.post("/auth/password", json={"current_password": password, "new_password": "short"})).status_code == 422
    assert (await client.post("/auth/password", json={"current_password": password, "new_password": NEW})).status_code == 204
    lines = audit_lines(caplog.text)
    assert ("password_change", "refused", account, account) in lines
    assert ("password_change", "refused_policy", account, account) in lines
    assert ("password_change", "success", account, account) in lines
    for secret in (password, NEW, "wrong-current-pw", login, "10.9.8.7", client.headers["Cookie"].split("=", 1)[1],
                   client.headers["X-CSRF-Token"]):
        assert secret not in caplog.text, secret
    await client.aclose()


async def test_change_failing_inside_the_transaction_is_audited(app, caplog, monkeypatch):
    from product_integration.auth import accounts
    caplog.set_level(logging.INFO)
    client, login, password, identity = await _user(app)

    def broken(session, account_id):
        raise RuntimeError("fictitious failure " + login)

    with monkeypatch.context() as patched:
        patched.setattr(accounts, "_revoke_all_sessions", broken)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                     base_url="http://api.test", headers=dict(client.headers)) as c:
            assert (await c.post("/auth/password", json={"current_password": password, "new_password": NEW})).status_code == 500
    account = f"account:{identity['account_id']}"
    assert ("password_change", "failure", account, account) in audit_lines(caplog.text)
    assert login not in "\n".join(l for l in caplog.text.splitlines() if " audit " in l)
    await client.aclose()


def test_operator_reset_success_and_failures_are_audited_by_the_command(monkeypatch, capsys):
    login, password = new_account("audit-reset")
    monkeypatch.setattr("sys.stdin", io.StringIO(NEW + "\n"))
    assert cli.main(["reset-password", "--login", login, "--password-stdin"]) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    assert cli.main(["reset-password", "--login", login, "--password-stdin"]) == 2
    monkeypatch.setattr("sys.stdin", io.StringIO(NEW + "\n"))
    assert cli.main(["reset-password", "--login", "nobody-" + uuid.uuid4().hex[:8], "--password-stdin"]) == 2
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert cli.main(["reset-password", "--login", login, "--password-stdin"]) == 2
    err = capsys.readouterr().err
    lines = audit_lines(err)
    targets = {t for op, r, a, t in lines if op == "password_reset" and r == "success"}
    assert len(targets) == 1 and next(iter(targets)).startswith("account:")
    assert ("password_reset", "refused_policy", "operator", next(iter(targets))) in lines
    assert ("password_reset", "refused_unknown_login", "operator", "-") in lines
    assert ("password_reset", "refused_input", "operator", "-") in lines
    for secret in (NEW, password, login, "short"):
        assert secret not in err, secret


def test_operator_command_in_its_own_process_writes_one_audit_line():
    login, password = new_account("audit-proc")
    done = subprocess.run([sys.executable, "-m", "product_integration.auth.cli", "reset-password", "--login", login,
                           "--password-stdin"], input=NEW + "\n", capture_output=True, text=True,
                          env=dict(os.environ), timeout=120)
    assert done.returncode == 0, done.stderr
    lines = audit_lines(done.stderr)
    assert len(lines) == 1 and lines[0][:3] == ("password_reset", "success", "operator")
    for secret in (NEW, password, login):
        assert secret not in done.stderr and secret not in done.stdout
