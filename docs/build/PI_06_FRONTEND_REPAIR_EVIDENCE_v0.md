# PI_06_FRONTEND_REPAIR_EVIDENCE_v0

## 1. Identity

```text
Original frontend candidate:      c7c659ac47cc38f1e36fa4a89fc73755449e4e5b
Independent verification SHA:         89a53b9848a9292c7b36b3c87b58c31557c8826b
Repair branch:                            pi-06-frontend-repair-candidate
Repair candidate SHA:                         reported in the accompanying build handoff
Tree SHA:                                         reported in the accompanying build handoff
```

---

## 2. PI-06-VF-03 — ambiguous Playwright VIN locator

**Root cause**: `tests/e2e/helpers.ts`'s `registerAndResolveVehicle` used `page.getByLabel('VIN')` without
exact matching. Playwright's accessible-name matching is substring-based by default, and the literal string
"VIN" is itself a substring of the newer field's own label ("Registration number (if you don't have the
VIN)"), producing an ambiguous, strict-mode-violating match.

**Repair**: `page.getByLabel('VIN', { exact: true })` — the minimal fix, consistent with this file's existing
convention of targeting fields by label text throughout (not switching to CSS id selectors for this one
field alone). No application label was changed to make the test pass; the defect was entirely in test
targeting, per the repair instruction's own framing.

**Regression proof**: every one of the repaired suite's 12 test cases now proceeds past vehicle registration
(§7 below) — the exact requirement stated in the repair instruction's §3.

**A second, related defect found and fixed during this repair, not originally itemized as VF-03 but part of
the same "E2E can't reliably drive the app" problem class**: `answerCurrentQuestion`'s own select-vs-input
branch used a one-shot `.count()` snapshot, which could observe a transitional DOM state between one
question's component unmounting and the next mounting (a direct consequence of the VF-04 fix's `key`
addition — see §3) and commit to the wrong branch. Fixed by waiting for the `#answer` control to be
genuinely attached and enabled before inspecting its tag name, plus a short settle wait matched to the real
backend's own real network latency. Applied consistently in `helpers.ts` and the two other spec files that
had the same pattern (`e-pgdr-multiple-questions.spec.ts`, `k-process-restart-continuation.spec.ts`).

```text
PI-06-VF-03 = CLOSED
```

---

## 3. PI-06-VF-04 — DiagnosticQuestionForm remains disabled after first successful answer

**Root cause, confirmed by direct source read**: `DiagnosticQuestionForm.handleSubmit` called `setStatus
('submitting')`, then on success called `onAnswered(result)` — but never called `setStatus('ready')` on that
path (only the `catch` block did). Combined with `Diagnostic.tsx` rendering `<DiagnosticQuestionForm ... />`
at the same tree position across question changes with no distinguishing `key`, React reused the same
component instance, and its stale `status === 'submitting'` (and therefore `disabled={status ===
'submitting'}`) persisted indefinitely into every subsequent question.

**Repair, both layers, per the repair instruction's own requirement**:

1. `DiagnosticQuestionForm.tsx`: `setStatus('ready')` (and `setValue('')`) now called immediately before
   `onAnswered(result)` on the success path.
2. `Diagnostic.tsx`: `<DiagnosticQuestionForm key={current.pending_questions[0].question_id} ... />` — keyed
   by `question_id`, the actual stable identifier `DiagnosticQuestionSchema` provides (confirmed against the
   real PI-05 contract — no synthetic identity invented), so React genuinely mounts a fresh instance per
   question. Fix #1 is correct and sufficient on its own; fix #2 makes the correctness structural rather than
   dependent on remembering to reset state correctly in every future code path that renders this form.

**Question identity (§5 of the repair instruction)**: `question_id` is the real, stable field PI-05 returns
per question (confirmed against `DiagnosticQuestionSchema` in `schemas.py`) — used directly, not invented.

---

## 4. Multi-question regression proof (§6 of the repair instruction)

`tests/e2e/e-pgdr-multiple-questions.spec.ts`, run against real PI-05/VIR/PGDR/PostgreSQL:

```text
7 real, consecutive BLOCKED/answer cycles completed (the real NOISE_COMPLAINT fixture, confirmed to require
  more than one question -- asserted explicitly, not merely tolerated) -- far exceeding the "at least two"
  minimum.
Same Case, same single PGDR RunnerExecution confirmed via real GET /cases/{id}/history after the full cycle:
  exactly 1 PGDR execution, execution_status "COMPLETED" -- no duplicate diagnostic start.
```

Independently step-debugged before this: a targeted script confirmed `select#answer`'s `disabled` attribute
is `false` immediately after question 1 is answered (was `true`, stuck, before the repair).

```text
PI-06-VF-04 = CLOSED
```

---

## 5. PI-06-VF-05 — navigation mapping repair

**Actual backend semantics, confirmed by direct query against the real backend (not assumed)**:

