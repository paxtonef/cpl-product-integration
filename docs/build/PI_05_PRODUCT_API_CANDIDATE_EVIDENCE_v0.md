# PI_05_PRODUCT_API_CANDIDATE_EVIDENCE_v0

## 1. Identity

```text
Base SHA:                          5e8858d2f114edbed424b56b865997ac41fe84c7  (PI-04 closure, main)
Candidate branch:                      pi-05-product-api-candidate
Candidate SHA:                             reported in the accompanying build handoff
Tree SHA:                                      reported in the accompanying build handoff

FastAPI:                    0.141.1
Python:                         3.12.3
PostgreSQL:                         16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)
CPL software baseline:      6181dabb9239e281974c368ad8f5df80350cabf1 (unchanged, pinned)
CPL migration head:             027 (unchanged, zero new migrations)
VIR full SHA:                       a342aba7cc2fc517621f4fc79c3191bdfdc9e10b (confirmed unchanged since
                                       every prior reference in this project)
PGDR full SHA:                          0580b1a5ba5867a607a33197372fcaf4164f0fb6 (confirmed unchanged)
```

---

## 2. Route inventory

```text
POST   /contacts                                              create contact (CPL create_contact, direct --
                                                                  PI-04 has no contact-only wrapper)
GET    /contacts/{contact_id}                                     retrieve contact (CPL get_contact, direct)
POST   /vehicles                                                   register_vehicle_for_contact (PI-04)
POST   /cases                                                          resolve_vehicle_identity (PI-04 --
                                                                          Case creation + VIR admission,
                                                                          matching PI-04's own coupled
                                                                          granularity)
POST   /cases/{case_id}/vir/clarifications                                VIR clarification (PI-01's
                                                                              register_vir_resolution_result,
                                                                              Path B, direct -- PI-04 has no
                                                                              clarification wrapper)
GET    /cases/{case_id}                                                       Case status (direct read)
GET    /cases/{case_id}/history                                                   Case history (direct read)
POST   /cases/{case_id}/diagnostics                                                   start_vehicle_diagnostic
                                                                                          (PI-04)
POST   /cases/{case_id}/diagnostics/{execution_id}/answers                                continue_vehicle_
                                                                                              diagnostic (PI-04)
GET    /executions/{execution_id}                                                             execution status
                                                                                                  (direct read)
GET    /executions/{execution_id}/artifact                                                        artifact
                                                                                                      retrieval
                                                                                                      (direct
                                                                                                      read)
```

11 routes total, resource-oriented, matching every capability §19 requires — no speculative endpoints.

---

## 3. Two intentional direct-CPL/PI-01 reuses (not PI-04 duplication)

**Contact-only creation/retrieval** (§8): PI-04's `register_vehicle_for_contact` always couples Contact with
Asset creation; it has no contact-only entry point. `POST /contacts`/`GET /contacts/{id}` call CPL's own
`create_contact`/`get_contact` directly — the exact capability §6 explicitly permits reaching past PI-04 for
("use existing CPL/product-integration read paths ... without duplicating domain behavior"). No local Contact
model, no re-derived identity logic.

