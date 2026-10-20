"""Clôture PI V1 — a requested stop is a clean stop, a crashed service is a failure.

Found during the final local reception from the installed PREFIX: on SIGTERM (what `systemctl stop` sends to
the whole control group, KillMode=control-group, and what an operator sends to the launcher) the TERM trap of
scripts/lancer_montage.sh stopped the services but did not exit, so the supervision loop then saw a stopped
service and exited with code 1 and « Un service du montage s'est arrêté » : systemd would record every normal
stop as a failure. A service that dies on its own must still end the assembly with code 1 (Restart=on-failure).
The real script in production mode, a FICTIVE notice, loopback only.
"""
from __future__ import annotations

import os
import signal
import subprocess
import time

from tests.test_3a_lancement_reel import Montage

FAILURE = "Un service du montage s'est arrêté"


def _output(m: Montage) -> str:
    return (m.root / "montage.out").read_text(errors="replace")


def _children(m: Montage) -> list[int]:
    out = subprocess.run(["pgrep", "-P", str(m.proc.pid), "-f", "uvicorn"], capture_output=True, text=True).stdout
    return [int(p) for p in out.split()]


def test_sigterm_to_the_control_group_is_a_clean_stop(tmp_path):
    m = Montage(tmp_path)
    m.start()
    m.stop()                                              # SIGTERM to the whole process group, as systemd does
    assert m.proc.returncode == 0, _output(m)
    assert FAILURE not in _output(m)


def test_sigterm_to_the_launcher_alone_stops_every_service_cleanly(tmp_path):
    m = Montage(tmp_path)
    m.start()
    children = _children(m)
    assert len(children) == 3
    os.kill(m.proc.pid, signal.SIGTERM)
    assert m.proc.wait(timeout=30) == 0, _output(m)
    assert FAILURE not in _output(m)
    time.sleep(0.5)
    for pid in children:
        assert subprocess.run(["kill", "-0", str(pid)], capture_output=True).returncode != 0, pid


def test_a_service_that_dies_on_its_own_still_ends_the_assembly_with_a_failure(tmp_path):
    m = Montage(tmp_path)
    m.start()
    os.kill(_children(m)[0], signal.SIGKILL)              # VIR crashes
    assert m.proc.wait(timeout=30) == 1
    assert FAILURE in _output(m)
