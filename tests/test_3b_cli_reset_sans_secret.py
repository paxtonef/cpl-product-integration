"""Bloc 3B — the operator reset run without the service's throttling secret.

Found during the 3B acceptance: `reset-password` run outside the service's
environment (PI_LOGIN_THROTTLE_SECRET absent) ended with a Python traceback
after the password had been typed. It now refuses before asking for the
password, with one plain line and the exit code of every refusal (2), leaves
an audit line, and changes nothing. The real command, as a subprocess.
"""
from __future__ import annotations

import os
import subprocess
import sys

from product_integration.auth import accounts

from tests.auth_support import new_account


def run(args: list[str], password: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "product_integration.auth.cli", *args], input=password + "\n",
                          capture_output=True, text=True, env=env, timeout=120)


def test_reset_without_the_secret_is_refused_plainly_and_changes_nothing():
    login, password = new_account("nosecret")
    env = {k: v for k, v in os.environ.items() if not k.startswith("PI_LOGIN_THROTTLE_SECRET")}
    new = "fictive-reset-" + os.urandom(6).hex()
    out = run(["reset-password", "--login", login, "--password-stdin"], new, env)
    assert out.returncode == 2, out.stderr
    assert "Traceback" not in out.stderr and "refused: PI_LOGIN_THROTTLE_SECRET" in out.stderr
    assert "operation=password_reset result=refused_config actor=operator target=-" in out.stderr
    for secret in (new, login, password):
        assert secret not in out.stderr + out.stdout
    assert accounts.authenticate(login, password) is not None          # unchanged
    assert accounts.authenticate(login, new) is None


def test_purge_sessions_needs_no_secret():
    env = {k: v for k, v in os.environ.items() if not k.startswith("PI_LOGIN_THROTTLE_SECRET")}
    out = run(["purge-sessions"], "", env)
    assert out.returncode == 0 and "expired sessions removed:" in out.stdout and "Traceback" not in out.stderr
