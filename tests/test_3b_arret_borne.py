"""Bloc 3B — stopping the production launch is bounded, whatever the clients.

Found during the 3B installation check: with one idle TLS keep-alive
connection left open by a client, SIGTERM took 30 s (the TLS close waits for
the client's close_notify), beyond the 20 s the service unit gives before
SIGKILL. The services now get a graceful-shutdown bound below the unit's stop
timeout. The real scripts/lancer_montage.sh in production mode, a FICTIVE
notice, loopback only.
"""
from __future__ import annotations

import re
import time

import httpx

from tests.test_3a_lancement_reel import REPO, Montage

UNIT = REPO / "deploy" / "systemd" / "cpl-produit.service"


def unit_stop_timeout() -> int:
    return int(re.search(r"^TimeoutStopSec=(\d+)$", UNIT.read_text(), re.M).group(1))


def test_stop_with_an_idle_tls_connection_ends_within_the_units_stop_timeout(tmp_path):
    m = Montage(tmp_path)
    m.start()
    idle = httpx.Client(base_url=m.base, verify=False, timeout=30)
    try:
        assert idle.get("/health").status_code == 200       # keep-alive connection, then left idle
        started = time.monotonic()
        m.stop()
        elapsed = time.monotonic() - started
    finally:
        idle.close()
    assert elapsed < unit_stop_timeout() - 2, f"stop took {elapsed:.1f} s"
    assert m.proc.returncode is not None


def test_a_restart_keeps_the_previous_logs_audit_lines_included(tmp_path):
    """Found during the 3B retention check: each start truncated pi05.log, pgdr.log and vir.log, so a restart
    (systemd Restart=on-failure included) erased the password audit lines and the trace of the failure."""
    import secrets
    import uuid

    from product_integration.auth import accounts

    m = Montage(tmp_path)
    m.start()
    login, password = f"journal-{uuid.uuid4().hex[:8]}", "fictive-" + secrets.token_urlsafe(12)
    account_id = accounts.create_account(login, password)
    with httpx.Client(base_url=m.base + "/api", verify=False, timeout=30) as c:
        r = c.post("/auth/login", json={"login": login, "password": password})
        c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        assert c.post("/auth/password", json={"current_password": "wrong-current-pw",
                                              "new_password": "fictive-new-" + uuid.uuid4().hex}).status_code == 400
    time.sleep(0.5)
    line = f"operation=password_change result=refused actor=account:{account_id}"
    assert line in m.logs()["pi05.log"]
    m.stop()
    m.start()
    try:
        logs = m.logs()
        assert line in logs["pi05.log"]                                     # still there after the restart
        assert logs["pgdr.log"].count("Application startup complete") == 2
        assert (m.dir / "vir.log").read_text().count("Application startup complete") == 2
    finally:
        m.stop()
