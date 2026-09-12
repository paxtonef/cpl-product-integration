# PI_06_FRONTEND_CANDIDATE_EVIDENCE_v0

## 1. Identity

```text
Canonical baseline:      71ecd48e8dc939e47ad738e2f8ae55e3f4811fd0
Structuring SHA:              d476e517dd12cb7414395a61bd16a89832963aff
Structuring verification SHA:     d3b50ae4fbc60fee3d7c35803cf8d77525d04a7b
Frontend branch:                      pi-06-frontend-build-candidate
Candidate SHA:                            reported in the accompanying build handoff
Tree SHA:                                     reported in the accompanying build handoff
```

---

## 2. Executive summary — read this first

The frontend application itself is complete, correct, and verified at every layer I could actually execute in
this build environment: TypeScript typecheck, production build, unit/component tests, and a full supplementary
HTTP-level walkthrough of the real journeys against the real running PI-05/VIR/PGDR/PostgreSQL stack.

**One thing did not run**: real Playwright browser E2E. This build environment's network egress allowlist does
not include Playwright's browser-binary CDN (`cdn.playwright.dev`), so no Chromium binary could be downloaded,
and `browserType.launch()` fails immediately with `Executable doesn't exist`. This is a pure environment/
tooling access constraint in this specific sandbox — not a defect in the frontend code, not a PI-05 API gap,
and not a structuring contradiction. The complete, correct 12-spec Playwright suite (11 acceptance journeys)
is written, discovered and parsed correctly by Playwright's own `--list` command, and is ready to run
immediately in any environment with that one additional network allowance.

Given this, the honest completion state for this candidate is **not** `FRONTEND_CANDIDATE_COMPLETE` (which
explicitly requires "browser E2E PASS," and it did not run) — see §22 for the exact reasoning and the
recommended next step.

---

## 3. Framework / versions

```text
Framework:            React 18.3.1 + Vite 5.4 + TypeScript 5.5, client-side SPA (mandated by structuring §16)
Node:                     v22.22.2
npm:                          10.9.7
react-router-dom:                 6.26
Playwright:                           1.46 (installed; browser binary NOT installable in this environment,
                                        see §2/§17)
Vitest:                                   2.0.5
```

---

## 4. Frontend directory

```text
frontend/
  BUILD_PLAN.md               (§4 of the build instruction — HOW-only plan, written before any production code)
  package.json, tsconfig.json, vite.config.ts, playwright.config.ts, index.html
  src/
    api/            (client.ts, errors.ts, types.ts)
    routes/         (Entry, Registration, CaseHub, Clarification, Diagnostic, Result, History — 7 files)
    components/     (12 files — the canonical component list, §11 below)
    state/          (navigation.ts — the pure navigation-model decision function)
    App.tsx, main.tsx
  tests/
    unit/           (3 spec files + setup.ts — vitest + @testing-library/react)
    e2e/            (11 spec files, one per canonical acceptance journey, + helpers.ts — Playwright)
```

---

## 5. Route inventory — matches structuring §20 exactly

```text
/                                              Entry
/register                                          Registration
/cases/:caseId                                         Case hub (VIR result / entry to diagnostics)
/cases/:caseId/clarification                               VIR Clarification
/cases/:caseId/diagnostic                                       Diagnostic Start / Question (state-driven)
/cases/:caseId/result                                                Result
/cases/:caseId/history                                                   History
```

7 routes, exactly as structured. No additional route family introduced.

---

## 6. Screen inventory — matches structuring §3 exactly

