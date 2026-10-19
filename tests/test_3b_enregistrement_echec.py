"""Bloc 3B, point 3 — when CPL does not record a confirmed result.

The driver still gets the manufacturer's texts, with an explicit « Résultat
non enregistré » and a retry. The retry (POST /v1/parcours/{pid}/record,
handled by PI alone) writes the very record that was refused: no diagnosis,
no sorting, no PGDR request, no provider call is made again, and the record
is never written twice. « Résultat enregistré » is said only once CPL has
committed the record, and nothing at all is said about a record before the
driver's explicit confirmation. Real PI-05 app, real PostgreSQL, real VIR and
PGDR apps (ASGI), FICTIVE notice, FAKE sorting; CPL's refusal is produced by
a failing artifact registration (nothing written), as in bloc 3A.
"""
from __future__ import annotations

import httpx
import pytest

import vir.api.routes as vir_routes

from product_integration.pgdr import notice_results
from tests import vir_real_mode_support as support
from tests.notice_parcours_support import GREEN_MEANING, photo_with_metadata
from tests.test_3a_persistance_parcours import rows
from tests.test_notice_parcours import (  # noqa: F401  (fixtures)
    PLATE, UNKNOWN, app, case, make_app, page_client, pgdr, propose, started, user, user_a, user_b, vir_store,
)

NOT_RECORDED = "Résultat non enregistré"
RECORDED = "Résultat enregistré"


def cpl_refuses(patched) -> None:
    def broken(*a, **k):
        raise RuntimeError("fictitious CPL refusal while registering the artifact")
    patched.setattr(notice_results, "register_artifact", broken)


class OutgoingCalls:
    """Every request PI sends to another service in these tests (VIR at vir.test, PGDR at pgdr.test): a
    provider lookup goes through VIR only, a diagnosis or a sorting through PGDR only."""

    def __init__(self, monkeypatch):
        self.hosts: list[str] = []
        original = httpx.ASGITransport.handle_async_request

        async def counting(transport, request):
            self.hosts.append(request.url.host)
            return await original(transport, request)
        monkeypatch.setattr(httpx.ASGITransport, "handle_async_request", counting)

    def to_services(self) -> list[str]:
        return [h for h in self.hosts if h != "api.test"]


async def to_confirmation(client, case_id: str):
    pid, page = await started(client, case_id)
    await propose(page, pid, photo_with_metadata(PLATE, support.VIN))
    await page.post(f"/v1/parcours/{pid}/return", json={})
    out = await page.post(f"/v1/parcours/{pid}/selection", json={"entry_ids": ["fn_green_lamps"]})
    assert "product_record" not in out.json()
    return pid, page


async def test_refused_record_shows_the_texts_says_not_recorded_and_the_retry_writes_it_once(app, pgdr, user_a,
                                                                                               monkeypatch):
    case_id = await case(user_a)
    pid, page = await to_confirmation(user_a, case_id)
    with monkeypatch.context() as patched:
        cpl_refuses(patched)
        out = await page.post(f"/v1/parcours/{pid}/confirm", json={"entry_ids": ["fn_green_lamps"], "confirmed": True})
    body = out.json()
    assert out.status_code == 200 and body["phase"] == "restitution"
    assert body["premier_constat"] and body["sections"][0]["meaning"] == [{"text": GREEN_MEANING}]
    assert body["product_record"]["status"] == "not_recorded" and body["product_record"]["retry"] is True
    assert body["product_record"]["message"].startswith(NOT_RECORDED)
    assert rows(case_id) == []
    assert (await user_a.get(f"/cases/{case_id}/notice-results")).json()["results"] == []

    # Retry: PI writes the record it kept -- nothing goes to PGDR, the sorting or VIR.
    outgoing = OutgoingCalls(monkeypatch)
    pgdr_before, sorting_before = list(pgdr.transport.calls), list(pgdr.seen)
    with monkeypatch.context() as patched:          # CPL refuses again: still not recorded, retry offered again
        cpl_refuses(patched)
        again = await page.post(f"/v1/parcours/{pid}/record", json={})
    assert again.status_code == 200 and again.json()["product_record"]["status"] == "not_recorded"
    assert rows(case_id) == []
    retried = await page.post(f"/v1/parcours/{pid}/record", json={})
    assert retried.status_code == 200
    record = retried.json()["product_record"]
    assert record["status"] == "recorded" and record["message"].startswith(RECORDED) and record["retry"] is False
    assert set(retried.json()) == {"product_record"}
    (row,) = rows(case_id)
    assert row.payload["selection"] == {"entry_ids": ["fn_green_lamps"], "by": "driver"}
    assert row.payload["sections"][0]["meaning"] == [{"text": GREEN_MEANING}]
    # A second retry, or a double click: still one record.
    for _ in range(2):
        assert (await page.post(f"/v1/parcours/{pid}/record", json={})).json()["product_record"]["status"] == "recorded"
    assert len(rows(case_id)) == 1
    assert pgdr.transport.calls == pgdr_before and pgdr.seen == sorting_before
    assert outgoing.to_services() == []
    results = (await user_a.get(f"/cases/{case_id}/notice-results")).json()["results"]
    assert len(results) == 1 and results[0]["record_id"] == str(row.artifact_id)
    await page.aclose()


