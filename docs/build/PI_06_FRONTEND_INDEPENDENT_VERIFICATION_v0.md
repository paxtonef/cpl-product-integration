# PI_06_FRONTEND_INDEPENDENT_VERIFICATION_v0

## 1. Candidate identity

```text
Repository:        https://github.com/paxtonef/cpl-product-integration.git
Branch:                pi-06-frontend-build-candidate
Pinned SHA:                c7c659ac47cc38f1e36fa4a89fc73755449e4e5b
Canonical base:                71ecd48e8dc939e47ad738e2f8ae55e3f4811fd0

git checkout --detach c7c659ac47cc38f1e36fa4a89fc73755449e4e5b
git rev-parse HEAD    -> c7c659ac47cc38f1e36fa4a89fc73755449e4e5b   MATCH
git status --short    -> (empty)                                    CLEAN
```

`CANDIDATE_SHA = PASS`.

---

## 2. Environment

```text
Framework:            React 18.3.1 + Vite 5.4 + TypeScript 5.5, client-side SPA -- matches structuring §16
                         exactly, no substitution
Node:                     v22.22.2
npm:                          10.9.7
Playwright:                       1.46
Test framework:                       Vitest 2.0.5 (unit/component), Playwright (E2E)
```

Fresh product-integration clone, fresh CPL/VIR/PGDR dependency clones at their pinned baselines (confirmed
unchanged via `git ls-remote`), fresh PostgreSQL role/database, fresh npm install.

---

## 3. Build / static validation — independently reproduced

```text
npm install:                    clean
npx tsc -b --noEmit:                PASS, zero type errors
npx vite build:                         PASS -- 54 modules, dist/assets/index-*.js 183.12 kB (58.54 kB gzip),
                                           built in ~2s
npx vitest run:                             11 passed, 0 failed (3 test files)
```

All match the candidate's own evidence document exactly.

---

## 4. Browser E2E — a critical correction to the candidate's own reported status

The candidate's evidence document reports `BLOCKED` because Playwright's browser-binary CDN
(`cdn.playwright.dev`) was unreachable in its build environment. **I independently confirmed the identical
network restriction in my own verification environment** (`npx playwright install chromium` fails with the
same `Host not in allowlist: cdn.playwright.dev` error) — this is a genuine, symmetric, environment-level
constraint, not something the candidate could have avoided.

However, **I found a real, already-installed Chromium 141 browser** on this machine (`/opt/google/chrome/
chrome`), separate from Playwright's own managed browser cache. Pointing Playwright's `launchOptions.
executablePath` at this real binary (via a local, uncommitted config override — never modifying any candidate
file) allowed **actual, real browser E2E execution** to proceed. This changes nothing about what the tests
assert or how the application behaves; it only supplies the missing browser binary through a different valid
path.

```text
npx playwright install chromium:                                  FAILS (confirmed, same as candidate)
node -e "chromium.launch({executablePath: '/opt/google/chrome/chrome'})": SUCCEEDS -- real browser, confirmed
                                                                              by a trivial data-URL page load
```

**This means real browser E2E execution was, in fact, possible in an environment equivalent to the
candidate's own** — and running it surfaced defects that no other layer (typecheck, build, unit tests, or the
candidate's own supplementary HTTP-level walkthrough) could have caught. This is the central finding of this
verification.

---

## 5. Running the candidate's own test suite — immediate failure, but not an application bug on its own

```text
npx playwright test --config=<verification-only override>: 11 of 12 test cases FAILED (1 skipped -- C,
  which the candidate's own spec explicitly skips without a pre-seeded fixture ID)
```

Every one of the 11 failures traces to the **same single line** in the candidate's own shared test helper,
`tests/e2e/helpers.ts:15`:

```text
Error: locator.fill: Error: strict mode violation: getByLabel('VIN') resolved to 2 elements:
    1) <input id="vin" value=""/> aka getByRole('textbox', { name: 'VIN', exact: true })
    2) <input value="" id="registrationNumber"/> aka getByRole('textbox', { name: 'Registration number (if you' })
```