**VIR clarification** (§12): PI-04 exposes only fresh VIR resolution (`resolve_vehicle_identity`, Path A). The
clarification submission route calls PI-01's own `register_vir_resolution_result` (Path B) directly, plus
PI-04's own internal `_sync_case_with_execution` primitive (the exact honest-failure, single-transaction Case
sync PI-04-VF-01 produced) for the resulting `IN_PROGRESS` transition — reusing PI-04's own logic rather than
reimplementing a second Case-sync mechanism, which §16 explicitly forbids ("Do not create a second Case state
machine in the API layer").

---

## 4. A real bug found and fixed during this build

Initial route implementations for `start_vehicle_diagnostic`/`continue_vehicle_diagnostic` only branched HTTP
status on `BLOCKED`/`COMPLETED` — a genuine `CASE_ORCHESTRATION_FAILURE`/`PGDR_TECHNICAL_FAILURE`/`CPL_
PERSISTENCE_FAILURE` outcome from PI-04 silently fell through as an HTTP 200 success, discovered when testing
the Case-orchestration-failure path directly through real HTTP (not caught by the earlier happy-path/
clarification/refusal smoke tests, since none of those exercise a genuine failure outcome). Fixed by adding
an explicit `_raise_if_diagnostic_failure` check before constructing any success response in both diagnostic
routes, mapping each PI-03/PI-04 failure outcome to its documented `ProductAPIError` category. Confirmed fixed
via `test_case_orchestration_failure_mapped_correctly` — genuine 502, typed `CASE_ORCHESTRATION_FAILURE`, no
raw exception text anywhere in the response body.

---

## 5. HTTP status mapping (documented, §22)

```text
validation error (malformed body)                       -> 422 (FastAPI's own default)
resource not found                                           -> 404
cross-resource mismatch (§31)                                    -> 404 (see errors.py's own module
                                                                     docstring for the reasoning: without a
                                                                     real authentication layer, a 403 would
                                                                     claim more than this API can honestly
                                                                     know)
PI-02 handoff refusal                                                -> 200 (a real, informative product
                                                                          outcome, never an error; created
                                                                          nothing, so not 201)
PGDR BLOCKED                                                             -> 201 (a new PGDR RunnerExecution
                                                                              was genuinely created)
PGDR terminal (COMPLETED, including ESCALATED)                              -> 201 (start) / 200 (continue) --
                                                                                  never represented as failure
conflict / invalid continuation                                                 -> 409
authority rejection                                                                 -> 403
VIR/PGDR technical failure, CPL persistence failure,                                    -> 502 (upstream/
  Case orchestration failure                                                              integration
                                                                                             failure, not the
                                                                                              client's fault)
process-local PGDR state unavailable (§28/§46)                                                  -> 409
unexpected/unclassified                                                                             -> 500
                                                                                                        (last
                                                                                                        resort)
```

---

## 6. Process-local PGDR session registry — the honest answer to §28/§46

`api/registry.py`'s `PGDRSessionRegistry` is a plain, explicitly-documented, process-local in-memory dict
mapping `execution_id -> (SessionController, DiagnosticSession)` — not a database, not a new PGDR persistence
mechanism (forbidden). It is exactly the "process-local controller state" §28 itself anticipates and permits.
Within one running process, it lets genuinely separate HTTP requests share the same `SessionController`
instance for a given PGDR execution, making `BLOCKED`→`continue` work correctly across real, independent HTTP
calls (confirmed, §9 below). It is lost on process restart — confirmed and tested directly, not left
implicit (§10 below).

---

## 7. Files added / modified

```text
pyproject.toml                                             (+1 dependency: fastapi)
src/product_integration/api/__init__.py
src/product_integration/api/app.py                             (FastAPI factory)
src/product_integration/api/deps.py                                 (dependency injection)
src/product_integration/api/errors.py                                   (typed error taxonomy + HTTP mapping)
src/product_integration/api/registry.py                                     (process-local PGDR session
                                                                                registry)
src/product_integration/api/routes.py                                           (all 11 routes)
src/product_integration/api/schemas.py                                              (request/response
                                                                                        Pydantic models)
tests/test_product_api.py                                                               (13 tests, HTTP only)
```

No CPL file touched. No VIR file touched. No PGDR file touched. No new migration. No PI-06 frontend/React
code anywhere (confirmed: zero matches for React/JSX/TSX/Next/Vite in the diff).

---

## 8. Test environment

```text
PostgreSQL version:      16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)
CPL migration head:          027, applied fresh from an empty database
Command:                         python -m pytest tests/ -v
```

---

## 9. HTTP-only happy path (§37, mandatory)

`test_full_journey_http_only`: real HTTP calls only — `POST /vehicles` → `POST /cases` (real VIR resolution
via ASGI) → `GET /cases/{id}` → `POST /diagnostics` (real PGDR, `BLOCKED`) → repeated `POST /answers` (7 real
turns) → `COMPLETED` → `GET /executions/{id}/artifact` → `GET /executions/{id}` → `GET /cases/{id}/history`.
No direct Python call into `product_integration.orchestration.case_orchestration` anywhere in this test.
Confirmed: exactly one VIR execution, one PGDR execution, both retrievable via `/history`.

---

## 10. HTTP clarification path (§38, mandatory)

`test_clarification_path_http_only`: `POST /cases` with the known real AMBIGUOUS-triggering fixture
(`registration_number="AM-BIG-01"`) → genuine `clarification_questions` retrieved via
`GET /executions/{id}/artifact` → `POST /cases/{case_id}/vir/clarifications` with a real answer → confirmed a
**new** VIR execution for the clarified result (PI-01's own established pattern: a clarified resolution_id is
its own governed execution) and confirmed via `/history` that exactly 2 VIR executions exist total — no
duplicate *fresh* resolution was triggered merely to obtain the clarified result.

---

## 11. HTTP BLOCKED/continue path (§39, mandatory)

`test_blocked_continue_separate_requests`: the HTTP request that returns `BLOCKED` completes and closes fully;
a genuinely separate, later `httpx.AsyncClient` request submits the answer. Confirmed: same execution_id, no
duplicate, `current_execution_id` correctly updated. `test_no_open_transaction_across_blocked_wait`
independently confirms via `pg_stat_activity` (server-side) that zero backends hold any transaction after the
`BLOCKED` HTTP response.

---

## 12. HTTP PI-02 refusal path (§40, mandatory)

`test_refusal_via_http`: uses PI-01's own Path B (matching the exact pattern independently verified at PI-04's
own re-verification) to set up a real, persisted `provider_unavailable` VIR result — the SETUP, not the test
point. The actual test point (`POST /cases/{case_id}/diagnostics`) is real HTTP: confirmed `200` (nothing
created), outcome `PI02_HANDOFF_REFUSED`, zero PGDR executions in `/history`.

