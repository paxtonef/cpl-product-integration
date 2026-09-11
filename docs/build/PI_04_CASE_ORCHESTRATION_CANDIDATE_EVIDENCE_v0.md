# PI_04_CASE_ORCHESTRATION_CANDIDATE_EVIDENCE_v0

## 1. Identity

```text
Base SHA:                          3bd2ade81da9304e75a8046f6222c134bd4ebe0a  (PI-03 closure, main)
Candidate branch:                      pi-04-case-orchestration-candidate
Candidate SHA:                             reported in the accompanying build handoff
Tree SHA:                                      reported in the accompanying build handoff

CPL software baseline:      6181dabb9239e281974c368ad8f5df80350cabf1 (unchanged, pinned)
CPL migration head:             027 (unchanged, zero new migrations)
VIR full SHA:                       a342aba7cc2fc517621f4fc79c3191bdfdc9e10b (confirmed unchanged since
                                       every prior reference in this project)
PGDR full SHA:                          0580b1a5ba5867a607a33197372fcaf4164f0fb6 (confirmed unchanged)
```

---

## 2. PI-01/PI-02/PI-03 reuse — composed, not duplicated

```text
PI-01 (product_integration.cpl_registration.register_vir_execution): called directly by
  resolve_vehicle_identity, unmodified. Its own outcome vocabulary (VIRRegistrationOutcome) is passed
  through verbatim in VehicleIdentityResolutionResult.outcome — never re-wrapped.
PI-01 (register_vir_resolution_result, Path B): used only in the candidate's own refusal test, to inject a
  real VIR domain object carrying one of PI-02's 3 refused statuses (see §11 below) — not used by production
  orchestration code, which always goes through the fresh-resolve Path A.
PI-02 (product_integration.pgdr.handoff_mapper.map_resolution): called directly by start_vehicle_diagnostic,
  unmodified. Its VIRPGDRHandoffError is caught at exactly one place — the refusal boundary — and translated
  into DiagnosticStartOutcome.PI02_HANDOFF_REFUSED, never suppressed or reinterpreted.
PI-03 (product_integration.pgdr.session_adapter.start_pgdr_session / continue_pgdr_session): called directly
  by start_vehicle_diagnostic / continue_vehicle_diagnostic, unmodified. PGDRSessionOutcome is passed through
  verbatim.
```

No PI-01/PI-02/PI-03 internal logic is reimplemented anywhere in `case_orchestration.py` — confirmed by
direct source read (the module contains no VIR HTTP calls, no PGDR SessionController calls beyond passing the
caller-supplied instance through, no contradiction-flattening or status-mapping logic of its own).

---

## 3. Two real architectural findings, corrected during this build

**Finding 1 — `OperationOutcome` is a single, shared enum, not two separate vocabularies.**
`app.cpl.assets.outcomes.OperationOutcome` is confirmed, by direct source read, to be the *same class* as
`app.cpl.identity.outcomes.OperationOutcome` (re-exported, not redefined) — real values `SUCCESS, NOT_FOUND,
REJECTED, INVALID, CONFLICTING, ALREADY_EXISTS`. An early draft of this candidate incorrectly assumed
`AUTHORITY_REJECTION`/`CONFLICT` values (borrowed from the unrelated `RunnerOutcome`/`CaseOutcome`
vocabularies) — corrected before this candidate's own test suite was written, confirmed by the exact mapping
in `_map_operation_outcome`.

**Finding 2 — B5's Case layer does not catch `AuthorityDeniedError`; B6's Runner layer does.**
Direct source read of `app/cpl/cases/lifecycle.py` (`create_case`, `transition_case_status`) confirms
`authority.require(...)` is called unconditionally with no surrounding `try/except AuthorityDeniedError` —
unlike `app/cpl/runners/execution.py`'s `admit_execution`/`transition_status`, which do catch it and convert
to a typed `RunnerOutcome.AUTHORITY_REJECTION`. This means `CaseOutcome.AUTHORITY_REJECTION` (though it
exists in the vocabulary) is unreachable through `create_case`'s own internal logic — a real, structural
parallel to the previously-independently-confirmed "dead enum value" pattern (VIR's `UNSUPPORTED_COUNTRY`/
`INVALID_IDENTIFIER`). PI-04's own code catches `AuthorityDeniedError` explicitly around every B3/B5 call it
makes, translating it into this orchestration's own `AUTHORITY_REJECTION`-equivalent outcome — the correct
place for this translation to live, since B3/B5 themselves don't do it.

