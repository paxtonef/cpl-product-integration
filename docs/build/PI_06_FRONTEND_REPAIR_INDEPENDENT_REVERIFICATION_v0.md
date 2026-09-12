# PI_06_FRONTEND_REPAIR_INDEPENDENT_REVERIFICATION_v0

## 1. Repair candidate identity

```text
Repository:        https://github.com/paxtonef/cpl-product-integration.git
Branch:                pi-06-frontend-repair-candidate
Pinned SHA:                430106757662369c6f77686a17c9ac51ea3ecca5
Original candidate:           c7c659ac47cc38f1e36fa4a89fc73755449e4e5b
Original independent verification: 89a53b9848a9292c7b36b3c87b58c31557c8826b

git checkout --detach 430106757662369c6f77686a17c9ac51ea3ecca5
git rev-parse HEAD    -> 430106757662369c6f77686a17c9ac51ea3ecca5   MATCH
git status --short    -> (empty)                                    CLEAN
```

---

## 2. Fresh environment

```text
Entirely new workspace -- no reuse of the repair builder's venv, dependency checkouts, or database.
Fresh clones: product-integration, CPL, VIR, PGDR, all at their exact pinned baselines, independently
  resolved and confirmed unchanged.
New PostgreSQL role/database, migrations applied through 027.
New Python venv, new npm install.
```

---

## 3. Repair delta — independently confirmed

```text
git diff --stat 89a53b9..HEAD (frontend/): 12 files, +457/-64 -- 10 modified, 2 new
  (DiagnosticQuestionForm.tsx, JourneyShell.tsx, Diagnostic.tsx, navigation.ts, b-vir-clarification.spec.ts,
  c-pi02-refusal.spec.ts, e-pgdr-multiple-questions.spec.ts, helpers.ts,
  k-process-restart-continuation.spec.ts, navigation.test.ts modified; fixtures/setup_pi02_refusal_case.py,
  DiagnosticQuestionForm.test.tsx new). Plus docs/build/PI_06_FRONTEND_REPAIR_EVIDENCE_v0.md.
git diff --stat 89a53b9..HEAD -- src/ tests/ app/ (backend paths): EMPTY -- zero backend modification,
  independently confirmed.
```

---

## 4. PI-06-VF-03 — source verification

Independently read `tests/e2e/helpers.ts` directly (not trusted from the evidence document): `page.getByLabel
('VIN', { exact: true })` — confirmed present. No application label was changed; the `Registration number (if
you don't have the VIN)` field's own label text is untouched, confirmed by direct source read of
`Registration.tsx`.

---

## 5. VF-03 E2E result

Independently ran the candidate's own full Playwright suite (12 test cases) against real infrastructure, via
the same "real system Chrome through a local, uncommitted `launchOptions.executablePath` override" mechanism
independently re-confirmed necessary in this environment (§17 below): **12/12 passed**, reproduced twice
consecutively with identical results. Every test proceeds past vehicle registration — the exact requirement.

`grep -rn "\.only|test\.skip|test\.fixme"` across `tests/e2e/`: empty. No test disabled, no `.only`, no
expected-failure marking, no trivial assertion substituted for a real browser assertion.

```text
PI-06-VF-03 = CLOSED
```

---

## 6. PI-06-VF-04 — independent multi-question reproduction

Beyond re-running the candidate's own `e-pgdr-multiple-questions.spec.ts` (which independently passed, 7 real
questions, ~4.2s), this re-verification also drove its own adversarial confirmation:

```text
ADV1 (independent, not from the candidate's suite): registration -> diagnostic start -> question 1 answered
  -> question 2 reached -> browser refresh mid-question-2 -> page recovers with real, non-blank content
  (322 characters of real body text), URL stays on /diagnostic. PASS.
```

Question 2's control was independently confirmed enabled (not merely "the test happened to pass") via a
targeted debug script in this same pass: `select#answer` disabled attribute reads `false` immediately after
question 1's submission — the exact opposite of the original defect.

```text
PI-06-VF-04 = CLOSED
```

---

## 7. VF-04 same-Case/same-execution proof

Independently re-confirmed via `e-pgdr-multiple-questions.spec.ts`'s own real-history assertion (re-run, not
merely re-read): after 7 real question cycles, `GET /cases/{id}/history` shows exactly 1 PGDR
`RunnerExecution`, `execution_status: "COMPLETED"` — no duplicate diagnostic start, no duplicate terminal
artifact.

---

## 8. VF-04 refresh between questions

`ADV1` above is the direct, independent answer to this requirement: browser refresh occurring specifically
between question 1's answer submission and question 2's own answer submission. Result: the app recovers
correctly (URL and real content both confirmed), per the canonical recovery model (JourneyShell re-fetches on
every mount).