Entry, Registration, VIR Resolving (transient — the brief window while `POST /cases` is in flight, rendered
inline in the Registration screen's own submit flow, not a separate route), VIR Result, VIR Clarification,
VIR Refusal, Diagnostic Start, Diagnostic Question (BLOCKED), Result, Case History — 10 screens.

---

## 7. Component inventory — the actual canonical list (PI-06-VF-02 accounted for)

```text
JourneyShell, RegistrationForm, VIRResolutionPanel, ClarificationForm, RefusalPanel, ComplaintForm,
ConsentForm, DiagnosticQuestionForm, ExecutionStatusPanel, GaragePreparationReportView, CaseHistoryView,
ErrorBanner
```

12 components — the real, complete list from structuring §19, not the miscounted "eleven" from its own
summary sentence (§26 of the build instruction explicitly requires using the actual list, which this build
does).

---

## 8. API-client method inventory — PI-06-VF-01 accounted for

```text
createContact, getContact, registerVehicle, startCaseVIR, submitClarification, getCase, getCaseHistory,
startDiagnostic, submitAnswer, getExecutionStatus, getArtifact
```

11 methods — one per real PI-05 route, explicitly including `createContact`/`getContact`, which the
structuring document's own §18 summary omitted (PI-06-VF-01). §10 of the build instruction required these be
included regardless of the summary's omission; they are.

---

## 9. PI-05 route coverage

All 11 real PI-05 routes (independently confirmed via `GET /openapi.json` against the actual running backend
during this build — §17 below) have a corresponding API-client method and at least one call site in the
application. No route is silently uncovered.

---

## 10. Build / static checks

```text
npm install:              clean, no errors
npx tsc -b --noEmit:           PASS, zero type errors
npx vite build:                     PASS — 54 modules transformed, dist/assets/index-*.js ~183KB (58KB gzip),
                                       built in ~2s
```

---

## 11. Unit / component tests

```text
npx vitest run:
  tests/unit/navigation.test.ts        7 tests, all PASS — every real case_status value from CPL's own
                                          VALID_CASE_STATUSES is exercised, including the "unknown" fallback
                                          for CLOSED/CANCELLED/REOPENED (never silently guessed)
  tests/unit/ErrorBanner.test.tsx          2 tests, all PASS — confirms raw backend text is never rendered,
                                              and confirms PGDR_TECHNICAL_FAILURE / CASE_ORCHESTRATION_FAILURE
                                              render genuinely distinct messages
  tests/unit/ClarificationForm.test.tsx        2 tests, all PASS — required-question validation, select-vs-
                                                  input rendering

Total: 11 passed, 0 failed, 3 test files.
```

A real bug was found and fixed during this pass: `ErrorBanner`'s category-to-message lookup fell through to
a hardcoded generic string for any category outside PI-05's own real vocabulary — including the frontend's
own client-side `VALIDATION` category — silently discarding a real, already-meaningful validation message.
Fixed by rendering the error's own `.message` for that one client-side-only category while continuing to use
the translated, safe message for every real backend category (never raw backend text for those). Caught by
`ClarificationForm.test.tsx`'s own assertion, not merely claimed fixed.

---

## 12. Production build

```text
npx vite build: PASS (§10 above)
```

---

## 13. Browser E2E — NOT executed in this environment; suite is complete and ready

```text
npx playwright test --list: 12 tests discovered and parsed correctly across 11 spec files (H is split into
  H and H2 — return-via-new-context and the Entry screen's own return form)
npx playwright test a-happy-path.spec.ts: FAILS immediately with
  "browserType.launch: Executable doesn't exist at /opt/pw-browsers/chromium_headless_shell-1243/..."
  -- confirmed a pure browser-binary-missing failure, not an application or test-logic failure (9ms failure
  time, before any page interaction was attempted)
npx playwright install chromium: FAILS -- "Host not in allowlist: cdn.playwright.dev. Add this host to your
  network egress settings to allow access."
```

**Root cause**: this build environment's network egress allowlist does not include `cdn.playwright.dev`
(Playwright's own browser-binary distribution host). No workaround exists that stays within the allowed
domain list — this is not a code, configuration, or product issue.

**What is genuinely ready**: all 11 acceptance journeys (§14 below) are written as complete, syntactically
valid, logically complete Playwright specs, confirmed parseable by Playwright's own tooling. Running them
requires only one additional network allowance (`cdn.playwright.dev`) in an environment otherwise identical
to this one, or running in any environment with normal internet access.

---

## 14. Acceptance journey mapping — 11 specs written, 0 executed via real browser

| # | Journey | Spec file | Notes |
|---|---|---|---|
| A | Happy path | `a-happy-path.spec.ts` | full registration -> VIR -> PGDR -> result -> history |
| B | VIR clarification | `b-vir-clarification.spec.ts` | uses the real `AM-BIG-01` AMBIGUOUS fixture, confirmed real at PI-01's own build |
| C | PI-02 refusal | `c-pi02-refusal.spec.ts` | setup uses PI-01's own Path B directly (the same pattern established throughout this project's backend verification, since the real refused status is not reachable through the live VIR stub's resolve() engine); the refusal itself is exercised via real browser navigation + a real HTTP call |
| D | PGDR one-question BLOCKED | `d-pgdr-blocked-one-question.spec.ts` | |
| E | PGDR multiple-question | `e-pgdr-multiple-questions.spec.ts` | asserts more than one real question is required, not merely tolerated |
| F | ESCALATED | `f-escalated.spec.ts` | real SafetyEngine-triggering complaint, asserts `execution_status == "COMPLETED"`, never `FAILED` |
| G | Browser refresh mid-journey | `g-browser-refresh.spec.ts` | within one process lifetime |
| H / H2 | Return to existing Case | `h-return-to-case.spec.ts` | via a genuinely new browser context, and via the Entry screen's own form |
| I | Technical failure | `i-technical-failure.spec.ts` | one-time network-level interception reproducing the real `PGDR_TECHNICAL_FAILURE` response shape, then a real retry through to the real backend — disclosed rationale in §15 |
| J | Orchestration failure | `j-orchestration-failure.spec.ts` | same interception approach, real `CASE_ORCHESTRATION_FAILURE` shape |
| K | Process-restart continuation | `k-process-restart-continuation.spec.ts` | same interception approach, real `PROCESS_LOCAL_STATE_UNAVAILABLE` shape (structuring's own added 11th journey) |

---

## 15. Disclosed testing-approach note for I / J / K

Journeys I, J, and K use Playwright's `page.route()` network interception to reproduce PI-05's own exact,
real response shapes for technical failure / orchestration failure / process-restart scenarios, rather than
coordinating live fault injection inside the real PI-05 process mid-browser-test. This mirrors the same
practical pattern PI-05's own backend test suite uses for equivalent scenarios (Python-level monkeypatching
of specific functions, not literally taking a real service down) — the response *shape* is real and verified
against `errors.py`'s actual `ProductAPIError` body format, not invented. This is disclosed explicitly, not
presented as indistinguishable from a purely organic failure.

---

## 16. Real PI-05 evidence

```text
Started the real, unmodified PI-05 FastAPI app via:
  DATABASE_URL=postgresql://pi06e2e:pi06e2e@localhost:5432/pi06e2e_test \
    python -m uvicorn product_integration.api.app:app --host 0.0.0.0 --port 8000
GET /openapi.json -> 200, 11 paths (exact match to the route inventory, §5/§9)
```

---

## 17. Real PostgreSQL evidence

```text
PostgreSQL version: 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)
Fresh role/database: pi06e2e / pi06e2e_test
Migrations applied from empty through head (027) via the real cpl_baseline alembic chain
Backend regression suite (§21) re-ran against this same database after the E2E HTTP walkthrough: 136/136
```

---

## 18. Real VIR evidence

```text
Started the real, unmodified VIR FastAPI app via:
  python -m uvicorn vir.api.routes:app --host 0.0.0.0 --port 80
A hosts-file entry (127.0.0.1 vir-service.internal) was added so PI-05's own hardcoded VIR_BASE_URL
  ("http://vir-service.internal", confirmed by direct source read of deps.py -- this constant was NOT
  modified) resolves to the locally-running real VIR instance. This is local network/DNS configuration on
  the build machine, not a code change to any PI-01..PI-05 file.
GET http://vir-service.internal/health -> 200, confirmed real VIR serving requests (the real POST /cases ->
  real VIR resolve() call in §19 below is the actual proof this worked end-to-end, not just a health check).
```

---

## 19. Real PGDR evidence

The supplementary HTTP-level walkthrough (§20) drove a real `SessionController` through PI-05's real
`/diagnostics`/`/answers` routes — confirmed by the real, French-language, dynamically-generated question
text returned (`"Où se trouve le véhicule actuellement ?"`, etc.), which could only come from PGDR's actual
question-selection engine, never a fixture or mock.

---

## 20. Supplementary HTTP-level walkthrough (not a substitute for browser E2E — see §2/§13)

Run directly against the real backend stack described in §16-19, using the exact same request/response
shapes the frontend's own `api/client.ts` sends and expects:

```text
POST /vehicles                          -> 201, SUCCESS
POST /cases (VIN "VF3...")                  -> 201, SUCCESS, vir_resolution_status "RESOLVED"
POST /cases/{id}/diagnostics                    -> 201, BLOCKED, real question 1 of 7
POST .../answers (x7, real questions)               -> 200 each, BLOCKED until the 7th -> 200, COMPLETED
GET /executions/{id}/artifact                           -> 200, payload contains report_id, matching
                                                             GaragePreparationReport's real 15-field shape
GET /cases/{id}/history                                     -> 200, exactly 2 executions (VIR, PGDR)

Separately, ESCALATED fixture:
POST /cases (fresh)                                             -> 201, SUCCESS
POST /cases/{id}/diagnostics (smoke/burning-smell complaint)         -> 201, COMPLETED immediately
GET /executions/{id}                                                     -> execution_status == "COMPLETED"
                                                                             (never FAILED)
```

All PASS. This confirms the frontend's own TypeScript types and API client assumptions are correct against
the real backend — genuinely valuable evidence, but explicitly not a substitute for real rendered-DOM browser
interaction (form filling, click handling, client-side routing, redirect behavior), which only real Playwright
E2E can prove.

---

## 21. Backend regression

```text
python -m pytest tests/ -q (from the real, running database used throughout this build):
  136 passed, 0 failed, 0 skipped

Matches the pre-existing baseline exactly (PI-01's 41 + PI-02's 42 + PI-03's 19 + PI-04's 21 + PI-05's 13).
Zero regression.
```

---

## 22. Files modified

```text
Zero files modified in src/ or tests/ (the existing PI-01..PI-05 backend) -- confirmed via
  `git diff --stat 71ecd48..HEAD -- src/ tests/`, empty output.
One new top-level directory added: frontend/ (49 tracked files -- see §4 for the full layout).
```

---

## 23. Modification counts

```text
PI-05 modifications: 0
CPL modifications:       0
VIR modifications:           0
PGDR modifications:              0
```

---

## 24. Findings

**Blocking (environment, not product)**: real Playwright browser E2E could not be executed in this build
environment due to network egress restrictions on Playwright's browser-binary CDN. See §2/§13/§25 for full
reasoning and recommended resolution. This is the sole reason this candidate is not reported
`FRONTEND_CANDIDATE_COMPLETE`.

**Non-blocking**: none newly introduced by this build. `PI-06-VF-01`/`PI-06-VF-02` were both correctly
accounted for (§7/§8), not repaired-around.

---

## 25. Structuring deviations

None. Every screen, route, component, and API mapping implemented matches `PI_06_FRONTEND_JOURNEY_
STRUCTURING_v0.md` exactly. No product decision was redesigned or reopened.

---

## 26. API gaps

None. All 11 required routes are covered (§9).

---

## PI-06 FRONTEND BUILD

```text
Repository:
  https://github.com/paxtonef/cpl-product-integration.git

Canonical base:
  71ecd48e8dc939e47ad738e2f8ae55e3f4811fd0

Structuring:
  d476e517dd12cb7414395a61bd16a89832963aff

Structuring verification:
  d3b50ae4fbc60fee3d7c35803cf8d77525d04a7b

Branch:
  pi-06-frontend-build-candidate

Candidate SHA:
  reported in the accompanying build handoff

Tree SHA:
  reported in the accompanying build handoff

Framework:
  React 18.3.1 + Vite 5.4 + TypeScript 5.5

Routes:
  7

Screens:
  10

Components:
  12

PI-05 API coverage:
  PASS

PI-06-VF-01:
  ACCOUNTED_FOR

PI-06-VF-02:
  ACCOUNTED_FOR

VIR clarification:
  IMPLEMENTED, SUPPLEMENTARY-HTTP-VERIFIED, browser-E2E NOT RUN (environment constraint)

PI-02 refusal:
  IMPLEMENTED, browser-E2E NOT RUN (environment constraint)

PGDR BLOCKED/question:
  IMPLEMENTED, SUPPLEMENTARY-HTTP-VERIFIED (real 7-question cycle), browser-E2E NOT RUN

Repeated PGDR questions:
  PASS (supplementary HTTP-level: 7 real turns confirmed)

ESCALATED:
  PASS (supplementary HTTP-level: execution_status COMPLETED confirmed)

Result:
  IMPLEMENTED, SUPPLEMENTARY-HTTP-VERIFIED (real report payload retrieved and shape-matched)

History:
  IMPLEMENTED, SUPPLEMENTARY-HTTP-VERIFIED (real 2-execution history retrieved)

Refresh:
  IMPLEMENTED (JourneyShell re-fetches on every mount), browser-E2E NOT RUN

Deep-link recovery:
  IMPLEMENTED, browser-E2E NOT RUN

Technical failure UX:
  IMPLEMENTED, spec written (interception-based, disclosed §15), browser-E2E NOT RUN

Orchestration failure UX:
  IMPLEMENTED, spec written (interception-based, disclosed §15), browser-E2E NOT RUN

Accessibility:
  IMPLEMENTED (labels, keyboard-operable native form controls, role=alert/status, loading states) --
  not independently audited via automated a11y tooling in this pass

Unit/component tests:
  11 passed / 0 failed

Production build:
  PASS

Browser E2E:
  0/12 executed (environment network restriction; all 12 discovered/parsed correctly by Playwright's own
  tooling, 0 code defects found in the specs themselves)

Acceptance journeys:
  11/11 written, 0/11 executed via real browser (supplementary HTTP-level walkthrough covers A/F fully,
  see §20)

Real PI-05:
  PASS

Real PostgreSQL:
  PASS

Real VIR:
  PASS

Real PGDR:
  PASS

Backend regression:
  136/136 passed

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
  1 (environment: Playwright browser binary unavailable in this build sandbox -- not a code/product defect)

FINAL STATE:
  BLOCKED (browser E2E execution blocked by this build environment's network egress restrictions; the
  frontend application, its full acceptance-journey test suite, and all buildable/testable layers are
  otherwise complete and verified -- see §2 for the precise reasoning and recommended resolution: run
  `npx playwright test` in an environment with network access to cdn.playwright.dev, or grant that one
  additional allowance in this environment)
```
