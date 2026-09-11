# PI_05_INDEPENDENT_VERIFICATION_v0

## 1. Candidate identity

```text
Repository:        https://github.com/paxtonef/cpl-product-integration.git
Branch:                pi-05-product-api-candidate
Pinned SHA:                7bd1da6645f265a9644b34cdb078b7f3d7f26664
Product-integration base:      5e8858d2f114edbed424b56b865997ac41fe84c7

git checkout --detach 7bd1da6645f265a9644b34cdb078b7f3d7f26664
git rev-parse HEAD    -> 7bd1da6645f265a9644b34cdb078b7f3d7f26664   MATCH
git status --short    -> (empty)                                    CLEAN
```

`CANDIDATE_SHA = PASS`.

---

## 2. Fresh environment

```text
Entirely new workspace: /home/claude/pi05_iv — no reuse of the builder's venv, dependency checkouts, or
  database.
Fresh clones: product-integration, CPL, VIR, PGDR, all at their exact pinned baselines, independently
  resolved and confirmed unchanged (no drift across the entire PI-01 through PI-05 lifecycle).
New PostgreSQL role (pi05iv), new database, fresh migrations through 027.
New Python venv, independently installed.
```

---

## 3. Versions

```text
FastAPI: 0.141.1
Pydantic: 2.13.5
Python: 3.12.3
PostgreSQL: 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)
```

App boots, routes register, OpenAPI generates, dependency injection works — confirmed independently (§20
below).

---

## 4. Route inventory — independently enumerated

```text
POST   /contacts                                               -> contact/account
GET    /contacts/{contact_id}                                      -> contact/account
POST   /vehicles                                                    -> vehicle registration
POST   /cases                                                           -> Case journey initialization + VIR
                                                                            invocation
POST   /cases/{case_id}/vir/clarifications                                 -> VIR clarification
GET    /cases/{case_id}                                                        -> Case status
GET    /cases/{case_id}/history                                                    -> history
POST   /cases/{case_id}/diagnostics                                                    -> PGDR start
POST   /cases/{case_id}/diagnostics/{execution_id}/answers                                 -> PGDR
                                                                                               continuation
GET    /executions/{execution_id}                                                              -> execution
                                                                                                   status
                                                                                                   polling
GET    /executions/{execution_id}/artifact                                                         -> artifact/
                                                                                                       result
                                                                                                       retrieval
```

Independently confirmed via `app.openapi()`: exactly 11 paths, matching this enumeration exactly. Every
required capability (§2 of this instruction) maps to a reachable route — no gap.

`ROUTE SURFACE = PASS`.

---

## 5. PI-04 reuse audit — independently read, not trusted from evidence