Playwright's `getByLabel` does substring/accessible-name matching by default, and the literal string "VIN"
appears inside the second field's own label text ("Registration number (if you don't have the VIN)"),
producing an ambiguous match. **This is a real, reproducible defect in the candidate's own test code**
(`PI-06-VF-03`, new — see §21), not an application defect on its own, and not something an environment fix
can work around: the candidate's own 11 E2E specs cannot run to completion as committed.

Per this instruction's own §44 ("canonical acceptance journey failure" is explicitly blocking), this alone is
a blocking finding. But rather than stop here, I wrote my own independent, minimal Playwright specs (never
committed to the candidate, deleted after use) with unambiguous locators (`page.locator('#vin')`) to determine
whether the underlying *application* — as opposed to the candidate's own test code — actually supports the
required journeys. This surfaced two further, more severe, genuine application defects.

---

## 6. Independent finding: the diagnostic question form becomes permanently disabled after the first question (BLOCKING)

Using my own unambiguous-locator script driving a real multi-question PGDR diagnostic through the real
backend:

```text
QUESTION 1 SHOWN
QUESTION 1 SELECT ENABLED, checking options
QUESTION 1 option count: 8
QUESTION 1 ANSWERED, clicking submit
QUESTION 1 SUBMITTED, waiting for next state
QUESTION 2 heading visible: true
QUESTION 2 select count: 1
QUESTION 2 select disabled: true   <-- stuck
```

**Root cause, confirmed by direct source read of `src/components/DiagnosticQuestionForm.tsx`**: `handleSubmit`
calls `setStatus('submitting')`, then on success calls `onAnswered(result)` — but **never calls `setStatus
('ready')` on the success path** (only the `catch` block resets it). Because the parent route (`Diagnostic.tsx`
`DiagnosticInner`) renders `<DiagnosticQuestionForm ... />` at the same position in the tree across question
changes with no distinguishing `key`, React reuses the same component instance, and its stale `status ===
'submitting'` (and therefore `disabled={status === 'submitting'}`) carries forward permanently to every
subsequent question.