---

## 13. HTTP ESCALATED path (§41, mandatory)

`test_escalated_via_http`: a real complaint matching PGDR's actual `SafetyEngine` rule drives `POST /
diagnostics` straight to `COMPLETED` (escalated). Confirmed via `GET /executions/{id}`: `execution_status ==
"COMPLETED"`, never `"FAILED"`. Confirmed via `GET /cases/{id}`: `case_status == "RESOLVED"`.

---

## 14. HTTP Case orchestration failure (§42, mandatory)

`test_case_orchestration_failure_mapped_correctly`: a genuine PI-04-layer failure injected into `transition_
case_status`, driven through real `POST /diagnostics`. Confirmed: `502`, `error_category ==
"CASE_ORCHESTRATION_FAILURE"`, `case_id`/`execution_id` present for reconciliation, no raw exception text or
traceback anywhere in the response body (explicitly asserted).

---

## 15. Status polling (§43)

Exercised across every state in the test suite: `BLOCKED` (`test_blocked_continue_separate_requests`),
`COMPLETED` (`test_full_journey_http_only`, `test_escalated_via_http`), and the failure condition (`test_
process_restart_continuation_surfaces_limitation_honestly`'s post-attempt query, confirming the execution
remains `BLOCKED` and valid). All responses match independently-queried persisted state.

---

## 16. Artifact retrieval (§17)

Confirmed for both VIR (`test_clarification_path_http_only`) and PGDR (`test_full_journey_http_only`)
artifacts — real payload content, provenance (`execution_id`) preserved, no reinterpretation of domain output.

---

## 17. History (§18/§44)

`GET /cases/{case_id}/history` confirmed across the happy path (2 executions), clarification (2 VIR
executions), and refusal (0 PGDR executions) scenarios — built entirely from persisted governed state, never
from request-local memory.

---

## 18. Restart durability (§45)

`test_full_journey_retrievable_after_fresh_session`: after a completed journey, a genuinely new `FastAPI` app
instance, new dependency overrides, and new `httpx.AsyncClient` retrieve the Case, history, and artifact —
all correctly present.

---

## 19. Process-restart continuation check (§46, the critical PI-05 frontier test)

`test_process_restart_continuation_surfaces_limitation_honestly`: a `BLOCKED` diagnostic is started; a
genuinely fresh, empty `PGDRSessionRegistry` plus a new `FastAPI` app instance simulate process restart (same
database, no shared in-memory state). A later HTTP continuation attempt against the *same* execution_id:

```text
Result: 409, error_category = "PROCESS_LOCAL_STATE_UNAVAILABLE"
No raw exception. The underlying PGDR RunnerExecution remains queryable and correctly BLOCKED afterward --
  confirmed independently via GET /executions/{id}.
