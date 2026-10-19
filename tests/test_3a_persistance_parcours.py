"""Bloc 3A, point 1 — the confirmed result of the notice parcours is kept in
CPL, through CPL's existing structures (a RunnerExecution of runner type
PGDR_V1_NOTICE and one artifact, schema pgdr_v1_premier_constat; no CPL
schema change).

Kept: the case and its owner, the VIR resolution used (execution, artifact,
resolution id), the notice (document, edition, content fingerprint), the
entry_ids the DRIVER selected (never a recognition), the explicit
confirmation and its date, the Premier Constat and the exact sections
produced, provenance and limits. Not kept: the photo, the sorting answer,
the catalogue, the parcours identifier. One transaction; the same result
twice (double click) is one record; owner only. After a complete restart the
result is read from CPL as confirmed -- a newer notice never replaces it --
without PGDR, without sorting; an unfinished parcours is restarted
explicitly, never presented as resumed. FICTIVE notice, FAKE sorting.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx
import pytest
import yaml
from sqlalchemy import text

import pgdr.v1_parcours as v1
from pgdr.adapters.manifest_notice_repository import ManifestNoticeRepository, content_fingerprint

from app.db.engine import SessionLocal

from product_integration.pgdr import notice_results
from tests import vir_real_mode_support as support
from tests.notice_parcours_support import GREEN_MEANING, SIMULATED_VEHICLE, build_notice, photo_with_metadata
from tests.test_notice_parcours import (  # noqa: F401  (fixtures)
    PLATE, RESOLVED_VIN, UNKNOWN, app, case, make_app, open_parcours, page_client, pgdr, pgdr_calls, propose, started,
    user, user_a, user_b, vir_store,
)


async def confirmed(client, case_id: str, entry_ids=("fn_green_lamps",)) -> tuple[str, dict]:
    pid, page = await started(client, case_id)
    await propose(page, pid, photo_with_metadata(PLATE, support.VIN))
    await page.post(f"/v1/parcours/{pid}/return", json={})
    await page.post(f"/v1/parcours/{pid}/selection", json={"entry_ids": list(entry_ids)})
    out = await page.post(f"/v1/parcours/{pid}/confirm", json={"entry_ids": list(entry_ids), "confirmed": True})
    assert out.status_code == 200 and out.json()["phase"] == "restitution", out.text
    await page.aclose()
    return pid, out.json()


def rows(case_id: str) -> list:
    with SessionLocal() as s:
        return s.execute(text(
            "SELECT e.execution_id, e.execution_status, e.initiated_by_contact_id, a.artifact_id, a.artifact_status, "
            "a.schema_name, a.payload FROM cpl.runner_executions e JOIN cpl.runner_artifacts a "
            "ON a.execution_id = e.execution_id WHERE e.case_id = :c AND e.runner_type = 'PGDR_V1_NOTICE' "
            "ORDER BY e.created_at"), {"c": case_id}).all()


def vir_refs(case_id: str) -> dict:
    with SessionLocal() as s:
        r = s.execute(text(
            "SELECT e.execution_id, a.artifact_id, a.payload->>'resolution_id' AS rid FROM cpl.runner_executions e "
            "JOIN cpl.runner_artifacts a ON a.execution_id = e.execution_id WHERE e.case_id = :c AND e.runner_type = 'VIR' "
            "ORDER BY e.created_at DESC LIMIT 1"), {"c": case_id}).one()
    return {"execution_id": str(r.execution_id), "artifact_id": str(r.artifact_id), "resolution_id": r.rid}


async def test_confirmed_result_is_kept_with_everything_required_and_nothing_else(app, pgdr, user_a):
    case_id = await case(user_a)
    before = datetime.now(timezone.utc)
    pid, out = await confirmed(user_a, case_id)
    (row,) = rows(case_id)
    assert row.execution_status == "COMPLETED" and row.artifact_status == "VALIDATED"
    assert row.schema_name == "pgdr_v1_premier_constat"
    assert str(row.initiated_by_contact_id) == user_a.login["contact_id"]
    rec = row.payload
    assert rec["case_id"] == case_id and rec["owner_contact_id"] == user_a.login["contact_id"]
    assert rec["vir"] == vir_refs(case_id)
    notice = v1.get_wiring().repository.catalogue
    assert rec["notice"] == {"document_id": notice.document.document_id, "title": notice.document.document_title,
                             "edition": notice.document.edition, "language": notice.language,
                             "content_sha256": notice.content_sha256}
    assert rec["selection"]["entry_ids"] == ["fn_green_lamps"] and rec["selection"]["by"] == "driver"
    assert rec["confirmation"]["explicit"] is True
    assert before <= datetime.fromisoformat(rec["confirmation"]["confirmed_at"]) <= datetime.now(timezone.utc)
    assert [s_["entry_id"] for s_ in rec["sections"]] == ["fn_green_lamps"]
    assert rec["sections"][0]["meaning"] == [{"text": GREEN_MEANING}]
    assert rec["premier_constat"]["presentation"]["end"] == out["premier_constat"]["presentation"]["end"]
    assert rec["provenance"]["selection_origin"] == "driver" and rec["limits"]
    blob = json.dumps(rec)
    for absent in (pid, PLATE, support.VIN, RESOLVED_VIN, "photo_base64", "proposed_entry_ids", "GPS",
                   "The fictive red light switches on",            # another entry of the catalogue
                   "fn_amber_sensor", "fn_white_cruise"):
        assert absent not in blob, absent


async def test_double_click_is_one_record_and_concurrent_writes_too(app, pgdr, user_a):
    case_id = await case(user_a)
    pid, page = await started(user_a, case_id)
    await page.post(f"/v1/parcours/{pid}/selection", json={"entry_ids": ["fn_green_lamps"]})
    body = {"entry_ids": ["fn_green_lamps"], "confirmed": True}
    first, second = await asyncio.gather(page.post(f"/v1/parcours/{pid}/confirm", json=body),
                                         page.post(f"/v1/parcours/{pid}/confirm", json=body))
    assert sorted([first.status_code, second.status_code])[0] == 200
    assert len(rows(case_id)) == 1
    (row,) = rows(case_id)
    with ThreadPoolExecutor(4) as pool:   # the same record written four times at once
        ids = list(pool.map(lambda _: notice_results.persist(
            row.payload, case_id=uuid.UUID(case_id), contact_id=uuid.UUID(user_a.login["contact_id"]),
            actor_reference="pi-account:test"), range(4)))
    assert set(ids) == {row.artifact_id} and len(rows(case_id)) == 1
    await page.aclose()


async def test_failure_while_recording_leaves_nothing_partial(app, pgdr, user_a, monkeypatch):
    case_id = await case(user_a)
    with monkeypatch.context() as patched:
        def broken(*a, **k):
            raise RuntimeError("fictitious failure while registering the artifact")
        patched.setattr(notice_results, "register_artifact", broken)
        pid, out = await confirmed(user_a, case_id)
        assert out["premier_constat"]                 # the driver still sees the manufacturer's texts
    assert rows(case_id) == []
    with SessionLocal() as s:
        assert s.execute(text("SELECT count(*) FROM cpl.runner_executions WHERE case_id = :c "
                              "AND runner_type = 'PGDR_V1_NOTICE'"), {"c": case_id}).scalar() == 0


async def test_only_the_owner_reads_the_results(app, pgdr, user_a, user_b):
    case_id = await case(user_a)
    await confirmed(user_a, case_id)
    assert len((await user_a.get(f"/cases/{case_id}/notice-results")).json()["results"]) == 1
    r = await user_b.get(f"/cases/{case_id}/notice-results")
    assert r.status_code == 404 and "fn_green" not in r.text
    anonymous = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test")
    assert (await anonymous.get(f"/cases/{case_id}/notice-results")).status_code == 401
    await anonymous.aclose()


async def test_after_a_complete_restart_the_confirmed_result_is_read_as_it_was(vir_store, pgdr, tmp_path):
    import vir.api.routes as vir_routes
    first = make_app(pgdr, vir_routes.app)
    client = await user(first, "nprest")
    case_id = await case(client)
    _, out = await confirmed(client, case_id)
    unfinished, page = await started(client, case_id)       # a second parcours, left unfinished
    await page.aclose()
    kept = (await client.get(f"/cases/{case_id}/notice-results")).json()["results"]

    # Complete restart: new PI process state (registry), PGDR's parcours lost, and a NEWER notice version.
    v1._parcours.clear()
    newer = build_notice(tmp_path / "newer", SIMULATED_VEHICLE)
    manifest = newer.read_text(encoding="utf-8").replace(GREEN_MEANING, "A newer fictive wording of the green light.")
    newer.write_text(manifest, encoding="utf-8")
    d = yaml.safe_load(manifest)
    d["review"]["content_sha256"] = content_fingerprint({k: v for k, v in d.items() if k != "review"})
    newer.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")
    v1._wiring = v1.build_wiring(ManifestNoticeRepository(newer), dev_trial=False, tri=v1._wiring.tri)
    second = make_app(pgdr, vir_routes.app)
    calls_before, seen_before = len(pgdr.transport.calls), len(pgdr.seen)
    again = httpx.AsyncClient(transport=httpx.ASGITransport(app=second), base_url="http://api.test",
                              headers=dict(client.headers))
    r = await again.get(f"/cases/{case_id}/notice-results")
    assert r.status_code == 200 and r.json()["results"] == kept
    assert kept[0]["sections"][0]["meaning"] == [{"text": GREEN_MEANING}]
    assert kept[0]["notice"]["content_sha256"] != v1.get_wiring().repository.catalogue.content_sha256
    assert len(pgdr.transport.calls) == calls_before and len(pgdr.seen) == seen_before   # neither PGDR nor sorting

    # The unfinished parcours is not resumed: it is unknown, and opening the notice starts a new one.
    page2 = page_client(again)
    r = await page2.get(f"/v1/parcours/{unfinished}")
    assert r.status_code == 404 and "nouveau parcours" in r.json()["detail"]
    reopened = await open_parcours(again, case_id)
    new_pid = reopened["page"].split("p=", 1)[1]
    assert new_pid != unfinished and (await page2.get(f"/v1/parcours/{new_pid}")).json()["phase"] == "vir"
    assert len((await again.get(f"/cases/{case_id}/notice-results")).json()["results"]) == 1
    for c in (client, again, page2):
        await c.aclose()