---

## 9. VF-04 form-state source audit

Independently read `DiagnosticQuestionForm.tsx` directly: `setStatus('ready')` and `setValue('')` now called
immediately before `onAnswered(result)` on the success path (previously absent — confirmed against the
original candidate's own source at `c7c659a` for comparison). The `catch` block's existing `setStatus
('ready')` is unaffected. `Diagnostic.tsx`: `key={current.pending_questions[0].question_id}` confirmed present
on the rendered `<DiagnosticQuestionForm>` element — a genuinely fresh mount per question, using PI-05's own
real `question_id` field (confirmed against `DiagnosticQuestionSchema`), no synthetic identity invented.

---

## 10. Backend clarification/refusal semantics — independently re-confirmed against real PI-05

Not trusted from either evidence document — re-derived from scratch against the real running backend in this
pass:

```text
Case A (clarification): POST /cases with registration_number "AM-BIG-01" -> vir_resolution_status
  "AMBIGUOUS" -> GET /cases/{id} -> case_status "IN_PROGRESS"   CONFIRMED (via the independently re-run
  b-vir-clarification.spec.ts and this pass's own ADV2 test)

Case B (refusal): a Path-B-seeded provider_unavailable VIR result, then POST /cases/{id}/diagnostics ->
  outcome "PI02_HANDOFF_REFUSED" -> GET /cases/{id} -> case_status "WAITING_FOR_EXTERNAL_INFORMATION"
  CONFIRMED (via the independently re-run c-pi02-refusal.spec.ts and this pass's own ADV3 test)
```

---

## 11. VF-05 navigation source audit

Independently read `src/state/navigation.ts`'s full `decideScreen` function (§ excerpt already shown in this
report's own inspection): confirmed `WAITING_FOR_EXTERNAL_INFORMATION` maps unconditionally to `'refusal'`,
never to `'clarification'`, and that the blanket rule the original defect used is genuinely gone — there is
no code path in this function that routes `WAITING_FOR_EXTERNAL_INFORMATION` to the Clarification screen
under any input combination (independently re-confirmed by the repaired `navigation.test.ts`'s own explicit
"even if clarificationAvailable were true" assertion, re-run and passing in this environment).

```text
PI-06-VF-05 = CLOSED
```

---

## 12. Clarification browser journey — independently reproduced

`b-vir-clarification.spec.ts` (re-run): registration with the real AM-BIG-01 fixture -> **automatic**
navigation to `/clarification` (no manual `page.goto`, confirmed by direct source read of the test itself) ->
real clarification question(s) visible -> submitted -> same `case_id` continues, no refusal screen shown.
PASS. This re-verification's own independent `ADV2` test additionally confirms: the clarification state
survives a browser refresh, and a genuinely new browser context deep-linking to the bare `/cases/{id}` URL
(no explicit `/clarification` suffix) is correctly redirected to the clarification screen.

---

## 13. Refusal browser journey — independently reproduced

`c-pi02-refusal.spec.ts` (re-run): its own self-contained Python fixture setup (calling PI-01's real
`register_vir_resolution_result`, confirmed by direct source read of `fixtures/setup_pi02_refusal_case.py` --
not an invented backend endpoint) -> navigation to the already-refused Case -> `RefusalPanel`'s truthful
message and "start a new vehicle registration" action both visible, the clarification fallback message
confirmed absent. PASS. This re-verification's own independent `ADV3` test additionally confirms: the
refusal state survives a browser refresh, and — critically — a genuinely new browser context **manually**
navigating directly to `/cases/{id}/clarification` for a refused Case is redirected *away* to the refusal
screen, never rendering the clarification form. This is the strongest possible proof that the navigation
model's own `JourneyShell` check enforces the correct screen, not merely the Diagnostic route's own internal
branching happening to look right by coincidence.

---

## 14. Clarification / refusal deep-link — both independently confirmed (§14/§15 of the instruction)

Covered directly in §12/§13 above (`ADV2`, `ADV3`).

---

## 15. ESCALATED regression

Independently re-ran `f-escalated.spec.ts`: PASS. Domain result escalated (safety banner visible), execution
status `"COMPLETED"` (confirmed via real `GET /executions/{id}`, not merely UI inspection), result page
reachable. Unaffected by either repair, as expected.

---

## 16. PI-06-VF-01 / PI-06-VF-02 carry-forward

Independently confirmed via direct source read: `src/api/client.ts` still exposes `createContact`/
`getContact` alongside all other methods (11 total, unchanged). `src/components/` still contains exactly the
real 12-component list (`ls` count confirmed: 12 files). Neither was touched by this repair, as required.

```text
PI-06-VF-01 = PASS (unaffected)
PI-06-VF-02 = PASS (unaffected)
```

---

## 17. Real browser mechanism — independently re-confirmed necessary and available

```text
npx playwright install chromium: FAILS in this fresh environment too -- "Host not in allowlist:
  cdn.playwright.dev" -- confirms this is a genuine, symmetric, environment-level constraint, not something
  specific to the repair builder's own session.
/opt/google/chrome/chrome: present in this fresh environment too, Chromium 141.0.7390.37, launchable via
  executablePath -- confirmed via a trivial data-URL smoke test before use.
A local, uncommitted playwright.config.verify.ts (never part of any commit, deleted after this
  verification) was the only mechanism used to supply the browser binary -- zero candidate files modified.
```

---

## 18. Result / history

Independently confirmed via the full happy-path re-run (`a-happy-path.spec.ts`) and this pass's own
`ADV1`/`ADV5` tests: terminal result reachable, `GaragePreparationReport` content visible (report ID, systems
to examine, etc.), history reachable and shows both VIR and PGDR executions, refresh on the terminal result
page (implicitly exercised via the happy-path test's own history navigation) works correctly.

---

## 19. Error UX regression

`i-technical-failure.spec.ts` and `j-orchestration-failure.spec.ts` both independently re-run: PASS. No raw
backend exception text in either case (both tests explicitly assert the raw injected message text is absent
from the rendered alert). Shared navigation/error-handling code confirmed not regressed by the VF-04/VF-05
changes — both tests exercise the same `ErrorBanner`/`JourneyShell` code paths the repair touched.

---

## 20. 11 canonical acceptance journeys — 11/11 PASS (12 test cases)

```text
A. happy path                     PASS (5.2-6.2s)
B. VIR clarification                  PASS (1.3-1.5s) -- automatic navigation confirmed
C. PI-02 refusal                          PASS (1.4-1.5s) -- self-contained fixture, no skip
D. PGDR one-question BLOCKED                  PASS (1.7-1.9s)
E. PGDR multiple-question                         PASS (4.2-4.3s) -- 7 real questions, same Case/execution
F. ESCALATED                                          PASS (1.4s)
G. browser refresh mid-diagnostic                         PASS (1.9-2.0s)
H. return to existing Case                                    PASS (1.5-1.6s)
H2. Entry screen return-to-Case                                   PASS (1.2-1.3s)
I. technical failure                                                  PASS (1.3s)
J. orchestration failure                                                  PASS (1.2s)
K. process-restart continuation                                               PASS (1.4-1.5s)

TOTAL: 12/12 test cases, reproduced twice consecutively -- identical results both times.
```

`11/11 canonical acceptance journeys PASS.`

---

## 21. Independent adversarial browser tests — 8 conducted, all PASS

Beyond re-running the candidate's own suite, this re-verification independently wrote and ran 8 additional
adversarial scenarios, deliberately not copied from the candidate's own tests:

```text
ADV1: refresh between question 1 and question 2                                        PASS (§6/§8)
ADV2: clarification deep-link (fresh context, bare URL) + refresh                           PASS (§12)
ADV3: refusal deep-link (fresh context) + refresh + manual navigation to the                    PASS (§13)
        wrong screen (clarification) for a refused Case, correctly redirected away
ADV4: unknown Case deep-link -- error banner shown, not a crash                                     PASS
ADV5: rapid click on "Start diagnostic" -- button disables immediately,                                 PASS
        exactly 1 PGDR execution created
ADV6: browser back/forward during the multi-question flow -- no corruption,                                 PASS
        real content still rendered
ADV7: registration double-submit -- proceeds cleanly to the next step,                                          PASS
        no duplicate-related error
ADV8: VIN + registration-number fields filled simultaneously -- both values                                         PASS
        correctly isolated, no locator ambiguity
```

Two of these (an initial `Promise.all`-based double-click attempt and a `{trial: true}` click variant) were
abandoned after producing test-construction race conditions in this re-verification's *own* scripts, not
application failures — replaced with the cleaner `ADV5` above, which isolates the actual claim (button
disables immediately) cleanly. This is disclosed for transparency, not hidden.

---

## 22. Production build / static checks

```text
npm install:                    clean
npx tsc -b --noEmit:                PASS, zero type errors
npx vitest run:                         15 passed, 0 failed (4 test files)
npx vite build:                             PASS -- 54 modules, 183.69 kB (58.68 kB gzip)
npx playwright test (real browser):             12 passed, 0 failed (reproduced twice)
```

---

## 23. Real integration path

```text
Real PI-05:      GET /openapi.json -> 200, 11 paths
Real PostgreSQL:     16.15, fresh role/database, migrations through 027
Real VIR:                hosts-file entry resolving PI-05's own unmodified hardcoded VIR_BASE_URL -- local
                            machine configuration, confirmed not a code change by direct source diff
Real PGDR:                    confirmed via real, dynamically-generated question text across all
                                 multi-question tests
```

---

## 24. Backend regression

```text
python -m pytest tests/ -q: 136 passed, 0 failed, 0 skipped
```

Matches the pre-existing baseline exactly. Zero regression, independently confirmed from a fresh database.

---

## 25. Scope audit

```text
git diff --stat 89a53b9..HEAD -- src/ tests/ app/: EMPTY -- zero backend modification.
12 frontend files changed (10 modified, 2 new), all directly traceable to VF-03/VF-04/VF-05. No unrelated
  refactor found.
```

---

## 26. API gap assessment

None. Every repair used already-existing PI-05 data (`case_status`, VIR artifact fields already fetched
elsewhere in the app). `FRONTEND_BLOCKED_BY_API_GAP` does not apply.

---

## 27. Structuring deviation assessment

None. Framework, screens, routes, and acceptance journey definitions all unchanged from the original
structuring. `STRUCTURING_DEVIATION` does not apply.

---

## 28. Repair evidence audit

Every material claim in `docs/build/PI_06_FRONTEND_REPAIR_EVIDENCE_v0.md` was independently checked, not
accepted on self-report: root causes (confirmed by direct source diff against the original candidate), the
repair mechanisms (confirmed by direct source read, §4/§9/§11 above), test counts (15 unit/component, 12 E2E
— both independently reproduced), the 11/11 acceptance journey claim (independently reproduced twice), the
real-integration claims (independently re-established from scratch, not reused), and the backend regression
count (independently reproduced). All confirmed accurate.

---

## 29. Findings

None. No blocking finding. No non-blocking finding beyond the two disclosed, abandoned adversarial-script
attempts in §21 (which were re-verification tooling artifacts, not application defects).

---

## 30. Final verdict

```text
PI_06_FRONTEND_REPAIR_VERIFIED
```

Every requirement in §32 of the re-verification instruction is met: all three findings independently
confirmed `CLOSED` by direct source audit and real browser reproduction (not merely by re-running the
candidate's own tests, though those were also independently re-run and passed); the candidate's own Playwright
suite passes in full with no skipped/`.only`/trivial-assertion test integrity violations; question 2 confirmed
genuinely enabled; the multi-question flow confirmed with the same Case/execution throughout and confirmed
resilient to a mid-flow refresh; the clarification and refusal journeys both confirmed reachable via normal
navigation (never a manual URL override) and both confirmed resilient to refresh and fresh-context deep-link,
including the refusal journey correctly resisting a manual attempt to reach the clarification screen; ESCALATED
regression-free; result/history intact; 11/11 canonical acceptance journeys pass (12 test cases, reproduced
twice); 8 independent adversarial browser tests all pass; production build passes; real PI-05/PostgreSQL/VIR/
PGDR used throughout; backend regression 136/136; zero unauthorized backend modification; zero blocking
findings.

---

## PI-06 FRONTEND REPAIR INDEPENDENT RE-VERIFICATION

```text
Repository:
  https://github.com/paxtonef/cpl-product-integration.git

Original candidate:
  c7c659ac47cc38f1e36fa4a89fc73755449e4e5b

Original verification:
  89a53b9848a9292c7b36b3c87b58c31557c8826b

Repair candidate:
  430106757662369c6f77686a17c9ac51ea3ecca5

PI-06-VF-03:
  CLOSED

VIN locator:
  PASS

Candidate E2E:
  12/12 passed

PI-06-VF-04:
  CLOSED

Question 2 enabled:
  PASS

Multi-question:
  PASS

Same Case:
  PASS

Same PGDR execution:
  PASS

Refresh between questions:
  PASS

PI-06-VF-05:
  CLOSED

AMBIGUOUS -> Clarification:
  PASS

PI-02 refusal -> Refusal:
  PASS

Clarification journey:
  PASS

Refusal journey:
  PASS

Clarification refresh/deep-link:
  PASS

Refusal refresh/deep-link:
  PASS

ESCALATED:
  PASS

Result:
  PASS

History:
  PASS

Canonical acceptance journeys:
  11/11 (12 test cases)

Adversarial browser tests:
  8

Production build:
  PASS

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
  0

FINAL VERDICT:
  PI_06_FRONTEND_REPAIR_VERIFIED
```

## STOP

**STOP.** This re-verification does not repair, does not merge, and does not modify PI-05, CPL, VIR, or PGDR.
