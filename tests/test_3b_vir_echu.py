"""Bloc 3B — a case whose VIR identification VIR no longer keeps.

Found during the 3B retention check: once VIR's retention has ended and its
record is purged (vir purge, or the purge at each write), the case's
identity details were answered as a VIR technical failure (502, "temporarily
unavailable"), which is untrue. They are now answered as no longer kept
(410, VIR_RESULT_NOT_KEPT), and a confirmation is refused the same way with
nothing written; the case itself and its kept results stay readable. Real
PI-05 app, real PostgreSQL, real VIR app (simulated fixture), real PGDR app.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

import vir.api.routes as vir_routes

from sqlalchemy import text

from app.db.engine import SessionLocal

from tests.test_3a_persistance_parcours import confirmed
from tests.test_notice_parcours import app, case, pgdr, user_a, vir_store  # noqa: F401  (fixtures)

FAR = datetime(2200, 1, 1, tzinfo=timezone.utc)


def executions(case_id: str) -> int:
    with SessionLocal() as s:
        return s.execute(text("SELECT count(*) FROM cpl.runner_executions WHERE case_id = :c"), {"c": case_id}).scalar()


async def test_purged_identification_is_said_no_longer_kept_and_the_case_stays(app, pgdr, user_a):
    case_id = await case(user_a)
    await confirmed(user_a, case_id)
    assert (await user_a.get(f"/cases/{case_id}/vir")).status_code == 200
    assert vir_routes.STORE.purge_expired(now=FAR) >= 1            # VIR's retention ended for every record

    r = await user_a.get(f"/cases/{case_id}/vir")
    assert r.status_code == 410 and r.json()["error_category"] == "VIR_RESULT_NOT_KEPT", r.text
    before = executions(case_id)
    c = await user_a.post(f"/cases/{case_id}/vir/confirmations",
                          json={"field_path": "drivetrain", "value": "front_wheel_drive"})
    assert c.status_code == 410 and c.json()["error_category"] == "VIR_RESULT_NOT_KEPT", c.text
    assert executions(case_id) == before
    assert (await user_a.get(f"/cases/{case_id}")).status_code == 200
    assert len((await user_a.get(f"/cases/{case_id}/notice-results")).json()["results"]) == 1


pytestmark = pytest.mark.asyncio
