# PI_06_FRONTEND_JOURNEY_STRUCTURING_v0

**Structuring only. No frontend code is produced by this document. No PI-01..PI-05, CPL, VIR, or PGDR file is
touched.**

---

## 1. Product baseline

```text
Product-integration main:  f10faa0ec21d96858ea50983eb834103fdd90f3c  (PI-05 closure)
PI-05 integrated software:     9a762732d1ff5e315b78fe1862e739a9e557754d
PI-05 status:                       CLOSED
```

Every API route, request/response schema, and error category referenced below was read directly from the
pinned source at this commit — `src/product_integration/api/routes.py`, `schemas.py`, `errors.py` — not
assumed or reconstructed from memory. Where a screen needs to show PGDR's own domain output, its exact field
set was read directly from `pgdr.models.GaragePreparationReport` (PGDR baseline `0580b1a5ba5867a607a33197372
fcaf4164f0fb6`), and VIR's clarification shape from `vir.domain.models.ClarificationQuestion` (VIR baseline
`a342aba7cc2fc517621f4fc79c3191bdfdc9e10b`).

Backend product path (unchanged, reused exactly as PI-05 exposes it):

```text
Contact -> Vehicle -> Case -> VIR -> VIR clarification (if needed) -> PGDR -> PGDR answer continuation
(if needed) -> final result -> history
```

---

## 2. User journey

```text
ENTRY
  |
CONTACT / REGISTRATION            POST /contacts  (or supply existing contact_id)
  |
VEHICLE REGISTRATION              POST /vehicles
  |
CASE / DIAGNOSTIC START (VIR)     POST /cases
  |
VIR RESOLUTION
  |-- resolved / provisionally_resolved / ambiguous-without-questions -> proceed
  |-- clarification required (ambiguous, clarification_questions present) -> CLARIFICATION screen
  |-- progression refused (PI02_HANDOFF_REFUSED) -> REFUSAL screen, journey halts here
  |
PGDR COMPLAINT + CONTEXT + CONSENT   (collected in-browser, never derived from VIR)
  |
POST /cases/{case_id}/diagnostics
  |
PGDR SESSION
  |-- BLOCKED (question) -> QUESTION screen -> POST .../answers -> loops
  |-- COMPLETED (incl. ESCALATED) -> RESULT screen
  |
RESULT                             GET /executions/{execution_id}/artifact
  |
HISTORY / RETURN TO CASE            GET /cases/{case_id}/history
```

This is the exact shape the Reality Check names in §2/§5 of the PI-06 instruction, transcribed with real API
calls attached to each transition rather than left implicit.

---

## 3. Screen inventory

Ten screens, not twelve — two of the instruction's own candidate list (§6: "diagnostic progress" and
"PGDR question/answer") collapse into one stateful screen, since PGDR's `BLOCKED` state *is* the progress
indicator (there is no separate "PGDR is thinking" state PI-05 exposes between question cycles — confirmed:
`start_vehicle_diagnostic`/`continue_vehicle_diagnostic` are synchronous HTTP calls that return either
`BLOCKED` or a terminal outcome, never an intermediate "running" status a screen would need to represent
distinctly).

