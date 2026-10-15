"""PI-05 launch: VIR's address comes from PI_VIR_BASE_URL when set (so the
assembly can run on the loopback without a hosts-file entry or port 80);
the historical default is unchanged when it is not set. Evaluated in a
fresh interpreter so this process's imported modules stay untouched."""
import os
import subprocess
import sys

_PRINT = "import product_integration.api.deps as d; print(d.VIR_BASE_URL)"


def _vir_base_url(extra_env: dict) -> str:
    env = {k: v for k, v in os.environ.items() if k != "PI_VIR_BASE_URL"}
    env.update(extra_env)
    done = subprocess.run([sys.executable, "-c", _PRINT], env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def test_default_vir_base_url_unchanged():
    assert _vir_base_url({}) == "http://vir-service.internal"


def test_vir_base_url_from_environment():
    assert _vir_base_url({"PI_VIR_BASE_URL": "http://127.0.0.1:8001"}) == "http://127.0.0.1:8001"