```

**Classification**: this is the same, already-known PGDR `SessionController` cross-instance limitation PI-03
disclosed and PI-04 carried forward — not a new gap PI-05 introduced. Per §51's own definition,
`PRODUCT_GAP_BLOCKING` applies only "if the complete product journey cannot genuinely be driven via HTTP using
the current closed PI-01..PI-04 capabilities." Within one continuously-running process — the operational model
every prior PI unit in this project has used to evaluate this exact limitation (`PRODUCT_GAP`, never
`PRODUCT_GAP_BLOCKING`, since "the current bounded operational model" fully supports the required journey) —
the entire governed journey **is** genuinely drivable via HTTP alone, proven by §9-§17 above using real,
separate HTTP requests throughout. The process-restart scenario is a narrower, explicitly-anticipated
additional test (§46 names it directly and provides its own classification guidance), not a redefinition of
the done condition (§54, which itself does not mention process-restart survival).

```text
PRODUCT_GAP_BLOCKING: NO
```

Carried forward explicitly: the underlying PGDR cross-instance session-reconstruction limitation is not
solved here, not disguised, and now has one additional, concrete, HTTP-level manifestation documented and
tested (surfaced as a clean, typed 409 rather than a crash or a silent false success).

---

## 20. OpenAPI schema (§47)

`test_openapi_schema_generates`: `app.openapi()` succeeds, produces a valid schema with all 11 routes present,
including `/cases` and `/cases/{case_id}/diagnostics`.

---

## 21. Full regression (§48)

```text
PI-05's own suite: 13 passed, 0 failed, 0 skipped
Combined suite (PI-01's 41 + PI-02's 42 + PI-03's 19 + PI-04's 21 + PI-05's 13): 136 passed, 0 failed, 0 skipped

Run three times total from completely fresh, dropped-and-recreated databases during this build — 136/136
every time, no flakiness.
```

---

## 22. Blocking findings

None.

---

## 23. Non-blocking findings

None new. PI-01/PI-02/PI-03's own carried findings remain unaffected — this candidate touches none of the
files they concern.

---

## 24. Governance deviations / COMMON_GAP status

```text
COMMON_GAP: 0
```

No CPL modification anywhere. Every capability PI-05 needed already existed in CPL, PI-01, or PI-04 —
composition and thin HTTP transport, not extension, was sufficient throughout.

---

## PI-05 CANDIDATE

```text
Repository:
  https://github.com/paxtonef/cpl-product-integration.git

Base:
  5e8858d2f114edbed424b56b865997ac41fe84c7

Branch:
  pi-05-product-api-candidate

Candidate SHA:
  reported in the accompanying build handoff

Tree SHA:
  reported in the accompanying build handoff

FastAPI:
  0.141.1

Python:
  3.12.3

PostgreSQL:
  16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)

CPL baseline:
  6181dabb9239e281974c368ad8f5df80350cabf1

CPL migration head:
  027

VIR baseline:
  a342aba7cc2fc517621f4fc79c3191bdfdc9e10b

PGDR baseline:
  0580b1a5ba5867a607a33197372fcaf4164f0fb6

Contact/account API:
  PASS

Vehicle registration API:
  PASS

Case journey API:
  PASS

VIR invocation:
  PASS

VIR clarification:
  PASS

PGDR invocation:
  PASS

PGDR answer submission:
  PASS

Execution polling:
  PASS

Artifact retrieval:
  PASS

History:
  PASS

HTTP-only happy path:
  PASS

HTTP-only clarification:
  PASS

HTTP-only BLOCKED continuation:
  PASS

PI-02 refusal:
  PASS

ESCALATED:
  PASS

Case orchestration failure mapping:
  PASS

Restart durability:
  PASS

Process-restart continuation:
  PRODUCT_GAP (non-blocking; known PGDR cross-instance limitation, honestly surfaced as a typed 409, does not
  prevent the journey being HTTP-drivable within the intended operational model)

OpenAPI:
  PASS

Real PostgreSQL:
  PASS

Real VIR:
  PASS

Real PGDR:
  PASS

PI-01 regression:
  PASS

PI-02 regression:
  PASS

PI-03 regression:
  PASS

PI-04 regression:
  PASS

Tests:
  13 (PI-05 own suite) + 136 (combined with PI-01/PI-02/PI-03/PI-04, real PostgreSQL, zero regression)

CPL modifications:
  0

VIR modifications:
  0

PGDR modifications:
  0

PI-06 leakage:
  0

COMMON_GAP:
  0

PRODUCT_GAP_BLOCKING:
  NO

Blocking findings:
  0

Governance deviations:
  0

FINAL STATE:
  CANDIDATE_COMPLETE
```