Read `routes.py` in full directly. Confirmed: `register_vehicle_for_contact`, `resolve_vehicle_identity`,
`start_vehicle_diagnostic`, `continue_vehicle_diagnostic` are called exactly as PI-04 exports them, with no
reimplementation of their internal logic anywhere in the route handlers. Two routes intentionally reach past
PI-04 (contact-only creation/retrieval via CPL's own `create_contact`/`get_contact`; VIR clarification via
PI-01's own `register_vir_resolution_result`, plus PI-04's own internal `_sync_case_with_execution`
primitive for the resulting Case sync) — confirmed these are the exact two capabilities PI-04 itself doesn't
wrap (verified independently against PI-04's own four-function public surface), not a broader pattern of
bypassing PI-04.

`PI-04 REUSE = PASS`.

---

## 6. Two minor, non-blocking findings from direct source read

**PI-05-VF-01 (non-blocking)**: `_build_real_vir_request` (`routes.py`) is defined but never called anywhere
— confirmed by `grep`. Dead code; no functional consequence, since `start_case_route` constructs its VIR
request inline instead. Cosmetic only.

**PI-05-VF-02 (non-blocking)**: the resource-consistency check in `submit_answer_route` confirms
`execution.case_id == case_id` but does not additionally confirm `execution.runner_type == "PGDR"`.
Independently tested: passing a VIR execution_id (genuinely belonging to the same case) to the PGDR-answer
endpoint is still safely rejected (confirmed — `409`, no silent success, no corruption), but via the
`PROCESS_LOCAL_STATE_UNAVAILABLE` category rather than a clearer `CROSS_RESOURCE_MISMATCH`/`NOT_FOUND`-style
message, since a VIR execution is correctly never present in the PGDR registry. The rejection itself is
correct and safe; only the error message's precision is imperfect.

Neither finding is blocking: no silent success, no data corruption, no bypass of any real check occurs in
either case.

---

## 7. HTTP-only rule audit (§7, mandatory)

Independently `grep`'d the candidate's own test file for any direct call to `resolve_vehicle_identity`/
`start_vehicle_diagnostic`/`continue_vehicle_diagnostic`/`register_vehicle_for_contact` — zero hits outside
legitimate non-HTTP *setup* (the PI-02-refusal test's use of PI-01's own `register_vir_resolution_result`,
exactly matching the already-established, already-accepted pattern from PI-04's own independent verification,
since the refused status is not reachable through the live VIR stub's `resolve()` engine). No test-code
shortcut bypasses the actual HTTP surface for any journey transition.

`HTTP-ONLY RULE = PASS`.

---

## 8. Full HTTP happy path — independently reproduced (§32, mandatory)

Ran an entirely independent, self-written script (not copied from the candidate's tests): `POST /vehicles` →
`POST /cases` (real VIR via ASGI) → `POST /diagnostics` (real PGDR, `BLOCKED`) → real answer submissions →
`COMPLETED` → artifact/execution/history retrieval — all confirmed. Also reproduced the candidate's own test
suite fresh (§14 below).

---

## 9. Full HTTP clarification path — independently confirmed via reproduced suite (§33, mandatory)

The candidate's own `test_clarification_path_http_only` was reproduced fresh (§14): real AMBIGUOUS fixture,
real `clarification_questions` retrieved via HTTP, real clarification submission, confirmed a **new** VIR
execution for the clarified result (no duplicate fresh resolve), confirmed via `/history`.

---

## 10. Full HTTP BLOCKED path — independently reproduced with genuine concurrency (§34, mandatory)

Beyond the candidate's own sequential test, independently fired **5 genuinely concurrent** `POST /diagnostics`
requests (`asyncio.gather`, real concurrency within the ASGI transport, not sequential retries) against the
same Case:

```text
Result: all 5 responses returned the SAME execution_id, all 201/BLOCKED.
Independently queried: exactly 1 PGDR RunnerExecution row exists for this case.
```

This is a genuinely stronger proof of idempotency-under-load than the candidate's own coverage (which only
tests two sequential repeated calls).

---

## 11. Process-restart continuation — the critical frontier test, independently and rigorously re-run (§16, mandatory)

Wrote an entirely independent reproduction: Phase 1 (pre-restart) constructs one `FastAPI` app instance, one
`httpx.AsyncClient`, drives a real diagnostic to `BLOCKED`, then **explicitly deletes** the app/transport/
client objects (`del client1, transport1, app1`) to ensure nothing from that context survives in this
verification's own script. Phase 2 constructs a **genuinely separate** `FastAPI` app instance with a fresh,
empty `PGDRSessionRegistry` and a new `httpx.AsyncClient` — as close to "recreate the app context" as
achievable without literally forking a new OS process, and using the same mechanism (fresh registry) that a
true process restart would produce (the registry is the *only* process-local state involved; there is no
other in-memory structure this candidate's design depends on).

```text
Pre-continuation-attempt: independently queried GET /executions/{id} confirms execution_status == "BLOCKED"
  (durable, DB-backed truth, unaffected by any in-memory state).

Continuation attempt result:
  status_code: 409 (never 500, never a silent 200)
  error_category: "PROCESS_LOCAL_STATE_UNAVAILABLE"
  No "Traceback" or exception-raising language anywhere in the response body (explicitly asserted).

Post-attempt state, independently re-queried:
  PGDR execution_status: still "BLOCKED" -- unchanged, uncorrupted.
  Case.case_status: still "WAITING_FOR_USER" -- unchanged, uncorrupted.
```

**Classification determination** (this verification's own independent judgment, not accepted from the
candidate's evidence without scrutiny): per this instruction's own §16, the question is whether "entire
journey is drivable via HTTP alone" remains true "under the intended operating model." This project has
already, repeatedly, and consistently answered the equivalent question for the identical underlying PGDR
limitation at every prior PI unit that encountered it (PI-03's own independent verification and repair,
PI-04's own independent verification and repair) — in every case, the limitation was classified `PRODUCT_GAP`
(carried, disclosed, non-blocking), never `PRODUCT_GAP_BLOCKING` or `COMMON_GAP`, because the required
capability was fully demonstrated within one continuously-running process (the operational model each of
those units' own done-condition was evaluated against). This verification independently confirms the same
holds for PI-05: §8-§10 above prove, using genuinely separate HTTP requests (and, beyond the candidate's own
coverage, genuine concurrency) within one process, that the entire governed journey **is** drivable via HTTP
alone. The process-restart scenario is a real, additional, narrower, and correctly-anticipated test (this
instruction's own §16 names it as a distinct, separate check with its own classification guidance) — not a
redefinition of the done condition itself. Applying `PRODUCT_GAP_BLOCKING` here, when the identical
limitation was not applied at PI-03 or PI-04, would be an inconsistent standard for the same underlying fact.

```text
PROCESS-RESTART CONTINUATION = PRODUCT_GAP (non-blocking, carried, honestly surfaced)
```

---

## 12. Execution status polling (§17)

Independently confirmed across `BLOCKED` (§10/§11), `COMPLETED` (§8, §13 below), and the failure condition
(§11's post-attempt query) — all responses matched independently-queried persisted state.

---

## 13. PI-02 refusal / ESCALATED — independently reproduced (§21/§22, mandatory)

```text
PI-02 refusal: real Path-B setup (matching the established pattern from PI-04's own verification), then a
  genuine HTTP POST /diagnostics call -- confirmed 200 (nothing created), outcome PI02_HANDOFF_REFUSED, zero
  PGDR executions in history.
ESCALATED: a real complaint matching PGDR's actual SafetyEngine rule, driven via genuine HTTP -- confirmed
  201, outcome COMPLETED, execution_status == "COMPLETED" (never "FAILED").
```

Both independently reproduced from fresh, self-written scripts, not copied from the candidate's tests.

---

## 14. Candidate's own test suite — independently reproduced in full

```text
python -m pytest tests/test_product_api.py -v: 13 passed, 0 failed
```

All 13 tests reproduced independently, including `test_case_orchestration_failure_mapped_correctly` (§15
below) and `test_process_restart_continuation_surfaces_limitation_honestly` (matches §11's independent
reproduction above).

---

## 15. Case orchestration failure mapping — independently confirmed (§23, mandatory)

Reproduced the candidate's own test: a genuine `transition_case_status` failure injected, driven through
real `POST /diagnostics`. Confirmed `502`, `error_category == "CASE_ORCHESTRATION_FAILURE"`, no raw exception
text or traceback anywhere in the response body, `case_id`/`execution_id` present for reconciliation. This
category is confirmed genuinely distinct from `PGDR_TECHNICAL_FAILURE` and `CPL_PERSISTENCE_FAILURE` by
direct source read of `errors.py`'s own `_CATEGORY_TO_STATUS` mapping — all three are separate dictionary
entries with independently-documented meanings.

---

## 16. Error model / HTTP status mapping — independently audited (§24/§25)

Read `errors.py` in full. Confirmed distinct categories exist for: not found, cross-resource mismatch,
authority rejection, conflict, VIR technical failure, VIR non-resolution, PGDR technical failure, CPL
persistence failure, Case orchestration failure, process-local state unavailable, and an unexpected/last-
resort category — 11 distinct categories, none collapsed into a single generic 500 except the genuinely
unclassified fallback. Independently confirmed the one gap present in the original candidate build (BLOCKED/
COMPLETED-only branching silently allowing failure outcomes through as 200) was found and fixed by the
candidate's own build process itself, per its own evidence document — independently re-confirmed fixed via
§15 above.

---

## 17. Resource relationship check (§26)

Independently tested beyond the candidate's own `test_cross_resource_mismatch_rejected` (§7 of this report's
adversarial coverage): a VIR execution_id from the *same* case passed to the PGDR-answer endpoint — confirmed
safely rejected (409), never silently accepted, though via a category (§6's PI-05-VF-02) that could be more
precise. No actual authorization bypass found in either case.

---

## 18. Repeated HTTP calls (§27)

Independently confirmed: repeated vehicle registration (same idempotency keys) returns identical
`contact_id`/`asset_id`; repeated `POST /diagnostics` against an already-`BLOCKED` case (including under
genuine concurrency, §10) returns the same `execution_id`, never a duplicate `RunnerExecution` row.

---

## 19. Transaction boundary (§28)

Independently confirmed via `pg_stat_activity` (server-side, not merely a second client query): zero
backends hold any open transaction after a `BLOCKED` HTTP response.

---

## 20. Real PostgreSQL / Real VIR / Real PGDR / OpenAPI (§29-31, §36)

```text
PostgreSQL 16.15, fresh role/database, migrations applied from empty through 027 -- confirmed throughout.
Real VIR: httpx.ASGITransport against VIR's actual FastAPI app -- never a fake response, confirmed throughout.
Real PGDR: production-default SessionController via PI-03, confirmed throughout.
OpenAPI: app.openapi() succeeds, 11 paths, matching the independently-enumerated route inventory exactly.
```

---

## 21. Restart durability (§35)

Independently reproduced the candidate's own `test_full_journey_retrievable_after_fresh_session`: after a
completed journey, a genuinely new `FastAPI` app instance and new `httpx.AsyncClient` retrieve the Case,
history, and artifact — all correctly present.

---

## 22. Candidate evidence audit (§37)

Every material claim in `docs/build/PI_05_PRODUCT_API_CANDIDATE_EVIDENCE_v0.md` was checked independently:
base/candidate/tree SHAs, route inventory, versions, error mapping, HTTP status mapping, all mandatory HTTP
journeys, real VIR/PGDR/PostgreSQL, OpenAPI, test counts (13 + 136), scope, `COMMON_GAP`, `PRODUCT_GAP_
BLOCKING` — **all confirmed accurate**. The evidence document's own §4 (the diagnostic-failure-mapping bug
found and fixed during the build) was independently confirmed accurate and the fix independently re-verified
working (§15). This verification's own findings (§6) go slightly beyond the candidate's own evidence — dead
code and an error-category imprecision — but neither contradicts any claim the evidence document makes; both
are new observations, not corrections.

---

## 23. Full regression (§38)

```text
Combined suite (PI-01's 41 + PI-02's 42 + PI-03's 19 + PI-04's 21 + PI-05's 13): 136 passed, 0 failed, 0 skipped
```

Independently reproduced, not copied from the candidate's own count.

---

## 24. Scope audit (§39)

```text
git diff --stat 5e8858d..7bd1da6: exactly 10 files (1 modified: pyproject.toml, +1 dependency; 9 new). Zero
  other file modified.
CPL, VIR, PGDR dependency checkouts: git status clean in all three -- none touched.
grep for React/JSX/TSX/Next/Vite in the candidate's own diff: zero hits.
```

`SCOPE_VIOLATION: NONE FOUND` beyond the two non-blocking findings (§6), which are correctness/cosmetic
observations, not scope violations.

---

## 25. COMMON_GAP / PRODUCT_GAP assessment

```text
COMMON_GAP: 0
```

Nothing about CPL's own primitives is implicated anywhere in this verification. The process-restart
limitation (§11) is entirely a PGDR-design characteristic (its `SessionController` is purely in-memory,
confirmed at PI-03's own original build and independently re-confirmed unchanged at every subsequent PI
unit's verification pass, including this one) — not a CPL deficiency.

```text
PRODUCT_GAP_BLOCKING: NO
```

Per §11's reasoning above.

---

## 26. Findings register

**PI-05-VF-01** — non-blocking. Dead code (`_build_real_vir_request`), no functional consequence.

**PI-05-VF-02** — non-blocking. `submit_answer_route`'s resource-consistency check does not verify
`runner_type == "PGDR"`; a same-case VIR execution_id is still safely rejected (via `PROCESS_LOCAL_STATE_
UNAVAILABLE` rather than a more precise category). No bypass, no corruption, no silent success.

No `BLOCKING` finding.

---

## 27. Governance deviations

None.

---

## 28. Final verdict

```text
PI_05_VERIFIED
```

Every requirement in §44 of this verification instruction is met: candidate reproduced, required route
surface confirmed complete (11 routes, independently enumerated), HTTP-only happy path/clarification/BLOCKED-
continuation all independently reproduced and strengthened (genuine concurrency beyond the candidate's own
coverage), execution polling/artifact retrieval/history all `PASS`, PI-02 refusal/ESCALATED/Case orchestration
failure mapping all independently reproduced and `PASS`, restart durability `PASS`, OpenAPI `PASS`, real
PostgreSQL/VIR/PGDR throughout, full regression `PASS`, zero blocking findings. Process-restart continuation
independently and rigorously re-tested, confirmed to behave exactly as the candidate claims (clean typed
409, zero corruption), and independently classified — after deliberate consideration of this project's own
established precedent for the identical underlying limitation — as `PRODUCT_GAP`, not `PRODUCT_GAP_BLOCKING`.

---

## PI-05 INDEPENDENT VERIFICATION

```text
Repository:
  https://github.com/paxtonef/cpl-product-integration.git

Base:
  5e8858d2f114edbed424b56b865997ac41fe84c7

Candidate:
  7bd1da6645f265a9644b34cdb078b7f3d7f26664

Branch:
  pi-05-product-api-candidate

Candidate SHA:
  PASS

FastAPI:
  0.141.1

Python:
  3.12.3

PostgreSQL:
  16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)

Route surface:
  PASS

Contact/account:
  PASS

Vehicle registration:
  PASS

Case journey:
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

HTTP happy path:
  PASS

HTTP clarification:
  PASS

HTTP BLOCKED continuation:
  PASS

Process-restart continuation:
  PRODUCT_GAP

PI-02 refusal:
  PASS

ESCALATED:
  PASS

Case orchestration failure mapping:
  PASS

Restart durability:
  PASS

OpenAPI:
  PASS

Real PostgreSQL:
  PASS

Real VIR:
  PASS

Real PGDR:
  PASS

Tests:
  136 passed / 0 failed (independently reproduced)

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

Non-blocking findings:
  2 (PI-05-VF-01, PI-05-VF-02)

Governance deviations:
  0

FINAL VERDICT:
  PI_05_VERIFIED
```

## STOP

**STOP.** This verification does not repair, does not merge, and does not start PI-06.
