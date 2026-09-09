# PI_01_VIR_INTEGRATION_CANDIDATE_EVIDENCE_v0

## 1. Candidate identity

```text
Product-integration repository:  NEW — no existing repository found under any plausible name
                                    (checked: cpl-product-integration, product-integration, cpl-pi,
                                    cpl-vir-pgdr-integration, pi-integration — all confirmed nonexistent
                                    by comparing the git error pattern against both a known-good repo and
                                    a deliberately fake one; git's "could not read Username" response is
                                    identical for private and nonexistent repos, so this is the strongest
                                    check available without direct account enumeration)
Candidate branch:                    pi-01-vir-integration-candidate
Candidate SHA:                          reported in the accompanying build handoff, per this project's
                                           established materialization protocol (the exact SHA cannot be
                                           known before the commit exists; recorded definitively at push time)
Tree SHA:                                   likewise reported at handoff time

CPL software baseline consumed:      6181dabb9239e281974c368ad8f5df80350cabf1  (the merge commit — NOT
                                        governance HEAD; confirmed by checking out this exact SHA before
                                        installing CPL as a dependency)
CPL Reality Check governance SHA:       306f3732d1862f7368eb46d0366683fa9b55e1e2
VIR full baseline SHA:                     a342aba7cc2fc517621f4fc79c3191bdfdc9e10b (resolved from the
                                              short form in the PI-01 instruction; confirmed still VIR's
                                              current HEAD at build time — no staleness)
```

---

## 2. Runtime and dependency versions

```text
Python:        3.12.3
PostgreSQL:    16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)
httpx:         installed via pyproject.toml (>=0.27.0)
pydantic:      >=2.0.0
pytest:        9.1.1
pytest-asyncio: 1.4.0
CPL migration head consumed: 027 (unchanged — PI-01 introduces zero new migrations, zero new tables)
```

---

## 3. Repository scope discipline

`git diff` against `cpl_baseline` and `vir_baseline` (the two dependency checkouts used to build and test
this candidate): **zero changes to either.** Both were used exactly as pinned, read-only. PI-01's own
repository contains 14 new files, all under `src/product_integration/` and `tests/`, plus `pyproject.toml`
and `.gitignore`. No CPL migration was created. No CPL, VIR, or PGDR file was modified.

---

## 4. Files added

```text
src/product_integration/__init__.py
src/product_integration/cpl_registration.py       (the two-transaction orchestration function)
src/product_integration/vehicle_detail_writer.py     (Reality Check gap G-02's minimum write function)
src/product_integration/vir/__init__.py
src/product_integration/vir/client.py                    (async VIR HTTP client, 4 endpoints)
src/product_integration/vir/errors.py                        (explicit error taxonomy)
src/product_integration/vir/schemas.py                           (independent wire-contract models)
src/product_integration/vir/status_mapping.py                        (explicit 8->6 status transform)
tests/__init__.py
tests/conftest.py                                                        (VIR ASGI fixture, CPL session fixtures)
tests/test_cpl_registration.py                                              (categories C-I, definitive acceptance)
tests/test_status_mapping.py                                                   (category B)
tests/test_vir_client.py                                                         (category A)
pyproject.toml, .gitignore
```

---

## 5. Tests added and full results

```text
Command: python -m pytest tests/ -v          (real PostgreSQL 16, fresh database each full run)

Category A — VIR client:                     10/10 PASS  (tests/test_vir_client.py)
Category B — status mapping:                     11/11 PASS  (tests/test_status_mapping.py)
Categories C-I + definitive acceptance:              11/11 PASS  (tests/test_cpl_registration.py)

TOTAL: 32/32 PASS, 0 FAIL, 0 SKIP
```

Run three times total during this build (once after each round of bug fixes, then twice more from a
completely fresh, dropped-and-recreated database) — 32/32 every time, no flakiness observed.

**Category I (regression, run separately per the instruction — CPL's own suite is a dependency here, not a
PI-01 test file):**

```text
CPL's own test suite (unmodified, run against the same PostgreSQL instance): 227/227 PASS — exact match to
  its own historical baseline; zero regression.
VIR's own test suite (unmodified, run independently): 103/103 PASS — zero regression.
```

Neither CPL's nor VIR's own test suite was modified, weakened, skipped, or xfailed to make PI-01 pass.

---

## 6. All 8 VIR status values tested

```text
resolved                 -> RESOLVED              PASS
provisionally_resolved   -> PARTIALLY_RESOLVED     PASS
ambiguous                -> AMBIGUOUS              PASS
insufficient_data        -> UNRESOLVED             PASS
contradictory            -> CONTRADICTORY          PASS
unsupported_country      -> FAILED                 PASS
provider_unavailable     -> FAILED                 PASS
invalid_identifier       -> FAILED                 PASS
unknown/unrecognized value -> UnknownVIRStatusError raised explicitly, PASS
```

