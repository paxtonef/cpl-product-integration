# PI_03_PGDR_SESSION_ADAPTER_CANDIDATE_EVIDENCE_v0

## 1. Identity

```text
Product-integration base SHA:  4366c6395c5e844792e57299404f06b3f9bec890  (PI-02 closure, main)
Candidate branch:                  pi-03-pgdr-session-adapter-candidate
Candidate SHA:                         reported in the accompanying build handoff
Tree SHA:                                  reported in the accompanying build handoff

PGDR full SHA:      0580b1a5ba5867a607a33197372fcaf4164f0fb6 (resolved fresh, confirmed identical to every
                       prior reference in this project — no drift)
CPL software baseline: 6181dabb9239e281974c368ad8f5df80350cabf1 (unchanged, pinned)
CPL migration head:        027 (unchanged, zero new migrations)
```

---

## 2. PGDR SessionController source inspection

```text
pgdr.session_controller.SessionController   (src/pgdr/session_controller.py, pinned baseline)
  __init__(governance_enabled: bool = True, governance_consumer: GGMConsumer | None = None)
  start(request: PreGarageDiagnosticRequest) -> DiagnosticSession
  submit_answer(session: DiagnosticSession, answer: Answer) -> DiagnosticSession
  get_current_state(session: DiagnosticSession) -> dict
```

Confirmed directly by reading the source (not from memory): `SessionController()` constructs fully offline
with default `governance_enabled=True` — no network call, no external service (`materialize_pgdr_runtime_or_
raise()` builds its GGM runtime entirely from the vendored `ggm` wheel already shipped in PGDR's own
repository). This candidate's tests use real, production-default `SessionController` instances throughout —
never a mock, never `governance_enabled=False`.

---

## 3. A real, evidence-grounded correction to the assumed SessionState mapping

The PI-03 instruction's own diagram (§9) and the Reality Check's §13 both describe "PGDR requiring
additional input" as a `SessionState.BLOCKED` value. **This does not match the actual pinned source.**
`pgdr.enums.SessionState` does define a `BLOCKED` member, but reading `SessionController.start()`/
`submit_answer()`/`_advance()`/`_finalize()` in full shows `session.log_transition(..., SessionState.BLOCKED,
...)` is never called anywhere. This was independently confirmed two ways, not merely asserted:

1. **Static**: `grep -rn "SessionState.BLOCKED" src/` across the entire PGDR source tree — zero hits outside
   the enum definition itself.
2. **Empirical**: ran a real, multi-turn diagnostic session end to end. After `start()`, with one real
   pending question, `session.state` was `SessionState.SYMPTOM_COLLECTION` — not `BLOCKED`. Every subsequent
   `submit_answer()` call that still left a pending question also left `session.state ==
   SYMPTOM_COLLECTION`. The final answer produced `session.state == COMPLETED`.

The real, actionable signal `SessionController` actually provides for "needs an answer" is `bool(session.
pending_questions)`, not a comparison against `SessionState.BLOCKED`. This is the mapping this candidate
implements — see `session_adapter.py`'s own module docstring for the full reasoning. This is a genuine
correction, independently and empirically re-derived, not a guess and not a deviation from the instruction's
intent (§10 explicitly required inspecting the actual enum/state model rather than deriving by string
similarity — this is exactly that inspection, taken to its empirically-verified conclusion).

The one part of the assumed mapping that **is** confirmed exactly as instructed: `SessionState.ESCALATED`
maps to CPL `COMPLETED`, never `FAILED` — confirmed both by direct source read (the safety-escalation branch
in `start()` still produces a fully-formed `session.result` with a real `garage_preparation_report`) and by a
real, scripted session that reaches `ESCALATED` (§7 below).

---

## 4. §13 state mapping table (as actually implemented)

| PGDR signal | CPL execution_status |
|---|---|
| `session.state in (COMPLETED, ESCALATED)` | `COMPLETED` |
| `session.pending_questions` non-empty | `BLOCKED` |
| anything else | `UnexpectedPGDRSessionStateError` raised — the completeness guard (§34), matching PI-02's own pattern: fails loudly rather than guessing if `SessionController`'s real, synchronous, always-resolves-to-one-of-two-signals behavior ever changes |

`SessionState.BLOCKED` itself is not part of this table's inputs, since it is never produced (§3).

---

## 5. CPL operations reused

```text
app.cpl.runners.execution.admit_execution
app.cpl.runners.execution.transition_status
app.cpl.runners.execution.persist_runner_report
app.cpl.runners.artifacts.register_artifact
```

Zero CPL modification. Confirmed by `git status --short` in the independently-held `cpl_baseline` checkout —
clean.

---

## 6. Artifact schema registration

```text
artifact_type / schema_name: "pgdr_garage_preparation_report"
schema_version:                 "1"
required_fields:                    ["report_id"]  (kept minimal, matching the same discipline PI-01 applied
                                       to "vir_resolution" — enough for reproducibility, nothing speculative)
```

