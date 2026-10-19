"""Bloc 3A — the real production launch.

scripts/lancer_montage.sh in production mode -- VIR and PGDR on the loopback,
PI's single public entry point under uvicorn with TLS (self-signed test
certificate), exactly as the service unit runs it -- with the test database,
a FICTIVE notice and no sorting transport. What is read is the processes'
own output (pi05.log, pgdr.log, the operator command's standard error),
not a test log capture. Loopback only; real Chromium for the page.

  point 1  the confirmed result survives a complete restart of the assembly
           and is read without PGDR; the unfinished parcours is not resumed
  point 2  X-Forwarded-For from a peer that is not a configured proxy is not
           believed (no throttling bypass); the secret is in no output
  point 3  password change (success, failure) and operator reset (success,
           failure) leave audit lines without any secret, login or address
  point 4  the legitimate parcours runs in the browser under the HTTPS entry,
           with PI's CSRF token from the page; without it, refused
  point 5  route templates or fixed labels only, for success, refusal,
           unknown route and exception, in PI's and PGDR's outputs
"""
from __future__ import annotations

import base64
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest

import product_integration
from product_integration.auth import accounts

from tests.notice_parcours_support import SIMULATED_VEHICLE, build_notice, photo_with_metadata

REPO = Path(product_integration.__file__).resolve().parents[2]
VIN = "VF3XXXXXXXXXXXXXX"           # VIR simulated fixture: Peugeot 3008 II, resolved
PLATE = "FICTIVE-PLATE-3A-R"
NEW = "fictive-new-password-" + uuid.uuid4().hex[:8]
AUDIT = re.compile(r"audit date=\S+ operation=(\S+) result=(\S+) actor=(\S+) target=(\S+)")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Montage:
    def __init__(self, root: Path):
        self.root = root
        self.dir = root / "montage"
        self.dir.mkdir()
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=127.0.0.1",
                        "-addext", "subjectAltName=IP:127.0.0.1", "-keyout", str(root / "key.pem"),
                        "-out", str(root / "cert.pem")], check=True, capture_output=True)
        dist = root / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<!doctype html><title>produit</title><div id=root></div>")
        self.port = free_port()
        self.secret = "fictive-throttle-" + secrets.token_hex(24)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PGDR_V1_", "PI_PGDR_", "PI_COOKIE"))}
        env.update({
            "VIR_SERVICE_TOKEN": "fictive-vir-" + secrets.token_hex(8),
            "VIR_DATA_ENCRYPTION_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
            "VIR_DATABASE_PATH": str(root / "vir.db"), "VIR_PORT": str(free_port()), "PGDR_PORT": str(free_port()),
            "PGDR_IDENTITY_HANDOFF_TOKEN": "fictive-pgdr-" + secrets.token_hex(8),
            "PI_LOGIN_THROTTLE_SECRET": self.secret, "MONTAGE_DIR": str(self.dir),
            "PI_FRONTEND_DIST": str(dist), "PI_PUBLIC_HOST": "127.0.0.1", "PI_PUBLIC_PORT": str(self.port),
            "PI_TLS_CERT": str(root / "cert.pem"), "PI_TLS_KEY": str(root / "key.pem"),
            "PGDR_V1_MANIFEST": str(build_notice(root / "notice", SIMULATED_VEHICLE)),
            "PI05_MEDIA_STORAGE_DIR": str(root / "media"),
        })
        self.env = env
        self.base = f"https://127.0.0.1:{self.port}"
        self.proc = None
        self.runs: list[dict[str, str]] = []

    def start(self) -> None:
        out = open(self.root / "montage.out", "ab")
        self.proc = subprocess.Popen(["bash", str(REPO / "scripts" / "lancer_montage.sh")], env=self.env,
                                     stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
        for _ in range(240):
            if "Montage prêt" in (self.root / "montage.out").read_text(errors="replace").split("--- arrêt ---")[-1]:
                return
            if self.proc.poll() is not None:
                raise AssertionError((self.root / "montage.out").read_text())
            time.sleep(0.25)
        raise AssertionError("montage not ready")

    def stop(self) -> None:
        os.killpg(self.proc.pid, signal.SIGTERM)
        try:
            self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(self.proc.pid, signal.SIGKILL)
            self.proc.wait(timeout=10)
        with open(self.root / "montage.out", "a") as out:
            out.write("\n--- arrêt ---\n")
        self.runs.append({name: (self.dir / name).read_text(errors="replace") for name in ("pi05.log", "pgdr.log")})

    def logs(self) -> dict[str, str]:
        return {name: (self.dir / name).read_text(errors="replace") for name in ("pi05.log", "pgdr.log")}

    def all_output(self) -> str:
        current = self.logs() if self.proc and self.proc.poll() is None else {}
        return "\n".join([*(v for run in self.runs for v in run.values()), *current.values(),
                          (self.root / "montage.out").read_text(errors="replace")])

    def client(self) -> httpx.Client:
        return httpx.Client(base_url=self.base + "/api", verify=False, timeout=30)


@pytest.fixture(scope="module")
def montage(tmp_path_factory):
    m = Montage(tmp_path_factory.mktemp("lancement"))
    m.start()
    yield m
    if m.proc.poll() is None:
        m.stop()


def sign_in(client: httpx.Client, login: str, password: str) -> dict:
    r = client.post("/auth/login", json={"login": login, "password": password})
    assert r.status_code == 200, r.text
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return r.json()


def new_case(client: httpx.Client) -> str:
    v = client.post("/vehicles", json={"contact_idempotency_key": "c-" + uuid.uuid4().hex[:10],
                                       "asset_idempotency_key": "a-" + uuid.uuid4().hex[:10]}).json()
    r = client.post("/cases", json={"contact_id": v["contact_id"], "asset_id": v["asset_id"],
                                    "request_id": "vir-" + uuid.uuid4().hex[:10], "vin": VIN,
                                    "registration_country_code": "FR", "consent": {"external_lookup_allowed": True},
                                    "case_idempotency_key": "case-" + uuid.uuid4().hex[:10]})
    assert r.status_code == 201, r.text
    return r.json()["case_id"]


STATE: dict = {}


def test_point3_password_audit_under_the_production_launch(montage):
    login, password = f"reel-{uuid.uuid4().hex[:8]}", "fictive-" + secrets.token_urlsafe(12)
    account_id = str(accounts.create_account(login, password))
    with montage.client() as c:
        sign_in(c, login, password)
        cookie = c.cookies.get("pi_session")
        token = c.headers["X-CSRF-Token"]
        assert c.post("/auth/password", json={"current_password": "wrong-current-pw", "new_password": NEW}).status_code == 400
        assert c.post("/auth/password", json={"current_password": password, "new_password": NEW}).status_code == 204
    with montage.client() as c:
        assert c.post("/auth/login", json={"login": login, "password": password}).status_code == 401   # former refused
        sign_in(c, login, NEW)
    reset = "fictive-reset-" + secrets.token_urlsafe(10)
    ok = subprocess.run([sys.executable, "-m", "product_integration.auth.cli", "reset-password", "--login", login,
                         "--password-stdin"], input=reset + "\n", capture_output=True, text=True, env=montage.env, timeout=120)
    ko = subprocess.run([sys.executable, "-m", "product_integration.auth.cli", "reset-password", "--login",
                         "nobody-" + uuid.uuid4().hex[:6], "--password-stdin"], input=reset + "\n", capture_output=True,
                        text=True, env=montage.env, timeout=120)
    assert ok.returncode == 0 and ko.returncode == 2
    time.sleep(0.5)
    pi = montage.logs()["pi05.log"]
    lines = AUDIT.findall(pi)
    me = f"account:{account_id}"
    assert ("password_change", "refused", me, me) in lines and ("password_change", "success", me, me) in lines
    assert AUDIT.findall(ok.stderr) == [("password_reset", "success", "operator", me)]
    assert AUDIT.findall(ko.stderr) == [("password_reset", "refused_unknown_login", "operator", "-")]
    audit_text = "\n".join(l for l in (pi + ok.stderr + ko.stderr).splitlines() if " audit " in l)
    for secret in (password, NEW, reset, "wrong-current-pw", login, cookie, token, "127.0.0.1", montage.secret):
        assert secret not in audit_text, secret
    STATE["secrets"] = [password, NEW, reset, login, cookie, token, montage.secret]


def test_point2_forwarded_for_from_an_unconfigured_peer_is_not_believed(montage):
    login, password = f"xff-{uuid.uuid4().hex[:8]}", "fictive-" + secrets.token_urlsafe(12)
    accounts.create_account(login, password)
    with montage.client() as c:
        for i in range(accounts.MAX_FAILED_ATTEMPTS):
            r = c.post("/auth/login", json={"login": login, "password": "guess-" + uuid.uuid4().hex[:8]},
                       headers={"X-Forwarded-For": f"203.0.113.{i + 1}", "Forwarded": f"for=203.0.113.{i + 1}"})
            assert r.status_code == 401
        # Every attempt counted for the real peer: still locked, whatever address the request claims.
        r = c.post("/auth/login", json={"login": login, "password": password}, headers={"X-Forwarded-For": "198.51.100.7"})
        assert r.status_code == 401
    STATE.setdefault("secrets", []).append(password)


def test_point4_and_1_legitimate_parcours_in_the_browser_under_https(montage):
    # Playwright opened and closed here (not the session fixture: its event loop would outlive this test).
    from playwright.sync_api import sync_playwright
    login, password = f"nav-{uuid.uuid4().hex[:8]}", "fictive-" + secrets.token_urlsafe(12)
    accounts.create_account(login, password)
    with montage.client() as c:
        sign_in(c, login, password)
        case_id = new_case(c)
        opened = c.post(f"/cases/{case_id}/notice-parcours").json()
        assert opened["status"] == "opened", opened
        pid = opened["page"].split("p=", 1)[1]
        unfinished = c.post(f"/cases/{case_id}/notice-parcours").json()["page"].split("p=", 1)[1]
        cookie = c.cookies.get("pi_session")
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(ignore_https_errors=True)
            context.add_cookies([{"name": "pi_session", "value": cookie, "domain": "127.0.0.1", "path": "/",
                                  "secure": True, "httpOnly": True, "sameSite": "Strict"}])
            page = context.new_page()
            sent = []
            page.on("request", lambda r: sent.append((r.method, r.url, r.all_headers())))
            errors = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.goto(f"{montage.base}/api/v1?p={pid}")
            page.click("#vir-continue")
            page.check("#consent-box")
            page.click("#consent-continue")
            page.set_input_files("#photo-input", files=[{"name": "dash.png", "mimeType": "image/png",
                                                          "buffer": photo_with_metadata(PLATE, VIN)}])
            page.click("#photo-continue")
            page.click('#catalogue-grid .tile[data-entry-id="fn_green_lamps"]')
            page.click("#selection-continue")
            page.click("#confirm")
            page.wait_for_selector("#screen-restitution:not([hidden])")
            assert page.locator('article.restitution[data-entry-id="fn_green_lamps"]').count() == 1
            writes = [h for m, u, h in sent if m == "POST"]
            assert len(writes) >= 4 and all(h.get("x-csrf-token") == c.headers["X-CSRF-Token"]
                                            and h.get("origin") == montage.base for h in writes), writes
            assert not [e for e in errors if "Content Security Policy" in e], errors
        finally:
            browser.close()
            pw.stop()
        # The same write without the token, or from another origin: refused by PI.
        with httpx.Client(base_url=montage.base + "/api", verify=False, timeout=30) as bare:
            raw = {"Cookie": f"pi_session={cookie}", "Origin": montage.base}
            assert bare.post(f"/v1/parcours/{pid}/return", json={}, headers=raw).status_code == 403
            assert bare.post(f"/v1/parcours/{pid}/return", json={}, headers={
                **raw, "Origin": "https://evil.test", "X-CSRF-Token": c.headers["X-CSRF-Token"]}).status_code == 403
        results = c.get(f"/cases/{case_id}/notice-results").json()["results"]
        assert len(results) == 1 and results[0]["selection"]["entry_ids"] == ["fn_green_lamps"]
    STATE.update(case_id=case_id, pid=pid, unfinished=unfinished, results=results, login=login, password=password,
                 cookie=cookie)
    STATE.setdefault("secrets", []).extend([password, login, cookie])


def test_point1_after_a_complete_restart_the_result_is_read_without_pgdr(montage):
    montage.stop()
    montage.start()
    with montage.client() as c:
        sign_in(c, STATE["login"], STATE["password"])
        r = c.get(f"/cases/{STATE['case_id']}/notice-results")
        assert r.status_code == 200 and r.json()["results"] == STATE["results"]
        page_headers = {"Origin": montage.base}
        for old in (STATE["pid"], STATE["unfinished"]):
            r = c.get(f"/v1/parcours/{old}", headers=page_headers)
            assert r.status_code == 404 and "nouveau parcours" in r.json()["detail"]
        time.sleep(0.5)
        assert "/api/v1/parcours/" not in montage.logs()["pgdr.log"]          # nothing asked of PGDR
        reopened = c.post(f"/cases/{STATE['case_id']}/notice-parcours").json()
        new = reopened["page"].split("p=", 1)[1]
        assert new not in (STATE["pid"], STATE["unfinished"])
        assert c.get(f"/v1/parcours/{new}").json()["phase"] == "vir"      # a new parcours, from its start
    STATE["new_pid"] = new


def test_point5_outputs_hold_route_templates_only(montage):
    with montage.client() as c:
        sign_in(c, STATE["login"], STATE["password"])
        assert c.get(f"/cases/{uuid.uuid4()}").status_code == 404                       # refusal
        assert c.get(f"/inconnue/{VIN}", params={"vin": VIN, "plate": PLATE}).status_code == 404   # unknown route
        assert c.get(f"/v1", params={"p": STATE["new_pid"], "plate": PLATE}).status_code == 200
    time.sleep(0.5)
    out = montage.all_output()
    pi = montage.logs()["pi05.log"] + "".join(run["pi05.log"] for run in montage.runs)
    pgdr = montage.logs()["pgdr.log"] + "".join(run["pgdr.log"] for run in montage.runs)
    assert "POST /api/auth/login 200" in pi and "POST /api/auth/password 400" in pi
    assert "GET /api/cases/{case_id} 404" in pi
    assert "POST /api/v1/parcours/{pid}{sub_path:path} 200" in pi
    assert "GET /api/v1 200" in pi
    assert "GET montage:FastAPI 404" in pi
    assert "POST /api/v1/parcours/{pid}/confirm 200" in pgdr and "POST /api/v1/vir-handoff 200" in pgdr
    for secret in [STATE["pid"], STATE["unfinished"], STATE["new_pid"], STATE["case_id"], VIN, PLATE, "?p=", "vin=",
                   *STATE["secrets"], "photo_base64", "Traceback"]:
        assert secret not in out, secret


FAILING_FACTORY = '''
from product_integration.api.production import create_production_app


def create():
    app = create_production_app()
    inner = next(r.app for r in app.routes if getattr(r, "path", None) == "/api")

    @inner.get("/essai-3a/panne/{value}")
    def panne(value: str):
        raise RuntimeError("message with request data " + value)

    return app
'''


def test_point5_an_exception_under_the_production_flags_is_one_fixed_line(montage, tmp_path):
    (tmp_path / "essai_panne_pi.py").write_text(FAILING_FACTORY)
    port = free_port()
    env = {**montage.env, "PYTHONPATH": os.pathsep.join([str(tmp_path), montage.env.get("PYTHONPATH", "")])}
    log = tmp_path / "pi.log"
    with open(log, "wb") as out:   # the flags of scripts/lancer_montage.sh, production mode
        proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "--factory", "essai_panne_pi:create", "--host", "127.0.0.1",
                                 "--port", str(port), "--workers", "1", "--no-server-header", "--no-access-log",
                                 "--no-proxy-headers", "--ssl-certfile", montage.env["PI_TLS_CERT"],
                                 "--ssl-keyfile", montage.env["PI_TLS_KEY"]], env=env, stdout=out, stderr=subprocess.STDOUT)
    try:
        for _ in range(100):
            try:
                if httpx.get(f"https://127.0.0.1:{port}/health", verify=False, timeout=1).status_code:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        r = httpx.get(f"https://127.0.0.1:{port}/api/essai-3a/panne/{VIN}", verify=False)
        assert r.status_code == 500 and VIN not in r.text
        assert r.headers["x-content-type-options"] == "nosniff"
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    out = log.read_text()
    assert "GET /api/essai-3a/panne/{value} exception RuntimeError" in out
    assert "GET /api/essai-3a/panne/{value} 500" in out
    for secret in (VIN, "message with request data", "Traceback"):
        assert secret not in out, secret