---

## 4. Case status mapping — derived from CPL's own frozen vocabulary

```text
VALID_CASE_STATUSES (app/cpl/cases/lifecycle.py, confirmed unchanged): OPEN, IN_PROGRESS, WAITING_FOR_USER,
  WAITING_FOR_EXTERNAL_INFORMATION, RESOLVED, CLOSED, REOPENED, CANCELLED

create_case()                         -> OPEN            (CPL's own default, confirmed by source read)
VIR execution admitted                     -> IN_PROGRESS
PI-02 refuses the VIR handoff                   -> WAITING_FOR_EXTERNAL_INFORMATION (reasoned: the Case is
                                                     not abandoned — it genuinely needs different/better
                                                     identity information; CANCELLED would wrongly imply a
                                                     deliberate stop)
PGDR BLOCKED (awaiting a user answer)                -> WAITING_FOR_USER
PGDR terminal (COMPLETED or ESCALATED)                    -> RESOLVED
A PGDR_TECHNICAL_FAILURE/CPL_PERSISTENCE_FAILURE               -> Case status left UNCHANGED (an adapter/
                                                                   authority-layer failure is not a governed
                                                                   domain observation about the Case itself)
```

No status is invented; every value used is one of CPL's own frozen 8.

---

## 5. Case.current_execution_id sequencing