Reasoning for each mapping is documented inline in `status_mapping.py` and grounded in direct evidence read
from VIR's own `resolution.py` at the pinned baseline (e.g., confirmed that `PROVIDER_UNAVAILABLE` and
`INVALID_IDENTIFIER` are reachable as genuine 200-OK governed outcomes with `vehicle_identity = None`, not
only via raised exceptions — this refined the mapping's justification during the build, see §11 for the
exact evidence).

---

## 7. Actual VIR HTTP mechanism used

VIR's real FastAPI app (`vir.api.routes.app`), exercised via `httpx.ASGITransport` — the genuine ASGI
request/response cycle (real routing, real Pydantic validation, real status codes, real JSON serialization),
in-process, with an isolated SQLite store swapped in via the exact same monkeypatch pattern VIR's own test
suite uses (`tests/test_api_persistence.py`, confirmed read directly). This satisfies the instruction's "VIR's
own TestClient... or a live VIR process" requirement — no VIR response was ever faked for the definitive
acceptance test; mocks (`httpx.MockTransport`) were used only for the unit-level transport/timeout/invalid-
response failure tests (§25's explicitly permitted exception).

---

## 8. Database linkage evidence

The definitive acceptance test (`test_g_definitive_acceptance_full_linked_state_survives_restart`) performs
exactly the 16-step scenario from PI-01 §26:

```text
1-3.   Real PostgreSQL, CPL migrations through 027, pinned CPL software behavior      — done by conftest.py's
                                                                                          session-scoped fixture
4-6.   Real VehicleIdentityRequest through the PI-01 VIR client, real VIR resolution,     — register_vir_execution
       resolution_status mapped through the exact approved table
7-10.  RunnerExecution, "vir_resolution" RunnerArtifact, AssetIdentityResolution,            — all four created
       VehicleDetail
11.    Commit                                                                                    — TX1 and TX2 both
                                                                                                     commit for real
12-13. Query PostgreSQL independently, prove linkage                                               — first assertion
                                                                                                       block
14-15. Restart/recreate the application session                                                        — a brand-new
                                                                                                            SQLAlchemy
                                                                                                            Session()
                                                                                                            from the
                                                                                                            connection
                                                                                                            pool, no
                                                                                                            shared
                                                                                                            Python
                                                                                                            object
16.    Query again, prove linkage survives restart                                                         — second
                                                                                                                assertion
                                                                                                                block,
                                                                                                                identical
                                                                                                                checks,
                                                                                                                fresh
                                                                                                                session
```

Result: **PASS**. `RunnerExecution.case_id`/`asset_id`, `RunnerArtifact.execution_id`,
`AssetIdentityResolution.asset_id`/`execution_id`, and `VehicleDetail.asset_id`/`source_resolution_id` all
verified linked correctly from a completely independent session, and at least one `RunnerGovernanceDecision`
per governed mutation confirmed present.

---

## 9. Traceability (§28)

| Item | Evidence |
|---|---|
| (a) async VIR HTTP client | `src/product_integration/vir/client.py`; validated by all of `test_vir_client.py` (10 tests) |
| (b) exact four endpoint support | `client.py`'s four public methods; each individually tested in `test_vir_client.py` |
| (c) 8->6 resolution-status mapping | `status_mapping.py`; validated by all 11 tests in `test_status_mapping.py` |
| (d) VehicleDetail write operation | `vehicle_detail_writer.py`; validated by `test_f01`/`test_f02`/`test_e02` |
| (e) vir_resolution artifact schema registration | `cpl_registration.py::ensure_vir_resolution_schema_registered`; validated by `test_d01` (`artifact_status == "VALIDATED"` proves the REQ-B6-089 mechanism actually engaged, not merely that a row exists) |
| (f) RunnerExecution persistence | validated by `test_c01`, `test_c02`, `test_g` |
| (g) RunnerArtifact persistence | validated by `test_d01`, `test_d02`, `test_g` |
| (h) AssetIdentityResolution persistence | validated by `test_e01`, `test_e02`, `test_g` |
| (i) VehicleDetail persistence | validated by `test_f01`, `test_f02`, `test_g` |
| (j) full linked-row acceptance test | `test_g_definitive_acceptance_full_linked_state_survives_restart` |

No item marked complete without a specific validating test named above.

---

## 10. Known limitations

- **VIR's own root-level `RUNNER_EXECUTION_CONTRACT.md` remains stale** (unrelated to this candidate — a VIR-
  internal documentation issue, already flagged in the Reality Check; not fixed here since PI-01 does not
  modify VIR).
