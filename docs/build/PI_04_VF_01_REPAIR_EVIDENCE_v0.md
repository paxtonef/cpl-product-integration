# PI_04_VF_01_REPAIR_EVIDENCE_v0

## 1. Identity

```text
Original candidate SHA:           761707bb23a2b724894acaa0576d1238d2732d7c
Independent verification SHA:         387f14b695e5574ea6787b9daafe26c8e0b29b42
Repair branch:                            pi-04-vf-01-repair-candidate
Repair parent SHA:                            387f14b695e5574ea6787b9daafe26c8e0b29b42
                                                 (candidate branch tip — implementation + verification report;
                                                 preserves full provenance, not rebased onto a bare
                                                 implementation-only commit)
Repair candidate SHA:                                reported in the accompanying build handoff
```

---

## 2. PI-04-VF-01 exact reproduction

Independent verification (`387f14b`) found: PGDR reaches `BLOCKED`, PI-03 correctly persists the PGDR
`RunnerExecution` as `BLOCKED`, PI-04's subsequent Case-side synchronization fails, the PGDR execution
remains validly `BLOCKED`, the Case stays stale at `IN_PROGRESS`, and the caller receives a raw, undocumented
exception.

---

## 3. Root cause

`_apply_pgdr_case_transition` (the original candidate's implementation) performed two Case-side writes —
`current_execution_id` update, then `transition_case_status` — as **two separate, independently-committed
transactions**, with **no exception handling** around the call in either `start_vehicle_diagnostic` or
`continue_vehicle_diagnostic`. A failure at either write propagated as a raw exception, and — because the
writes were split across two commits — could leave `current_execution_id` updated without the corresponding
status transition (or vice versa).

---

## 4. Repair philosophy — honest orchestration, not fictional atomicity (§5/§6 of the repair instruction)

This repair does **not** attempt to make the PGDR persistence (already complete, already committed by PI-03,
by the time PI-04's Case-sync step even runs) and the Case-side update into one distributed atomic
transaction — that boundary genuinely does not exist and pretending otherwise would be dishonest. What it
does instead:

1. Combines the Case's own two writes (`current_execution_id`, status transition) into **one** transaction —
   a legitimate, entirely local improvement that reduces (but, as the repair instruction itself notes, cannot
   fully eliminate — any single statement can still fail) the window in which the two facts could diverge.
2. Wraps this write in exception handling that **never lets a raw exception escape**, returning instead a
   typed `CaseOrchestrationTransitionError` carrying: `case_id`, the execution id, the observed domain
   status, the intended Case status, and the underlying error string.
3. Never rolls back or discards the already-valid PGDR execution — it is independently confirmed unaffected
   (§7 below).
4. Exposes a dedicated, idempotent `reconcile_case_orchestration()` entry point that re-derives the correct
   Case state from the **existing, already-persisted** `RunnerExecution` row — never re-invoking PGDR, never
   creating a new Case or execution.

---

## 5. Failure classification (§8/§16 of the repair instruction)

```text
New outcome value:   DiagnosticStartOutcome.CASE_ORCHESTRATION_FAILURE
                         (= ReconciliationOutcome.CASE_ORCHESTRATION_FAILURE, same string, shared value)
```

No CPL outcome vocabulary was touched or extended — this is a PI-04-local addition, alongside the existing
`PGDR_TECHNICAL_FAILURE`/`CPL_PERSISTENCE_FAILURE` values already established by PI-03/its own repair, which
remain entirely unmodified and unaffected by this change (confirmed: §12 below).

---

## 6. Files modified

```text
src/product_integration/orchestration/case_orchestration.py   — module docstring updated; the outcome
                                                                    classes gained CASE_ORCHESTRATION_FAILURE
                                                                    and a new ReconciliationOutcome class; a
                                                                    new ReconciliationResult dataclass;
                                                                    _apply_pgdr_case_transition replaced by
                                                                    _sync_case_with_execution (the shared,
                                                                    honest-failure primitive used by every
                                                                    Case-sync call site — VIR admission, PI-02
                                                                    refusal, and PGDR BLOCKED/COMPLETED — and
                                                                    by reconciliation) and a thin
                                                                    _sync_case_with_pgdr_result wrapper; a new
                                                                    public reconcile_case_orchestration()
                                                                    function; the three call sites
                                                                    (resolve_vehicle_identity's VIR-admission
                                                                    transition, start_vehicle_diagnostic's
                                                                    PI-02-refusal transition, and both
                                                                    start_vehicle_diagnostic/
                                                                    continue_vehicle_diagnostic's PGDR-result
                                                                    sync) updated to check for and honestly
                                                                    report a sync failure instead of calling
                                                                    an unguarded helper.
src/product_integration/orchestration/errors.py                   — new CaseOrchestrationTransitionError class.
tests/test_case_orchestration.py                                      — new TestPI04VF01Repair class, 11 tests;
                                                                            import list updated.
```

No CPL file touched. No VIR file touched. No PGDR file touched. No new migration.

**Scope note beyond the literal PGDR-BLOCKED instance**: the identical class of defect (a domain result
already correctly persisted by PI-01, followed by an unguarded Case write) existed at two other call sites
this repair also fixes — VIR admission's `IN_PROGRESS` transition and PI-02 refusal's
`WAITING_FOR_EXTERNAL_INFORMATION` transition. Leaving those two with the exact same unguarded pattern while
only fixing the PGDR path would have been an inconsistent, incomplete repair of the same underlying bug
class; both now use the identical `_sync_case_with_execution` primitive. This is the same fix pattern applied
consistently, not a redesign — no new behavior, no new CPL calls, no new architecture.

---

## 7. VF-01 reproduction against the repaired code (§15, mandatory)

Exact scenario reproduced: Contact/Asset/Case created, VIR completed, PGDR started and driven to `BLOCKED`
(real `SessionController`, PI-03 correctly persists `RunnerExecution.execution_status == "BLOCKED"`), a
failure injected into `transition_case_status` specifically (the Case-sync step), `start_vehicle_diagnostic`
called.

```text
start_vehicle_diagnostic did NOT raise -- returned:
  outcome:                 CASE_ORCHESTRATION_FAILURE
  pgdr_execution_id:           <real, valid execution id>
  pgdr_session:                     present (caller can still use it)
  pending_questions:                    present (caller can still see them)

Independently queried real PostgreSQL:
  PGDR RunnerExecution.execution_status: BLOCKED   (preserved, fully valid, untouched)
  Case.case_status:                          IN_PROGRESS   (honestly stale — never falsely reported as synced)
  PGDR RunnerExecution row count for this case:  1   (no duplicate)
  RunnerArtifact row count for this execution:       0   (BLOCKED has none — correctly, no duplicate concern)
```

Test: `test_vf01_exact_reproduction_no_raw_exception`.

---

## 8. Failure classification proof (§16, mandatory)

```text
CASE_ORCHESTRATION_FAILURE != PGDR_TECHNICAL_FAILURE      CONFIRMED (test_case_orchestration_failure_distinct_from_other_outcomes)
CASE_ORCHESTRATION_FAILURE != CPL_PERSISTENCE_FAILURE      CONFIRMED (same test)
CASE_ORCHESTRATION_FAILURE != BLOCKED (success)                CONFIRMED (same test)
CASE_ORCHESTRATION_FAILURE != COMPLETED (success)                   CONFIRMED (same test)
```

Additionally, driven through the real public API (not just asserted as distinct constants):
`test_pgdr_technical_failure_still_distinct_after_repair` reproduces PI-03-VF-01's own cross-controller
scenario through `continue_vehicle_diagnostic` and confirms the outcome is still `PGDR_TECHNICAL_FAILURE`,
never `CASE_ORCHESTRATION_FAILURE`. `test_cpl_persistence_failure_still_distinct_after_repair` injects a
genuine `register_artifact` failure and confirms `CPL_PERSISTENCE_FAILURE`, never `CASE_ORCHESTRATION_
FAILURE`.

---

## 9. Safe reconciliation (§17, mandatory)

`test_reconciliation_syncs_case_using_existing_execution`: reproduces the VF-01 scenario, then calls
`reconcile_case_orchestration(case_id=..., pgdr_execution_id=...)` with the injected failure removed.

```text
Result: outcome == RECONCILED
Case.case_status:                WAITING_FOR_USER   (correctly synchronized)
Case.current_execution_id:           == the same PGDR execution id (never a new one)
PGDR RunnerExecution row count:          1 (unchanged — no domain re-execution, no duplicate)
```

The original `pgdr_session`/`session_controller` returned from the failed `start_vehicle_diagnostic` call
remain fully usable afterward — the same test drives one further real `continue_vehicle_diagnostic` turn
successfully, confirming reconciliation didn't invalidate the live PGDR session.

`test_reconciliation_on_terminal_execution` confirms reconciliation correctly derives `RESOLVED` (not just
`WAITING_FOR_USER`) by re-reading the execution's own *current* persisted status — proving reconciliation is
driven by durable truth, not a stale in-memory outcome value.

---

## 10. Idempotent recovery (§18, mandatory)

`test_reconciliation_is_idempotent`: calls `reconcile_case_orchestration` twice in a row after the same
injected failure. Both calls return `RECONCILED`; the PGDR `RunnerExecution` row count remains exactly `1`
throughout — `transition_case_status`'s own existing idempotent-replay semantics (same idempotency_key ->
`NO_CHANGE`/replay, unchanged from B5) make the second call a safe no-op, not a duplicate transition.

---

## 11. Reconciliation information (§9 of the repair instruction)

`CaseOrchestrationTransitionError` (raised internally, converted to the typed result before reaching the
caller) and `ReconciliationResult`/`DiagnosticStartResult`/`DiagnosticContinueResult` all carry: `case_id`,
the PGDR execution id, the observed domain status, the intended Case status (on the error), and a `detail`
string with the underlying error — no raw ORM/session object is ever exposed.

---

## 12. Regression — happy path, BLOCKED, PI-02 refusal, ESCALATED, PI-03 taxonomy (§19-23)

```text
Happy path (test_happy_path_unaffected_by_repair):                         PASS — full journey, Case RESOLVED
Normal BLOCKED path, no injected failure (test_normal_blocked_path_...):       PASS — Case correctly
                                                                                   WAITING_FOR_USER,
                                                                                   current_execution_id correct
PI-02 refusal (test_pi02_refusal_unaffected_by_repair):                            PASS — PGDR never starts,
                                                                                       Case WAITING_FOR_EXTERNAL_
                                                                                       INFORMATION
ESCALATED (test_escalated_unaffected_by_repair):                                       PASS — Case RESOLVED,
                                                                                           execution COMPLETED
PI-03 failure taxonomy (§8 above):                                                         PASS — both
                                                                                               PGDR_TECHNICAL_
                                                                                               FAILURE and
                                                                                               CPL_PERSISTENCE_
                                                                                               FAILURE remain
                                                                                               distinct from
                                                                                               CASE_
                                                                                               ORCHESTRATION_
                                                                                               FAILURE
```

Every one of the original candidate's own 10 tests (unmodified) also still passes — confirmed in the full
suite run below.

---

## 13. Case retrieval after failure (§24)

`test_vf01_exact_reproduction_no_raw_exception` itself queries via a fresh `SessionLocal()` (no reliance on
any in-memory ORM identity map) and confirms both the valid `BLOCKED` `RunnerExecution` and the stale
`IN_PROGRESS` Case are truthfully observable together — exactly the pre-reconciliation state a real recovery
process would need to see.

---

## 14. Real PostgreSQL / Real PGDR (§25/§26)

```text
PostgreSQL version: 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)
Migration head:          027 (unchanged, no new migration)
Fresh role/database:         pi04rep / pi04rep_test
```

Every VF-01-related test uses a real `SessionController` driven to a genuine `BLOCKED` state through PI-03's
actual, unmodified code — never a fake-only PGDR object.

---

## 15. Full regression count (§27)

```text
PI-04's own suite: 21 passed, 0 failed (10 original + 11 new repair tests)
Combined suite (PI-01's 41 + PI-02's 42 + PI-03's 19 + PI-04's 21): 123 passed, 0 failed

Run three times total from completely fresh, dropped-and-recreated databases — 123/123 every time, no
flakiness.
```

---

## 16. Scope confirmation (§28)

```text
CPL modifications: 0
VIR modifications: 0
PGDR modifications: 0
CPL migrations: 0 (head remains 027)
PI-05 implementation: 0
```

Exactly 3 files modified (`case_orchestration.py`, `errors.py`, `test_case_orchestration.py`), 0 files added
beyond this evidence document, 0 files removed.

---

## 17. COMMON_GAP / PRODUCT_GAP (§29)

```text
COMMON_GAP: 0
PRODUCT_GAP_BLOCKING: NO
```

Confirmed unchanged from independent verification's own assessment — this entire repair lives within
`product_integration/orchestration/`, reusing CPL's existing `transition_case_status`/`Case.current_
execution_id` mechanisms exactly as before, without touching CPL at all.

---

## 18. Blocking findings

None introduced by this repair.

---

## 19. Governance deviations

None.

---

## PI-04 VF-01 REPAIR

```text
Repository:
  https://github.com/paxtonef/cpl-product-integration.git

Original candidate:
  761707bb23a2b724894acaa0576d1238d2732d7c

Independent verification:
  387f14b695e5574ea6787b9daafe26c8e0b29b42

Repair branch:
  pi-04-vf-01-repair-candidate

Repair candidate SHA:
  reported in the accompanying build handoff

Tree SHA:
  reported in the accompanying build handoff

PI-04-VF-01:
  CLOSED

PGDR BLOCKED execution preserved:
  PASS

Typed Case orchestration failure:
  PASS

Raw exception exposed:
  NO

Case synchronization failure distinguishable:
  PASS

Safe reconciliation:
  PASS

Same Case reused:
  PASS

Same PGDR execution reused:
  PASS

Duplicate execution:
  NO

Duplicate artifact:
  NO

current_execution_id reconciliation:
  PASS

Real PostgreSQL:
  PASS

Migration head:
  027

Happy path:
  PASS

Normal BLOCKED path:
  PASS

PI-02 refusal:
  PASS

ESCALATED:
  PASS

PI-03 failure taxonomy:
  PASS

Full regression:
  123 passed / 0 failed (112 baseline + 11 new), reproduced 3x from fresh databases

CPL modifications:
  0

VIR modifications:
  0

PGDR modifications:
  0

New migrations:
  0

PI-05 leakage:
  0

COMMON_GAP:
  0

PRODUCT_GAP_BLOCKING:
  NO

New blocking findings:
  0

Governance deviations:
  0

FINAL STATE:
  REPAIR_CANDIDATE_COMPLETE
```