Set to the VIR execution_id immediately after successful VIR admission; re-set to the PGDR execution_id once
PGDR starts (whether it reaches `BLOCKED` or a terminal state). Treated strictly as an opaque Case-side
pointer throughout — never read back as if it carried execution semantics of its own (confirmed: no code path
inspects `current_execution_id`'s value to make a decision; it is only ever written).

---

## 6. VIR-first ordering and PI-02 refusal (§15/§16)

`start_vehicle_diagnostic` always looks up the persisted VIR execution/artifact for the given `case_id`
first, reconstructs the real `VehicleIdentityResolution` from the durable artifact payload, and only then
calls PI-02's `map_resolution`. PGDR is never invoked before this. If `map_resolution` raises
`VIRPGDRHandoffError`, PGDR is never called — confirmed structurally (the `start_pgdr_session` call sits
strictly after the `try/except VIRPGDRHandoffError` block, unreachable if the exception fires).

---

## 7. Files added

```text
src/product_integration/orchestration/__init__.py
src/product_integration/orchestration/errors.py                (CaseOrchestrationError, VIRArtifactNotFoundError,
                                                                    CaseNotFoundError)
src/product_integration/orchestration/case_orchestration.py         (the four public functions + internal helpers)
tests/test_case_orchestration.py                                        (10 tests)
```

No CPL file touched. No VIR file touched. No PGDR file touched. No new migration. No PI-05 product-API or
frontend code anywhere (confirmed: zero FastAPI/APIRouter references in the diff).

---

## 8. Test environment

```text
PostgreSQL version:      16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)
CPL migration head:          027, applied fresh from an empty database
Command:                         python -m pytest tests/ -v
```

---

## 9. Test results

```text
PI-04's own suite (tests/test_case_orchestration.py): 10 passed, 0 failed, 0 skipped
Combined suite (PI-01's 41 + PI-02's 42 + PI-03's 19 + PI-04's 10): 112 passed, 0 failed, 0 skipped

Run three times total from completely fresh, dropped-and-recreated databases during this build — 112/112
every time, no flakiness.
```

---

## 10. Happy-path E2E evidence (§26, mandatory)

`test_happy_path_end_to_end`: real `register_vehicle_for_contact` → real VIR resolution via PI-01 (real
`SessionController`-equivalent VIR HTTP call through ASGI transport) → Case `IN_PROGRESS`,
`current_execution_id` == VIR execution → real PGDR session via PI-03 (`BLOCKED`, Case `WAITING_FOR_USER`,
`current_execution_id` == PGDR execution) → 7 real `continue_vehicle_diagnostic` turns → `COMPLETED`, Case
`RESOLVED`. Independently queried real PostgreSQL and confirmed: exactly one Contact, one Asset, one Case,
one VIR `RunnerExecution`, one VIR `RunnerArtifact`, one PGDR `RunnerExecution`, one PGDR `RunnerArtifact`.

---

## 11. BLOCKED/continue E2E evidence (§27, mandatory)

`test_blocked_then_continue_new_caller_context`: explicitly simulates a later caller invocation — local
variables from the `start_vehicle_diagnostic` call are deleted (`del resolution, start`) before
`continue_vehicle_diagnostic` is invoked, with only the persisted identifiers (`case_id`, `execution_id`)
plus the required-to-be-retained `session_controller`/`pgdr_session` objects (PI-03's own disclosed
limitation, carried forward — see §16) surviving. Confirms same Case, same PGDR `RunnerExecution`
(`execution_id` unchanged, row count still 1). `test_no_open_transaction_across_blocked_wait` independently
confirms via `pg_stat_activity` (server-side) that zero backends hold any transaction during the `BLOCKED`
wait.

---

## 12. PI-02 refusal E2E evidence (§28, mandatory)

`test_refused_vir_status_prevents_pgdr_start`: uses PI-01's own Path B
(`register_vir_resolution_result`) to register a real VIR `VehicleIdentityResolution` carrying
`provider_unavailable` — one of PI-02's 3 refused statuses. This candidate independently confirmed (by direct
source read of `vir.domain.resolution.ResolutionEngine._determine_status`, listing every actual `return
ResolutionStatus.*` statement) that `invalid_identifier` and `unsupported_country` are genuinely dead code at
the pinned VIR baseline — never returned by the live resolution engine — and that `provider_unavailable`,
while real values-wise reachable in principle, is not straightforwardly reachable through the live stub
providers' current configuration either. Path B is the correct, already-existing mechanism for exercising
this real VIR domain object without fabricating data. Confirmed: VIR's own governed state (`cpl_resolution_
status == "FAILED"`) is preserved; PGDR is never started (`PGDR RunnerExecution` count == 0); Case transitions
to `WAITING_FOR_EXTERNAL_INFORMATION`; the product result (`PI02_HANDOFF_REFUSED`) explains why progression
is not admissible.

---

## 13. ESCALATED E2E evidence (§29, mandatory)

`test_escalated_reaches_resolved_case_with_artifact`: a real complaint matching PGDR's actual `SafetyEngine`
rule (`PGDR-SAF-004`, smoke/burning-smell) drives the diagnostic straight to `ESCALATED` inside
`start_vehicle_diagnostic` itself (no `BLOCKED` cycle needed for this particular complaint). Confirmed: PGDR
`RunnerExecution.execution_status == "COMPLETED"` (never `FAILED`), `GaragePreparationReport` `RunnerArtifact`
exists, Case transitions to `RESOLVED`, the full journey remains retrievable end to end.

---

## 14. Persistence-failure E2E evidence (§30, mandatory)

`test_cpl_persistence_failure_during_pgdr_finalization`: a genuine CPL-side failure injected into
`register_artifact` during PGDR terminal finalization. Confirmed: outcome is
`PGDRSessionOutcome.CPL_PERSISTENCE_FAILURE` (PI-03's own vocabulary, passed through unmodified — no
collapsing into a generic `PRODUCT_FAILURE`); Case is **not** transitioned to `RESOLVED` (no false product
success); zero artifact rows exist for the failed execution (no duplicate/partial state).

---

## 15. Restart durability evidence (§31)

`test_journey_retrievable_from_fresh_session`: after a completed journey, a completely fresh `SessionLocal()`
independently confirms the Case, both `RunnerExecution` rows, and both `RunnerArtifact` rows all persisted
correctly and are retrievable by `case_id` alone.

---

## 16. Known PI-03 session limitation — carried forward, not solved

```text
PGDR SessionController cross-instance session reconstruction remains unsupported at the pinned PGDR baseline.
```

PI-04 inherits this limitation exactly as disclosed by PI-03: `continue_vehicle_diagnostic` requires the
caller to supply the same `session_controller`/`pgdr_session` objects PI-03 itself requires — PI-04 does not
invent persistence for PGDR's in-memory state (explicitly forbidden, §24). This is disclosed here, not
silently absorbed into a seemingly-complete API. For the current bounded operational model (a single process
holding these objects across turns, as this candidate's own tests demonstrate), the required product journey
remains fully achievable — this is **not** classified `PRODUCT_GAP_BLOCKING`; it is a known, carried
`PRODUCT_GAP` for a future multi-process/stateless deployment model, which is squarely a later PI's concern
(likely PI-05's, when a real HTTP API needs to decide how session state survives across requests), not a
reason to block PI-04's own completion.

---

## 17. Blocking findings

None.

---

## 18. Non-blocking findings

None new. PI-01's, PI-02's, and PI-03's carried findings (`PI-01-VF-02`, `PI-01-VF-03`, `PI-02-VF-01`) are
unaffected — this candidate touches none of the files they concern.

---

## 19. Governance deviations / COMMON_GAP status

```text
COMMON_GAP: 0
```

No CPL modification anywhere. Every capability PI-04 needed already existed in CPL (`create_contact`,
`get_contact`, `create_asset`, `create_case`, `transition_case_status`, plus everything PI-01/PI-02/PI-03
already established) — composition, not extension, was sufficient throughout.

---

## PI-04 CANDIDATE

```text
Repository:
  https://github.com/paxtonef/cpl-product-integration.git