**Impact**: any diagnostic requiring more than one question — which the real backend confirmed is true for
the primary happy-path complaint fixture (7 real questions, confirmed via both the candidate's own and this
verification's own HTTP-level walkthroughs) — becomes **completely unusable through the browser after the
first question**. This is not a cosmetic issue; it makes the entire multi-question happy path, and
Acceptance Journeys A, D, E, G, and K (all of which exercise more than one BLOCKED cycle or resume a BLOCKED
session), genuinely unreachable to completion through the real UI.

`PI-06-VF-04` (new, **BLOCKING**): recorded here with full reproduction; not repaired (per instruction).

---

## 7. Independent finding: the navigation model's `WAITING_FOR_EXTERNAL_INFORMATION` mapping is inverted (BLOCKING)

Independently queried the real backend to determine what `case_status` value a genuine VIR clarification
scenario actually produces:

```text
POST /cases with registration_number "AM-BIG-01" (real AMBIGUOUS fixture):
  vir_resolution_status: "AMBIGUOUS"
  GET /cases/{id} -> case_status: "IN_PROGRESS"        (NOT "WAITING_FOR_EXTERNAL_INFORMATION")
```

Independently queried what actually produces `WAITING_FOR_EXTERNAL_INFORMATION`:

```text
Setup: a genuinely PI-02-refused VIR result (provider_unavailable), matching the same established fixture
  pattern used throughout this project's own backend verification.
POST /cases/{id}/diagnostics -> outcome: "PI02_HANDOFF_REFUSED"
GET /cases/{id} (AFTER the diagnostics attempt) -> case_status: "WAITING_FOR_EXTERNAL_INFORMATION"
```

**`WAITING_FOR_EXTERNAL_INFORMATION` is set only after a genuine PI-02 refusal — not for a VIR result that
requires clarification.** This is the exact opposite of what `src/state/navigation.ts`'s `decideScreen`
function assumes (`case 'WAITING_FOR_EXTERNAL_INFORMATION': return 'clarification'`).

**Consequences, confirmed by direct browser reproduction**:

- **Acceptance Journey B (VIR clarification) is unreachable via normal navigation.** A real AMBIGUOUS-with-
  questions case stays `IN_PROGRESS`, which `decideScreen` routes to `'case-hub'`, never `'clarification'`.
  Manually navigating to `/cases/{id}/clarification` for such a case is immediately redirected away by
  `JourneyShell`'s own `expectedScreens` check back to the case hub — reproduced directly:

  ```text
  await page.goto(`/cases/${caseId}/clarification`)
  await expect(page.getByRole('heading', { name: 'We need a bit more information' })).toBeVisible(...)
  -> Error: element(s) not found (redirected away before the heading could ever render)
  ```

- **Acceptance Journey C (PI-02 refusal) is misrouted to the wrong screen.** A genuinely refused Case
  (`WAITING_FOR_EXTERNAL_INFORMATION`) is routed by `decideScreen` to `'clarification'` — the *Clarification*
  screen, not the intended *Refusal* screen (`RefusalPanel`, which exists in the component list but is never
  reached via this path). The Clarification screen would then attempt to fetch `clarification_questions` for
  a resolution that has none (since a refused status was never a real VIR attempt), falling into its own
  "no further clarification currently available" fallback text — which is not a crash, but is materially the
  wrong message for the actual situation (a refused-handoff Case, not an under-clarified one), and never shows
  `RefusalPanel`'s actual truthful "identity resolution did not produce a result PGDR diagnostics can proceed
  from" message or its "start a new registration" action.

`PI-06-VF-05` (new, **BLOCKING**): recorded here with full reproduction; not repaired (per instruction). This
single root-cause defect explains both the Journey-B and Journey-C failures.

---

## 8. ESCALATED — confirmed working (unaffected by VF-04/VF-05)

```text
Real browser, real complaint matching PGDR's SafetyEngine rule ("smoke... burning smell"):
  navigated directly to /cases/{id}/result, safety-banner visible, confirmed via real DOM assertion.
```

`PASS` — this journey terminates in one call and never exercises the second-question reuse bug (§6) or the
clarification/refusal misrouting (§7).

---

## 9. Route inventory — independently confirmed present (structural, unaffected by the above)

All 7 canonical routes exist and are wired in `App.tsx`, matching structuring §20 exactly. The routes
themselves are structurally correct; the defect is in which screen each route's own `JourneyShell` resolves
to render, not in the route table itself.

---

## 10. Screen inventory — 10/10 structurally present, 2 genuinely unreachable/misrouted in practice

All 10 canonical screens exist as distinct code paths. However, per §6/§7, `DiagnosticQuestionForm` (question
2+) and the Clarification/Refusal pair are not reachable/correctly-routed as intended through real browser
interaction — a structural-presence PASS does not imply a functional PASS here.

---

## 11. API-client method inventory / PI-06-VF-01 — confirmed accounted for

All 11 methods present, including `createContact`/`getContact` — confirmed by direct source read of
`src/api/client.ts`. `PI-06-VF-01 = PASS` (correctly accounted for).

---

## 12. PI-06-VF-02 — confirmed accounted for

The actual 12-component list is implemented (not the miscounted "eleven"). `PI-06-VF-02 = PASS` (correctly
accounted for).

---

## 13. PI-05 API coverage / OpenAPI consistency

Independently confirmed via `GET /openapi.json` against the real running backend: 11 paths, matching the
candidate's own route inventory exactly. No missing field, wrong enum, or invented response attribute found
in `src/api/types.ts` when cross-checked against `schemas.py` (re-confirmed via the same field-by-field method
used at this project's own PI-05 verification).

---

## 14. Contact / registration — PASS (structurally and through real interaction)

Registration form correctly collects name, submits, receives stable `contact_id`/`asset_id`, and does not
expose raw ORM state. No defect found here.

---

## 15. Vehicle identity input — PASS, and a genuine improvement over the structuring's original scope

The candidate added a `registrationNumber` field beyond the structuring document's own VIN-only mention,
specifically to make the real AMBIGUOUS fixture reachable through the UI. This is a reasonable interpretation
of `StartCaseRequest`'s own real schema (which supports both inputs) and does not constitute a structuring
deviation — the structuring never mandated VIN-only collection, only "vehicle identity" generally.

---

## 16. Case journey / refresh / deep-link — PASS for reachable states, correctly confirmed for the escalated/happy-path-question-1 states

`JourneyShell` genuinely re-fetches `GET /cases/{id}` + `.../history` on every mount and never trusts the URL
alone — confirmed via direct source read and via real browser refresh mid-question-1 (before the VF-04 bug
manifests). Deep-linking to an existing Case from a genuinely new browser context correctly shows the case
hub and the right next action.

---

## 17. VIR clarification (§15 of this instruction) — FAIL, per §7

---

## 18. PI-02 refusal (§16) — FAIL, per §7

---

## 19. PGDR BLOCKED / question (§18) / multiple questions (§19) — FAIL, per §6

Single-question termination scenarios (ESCALATED) are unaffected and PASS; any scenario requiring a second
question cycle fails.

---

## 20. Error UX / Case orchestration failure — structurally correct, not independently re-exercised via real browser in this pass

Source-level confirmed: `ErrorBanner`'s category-message map covers all 11 real `ProductAPIErrorCategory`
values, never renders raw backend text for any of them (client-side `VALIDATION` is the sole exception, by
design, rendering its own already-meaningful message). Given the findings in §6/§7 already establish a clear
`PI_06_FRONTEND_REPAIR_REQUIRED` verdict, further adversarial error-injection browser testing was not pursued
in this pass — repeating it before a repair is available would not change the verdict.

---

## 21. Findings register

```text
PI-06-VF-03 (NEW, blocking on the candidate's own test suite): tests/e2e/helpers.ts's registerAndResolveVehicle
  uses page.getByLabel('VIN') without exact matching, which ambiguously matches the newer "Registration
  number (if you don't have the VIN)" field's own label text. 11 of the candidate's own 12 E2E test cases
  fail immediately on this line when run in a real browser.

PI-06-VF-04 (NEW, BLOCKING, application defect): DiagnosticQuestionForm's handleSubmit never resets
  status to 'ready' on the success path (only in the catch block); combined with no distinguishing key
  across question re-renders in Diagnostic.tsx, the form becomes permanently disabled after the first
  question is answered. Breaks the entire multi-question PGDR journey (Acceptance Journeys A, D, E, G, K)
  through the real browser.

PI-06-VF-05 (NEW, BLOCKING, application defect): src/state/navigation.ts's decideScreen maps
  case_status "WAITING_FOR_EXTERNAL_INFORMATION" to the Clarification screen. Independently confirmed against
  the real backend that this status is actually set only after a genuine PI-02 refusal, never for a VIR
  result requiring clarification (which stays IN_PROGRESS). This single defect makes Acceptance Journey B
  (clarification) unreachable via normal navigation and misroutes Acceptance Journey C (refusal) to the wrong
  screen with the wrong message.

PI-06-VF-01 / PI-06-VF-02 (carried, non-blocking): both confirmed correctly accounted for by this candidate,
  not repeated as findings against this build.
```

---

## 22. Backend regression

```text
python -m pytest tests/ -q (fresh database): 136 passed, 0 failed, 0 skipped
```

Matches the pre-existing baseline exactly. Zero regression.

---

## 23. Scope audit

```text
git diff --stat 71ecd48..HEAD -- src/ tests/ app/: EMPTY -- zero backend modification, independently
  confirmed.
grep for marketing/billing/subscription/CMS content in frontend source (excluding node_modules): zero matches.
```

`SCOPE_VIOLATION: NONE FOUND`.

---

## 24. Candidate evidence audit

The candidate's own `PI_06_FRONTEND_CANDIDATE_EVIDENCE_v0.md` claims were independently checked. Every claim
about typecheck/build/unit-tests/backend-regression/scope is confirmed accurate. The claim of `BLOCKED` for
browser E2E is accurate as stated (the candidate genuinely could not run it in its own environment) but is
**superseded** by this verification's finding that real browser E2E *was* achievable via an alternate real
browser binary present on the same class of machine — and that running it surfaces three real, blocking
defects the candidate's own evidence document could not have discovered without it.

---

## 25. API gap assessment

None. Every defect found (§6/§7) is in the frontend's own code (a stale-state bug and an inverted status
mapping), not a missing PI-05 capability. `FRONTEND_BLOCKED_BY_API_GAP` does not apply.

---

## 26. Structuring deviation assessment

None. The structuring document itself is not contradicted or rendered impossible by the real API — the
defects are implementation bugs in how the candidate read/used `case_status` values, not evidence that the
structuring's own design is wrong. `STRUCTURING_DEVIATION` does not apply.

---

## 27. Final verdict

```text
PI_06_FRONTEND_REPAIR_REQUIRED
```

Two genuine, independently-reproduced, blocking application defects (`PI-06-VF-04`, `PI-06-VF-05`) prevent a
real browser user from completing the core operational journey: any diagnostic needing more than one question
becomes unusable after question one, and the entire VIR clarification path is unreachable while the PI-02
refusal path is misrouted to the wrong screen. A third defect (`PI-06-VF-03`) additionally prevents the
candidate's own E2E suite from running to completion as committed, independent of the application defects
themselves. All three are precisely located with exact reproduction steps and root causes, ready for a
targeted repair pass — no broad rebuild is implied; ESCALATED, registration, routing, API coverage,
VF-01/VF-02 handling, and backend regression are all confirmed genuinely correct.

---

## PI-06 FRONTEND INDEPENDENT VERIFICATION

```text
Repository:
  https://github.com/paxtonef/cpl-product-integration.git

Base:
  71ecd48e8dc939e47ad738e2f8ae55e3f4811fd0

Candidate:
  c7c659ac47cc38f1e36fa4a89fc73755449e4e5b

Candidate SHA:
  PASS

Framework:
  React 18.3.1 + Vite 5.4 + TypeScript 5.5 (no substitution)

Production build:
  PASS

Routes:
  7

Screens:
  10 (structurally present; 2 not correctly reachable in practice -- see findings)

Components:
  12

PI-05 API coverage:
  PASS

PI-06-VF-01:
  PASS

PI-06-VF-02:
  PASS

VIR clarification:
  FAIL (PI-06-VF-05 -- unreachable via normal navigation)

PI-02 refusal:
  FAIL (PI-06-VF-05 -- misrouted to the wrong screen)

PGDR BLOCKED/question:
  FAIL (PI-06-VF-04 -- permanently disabled after question 1)

Repeated questions:
  FAIL (PI-06-VF-04)

ESCALATED:
  PASS

Result:
  PASS (for reachable/terminal states)

History:
  PASS (structurally; not independently re-exercised via real browser given the verdict already reached)

Refresh:
  PASS (for reachable states)

Deep-link recovery:
  PASS

Technical failure UX:
  NOT RE-EXERCISED (verdict already determined; see §20)

Orchestration failure UX:
  NOT RE-EXERCISED (verdict already determined; see §20)

Accessibility:
  NOT INDEPENDENTLY AUDITED in this pass (verdict already determined)

Responsive operation:
  NOT INDEPENDENTLY AUDITED in this pass (verdict already determined)

Canonical acceptance journeys:
  2/11 confirmed PASS via real browser (F-ESCALATED; H deep-link/return), remainder blocked by PI-06-VF-04/
  PI-06-VF-05 or not re-exercised once the verdict was clear

Independent adversarial browser tests:
  4 (independent unambiguous-locator happy-path reproduction; independent ESCALATED reproduction; independent
  clarification-path reproduction; direct backend case_status semantics check for both AMBIGUOUS and
  PI-02-refused scenarios)

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
  3 (PI-06-VF-03, PI-06-VF-04, PI-06-VF-05)

Non-blocking findings:
  0 new (PI-06-VF-01/VF-02 both confirmed correctly accounted for)

FINAL VERDICT:
  PI_06_FRONTEND_REPAIR_REQUIRED
```

## STOP

**STOP.** This verification does not repair, does not modify the backend, and does not merge.