```text
A real VIR clarification case (registration_number "AM-BIG-01", real AMBIGUOUS fixture):
  vir_resolution_status: "AMBIGUOUS"
  GET /cases/{id} -> case_status: "IN_PROGRESS"

A real PI-02-refused case (provider_unavailable, via PI-01's own Path B):
  POST /cases/{id}/diagnostics -> outcome: "PI02_HANDOFF_REFUSED"
  GET /cases/{id} (AFTER the diagnostics attempt) -> case_status: "WAITING_FOR_EXTERNAL_INFORMATION"
```

**Repair**: `decideScreen` (`src/state/navigation.ts`) now takes a third parameter, `clarificationAvailable`,
derived from the actual VIR resolution (not from `case_status` name alone):

```text
case_status "WAITING_FOR_EXTERNAL_INFORMATION"           -> 'refusal' (a new screen state; this status is set
                                                              only after a genuine PI-02 refusal, never for a
                                                              clarification-needed VIR result)
case_status "IN_PROGRESS" + no PGDR execution +
  clarificationAvailable=true                                -> 'clarification'
case_status "IN_PROGRESS" + no PGDR execution + false            -> 'case-hub' (unchanged)
```

`clarificationAvailable` is computed in `JourneyShell.tsx`'s `useCaseJourney` hook: when `case_status` is
`IN_PROGRESS` with no PGDR execution yet, the latest VIR execution's artifact is fetched once, and
`clarificationAvailable = resolution_status.toLowerCase() === 'ambiguous' && clarification_questions.length >
0` — using only existing, already-fetched PI-05 data, no new backend field.

`Diagnostic.tsx` (the route `'refusal'` maps to) now renders `RefusalPanel` directly when `state.screen ===
'refusal'`, without re-attempting the diagnostic start that already produced this result, and without ever
falling into the clarification fallback message.

```text
PI-06-VF-05 = CLOSED
```

---

## 6. Navigation unit tests (§19 of the repair instruction)

`tests/unit/navigation.test.ts`, "CASE A" and "CASE B", encode the observed backend semantics directly:

```text
CASE A: decideScreen(IN_PROGRESS, false, true) -> 'clarification'                    PASS
CASE B: decideScreen(WAITING_FOR_EXTERNAL_INFORMATION, false, false) -> 'refusal'         PASS
        decideScreen(WAITING_FOR_EXTERNAL_INFORMATION, false, true) -> 'refusal' (never
          overridden by a clarification signal)                                              PASS
```

8 tests total (was 7), all passing.

---

## 7. Question-form unit/component tests (§20)

`tests/unit/DiagnosticQuestionForm.test.tsx` (new): render question 1 -> submit success -> form returns to
enabled (the direct VF-04 regression proof at the component level, independent of the real browser run);
submitting disables the form while the request is in flight; failure returns the form to usable state
(already-correct path, confirmed unaffected); a fresh keyed instance for a new question always mounts
enabled. 3 tests, all passing.

---

## 8. Canonical 11 acceptance journeys — 11/11 PASS (12 test cases)

Run against real PI-05, real PostgreSQL, real VIR, real PGDR, using the same "real system Chrome via a local,
uncommitted `launchOptions.executablePath` override" mechanism independent verification established (this
build environment has no network path to `cdn.playwright.dev`; no candidate file was modified to enable
this):

```text
A. happy path                                    PASS (4.9s) -- 7 real questions, terminal result, history
B. VIR clarification                                 PASS (1.4s) -- AUTOMATIC navigation to /clarification
                                                        confirmed (no manual goto), full submit-and-continue
C. PI-02 refusal                                         PASS (1.4s) -- real Path-B fixture (own setup
                                                            script, no skipped env-var dependency), truthful
                                                            RefusalPanel shown, zero PGDR executions
D. PGDR one-question BLOCKED                                 PASS (1.7s)
E. PGDR multiple-question (also VF-04's primary                 PASS (4.1s) -- 7 questions, same Case/
     regression proof)                                             execution throughout (§4)
F. ESCALATED                                                         PASS (1.4s) -- unaffected by either
                                                                         repair, re-confirmed regression-free
G. browser refresh mid-diagnostic                                        PASS (1.8-2.1s)
H. return to existing Case (new context)                                    PASS (1.6s)
H2. Entry screen return-to-Case form                                            PASS (1.2s)
I. technical failure                                                                PASS (1.3-1.5s)
J. orchestration failure                                                                PASS (1.2-1.3s)
K. process-restart continuation                                                             PASS (1.4-1.6s)

TOTAL: 12/12 test cases PASS, reproduced twice consecutively for stability -- identical results both times.
```

`11/11 canonical acceptance journeys PASS` (12 test cases, H split into H/H2 as in the original candidate).

---

## 9. Playwright results / production build / frontend static checks

```text
npm install:                    clean
npx tsc -b --noEmit:                 PASS, zero type errors
npx vitest run:                          15 passed, 0 failed (4 test files -- up from 3; DiagnosticQuestionForm.
                                            test.tsx is new)
npx vite build:                              PASS -- 54 modules, dist/assets/index-*.js 183.69 kB (58.68 kB
                                                gzip)
npx playwright test (real browser, real backend): 12 passed, 0 failed (§8 above)
```

---

## 10. Real backend/browser evidence

