"""Conservation 2/3 — deletion of a case past its period (PI purge -> CPL REQ-B5-116).

E. Before its deadline a case is unchanged; after it, the case and its own data are deleted.
F. The account, the shared vehicle, another case and the manufacturer knowledge are kept.
G. An error during the deletion, then a new run: consistent take-up.
H. A second execution has no further effect.
I. Another user still has no access; a deleted case answers 404.
K. A notice result recorded in a case within its period stays readable; the notice parcours still works.
D. Simulation writes nothing; execution is refused without a policy for cases.

Real PI app, real VIR app (simulated fixture), real PGDR with a FICTIVE notice, temporary test database,
fictitious identifiers only; 30 days is a test value, never a decided period.
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text

from app.db.engine import SessionLocal

from product_integration.conservation import purge

from tests import conservation_support as cs
from tests.test_3a_persistance_parcours import confirmed
from tests.test_notice_parcours import (  # noqa: F401  (fixtures)
    RESOLVED_VIN, app, case, open_parcours, pgdr, user, user_a, user_b, vir_store,
)

pytestmark = pytest.mark.asyncio


def _env(**overrides) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PI_CONSERVATION_")}
    env.update(cs.policy_env(**{"PI_CONSERVATION_DOSSIERS_JOURS": cs.TEST_DAYS, **overrides}))
    return env


def _case_row(case_id: str):
    with SessionLocal() as s:
        return s.execute(text("SELECT case_id, asset_id, primary_contact_id FROM cpl.cases WHERE case_id = :c"),
                         {"c": case_id}).first()


def _footprint(case_id: str) -> dict:
    """Every row of the case, with its content digest: equal before and after means untouched."""
    with SessionLocal() as s:
        q = lambda sql: s.execute(text(sql), {"c": case_id}).scalar()      # noqa: E731
        return {
            "case": q("SELECT md5(x::text) FROM cpl.cases x WHERE case_id = :c"),
            "executions": q("SELECT md5(string_agg(x::text, '|' ORDER BY x.execution_id)) FROM cpl.runner_executions x "
                            "WHERE case_id = :c"),
            "artifacts": q("SELECT md5(string_agg(a::text, '|' ORDER BY a.artifact_id)) FROM cpl.runner_artifacts a "
                           "JOIN cpl.runner_executions e USING (execution_id) WHERE e.case_id = :c"),
            "resolutions": q("SELECT count(*) FROM cpl.asset_identity_resolutions r JOIN cpl.runner_executions e "
                             "USING (execution_id) WHERE e.case_id = :c"),
            "decisions": q("SELECT count(*) FROM cpl.canonical_case_decisions WHERE case_id = :c"),
        }


def _executions(case_id: str) -> list:
    with SessionLocal() as s:
        return [r[0] for r in s.execute(text("SELECT execution_id FROM cpl.runner_executions WHERE case_id = :c"),
                                        {"c": case_id})]


def _count(sql: str, **params) -> int:
    with SessionLocal() as s:
        return s.execute(text(sql), params).scalar()


async def _case_on(client, contact_id, asset_id) -> str:
    """A second case on the same vehicle (shared vehicle)."""
    r = await client.post("/cases", json={
        "contact_id": str(contact_id), "asset_id": str(asset_id), "request_id": f"vir-{uuid.uuid4().hex[:8]}",
        "registration_country_code": "FR", "consent": {"external_lookup_allowed": True},
        "case_idempotency_key": f"case-{uuid.uuid4().hex}", "vin": RESOLVED_VIN})
    assert r.status_code == 201, r.text
    return r.json()["case_id"]


async def test_expired_case_is_deleted_with_its_own_data_and_nothing_else(app, pgdr, user_a, user_b):
    purge.execute(environ=_env())        # cases left due by an interrupted earlier run: a clean start
    old = await case(user_a)
    assert (await user_a.post(f"/cases/{old}/vir/confirmations",
                              json={"field_path": "drivetrain", "value": "front_wheel_drive"})).status_code == 200
    await confirmed(user_a, old)                                   # a Premier Constat in the case
    row = _case_row(old)
    shared = await _case_on(user_a, row.primary_contact_id, row.asset_id)
    await confirmed(user_a, shared)
    other_user_case = await case(user_b)
    old_executions = _executions(old)
    kept_results = (await user_a.get(f"/cases/{shared}/notice-results")).json()["results"]
    assert len(kept_results) == 1
    knowledge = _count("SELECT count(*) FROM cpl.manufacturer_knowledge_documents")
    assert (await user_b.get(f"/cases/{old}")).status_code == 404          # I: never the other user's

    # E (before): within its period, an execution leaves the case unchanged.
    before = {c: _footprint(c) for c in (old, shared, other_user_case)}
    run0 = cs.cli("purge", "--executer", env=_env())
    assert run0.returncode == 0 and "0 dossier(s) échu(s) supprimé(s)" in run0.stdout, run0.stdout + run0.stderr
    assert {c: _footprint(c) for c in before} == before

    # D: the simulation counts and writes nothing.
    cs.backdate_case_creation(old, 40)
    before = {c: _footprint(c) for c in (old, shared, other_user_case)}
    snap = cs.snapshot()
    sim = cs.cli("purge", env=_env())
    assert sim.returncode == 0 and cs.snapshot() == snap, sim.stderr
    assert "1 dossier(s) échu(s) seraient supprimés avec leurs données propres" in sim.stdout, sim.stdout
    assert "0 dossier(s) échu(s) reporté(s)" in sim.stdout and RESOLVED_VIN not in sim.stdout + sim.stderr

    # E (after): the case and its own data deleted.
    run = cs.cli("purge", "--executer", env=_env())
    assert run.returncode == 0, run.stdout + run.stderr
    assert "1 dossier(s) échu(s) supprimé(s) avec leurs données propres" in run.stdout, run.stdout
    assert RESOLVED_VIN not in run.stdout + run.stderr
    assert _case_row(old) is None and not _executions(old)
    assert _count("SELECT count(*) FROM cpl.runner_artifacts WHERE execution_id = ANY(:x)", x=old_executions) == 0
    assert _count("SELECT count(*) FROM cpl.asset_identity_resolutions WHERE execution_id = ANY(:x)",
                  x=old_executions) == 0
    assert _count("SELECT count(*) FROM cpl.canonical_case_decisions WHERE case_id = :c", c=old) == 0
    with SessionLocal() as s:
        trace = s.execute(text("SELECT * FROM cpl.case_deletions WHERE case_id = :c"), {"c": old}).mappings().one()
        op = s.execute(text("SELECT outcome, counts FROM pi_auth.conservation_operations "
                            "ORDER BY started_at DESC LIMIT 1")).one()
    assert trace["retention_days"] == 30 and trace["operator_reference"].startswith("pi-purge:")
    assert trace["deleted_counts"]["runner_artifacts"] >= 3 and trace["deleted_counts"]["cases"] == 1
    assert not {str(row.asset_id), str(row.primary_contact_id), RESOLVED_VIN} & {str(v) for v in trace.values()}
    assert RESOLVED_VIN not in str(dict(trace))
    assert op.outcome == "completed" and op.counts["cases"] == 1 and op.counts["cases_blocked"] == 0

    # I: a deleted case answers 404, to its owner as to anybody; the other user still has no access.
    for path in (f"/cases/{old}", f"/cases/{old}/vir", f"/cases/{old}/notice-results", f"/cases/{old}/history"):
        assert (await user_a.get(path)).status_code == 404, path
        assert (await user_b.get(path)).status_code == 404, path
    assert (await user_a.get(f"/executions/{old_executions[0]}/artifact")).status_code == 404
    assert (await user_a.post(f"/cases/{old}/notice-parcours")).status_code == 404
    assert (await user_b.get(f"/cases/{shared}")).status_code == 404

    # F: the account, the shared vehicle, the other cases and the knowledge are kept.
    listed = {c["case_id"] for c in (await user_a.get("/cases")).json()["cases"]}
    assert shared in listed and old not in listed
    assert _count("SELECT count(*) FROM cpl.assets WHERE asset_id = :a", a=row.asset_id) == 1
    assert _count("SELECT count(*) FROM automotive.vehicle_details WHERE asset_id = :a", a=row.asset_id) == 1
    assert _count("SELECT count(*) FROM cpl.contacts WHERE contact_id = :c", c=row.primary_contact_id) == 1
    assert _count("SELECT count(*) FROM cpl.contact_asset_relationships WHERE asset_id = :a", a=row.asset_id) >= 1
    assert _count("SELECT count(*) FROM cpl.manufacturer_knowledge_documents") == knowledge
    assert {c: _footprint(c) for c in (shared, other_user_case)} == \
        {c: before[c] for c in (shared, other_user_case)}

    # K: the result recorded in the case within its period is read as it was; the parcours still opens.
    assert (await user_a.get(f"/cases/{shared}/notice-results")).json()["results"] == kept_results
    assert (await user_a.get(f"/cases/{shared}/vir")).status_code == 200
    assert (await open_parcours(user_a, shared))["status"] == "opened"

    # H: a second execution has no further effect.
    snap = cs.snapshot()
    again = cs.cli("purge", "--executer", env=_env())
    assert again.returncode == 0 and "0 dossier(s) échu(s) supprimé(s)" in again.stdout, again.stdout
    after = cs.snapshot()
    assert {t: after[t] for t in after if t != "pi_auth.conservation_operations"} == \
        {t: snap[t] for t in snap if t != "pi_auth.conservation_operations"}
    assert _count("SELECT count(*) FROM cpl.case_deletions WHERE case_id = :c", c=old) == 1


async def test_an_error_during_the_deletion_stops_cleanly_and_a_new_run_finishes(app, user_a):
    purge.execute(environ=_env())
    cases = []
    for age in (50, 45, 40):                                   # deletion order: oldest first
        c = await case(user_a)
        cs.backdate_case_creation(c, age)
        cases.append(c)
    failing = _executions(cases[1])
    before = _footprint(cases[1]), _footprint(cases[2])
    with SessionLocal() as s:          # test database only: the database refuses deleting one case's executions
        s.execute(text(f"""
            CREATE OR REPLACE FUNCTION public.essai_suppression_refus() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF OLD.execution_id = ANY(ARRAY{[str(x) for x in failing]}::uuid[]) THEN
              RAISE EXCEPTION 'essai : refus'; END IF; RETURN OLD; END $$;
            CREATE TRIGGER essai_suppression_refus BEFORE DELETE ON cpl.runner_executions
              FOR EACH ROW EXECUTE FUNCTION public.essai_suppression_refus();"""))
        s.commit()
    try:
        r = cs.cli("purge", "--executer", env=_env())
        assert r.returncode == 1 and "Purge interrompue (" in r.stderr and "relancer" in r.stderr, r.stdout + r.stderr
        assert "essai : refus" not in r.stderr
        with SessionLocal() as s:
            op = s.execute(text("SELECT outcome, error_class, counts FROM pi_auth.conservation_operations "
                                "ORDER BY started_at DESC LIMIT 1")).one()
        assert op.outcome == "interrupted" and op.error_class and op.counts["cases"] == 1
        assert _case_row(cases[0]) is None                                     # deleted before the error: stays so
        assert (_footprint(cases[1]), _footprint(cases[2])) == before          # the failing case whole, the next untouched
        assert _count("SELECT count(*) FROM cpl.case_deletions WHERE case_id = :c", c=cases[1]) == 0
    finally:
        with SessionLocal() as s:
            s.execute(text("DROP TRIGGER IF EXISTS essai_suppression_refus ON cpl.runner_executions; "
                           "DROP FUNCTION IF EXISTS public.essai_suppression_refus();"))
            s.commit()
    r = cs.cli("purge", "--executer", env=_env())
    assert r.returncode == 0 and "2 dossier(s) échu(s) supprimé(s)" in r.stdout, r.stdout + r.stderr
    assert all(_case_row(c) is None for c in cases)
    assert _count("SELECT count(*) FROM cpl.case_deletions WHERE case_id = ANY(CAST(:c AS uuid[]))", c=cases) == 3


async def test_without_a_policy_for_cases_the_simulation_counts_and_the_execution_refuses(app, user_a):
    c = await case(user_a)
    cs.backdate_case_creation(c, 40)
    try:
        snap = cs.snapshot()
        env = _env(PI_CONSERVATION_DOSSIERS_JOURS=None)
        sim = cs.cli("purge", env=env)
        assert sim.returncode == 0 and f"{purge.NO_POLICY} (" in sim.stdout and "dossier(s) en base" in sim.stdout
        r = cs.cli("purge", "--executer", env=env)
        assert r.returncode == 2 and "PI_CONSERVATION_DOSSIERS_JOURS" in r.stderr
        assert cs.snapshot() == snap                                          # nothing written, no operation
        r = cs.cli("purge", "--executer", env=_env(PI_CONSERVATION_DOSSIERS_JOURS="illimitee"))
        assert r.returncode == 0 and _case_row(c) is not None                 # explicit "no limit": kept
    finally:
        cs.backdate_case_creation(c, -40)


async def test_a_parcours_of_a_deleted_case_is_refused_at_once_without_reaching_pgdr(app, pgdr, user_a, user_b):
    """1. The relay checks, on every call and before PGDR, that the case still exists and is the account's."""
    from tests.test_notice_parcours import started
    purge.execute(environ=_env())
    old = await case(user_a)
    pid, page = await started(user_a, old)
    base = f"/v1/parcours/{pid}"
    assert (await page.get(base + "/catalogue")).status_code == 200                # alive before the deletion
    other = await case(user_b)
    _, page_b = await started(user_b, other)
    assert (await page_b.get(base + "/catalogue")).status_code == 404               # another user: refused, as before
    cs.backdate_case_creation(old, 40)
    run = cs.cli("purge", "--executer", env=_env())
    assert run.returncode == 0 and _case_row(old) is None, run.stdout + run.stderr

    calls = len(pgdr.transport.calls)
    for method, path, body in (("GET", base, None), ("GET", base + "/catalogue", None),
                               ("POST", base + "/selection", {"entry_ids": ["fn_green_lamps"]}),
                               ("POST", base + "/confirm", {"entry_ids": ["fn_green_lamps"], "confirmed": True}),
                               ("POST", base + "/record", {})):
        r = await (page.get(path) if method == "GET" else page.post(path, json=body))
        assert r.status_code == 404, (path, r.text)
        assert set(r.json()) == {"detail", "error_category"} and "Parcours inconnu" in r.json()["detail"]
    assert len(pgdr.transport.calls) == calls                                       # PGDR never reached
    assert _case_row(old) is None and _count("SELECT count(*) FROM cpl.runner_executions WHERE case_id = :c",
                                             c=old) == 0                            # nothing recorded
    assert (await page_b.get(f"/v1/parcours/{pid}/catalogue")).status_code == 404
    await page.aclose()
    await page_b.aclose()