- **Clarification flow is exercised but not fully wired into the CPL registration path.** PI-01's VIR client
  supports `submit_clarification()` (tested, §24-A/§19), and `test_g`'s acceptance scenario uses a direct
  (non-clarification) resolution path. The instruction's §19 requirement — "the resulting VIR resolution can
  enter the same CPL registration path" after a clarification — is satisfied structurally (a post-
  clarification `VehicleIdentityResolution` has the identical shape as a direct one, and
  `register_vir_execution` does not care which path produced the `VehicleIdentityRequest`/response it's
  given), but no dedicated end-to-end test drives a full resolve-then-clarify-then-register sequence through
  `register_vir_execution` itself. This is a genuine test-coverage gap, disclosed rather than silently
  assumed adequate.
- **`resolver_version` is a caller-supplied string** (`register_vir_execution(..., resolver_version=...)`),
  defaulting to `"unknown"`. VIR's own API does not expose a per-resolution version field (confirmed — only
  `app.version = "0.1.0"` on the FastAPI app itself, checked at `/health` or app metadata, not per-call). A
  real deployment would need to decide how to source this (e.g., read VIR's `/health` response once and cache
  it) — not solved here, since it doesn't block any required acceptance criterion, but disclosed as a
  decision a future candidate or the calling product code will need to make.
- **`_mark_failed`'s best-effort re-marking after a `CPL_PERSISTENCE_FAILURE`** is itself wrapped in a
  bare `except Exception: pass` (deliberately, so a failing re-mark never masks the original failure) — this
  means that in the rare case where the database is down for both the original TX2 attempt and this fallback
  attempt, the `RunnerExecution` could be left in `RUNNING` rather than `FAILED`. This is disclosed as an
  edge case, not fixed with additional retry machinery, per the instruction's own "no hidden retry policy, no
  infinite retry" rule (§7) — extending that discipline to this fallback path as well, rather than
  special-casing it.

---

## 11. Blocking findings

None. No requirement could not be satisfied. No `COMMON_GAP_CANDIDATE` was found — every gap PI-01 needed to
close (VehicleDetail write path, status mapping, artifact schema registration) was exactly what the Reality
Check's gap register (G-01/G-02/G-03) predicted, resolved entirely within the product-integration layer, with
zero CPL modification.

---

## 12. Non-blocking findings

Two real bugs were found and fixed **during this build**, by the test suite itself, before any candidate was
declared complete — recorded here for transparency, not because they remain open:

- **Replay handling gap:** the orchestration function's first draft did not check whether `admit_execution`
  returned a replay (same idempotency key, same intent) before proceeding — it would have silently
  registered a second `RunnerArtifact` against an already-completed execution. Caught by
  `test_d02_no_duplicate_artifact_on_replayed_admission`, fixed by adding an explicit replay branch
  (`_existing_registration_result`) that returns the already-persisted linked state instead of re-running the
  VIR call and TX2.
- **Outcome mislabeling:** the first draft collapsed every non-`SUCCESS` admission outcome into
  `AUTHORITY_REJECTION`, which would have mislabeled a genuine `CONFLICT` (idempotency key reused with
  materially different intent) as an authority problem — exactly the "convert all failures into one generic
  state" anti-pattern §18 prohibits. Caught incidentally while debugging a stale-test-data issue, fixed by
  adding a distinct `CONFLICT` outcome and a dedicated test (`test_d03_conflict_distinguished_from_
  authority_rejection`).

A test-infrastructure bug (not a candidate defect) was also found and fixed: the test cleanup fixture's
`DELETE` order didn't account for `RunnerGovernanceDecision` rows keyed by `artifact_id` rather than
`execution_id` (a real fact about the schema, confirmed directly), causing a foreign-key violation during
cleanup. Fixed in `tests/conftest.py`.

---

## 13. Governance deviations

None. No frozen CPL requirement, WHAT, or invariant was found to be insufficient. No CPL modification was
made or requested. `COMMON_GAP = 0`, matching the Reality Check's own finding exactly.

---

## FINAL BUILDER REPORT

```text
Repository:            NEW (product-integration) — no existing repository found under any checked name
Branch:                    pi-01-vir-integration-candidate
Candidate SHA:                 reported in the accompanying build handoff (see §1)
Tree SHA:                          reported in the accompanying build handoff (see §1)

CPL software baseline:
  6181dabb9239e281974c368ad8f5df80350cabf1

CPL Reality Check governance SHA:
  306f3732d1862f7368eb46d0366683fa9b55e1e2

VIR full baseline SHA:
  a342aba7cc2fc517621f4fc79c3191bdfdc9e10b

PostgreSQL version:
  16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)

CPL migration head:
  027 (unchanged, zero new migrations)

Tests:
  32 passed / 0 failed / 0 skipped (PI-01's own suite)
  227 passed / 0 failed (CPL regression, unmodified)
  103 passed / 0 failed (VIR regression, unmodified)

PI-01 acceptance:
  PASS (definitive 16-step scenario, §26, including restart-persistence proof)

Blocking findings:
  0

Governance deviations:
  0

FINAL STATE:
  CANDIDATE_COMPLETE
```