```text
Real PI-05:      python -m uvicorn product_integration.api.app:app, real DATABASE_URL, GET /openapi.json ->
                    200, 11 paths
Real PostgreSQL:     16.15, fresh role/database (pi06repair_test), migrations applied through 027
Real VIR:                python -m uvicorn vir.api.routes:app on port 80, reached via a hosts-file entry
                            (127.0.0.1 vir-service.internal) resolving PI-05's own unmodified hardcoded
                            VIR_BASE_URL -- local machine configuration, not a code change
Real PGDR:                    confirmed via real, dynamically-generated question text observed during the
                                 E2E runs (7 real questions in Journey A/E, none of them fixture/mock text)
Real browser:                      Chromium 141 (/opt/google/chrome/chrome), launched via a local, uncommitted
                                      Playwright config override -- never part of the committed candidate
```

---

## 11. Backend regression

```text
python -m pytest tests/ -q: 136 passed, 0 failed, 0 skipped
```

Matches the pre-existing baseline exactly (41+42+19+21+13). Zero regression. Backend tests were not modified.

---

## 12. Files modified

```text
Modified (8):
  frontend/src/components/DiagnosticQuestionForm.tsx    (VF-04)
  frontend/src/components/JourneyShell.tsx                   (VF-05)
  frontend/src/routes/Diagnostic.tsx                              (VF-04 key, VF-05 refusal rendering)
  frontend/src/state/navigation.ts                                    (VF-05)
  frontend/tests/e2e/b-vir-clarification.spec.ts                          (VF-05 verification, strengthened)
  frontend/tests/e2e/c-pi02-refusal.spec.ts                                    (VF-05 verification, fixture
                                                                                  now self-contained)
  frontend/tests/e2e/e-pgdr-multiple-questions.spec.ts                            (VF-04 verification,
                                                                                     strengthened per §6)
  frontend/tests/e2e/helpers.ts                                                        (VF-03, plus the
                                                                                           related race-
                                                                                           condition fix)
  frontend/tests/e2e/k-process-restart-continuation.spec.ts                                 (same race-
                                                                                                condition fix
                                                                                                for
                                                                                                consistency)
  frontend/tests/unit/navigation.test.ts                                                        (VF-05
                                                                                                    regression
                                                                                                    tests)

New (2):
  frontend/tests/e2e/fixtures/setup_pi02_refusal_case.py    (VF-05/C verification -- real Path-B fixture
                                                                setup, not a backend endpoint)
  frontend/tests/unit/DiagnosticQuestionForm.test.tsx           (VF-04 regression test)
```

No unrelated frontend refactor. Every changed file traces directly to VF-03, VF-04, or VF-05.

---

## 13. Modification counts

```text
PI-05 modifications: 0
CPL modifications:       0
VIR modifications:           0
PGDR modifications:              0
New backend endpoint:                0
New migration:                           0
```

---

## 14. API gaps / structuring deviations

None. Everything used to repair these three findings was already-existing PI-05 data (`case_status`, VIR
artifact `clarification_questions`/`resolution_status`), consistent with the repair instruction's own §8/§26
requirement not to add backend fields. The structuring itself was never altered — same framework, same
screens, same routes, same acceptance journey definitions.

---

## 15. Findings

```text
Blocking:      0 (all three original findings closed, confirmed by real browser E2E, not merely by code
                    inspection)
Non-blocking:      0 new
```

---

## PI-06 FRONTEND REPAIR

```text
Repository:
  https://github.com/paxtonef/cpl-product-integration.git

Original candidate:
  c7c659ac47cc38f1e36fa4a89fc73755449e4e5b

Independent verification:
  89a53b9848a9292c7b36b3c87b58c31557c8826b

Repair branch:
  pi-06-frontend-repair-candidate

Repair candidate SHA:
  reported in the accompanying build handoff

Tree SHA:
  reported in the accompanying build handoff

PI-06-VF-03:
  CLOSED

VIN locator:
  PASS

Candidate E2E suite:
  12/12 passed

PI-06-VF-04:
  CLOSED

Question 2 enabled:
  PASS

Multi-question flow:
  PASS (7 real questions)

Same Case:
  PASS

Same PGDR execution:
  PASS

PI-06-VF-05:
  CLOSED

AMBIGUOUS -> Clarification:
  PASS

PI-02 refusal -> Refusal:
  PASS

Clarification browser journey:
  PASS

Refusal browser journey:
  PASS

ESCALATED regression:
  PASS

Canonical acceptance journeys:
  11/11 (12 test cases)

Production build:
  PASS

Frontend tests:
  15 passed / 0 failed (unit/component)

Real PI-05:
  PASS

Real PostgreSQL:
  PASS

Real VIR:
  PASS

Real PGDR:
  PASS

Backend regression:
  136 passed / 0 failed

PI-05 modifications:
  0

CPL modifications:
  0

VIR modifications:
  0

PGDR modifications:
  0

API gaps:
  NONE

Structuring deviations:
  NONE

Blocking findings:
  0

FINAL STATE:
  FRONTEND_REPAIR_CANDIDATE_COMPLETE
```