Uses the existing B6 `RunnerArtifactSchemaDefinition` registry mechanism (REQ-B6-089), idempotently
registered on first use. No second CPL artifact subsystem.

---

## 7. VIR artifact provenance mechanism (§16/§17)

Implements the Reality Check's exact §15 recommendation: the `EXECUTION_ADMISSION`
`RunnerGovernanceDecision`'s `new_value` JSONB already includes `execution_purpose` verbatim (confirmed by
direct source read of `admit_execution` — no caller-injectable extra field exists on that function, but
`execution_purpose` itself flows straight into the decision record unmodified). When a VIR `artifact_id` is
supplied, `execution_purpose` is given the structured value
`f"pgdr_diagnostic_session:vir_artifact_id={vir_artifact_id}"` — no new CPL column, table, schema element, or
foreign key anywhere. Tested directly: `test_vir_artifact_provenance_recorded_in_admission_decision` confirms
the VIR artifact_id string is present in the persisted decision's `new_value["execution_purpose"]`, queried
independently from the `RunnerGovernanceDecision` table.

---

## 8. Files added

```text
src/product_integration/pgdr/adapter_errors.py    (PGDRAdapterError, PGDRSessionAlreadyTerminalError,
                                                       UnexpectedPGDRSessionStateError)
src/product_integration/pgdr/session_adapter.py       (start_pgdr_session, continue_pgdr_session, and the
                                                           shared _admit_and_prepare/_persist_current_state
                                                           internals)
tests/test_pgdr_session_adapter.py                        (14 tests)
```

No CPL file touched. No VIR file touched. No PGDR file touched. No new migration. No PI-04 Case
orchestration, product API, or frontend code anywhere.

---

## 9. Test environment

```text
PostgreSQL version:      16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)
CPL migration head:          027, applied fresh from an empty database
Command:                         python -m pytest tests/ -v
```

---

## 10. Test results

```text
PI-03's own suite (tests/test_pgdr_session_adapter.py): 14 passed, 0 failed, 0 skipped
Combined suite (PI-01's 41 + PI-02's 42 + PI-03's 14):      97 passed, 0 failed, 0 skipped

Run three times total from completely fresh, dropped-and-recreated databases during this build — 97/97
every time, no flakiness observed.
```

---

## 11. BLOCKED-path evidence (§27, mandatory)

`test_blocked_path_full_multiturn_cycle`: a real complaint ("engine makes a strange noise") produces multiple
real questions from PGDR's actual question-selection engine. Confirmed `CPL execution_status == "BLOCKED"`
after the first `start()` call (queried from real PostgreSQL, independently). At least one real
`SessionController.submit_answer()` call is exercised (not a test-only bypass), followed by a full drive to
completion answering every real question the engine actually asked (7 turns in the representative run).

---

## 12. submit_answer evidence

Every BLOCKED→RUNNING→(BLOCKED|COMPLETED) cycle in `test_blocked_path_full_multiturn_cycle` and
`test_one_execution_for_entire_multiturn_session` calls the real `SessionController.submit_answer()` — no
test-only bypass exists anywhere in `session_adapter.py` (confirmed by reading the module: `continue_pgdr_
session` always calls `session_controller.submit_answer(pgdr_session, answer)` directly).

---

## 13. ESCALATED-path evidence (§26, mandatory)

`test_escalated_path_maps_to_cpl_completed_never_failed` and `test_escalated_reachable_via_safety_engine_
real_rules`: a real complaint ("smoke... burning smell") triggers PGDR's actual `SafetyEngine`, matching real
rule `PGDR-SAF-004` from `safety_rules.yaml` (config-driven, not contrived), producing `session.safety_
triage.level == "emergency_stop"` and `session.state == ESCALATED`. Confirmed: CPL `execution_status ==
"COMPLETED"` (never `FAILED`), and exactly one `pgdr_garage_preparation_report` `RunnerArtifact` registered.

---

## 14. Terminal RunnerExecution / GaragePreparationReport artifact evidence

Both `test_blocked_path_full_multiturn_cycle` (via `drive_to_completion`) and the ESCALATED tests confirm,
queried independently from real PostgreSQL: exactly one terminal `RunnerExecution`
(`execution_status == "COMPLETED"`) and exactly one associated `RunnerArtifact`
(`artifact_type == "pgdr_garage_preparation_report"`, `execution_id` matching) per completed session.

---

## 15. Exactly-once evidence (§30, mandatory)

Two independent tests: `test_exactly_once_terminal_artifact_on_repeated_continue_after_terminal` confirms a
second `continue_pgdr_session` call against an already-terminal execution is refused
(`PGDRSessionAlreadyTerminalError`) **before** PGDR is called again, and that exactly one artifact row exists
afterward. `test_exactly_once_on_replayed_start` confirms replaying the same `request.request_id` through
`start_pgdr_session` returns the same `execution_id` (REQ-B6-036's existing replay semantics, reused, not
reimplemented) with still exactly one artifact row.