Base:
  3bd2ade81da9304e75a8046f6222c134bd4ebe0a

Branch:
  pi-04-case-orchestration-candidate

Candidate SHA:
  reported in the accompanying build handoff

Tree SHA:
  reported in the accompanying build handoff

CPL baseline:
  6181dabb9239e281974c368ad8f5df80350cabf1

CPL migration head:
  027

VIR baseline:
  a342aba7cc2fc517621f4fc79c3191bdfdc9e10b

PGDR baseline:
  0580b1a5ba5867a607a33197372fcaf4164f0fb6

register_vehicle_for_contact:
  PASS

resolve_vehicle_identity:
  PASS

start_vehicle_diagnostic:
  PASS

continue_vehicle_diagnostic:
  PASS

One Case:
  PASS

VIR execution:
  PASS

VIR artifact:
  PASS

PGDR execution:
  PASS

PGDR artifact:
  PASS

current_execution_id sequencing:
  PASS

PI-02 refusal:
  PASS

BLOCKED continuation:
  PASS

ESCALATED path:
  PASS

Case retrieval:
  PASS

Restart durability:
  PASS

Real VIR:
  PASS

Real PGDR:
  PASS

Real PostgreSQL:
  PASS

PI-01 regression:
  PASS

PI-02 regression:
  PASS

PI-03 regression:
  PASS

Known PGDR cross-instance limitation:
  CARRIED

COMMON_GAP:
  0

PRODUCT_GAP_BLOCKING:
  NONE

CPL modifications:
  0

VIR modifications:
  0

PGDR modifications:
  0

PI-05 scope leakage:
  0

Tests:
  10 (PI-04 own suite) + 112 (combined with PI-01/PI-02/PI-03, real PostgreSQL, zero regression)

Blocking findings:
  0

Governance deviations:
  0

FINAL STATE:
  CANDIDATE_COMPLETE
```