async def test_recorded_is_said_only_once_cpl_has_committed(app, pgdr, user_a, monkeypatch):
    case_id = await case(user_a)
    pid, page = await to_confirmation(user_a, case_id)
    seen_at_answer: list[int] = []
    original = notice_results.persist

    def persist_then_count(*a, **k):
        kept = original(*a, **k)
        seen_at_answer.append(len(rows(case_id)))      # committed before PI answers
        return kept
    monkeypatch.setattr(notice_results, "persist", persist_then_count)
    out = await page.post(f"/v1/parcours/{pid}/confirm", json={"entry_ids": ["fn_green_lamps"], "confirmed": True})
    assert out.json()["product_record"]["status"] == "recorded" and seen_at_answer == [1]
    assert out.json()["product_record"]["message"].startswith(RECORDED)
    await page.aclose()


async def test_nothing_is_said_about_a_record_before_the_confirmation(app, pgdr, user_a):
    case_id = await case(user_a)
    pid, page = await started(user_a, case_id)
    answers = [await page.get(f"/v1/parcours/{pid}"),
               await propose(page, pid, photo_with_metadata(PLATE, support.VIN)),
               await page.post(f"/v1/parcours/{pid}/return", json={}),
               await page.post(f"/v1/parcours/{pid}/selection", json={"entry_ids": ["fn_green_lamps"]})]
    assert all(a.status_code == 200 and "product_record" not in a.json() for a in answers)
    # Nothing confirmed: a retry has nothing to write.
    r = await page.post(f"/v1/parcours/{pid}/record", json={})
    assert r.status_code == 409 and "product_record" not in r.json()
    assert rows(case_id) == []
    await page.aclose()


async def test_record_retry_refusals(app, pgdr, user_a, user_b, monkeypatch):
    case_id = await case(user_a)
    pid, page = await to_confirmation(user_a, case_id)
    with monkeypatch.context() as patched:
        cpl_refuses(patched)
        await page.post(f"/v1/parcours/{pid}/confirm", json={"entry_ids": ["fn_green_lamps"], "confirmed": True})
    other = page_client(user_b)
    r = await other.post(f"/v1/parcours/{pid}/record", json={})          # another user: like a missing parcours
    assert r.status_code == 404 and r.json() == UNKNOWN
    bare = page_client(user_a)
    assert (await bare.post(f"/v1/parcours/{pid}/record", json={}, headers={"X-CSRF-Token": "wrong"})).status_code == 403
    assert (await bare.post(f"/v1/parcours/{pid}/record", json={},
                            headers={"Origin": "https://evil.test"})).status_code == 403
    assert (await bare.post(f"/v1/parcours/{pid}/record", content=b"{}",
                            headers={"Content-Type": "text/plain"})).status_code == 415
    assert (await bare.get(f"/v1/parcours/{pid}/record")).status_code == 404
    unknown = await page.post("/v1/parcours/V1-" + "0" * 32 + "/record", json={})
    assert unknown.status_code == 404 and unknown.json() == UNKNOWN
    assert rows(case_id) == []
    for c in (page, other, bare):
        await c.aclose()


async def test_after_a_restart_the_unrecorded_result_is_not_offered_again(vir_store, pgdr, monkeypatch):
    first = make_app(pgdr, vir_routes.app)
    client = await user(first, "nprec")
    case_id = await case(client)
    pid, page = await to_confirmation(client, case_id)
    with monkeypatch.context() as patched:
        cpl_refuses(patched)
        await page.post(f"/v1/parcours/{pid}/confirm", json={"entry_ids": ["fn_green_lamps"], "confirmed": True})
    second = make_app(pgdr, vir_routes.app)           # new process state: the kept record is gone with the parcours
    page2 = httpx.AsyncClient(transport=httpx.ASGITransport(app=second), base_url="http://api.test",
                              headers=dict(page_client(client).headers))
    r = await page2.post(f"/v1/parcours/{pid}/record", json={})
    assert r.status_code == 404 and r.json() == UNKNOWN and rows(case_id) == []
    for c in (client, page, page2):
        await c.aclose()


pytestmark = pytest.mark.asyncio