| # | Screen | Purpose |
|---|---|---|
| 1 | **Entry** | Landing; start new journey or resume existing Case by ID |
| 2 | **Registration** | Contact + vehicle registration in one form (matches `POST /vehicles`' own coupled granularity) |
| 3 | **VIR Resolving** | Transient loading state while `POST /cases` is in flight |
| 4 | **VIR Result** | Shows resolution status; branches to Clarification, Refusal, or proceeds to Diagnostic Start |
| 5 | **VIR Clarification** | Renders `clarification_questions`, collects answers, submits |
| 6 | **VIR Refusal** | Explains non-admissible progression; offers registration retry, never a diagnostic |
| 7 | **Diagnostic Start** | Collects complaint text + consent, starts PGDR |
| 8 | **Diagnostic Question (BLOCKED)** | One question at a time; loops until terminal |
| 9 | **Result** | Renders the terminal `GaragePreparationReport`, including the ESCALATED distinction |
| 10 | **Case History** | Case-centric summary of the whole journey; reachable at any time via `case_id` |

An eleventh, cross-cutting **Error/Retry** presentation (§6's item 12) is not a separate *screen* — it is a
state every screen above can enter (§7), rendered in place, since the recoverable action always depends on
which screen it happened on (retry the same POST, or navigate back to Case History).

---

## 4. Screen-state matrix

Only states PI-05 actually produces are listed — none invented.

| Screen | States |
|---|---|
| Registration | `INITIAL`, `SUBMITTING`, `SUCCESS`, `CONFLICT`, `AUTHORITY_REJECTION`, `CPL_PERSISTENCE_FAILURE` |
| VIR Resolving | `LOADING` (no other state — this screen only exists for the duration of one `POST /cases` call) |
| VIR Result | `RESOLVED` (`SUCCESS` + status in `resolved`/`provisionally_resolved`/`insufficient_data`/`contradictory`/`ambiguous` with no questions), `CLARIFICATION_REQUIRED` (`ambiguous` + non-empty `clarification_questions`), `REFUSED` (`outcome=VIR_TECHNICAL_FAILURE`/a refused status — see §8), `VIR_TECHNICAL_FAILURE`, `CPL_PERSISTENCE_FAILURE` |
| VIR Clarification | `READY`, `SUBMITTING`, `SUCCESS` (loops back to VIR Result), `STILL_AMBIGUOUS` (clarified but still needs more), `NOT_FOUND`, `VIR_TECHNICAL_FAILURE` |
| VIR Refusal | `REFUSED` (terminal for this path — no retry action exists at the API level except starting over at Registration) |
| Diagnostic Start | `READY`, `SUBMITTING`, `BLOCKED`, `COMPLETED` (incl. escalated), `PI02_HANDOFF_REFUSED`, `CASE_NOT_FOUND`, `PGDR_TECHNICAL_FAILURE`, `CPL_PERSISTENCE_FAILURE`, `CASE_ORCHESTRATION_FAILURE` |
| Diagnostic Question | `ANSWER_REQUIRED`, `SUBMITTING`, `BLOCKED` (next question), `COMPLETED`, `CROSS_RESOURCE_MISMATCH`, `PROCESS_LOCAL_STATE_UNAVAILABLE`, `PGDR_TECHNICAL_FAILURE`, `CPL_PERSISTENCE_FAILURE`, `CASE_ORCHESTRATION_FAILURE` |
| Result | `TERMINAL_RESOLVED`, `TERMINAL_ESCALATED`, `LOADING` (fetching artifact), `NOT_FOUND` |
| Case History | `LOADING`, `READY`, `NOT_FOUND` |

`TECHNICAL_FAILURE`/`ORCHESTRATION_FAILURE` states named in the instruction's own §7 example list map
one-to-one onto the real `PGDR_TECHNICAL_FAILURE`/`CASE_ORCHESTRATION_FAILURE`/`CPL_PERSISTENCE_FAILURE`
categories `errors.py` actually defines — no separate frontend vocabulary is introduced.

---

## 5. API -> UI mapping

Every row is a real route, read directly from `routes.py`.

| User action | HTTP call | Success response | Business-state response | Error responses |
|---|---|---|---|---|
| Submit registration form | `POST /vehicles` | `RegisterVehicleResponse{outcome:"SUCCESS", contact_id, asset_id}` | — | `403` AUTHORITY_REJECTION, `409` CONFLICT, `404` NOT_FOUND, `502` CPL_PERSISTENCE_FAILURE |
| (Optional) look up an existing contact | `GET /contacts/{contact_id}` | `ContactResponse` | — | `404` NOT_FOUND |
| Start Case + VIR | `POST /cases` | `CaseVIRResponse{outcome:"SUCCESS", case_id, vir_execution_id, vir_artifact_id, vir_resolution_status}` | `vir_resolution_status` drives VIR Result branching (§8) | `403`, `409`, `502` VIR_TECHNICAL_FAILURE/CPL_PERSISTENCE_FAILURE |
| Read VIR resolution detail (to render clarification questions / result fields) | `GET /executions/{vir_execution_id}/artifact` | `ArtifactResponse{payload: <VehicleIdentityResolution dump>}` | `payload.clarification_questions` (non-empty) drives Clarification screen; `payload.resolution_status`/`payload.confidence`/`payload.vehicle_identity` render VIR Result | `404` NOT_FOUND |
| Submit clarification answers | `POST /cases/{case_id}/vir/clarifications` | `CaseVIRResponse` (new `vir_execution_id`) | Same branching as `POST /cases`'s response — may still require further clarification | `404`, `502` |
| View Case status | `GET /cases/{case_id}` | `CaseStatusResponse{case_status, current_execution_id, ...}` | drives navigation recovery (§16) | `404` NOT_FOUND |
| Start PGDR diagnostic | `POST /cases/{case_id}/diagnostics` | `DiagnosticResponse{outcome, execution_id, blocked, terminal, pending_questions, artifact_id}` | `blocked=true` -> Question screen; `terminal=true` -> Result screen; `outcome="PI02_HANDOFF_REFUSED"` -> Refusal screen | `404` CASE_NOT_FOUND (via `DiagnosticResponse` when `outcome="CASE_NOT_FOUND"` is not itself an HTTP error in the current implementation — see §18 note), `403`, `409`, `502` (PGDR_TECHNICAL_FAILURE / CPL_PERSISTENCE_FAILURE / CASE_ORCHESTRATION_FAILURE) |
| Submit an answer | `POST /cases/{case_id}/diagnostics/{execution_id}/answers` | `DiagnosticResponse` (same shape) | same branching | `404` CROSS_RESOURCE_MISMATCH, `409` PROCESS_LOCAL_STATE_UNAVAILABLE, `502` |
| Poll/re-check execution status | `GET /executions/{execution_id}` | `ExecutionStatusResponse{execution_status, blocked, terminal, artifact_id}` | used for refresh/recovery (§16/§17), not for a live polling loop (§13) | `404` |
| Retrieve final report | `GET /executions/{execution_id}/artifact` | `ArtifactResponse{payload: <GaragePreparationReport dump>}` | drives Result screen (§14) | `404` |
| View Case history | `GET /cases/{case_id}/history` | `CaseHistoryResponse{executions: [...]}` | drives History screen (§15) | `404` |

**No screen depends on undocumented API behavior** — every field referenced above is a real, named field on a
real response schema read directly from `schemas.py`.

---

## 6. Navigation model

Deterministic, derived entirely from `GET /cases/{case_id}` + `GET /cases/{case_id}/history` — never from
frontend-only memory:

```text
No case_id in URL / session           -> Entry / Registration
Case exists, case_status="OPEN"           -> should not normally be observed (create_case's own default,
                                              transient before VIR admission) -> VIR Resolving
Case exists, case_status="WAITING_FOR_EXTERNAL_INFORMATION"
                                               -> Clarification screen (re-fetch the VIR artifact for the
                                                  latest execution to get current clarification_questions)
Case exists, case_status="IN_PROGRESS", no PGDR execution in history
                                                   -> Diagnostic Start screen
Case exists, case_status="WAITING_FOR_USER"           -> re-fetch GET /executions/{current_execution_id};
                                                            its pending_questions equivalent is NOT returned
                                                            by GET /executions/{id} (that endpoint returns
                                                            only ExecutionStatusResponse, no pending_
                                                            questions field) -- see the explicit gap this
                                                            produces, §24/§31 below
Case exists, case_status="RESOLVED"                       -> Result screen (fetch artifact by
                                                                current_execution_id)
```

---

## 7. VIR clarification UX

```text
POST /cases returns vir_resolution_status="AMBIGUOUS"
  |
fetch GET /executions/{vir_execution_id}/artifact
  |
payload.clarification_questions non-empty?
  |-- yes -> render one ClarificationQuestion per entry (question_id, prompt, optional choices --
  |          exact fields read from vir.domain.models.ClarificationQuestion) -> user answers all required
  |          ones -> POST /cases/{case_id}/vir/clarifications {answers: [...]}
  |-- no  -> AMBIGUOUS with no clarification_questions is not clarifiable through this route; treat as
             VIR Result's generic "unresolved, no further product action available" state, not a crash
  |
response is a new CaseVIRResponse -- loop back to VIR Result branching (may need a SECOND round of
  clarification; the UI must support repeating this cycle, not assume one round suffices)
```

No fresh vehicle registration is triggered — the same `case_id` is reused throughout, exactly as PI-01's Path
B / PI-05's clarification route is designed (confirmed: `register_vir_resolution_result` links the clarified
result to the original execution via `clarifies_execution_id`, never creating a new Case).

---

## 8. PI-02 refusal UX

`POST /cases/{case_id}/diagnostics` returning `outcome="PI02_HANDOFF_REFUSED"` (HTTP `200`, not an error — see
§5) is the exact, only signal for this state. The screen must say, in plain terms: *identity resolution did
not produce a result PGDR diagnostics can proceed from*. The only supported next action, per the actual API
surface, is to return to Registration and attempt a new vehicle/Case — there is no retry-in-place operation
for a refused VIR result (PI-02's refusal is a property of the persisted VIR resolution itself, not a
transient failure). The UI must not invent a "try VIR again on the same Case" button, since no such endpoint
exists.

---

## 9. PGDR complaint / context / consent

Collected entirely client-side, mapped 1:1 onto `StartDiagnosticRequest`:

```text
complaint_text                          -> free-text field, required
consent_media_analysis_allowed              -> explicit checkbox, default unchecked (matches the schema's
                                                own default=False -- never pre-checked)
consent_report_storage_allowed                  -> explicit checkbox, default unchecked
```

`UserContext` is not currently a distinct input on `StartDiagnosticRequest` (confirmed by direct read of
`schemas.py` — the route constructs `UserContext()` with no fields from the request body at all). The
frontend therefore has **no UI surface for UserContext** under the current PI-05 contract — flagged explicitly
in §24 as a structural observation, not fabricated around.

None of these three inputs are derived from VIR data anywhere in this flow — confirmed structurally (VIR's
artifact payload is never read by the Diagnostic Start screen).

---

## 10. PGDR BLOCKED / question UX

```text
POST /diagnostics (or .../answers) returns blocked=true
  |
render pending_questions[0]  (question_id, prompt, optional choices)
  |
user answers -> POST /cases/{case_id}/diagnostics/{execution_id}/answers {question_id, value}
  |
response: blocked=true again (another question) OR terminal=true (Result)
```

The UI must loop this cycle an unbounded number of times (no fixed question count exists — confirmed:
PGDR's own question-selection engine determines this dynamically, observed at PI-03's own build to vary by
complaint). `execution_id` is retained across the whole loop, never re-derived.

---

## 11. Result UX

Rendered fields, read directly from `pgdr.models.GaragePreparationReport`:

```text
report_id, vehicle, customer_reported_problem, symptom_summary, onset_and_evolution,
reproduction_conditions, warning_indicators, safety_information, recent_vehicle_events,
evidence_index, systems_to_examine, suggested_professional_checks, unresolved_questions,
contradictions, limitations, generated_at
```

Plus artifact metadata from the wrapping `ArtifactResponse`: `artifact_id`, `execution_id`, `artifact_type`
(`"pgdr_garage_preparation_report"`), `artifact_status`.

Diagnostic outcome/status displayed: `ExecutionStatusResponse.execution_status`. Critical, explicit rule
(§14 of the PI-06 instruction, §24 of PI-03's own build): **`execution_status="COMPLETED"` covers both a
normal resolution and an escalated safety outcome** — the only way to distinguish them in the UI is by
inspecting the report's own `safety_information`/`warning_indicators` content, never by a separate "FAILED"
status, because none exists for this case (confirmed: PGDR's `ESCALATED` domain state maps to CPL `COMPLETED`
at PI-03's own build, unchanged since). The Result screen must present an escalated report with a visually
distinct, safety-forward treatment (e.g., a prominent safety banner) *driven by the report's own content*,
not by a nonexistent `status=ESCALATED` API field — no such field exists on `ExecutionStatusResponse` or
`ArtifactResponse`. This is a real, structural fact about the current API worth flagging (§24).

---

## 12. History UX

`GET /cases/{case_id}/history` returns `case_status`, `current_execution_id`, `contact_id`, `asset_id`, and
`executions: [{execution_id, runner_type, execution_status, artifact_id}]`. The screen renders one row per
execution (VIR, then PGDR, in the order the API returns them — confirmed `routes.py` orders by
`created_at`), each linking to its artifact if `artifact_id` is present. No event log, no per-question audit
trail is available through this endpoint or needed — this is a Case-level summary, not a technical console.

---

## 13. Error UX

| Category (from `ProductAPIErrorCategory`) | HTTP | Message treatment | Retry safe? | User input needed? | Support/operator escalation? |
|---|---|---|---|---|---|
| `NOT_FOUND` | 404 | "This item could not be found." | No (resource genuinely absent) | Possibly (re-check the link/ID) | No |
| `CROSS_RESOURCE_MISMATCH` | 404 | Same as NOT_FOUND (deliberately, per `errors.py`'s own documented reasoning) | No | Yes (verify the right Case) | No |
| `AUTHORITY_REJECTION` | 403 | "This action isn't permitted." | No | No | Yes |
| `CONFLICT` | 409 | "This can't be completed in the current state." | Sometimes (re-fetch state first) | No | No |
| `VIR_TECHNICAL_FAILURE` / `VIR_NON_RESOLUTION` | 502 | "Vehicle identity lookup is temporarily unavailable." | Yes | No | If repeated |
| `PGDR_TECHNICAL_FAILURE` | 502 | "The diagnostic service is temporarily unavailable." | Yes (retry the same answer submission) | No | If repeated |
| `CPL_PERSISTENCE_FAILURE` | 502 | "We couldn't save your progress — please try again." | Yes | No | If repeated |
| `CASE_ORCHESTRATION_FAILURE` | 502 | "Your diagnostic answer was recorded, but we're catching up your case status." | Yes — re-fetch `GET /cases/{case_id}` after a short delay; the underlying PGDR result is *not* lost (confirmed: PI-04-VF-01's own repair guarantees this) | No | If it doesn't resolve on refresh |
| `PROCESS_LOCAL_STATE_UNAVAILABLE` | 409 | "This diagnostic session can no longer accept an answer here." | No — this specific execution cannot be resumed; the honest, disclosed PGDR cross-instance limitation (§17) | No | Yes — no in-product recovery exists for this exact state |
| `UNEXPECTED` | 500 | Generic "Something went wrong." | Maybe | No | Yes |

Raw backend exception text is never present in any `ProductAPIError` response body (confirmed by direct
source read of `errors.py`) — the frontend must render only `error_category` + `message`, never a raw stack
trace even if one somehow appeared.

---

## 14. Refresh / recovery behavior

```text
Page refresh / browser close+reopen / new browser session / deep link to /cases/{case_id}:
  1. Read case_id from the URL (never from frontend-only storage as the source of truth).
  2. GET /cases/{case_id} -> case_status + current_execution_id.
  3. GET /cases/{case_id}/history -> full execution list.
  4. Apply the navigation model (§6) to decide which screen to show.
```

**The known PGDR cross-instance limitation, stated honestly** (§17 of the PI-06 instruction): if
`case_status="WAITING_FOR_USER"` after a refresh/new-session, the underlying PGDR `SessionController` that
was driving that diagnostic may no longer have in-memory state available in whatever backend process
originally handled it (confirmed limitation, carried since PI-03, still real at PI-05's own closure —
`PROCESS_LOCAL_STATE_UNAVAILABLE`, §13). The frontend cannot know in advance whether this will happen; it can
only attempt the next `POST .../answers` call and handle a `409 PROCESS_LOCAL_STATE_UNAVAILABLE` if it does.
**The UI must present this specific 409 as a distinct, named state** — "this diagnostic can't be continued
from here" — never as a generic technical failure, and never silently retried as if it might succeed (it
will not, by design, until the backend's own operational model changes — out of PI-06's scope to solve).

---

## 15. Resource-ID model

```text
Retained across the session (URL-addressable, Case-centric):
  case_id           -- the primary navigation key after journey creation
Retained transiently (needed to complete the current step, not for long-term navigation):
  contact_id, asset_id  -- only needed up through Case creation
  execution_id (current)   -- needed for the active diagnostic's answer submissions; re-derivable from
                                GET /cases/{case_id} (current_execution_id) at any time
  artifact_id                  -- needed only to fetch a specific result; re-derivable from history
```

The browser is never responsible for reconstructing which VIR artifact belongs to which Case, or which
execution is "current" by any means other than asking the API directly (§6) — confirmed this is exactly
`CaseStatusResponse.current_execution_id`'s purpose, already computed server-side.

---

## 16. Framework decision

```text
CHOSEN:      React + Vite (client-side SPA, TypeScript)
REJECTED:        Next.js
```

**Rationale**: this is an authenticated, bounded, ten-screen product wizard, not a content site — there is no
SEO/crawlability requirement and no content that benefits from server-side rendering. Next.js's core value
proposition (file-based routing with SSR/RSC, its own API-route layer) is a poor fit here specifically because
its API-route convention creates a live temptation to reimplement PI-05 logic inside the frontend framework
itself — exactly what §22/§4 forbid. A plain client-side SPA over a fixed API base URL keeps the "thin client"
boundary structurally enforced by the tooling, not just by discipline. React + Vite gives: trivial deployment
(a static build, served by any static host or reverse-proxied alongside FastAPI — no Node server process to
operate), a fast dev loop, straightforward client-side routing (`react-router`) for the Case-centric URL
scheme (§19), plain `fetch`/typed-client form handling with no SSR/hydration edge cases to reason about, and
straightforward Playwright E2E setup against a static build (§21). Maintenance burden is lower: one build
artifact, one runtime environment (the browser), no server-side framework version to track alongside FastAPI's
own.

No other framework was seriously considered — the decision criteria (§20 of the PI-06 instruction) don't
surface a case for anything heavier, and nothing in the repository's existing conventions (pure Python
backend, no prior frontend tooling) argues for a specific alternative.

---

## 17. Frontend architecture

```text
src/
  api/            -- the one API-client boundary (§18)
  routes/         -- one file per browser route (§19), each composing components from components/
  components/     -- the bounded component set (§17)
  state/          -- minimal client-only state (form drafts, in-flight flags) -- never a cache of
                       Case/execution truth (§21 of the PI-06 instruction)
```

Backend/CPL state is authoritative throughout — no local store (Redux, Zustand, or otherwise) holds a second
copy of `case_status`/`execution_status`/diagnostic results as a source of truth; every screen re-fetches from
the API on mount and after every mutating call, per §6's navigation model. Local state is limited to: current
form field values before submission, `SUBMITTING`/`LOADING` flags, and which `pending_questions[0]` is
currently displayed (itself always freshly derived from the last API response, never persisted independently).

---

## 18. API client boundary

One module, one typed method per route in §5's table — e.g. conceptually:

```text
createVehicle(body) -> RegisterVehicleResponse
startCaseVIR(body) -> CaseVIRResponse
getArtifact(executionId) -> ArtifactResponse
submitClarification(caseId, body) -> CaseVIRResponse
getCase(caseId) -> CaseStatusResponse
getCaseHistory(caseId) -> CaseHistoryResponse
startDiagnostic(caseId, body) -> DiagnosticResponse
submitAnswer(caseId, executionId, body) -> DiagnosticResponse
getExecutionStatus(executionId) -> ExecutionStatusResponse
```

Base URL is one configuration value. Every method: (a) sends exactly the request schema §5 documents, (b) on
a non-2xx response, normalizes into one client-side `ApiError{category, message, status}` shape built from
the real `{error_category, message, ...}` body `errors.py` actually returns — never invents a category the
backend didn't send. No orchestration logic (deciding what screen comes next, retry loops, polling) lives in
this layer — that belongs to the route-level components, which consult §5/§6/§13's tables.

---

## 19. Component boundaries

```text
JourneyShell                  -- Case-centric layout wrapper; owns the recovery logic in §14
RegistrationForm               -- Contact + vehicle fields, maps to POST /vehicles
VIRResolutionPanel                  -- renders VIR Result branching (§5/§8)
ClarificationForm                       -- renders clarification_questions, maps to §7
RefusalPanel                                -- the PI-02 refusal message + "start over" action (§8)
ComplaintForm                                   -- maps to §9
ConsentForm                                         -- explicit checkboxes, maps to §9 (may be a section of
                                                        ComplaintForm rather than a separate component --
                                                        left as an implementation choice, not a product
                                                        decision)
DiagnosticQuestionForm                                  -- one PGDR question at a time, maps to §10
ExecutionStatusPanel                                        -- used inside JourneyShell's recovery flow and
                                                                the Result screen's loading state
GaragePreparationReportView                                     -- renders the report fields in §11
CaseHistoryView                                                     -- renders §12
ErrorBanner                                                             -- renders §13's table uniformly
                                                                            across every screen
```

No generic design system, no component library beyond what's listed — matches §23's own instruction not to
build one.

---

## 20. Browser routing

```text
/                                              Entry
/register                                          Registration
/cases/{case_id}                                       Case-centric hub -- JourneyShell resolves which
                                                          sub-view to render per §6's navigation model
/cases/{case_id}/clarification                             VIR Clarification (only reachable when Case
                                                              state actually requires it -- direct navigation
                                                              otherwise redirects per §6)
/cases/{case_id}/diagnostic                                     Diagnostic Start / Question (same route,
                                                                   state-driven per §10)
/cases/{case_id}/result                                             Result
/cases/{case_id}/history                                                History
```

Every `/cases/{case_id}/*` route, on load, re-derives its actual state from the API (§6/§14) rather than
trusting the route name alone — a user landing on `/cases/{id}/result` for a Case that's actually still
`WAITING_FOR_USER` gets redirected to the diagnostic question view, not a broken/empty result page.

---

## 21. Acceptance journeys

All ten mandatory scenarios (§25 of the PI-06 instruction), each traced to real API behavior already proven
at PI-05's own independent verification:

```text
A. Happy path                    Registration -> Case+VIR (resolved) -> Diagnostic Start -> BLOCKED -> answer
                                    -> COMPLETED -> Result -> History
B. VIR clarification path            Registration -> Case+VIR (ambiguous) -> Clarification -> submit ->
                                        resolved -> continues as (A)
C. PI-02 refusal                         Case+VIR with a refused status -> Refusal screen, journey halts
D. PGDR one-question BLOCKED path            Diagnostic Start -> BLOCKED (1 question) -> answer -> terminal
E. PGDR multiple-question path                   Diagnostic Start -> BLOCKED -> answer -> BLOCKED (again,
                                                    N times) -> terminal
F. ESCALATED result                                  Complaint triggering PGDR's SafetyEngine -> COMPLETED
                                                        immediately -> Result screen shows the safety-forward
                                                        treatment (§11)
G. Browser refresh during journey                        Mid-diagnostic (BLOCKED) -> hard refresh -> same
                                                             process still running -> question re-renders
                                                             correctly from re-fetched state
H. Return to existing Case                                    Close browser entirely -> reopen -> navigate to
                                                                  /cases/{case_id} directly -> correct screen
                                                                  per §6
I. Technical failure                                              Inject a VIR/PGDR technical failure ->
                                                                      confirm §13's treatment, confirm retry
                                                                      succeeds once the fault is cleared
J. Orchestration failure                                              Inject a Case-sync failure after a
                                                                          valid BLOCKED persist -> confirm
                                                                          §13's CASE_ORCHESTRATION_FAILURE
                                                                          treatment, confirm the underlying
                                                                          diagnostic is not lost
```

A required eleventh scenario this structuring adds, since it names a real, distinct backend behavior with no
in-product recovery path (§14): **K. Process-restart continuation** — start a diagnostic, reach `BLOCKED`,
then (in a real E2E environment) restart the backend process; attempt to continue; confirm the UI presents
`PROCESS_LOCAL_STATE_UNAVAILABLE` as a distinct, honest terminal state for that specific diagnostic, not a
crash and not a silent retry loop.

---

## 22. Test strategy

```text
Unit tests            -- pure state-transform functions: given an API response, which screen/state does §6's
                            navigation model select? (No backend needed.)
Component tests            -- each form in §19 renders its fields correctly, validates required inputs
                                 client-side (§26), and calls the correct api/ method with the correct shape
                                 on submit, using a mocked API client.
API-contract tests              -- the api/ client's request/response typing is exercised against PI-05's
                                      real OpenAPI schema (fetched from the running FastAPI app, per PI-05's
                                      own confirmed schema generation) to catch drift early, without a full
                                      browser.
Browser E2E (Playwright)             -- all eleven acceptance journeys in §21, run against a real running
                                          PI-05 instance (real VIR ASGI, real PGDR SessionController, real
                                          PostgreSQL) -- never a mocked backend for these, matching PI-05's
                                          own "real infrastructure" discipline.
```

Definitive acceptance is the Playwright layer exercising real PI-05 behavior — unit/component/contract tests
support fast iteration but do not substitute for it.

---

## 23. Accessibility / basic UX minimum

```text
- All form inputs (Registration, Complaint/Consent, Clarification, Diagnostic Question) keyboard-operable,
  with visible focus states and associated <label> elements.
- Client-side required-field validation surfaces inline, adjacent to the field, before submission is
  attempted.
- Every SUBMITTING/LOADING state (§4) renders a visible, non-flashing loading indicator; buttons disable
  during submission to prevent duplicate requests (complementing, not replacing, PI-05's own server-side
  idempotency).
- BLOCKED/question state is visually and textually distinct from any error state -- a user must never
  mistake "we need your answer" for "something broke" (§12 of the PI-06 instruction, the same principle
  PI-05's own HTTP status mapping already encodes as 200/201, never 5xx).
- Result vs. error is unambiguous -- the Result screen (§11) and the ErrorBanner (§19) never share visual
  treatment.
- Responsive layout sufficient for the forms/panels in §19 to remain usable on a narrow viewport -- no
  specific breakpoint system mandated.
```

This is operational usability, not visual-brand design — matches §27's own boundary.

---

## 24. Risks / known limitations

```text
1. PGDR cross-instance session limitation (carried since PI-03, confirmed still real at PI-05's closure):
   a BLOCKED diagnostic cannot be continued from a different backend process than the one that started it.
   The frontend surfaces this honestly (§13/§14/§21-K) but cannot solve it -- out of PI-06's scope, and
   explicitly forbidden to "solve" via unauthorized persistence (§17 of the PI-06 instruction itself, which
   only asks that this be documented honestly, which this document does).

2. GET /executions/{execution_id} does not return pending_questions (confirmed by direct read of
   ExecutionStatusResponse -- only DiagnosticResponse, returned by the POST routes, carries that field). This
   means a page that only has an execution_id and needs to re-render "what question is pending" after a
   refresh (§6's WAITING_FOR_USER case) has no read-only endpoint to recover that specific detail without
   re-submitting something. The practical consequence: on refresh mid-BLOCKED-diagnostic, the frontend can
   confirm THAT a question is pending (execution_status="BLOCKED") but cannot re-render WHICH question it was
   without either (a) the process-local registry still holding the session (the common case within one
   process lifetime, per PI-05's own design) making the next answer submission itself return the current
   question again on a benign retry pattern, or (b) presenting a "reconnecting..." state that resolves once
   the user's next action round-trips. This is a minor UX rough edge, not a blocking gap -- the underlying
   diagnostic is never lost or corrupted (confirmed throughout PI-03/PI-04/PI-05's own verification), only
   the specific question text is momentarily unavailable to redisplay without another API interaction. Not
   filed as FRONTEND_BLOCKED_BY_API_GAP (§31) because it doesn't prevent journey completion -- it is a
   possible future enhancement to ExecutionStatusResponse, not a hard blocker, and is explicitly out of scope
   to fix in PI-06 (§4: "Do NOT invent new backend endpoints unless a real frontend blocker is demonstrated" --
   this is a rough edge, not a blocker, since the journey remains completable).

3. StartDiagnosticRequest has no UserContext input surface (§9) -- the backend already constructs an empty
   UserContext() regardless of what the frontend could send. Not a blocker (nothing in the required journey,
   §5 of the PI-06 instruction, asks for UserContext-specific UI), simply noted so no future confusion arises
   about where to add such fields if ever required -- it would require a PI-05 schema change first, out of
   PI-06's own scope.

4. AMBIGUOUS VIR results with an empty clarification_questions list have no product-level recovery action
   defined by the current API (§7) -- the frontend can only display this as an unresolved state, not offer a
   clarification form. Confirmed this is a genuine (if narrow) VIR-domain edge case, not a frontend
   omission.
```

---

## 25. Non-scope (confirmed, unchanged from the instruction's own §28)

Marketing site, CMS, payments/subscriptions, community/social features, advanced account management, admin
analytics, native mobile app, generic component library — none of these are structured or implied by anything
above.

---

## 26. Build units / decomposition

```text
ONE bounded build.
```

Rationale (§30 of the PI-06 instruction: "Do NOT assume decomposition is necessary"): ten screens, nine API
client methods, eleven component boundaries — small enough for a single coding pass to build and test as one
unit, using the component boundaries in §19 as internal structure rather than separate delivery packages.
Splitting into multiple build units (e.g., "registration+VIR" vs "PGDR+result") would introduce an
integration seam (shared routing, shared API client, shared error handling) with no corresponding benefit at
this size — the smallest structure that remains independently buildable and testable, per the instruction's
own criterion, is the whole thing as one unit.

---

## 27. Build dependency order

```text
1. API client (§18) + typed schemas mirroring §5's table -- everything else depends on this.
2. Routing shell (§20) + JourneyShell (§19) + navigation model (§6) -- the skeleton every screen mounts into.
3. Registration -> VIR Result -> Clarification -> Refusal (the identity-resolution half of the journey, §2
   through §8).
4. Diagnostic Start -> Question -> Result (the PGDR half, §9 through §11).
5. History (§12) -- depends on Case/execution data shapes already established by steps 3-4.
6. Error UX (§13) + accessibility pass (§23) -- cross-cutting, applied across everything built in 2-5.
7. Acceptance journeys (§21) + test strategy (§22) -- written against the completed build, exercising real
   PI-05.
```

---

## 28. FRONTEND_BUILD_READY verdict

No `FRONTEND_BLOCKED_BY_API_GAP` condition exists: every required user action in the journey (§5 of the
PI-06 instruction) maps to a real, already-verified PI-05 route (§5 above). The two structural observations
in §24 (items 2 and 3) are genuine, disclosed rough edges — neither prevents journey completion, and neither
requires a PI-05 modification to build a working, honest frontend around.

```text
FRONTEND_BUILD_READY = YES
```

---

## PI-06 FRONTEND JOURNEY STRUCTURING

```text
Product API baseline:
  f10faa0ec21d96858ea50983eb834103fdd90f3c

PI-05 integrated software:
  9a762732d1ff5e315b78fe1862e739a9e557754d

Journey:
  DETERMINED

Screens:
  10

API coverage:
  COMPLETE (2 non-blocking structural observations, §24 items 2-3 -- neither blocking)

Navigation:
  DETERMINED

Refresh/recovery:
  PASS (with the honest, disclosed PGDR cross-instance limitation, §14/§24-1)

Framework:
  React + Vite (TypeScript), client-side SPA

Frontend architecture:
  api/ + routes/ + components/ + state/, backend-authoritative, no local cache of Case/execution truth

Acceptance journeys:
  11 (the 10 mandatory + 1 added: process-restart continuation, §21-K)

Test strategy:
  DETERMINED (unit / component / API-contract / Playwright E2E against real PI-05)

Frontend build units:
  1

API blocker:
  NONE

FINAL VERDICT:
  FRONTEND_BUILD_READY
```