---

## 16. Restart durability evidence

`test_restart_durability_full_linked_state_survives`: after a terminal session, a completely fresh
`SessionLocal()` (no shared Python object with anything the adapter touched) independently confirms the
`RunnerExecution`, its `RunnerArtifact`, and the `EXECUTION_ADMISSION` decision's VIR-provenance note all
persisted correctly.

---

## 17. Failure atomicity evidence

`test_failure_atomicity_terminal_persistence_failure_leaves_no_masquerading_state`: a failure injected inside
`register_artifact` during terminal finalization leaves `execution_status == "FAILED"` (never `COMPLETED`)
and zero artifact rows — confirmed from an independent session, no partial success state.

---

## 18. No-open-transaction-across-BLOCKED evidence (§33, mandatory)

`test_no_open_transaction_across_blocked_wait`: after `start_pgdr_session` returns `BLOCKED`, a completely
independent `SessionLocal()` (a fresh connection from the pool) immediately observes the committed `BLOCKED`
status — only possible if the original transaction was already committed and closed, not held open.

---

## 19. Regression results

```text
PI-01 (41 tests): unmodified, all passing within the combined 97-test run.
PI-02 (42 tests): unmodified, all passing within the combined 97-test run.
```

Neither PI-01's nor PI-02's test files were touched by this candidate (confirmed by `git status` — only
3 new files, zero modifications).

---

## 20. Known, disclosed limitation (not a defect)

**Session-object custody (§32).** `SessionController` and `DiagnosticSession` are purely in-memory — PGDR
persists nothing, confirmed directly. This adapter does not invent PGDR-side persistence (explicitly out of
scope). The caller (PI-04 or a future product/API layer) must keep the same `SessionController` instance and
the same `DiagnosticSession` object alive across turns of one session (or hold it in a longer-lived process/
worker). On a replayed `start_pgdr_session` call (same `request.request_id` re-submitted), the adapter can
report CPL-side execution state but **cannot** hand back a reconstructed PGDR session object, since none
exists to reconstruct — `_existing_terminal_or_blocked_result`'s `session=None` on replay makes this
explicit rather than silently returning something misleading. This is a genuine `PRODUCT_GAP` for a real
multi-request-cycle deployment (e.g., a stateless HTTP API across requests), not a `COMMON_GAP` — nothing
about CPL is deficient; PI-04 will need to decide how to hold PGDR session state alive across a real product
request cycle (in-process cache, worker affinity, or similar), which is squarely PI-04's own scope, not
CPL's.

---

## 21. Blocking findings

None.

---

## 22. Non-blocking findings

None new. PI-01's and PI-02's carried observations (`PI-01-VF-02`, `PI-01-VF-03`, `PI-02-VF-01`) are
unaffected — this candidate touches none of the files they concern.

---

## 23. Governance deviations

None. Zero CPL modification, zero VIR modification, zero PGDR modification. `COMMON_GAP` remains `0` — the
one limitation disclosed (§20) is a `PRODUCT_GAP`, explicitly not converted into a `COMMON_GAP_CANDIDATE`,
since nothing about it implicates CPL's own primitives.

```text
COMMON_GAP: 0
```

---

## PI-03 CANDIDATE

```text
Repository:
  https://github.com/paxtonef/cpl-product-integration.git

Base:
  4366c6395c5e844792e57299404f06b3f9bec890

Branch:
  pi-03-pgdr-session-adapter-candidate

Candidate SHA:
  reported in the accompanying build handoff

Tree SHA:
  reported in the accompanying build handoff

PGDR baseline:
  0580b1a5ba5867a607a33197372fcaf4164f0fb6

CPL software baseline:
  6181dabb9239e281974c368ad8f5df80350cabf1

CPL migration head:
  027

SessionState mapping:
  PASS

BLOCKED path:
  PASS

submit_answer:
  PASS

ESCALATED -> COMPLETED:
  PASS

RunnerExecution:
  PASS

GaragePreparationReport artifact:
  PASS

VIR artifact provenance:
  PASS

Exactly-once terminal artifact:
  PASS

Restart durability:
  PASS

Failure atomicity:
  PASS

Real PostgreSQL:
  PASS

PostgreSQL version:
  16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)

PI-01 regression:
  PASS

PI-02 regression:
  PASS

Tests:
  14 (PI-03 own suite) + 97 (combined with PI-01/PI-02, real PostgreSQL, zero regression)

CPL modifications:
  0

VIR modifications:
  0

PGDR modifications:
  0

PI-04 scope leakage:
  0

COMMON_GAP:
  0

Blocking findings:
  0

Governance deviations:
  0

FINAL STATE:
  CANDIDATE_COMPLETE
```
