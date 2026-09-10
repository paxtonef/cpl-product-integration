# PI_03_VF_01_REPAIR_EVIDENCE_v0

## 1. Identity

```text
Original candidate SHA:           2e67ccf144051c4ef3752116812478f181b07a62
Independent verification SHA:         2960e0fffdda4f92881f5e6a686d1b0aa35f4b4d
Repair branch:                            pi-03-vf-01-repair-candidate
Repair parent SHA:                            2960e0fffdda4f92881f5e6a686d1b0aa35f4b4d
                                                 (candidate branch tip — implementation + verification report;
                                                 preserves full provenance, not rebased onto a bare
                                                 implementation-only commit)
Repair candidate SHA:                                reported in the accompanying build handoff
```

---

## 2. PI-03-VF-01 exact finding

Independent verification (`2960e0f`) found that `session_adapter.py`'s `_mark_failed` reported every failure
category — a genuine CPL database persistence failure, a `SessionController.start()` exception, and a
`SessionController.submit_answer()` exception (including the real `KeyError` that results when a session
started by one `SessionController` instance is resumed through a genuinely different instance) — under the
single, undifferentiated `PGDRSessionOutcome.CPL_PERSISTENCE_FAILURE` value. A caller branching on
`result.outcome` could not distinguish "the CPL database failed" from "PGDR itself failed to execute,"
violating the requirement that these remain distinguishable outcomes.

---

## 3. Root cause

`_mark_failed(execution_id, *, detail, authority) -> PGDRAdapterResult` had `outcome=PGDRSessionOutcome.
CPL_PERSISTENCE_FAILURE` **hardcoded** in its return statement — not a parameter, not derived from which
operation actually failed. Every call site (whether wrapping a genuine CPL persistence operation or a PGDR
`SessionController` call) inherited the same fixed label.

---

## 4. Existing outcome vocabulary inspected (§5 of the repair instruction — no new outcome invented)

```text
CPL app.cpl.runners.outcomes.RunnerOutcome (unchanged, not extended):
  SUCCESS, NOT_FOUND, NO_CHANGE, AUTHORITY_REJECTION, SEMANTIC_REJECTION, UNRESOLVED, CONFLICT,
  TECHNICAL_FAILURE

PI-01's own existing precedent (product_integration.cpl_registration.VIRRegistrationOutcome, unchanged,
not touched by this repair):
  SUCCESS, AUTHORITY_REJECTION, CONFLICT, VIR_TECHNICAL_FAILURE, CPL_PERSISTENCE_FAILURE
```

CPL's own `RunnerOutcome.TECHNICAL_FAILURE` is the semantically correct existing category: "the runner/
technical execution itself failed," as distinct from CPL's own persistence/semantic gates. PI-01 already
applied exactly this reasoning for VIR (`VIR_TECHNICAL_FAILURE`, kept distinct from `CPL_PERSISTENCE_FAILURE`
in the very same repository) — PI-03's own outcome enum simply hadn't carried that same discipline through
for the equivalent PGDR-side case. No CPL enum was extended; no new CPL outcome was invented. PI-03's own
product-integration-layer `PGDRSessionOutcome` class now applies the same category CPL already draws, named
to match PI-01's own established convention: `PGDR_TECHNICAL_FAILURE`.

---

## 5. Old vs. new classification

```text
OLD:
  CPL persistence failure        -> outcome = CPL_PERSISTENCE_FAILURE
  SessionController.start() fails    -> outcome = CPL_PERSISTENCE_FAILURE   (WRONG)
  SessionController.submit_answer() fails -> outcome = CPL_PERSISTENCE_FAILURE   (WRONG)

NEW:
  CPL persistence failure        -> outcome = CPL_PERSISTENCE_FAILURE   (unchanged, correct)
  SessionController.start() fails    -> outcome = PGDR_TECHNICAL_FAILURE   (corrected)
  SessionController.submit_answer() fails -> outcome = PGDR_TECHNICAL_FAILURE   (corrected)
```

---

## 6. Files modified

```text
src/product_integration/pgdr/session_adapter.py   (+46/-5)
  - added PGDRSessionOutcome.PGDR_TECHNICAL_FAILURE
  - _mark_failed gained an explicit `outcome` parameter, defaulting to CPL_PERSISTENCE_FAILURE (correct
    default for every call site inside _persist_current_state, which genuinely only wraps CPL-side
    operations)
  - the two PGDR-call exception handlers (start_pgdr_session, continue_pgdr_session) now pass
    outcome=PGDR_TECHNICAL_FAILURE explicitly

tests/test_pgdr_session_adapter.py   (+110/-0)
  - new TestPI03VF01Repair class, 5 tests
```

No other file touched. No CPL file touched. No PGDR file touched. No VIR file touched. No new migration.

---

## 7. Cross-controller resume reproduction (§12, mandatory)

Reproduced the exact 8-step scenario: controller A starts a session, reaches `BLOCKED`, CPL state persists;
a genuinely distinct controller B (`controller_b is not controller_a`, confirmed) attempts
`continue_pgdr_session`; the real `KeyError` from `SessionController.submit_answer()` is reproduced; the
adapter's public outcome is inspected.

```text
Result: outcome == PGDR_TECHNICAL_FAILURE
        outcome != CPL_PERSISTENCE_FAILURE
        CPL execution_status == "FAILED" (still correctly terminalized)
```

Test: `test_cross_controller_resume_failure_is_not_cpl_persistence_failure`.

---

## 8. Genuine CPL persistence-failure reproduction (§13, mandatory)

Independently injected a real CPL-side failure (`register_artifact` raising), driven through the same public
`start_pgdr_session` entry point.

```text
Result: outcome == CPL_PERSISTENCE_FAILURE
        execution_status == "FAILED"
        zero artifact rows (no masquerading partial state)
```

Test: `test_genuine_cpl_persistence_failure_still_classified_correctly`.

---

## 9. Proof the two outcomes differ (§14, mandatory)

`test_pgdr_technical_failure_and_cpl_persistence_failure_are_distinct_values`: explicit assertion
`PGDR_TECHNICAL_FAILURE != CPL_PERSISTENCE_FAILURE`, plus confirmation all six `PGDRSessionOutcome` values are
genuinely distinct strings (no accidental collision).

---

## 10. Real PostgreSQL

```text
PostgreSQL version: 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)
Migration head:          027 (unchanged, no new migration)
Fresh role/database:         pi03r / pi03r_test
```

Never mocked. Both mandatory repair tests (§7/§8 above) ran against real PostgreSQL.

---

## 11. Regression — BLOCKED lifecycle, ESCALATED, exactly-once, failure atomicity, VIR provenance

```text
BLOCKED/RUNNING/terminal lifecycle: unchanged, all original tests re-run and pass.
ESCALATED -> COMPLETED:                 re-confirmed explicitly by a new dedicated test
                                           (test_escalated_still_maps_to_completed_after_repair) in addition
                                           to the original candidate's own two ESCALATED tests, all passing.
Exactly-once:                                unchanged, both original tests re-run and pass.
Failure atomicity:                               unchanged, original test re-run and passes; the repair's own
                                                    §13 test is itself an additional, independent failure-
                                                    atomicity proof at the same injection point.
VIR provenance:                                      unchanged mechanism, both original tests re-run and pass;
                                                        the §12 test additionally confirms provenance-adjacent
                                                        execution-purpose handling is undisturbed.
No open transaction across wait:                           unchanged, original test re-run and passes.
```

---

## 12. Full regression count

```text
PI-03's own suite: 19 passed, 0 failed (14 original + 5 new repair tests)
Combined suite (PI-01's 41 + PI-02's 42 + PI-03's 19): 102 passed, 0 failed

Run three times total from completely fresh, dropped-and-recreated databases — 102/102 every time, no
flakiness.
```

---

## 13. Scope confirmation

```text
CPL modifications: 0
VIR modifications: 0
PGDR modifications: 0
CPL migrations: 0 (head remains 027)
PI-04 implementation: 0
```

Exactly 2 files modified (`session_adapter.py`, `test_pgdr_session_adapter.py`), 0 files added beyond this
evidence document, 0 files removed. No unrelated refactor — confirmed by `git diff --stat` against the
original candidate SHA.

---

## 14. Carried session-resume limitation (§25 — not silently solved)

```text
PGDR SessionController cross-instance session reconstruction remains unsupported at the observed PGDR
baseline (0580b1a5ba5867a607a33197372fcaf4164f0fb6).
```

This repair does not attempt to solve it, and explicitly proves it still doesn't work:
`test_underlying_pgdr_limitation_remains_unchanged` confirms the real `KeyError` is still raised by
`SessionController.submit_answer()` itself when called with a genuinely different controller instance — the
repair only corrects how the *resulting* adapter-level failure is *classified*, not the underlying PGDR
behavior. Classification per the original candidate evidence and the independent verification: `PRODUCT_GAP`
for a future PI-04 (or later) to address (e.g., a session/controller registry with an appropriate lifetime
policy), never a `COMMON_GAP` — nothing about CPL's own primitives is deficient.

---

## 15. COMMON_GAP

```text
COMMON_GAP: 0
```

Confirmed unchanged. The entire repair was completed within `product_integration/pgdr/`, reusing CPL's own
existing `RunnerOutcome.TECHNICAL_FAILURE` semantic category without touching CPL at all.

---

## 16. Blocking findings

None introduced by this repair.

---

## 17. Governance deviations

None.

---

## PI-03 VF-01 REPAIR

```text
Repository:
  https://github.com/paxtonef/cpl-product-integration.git

Original candidate:
  2e67ccf144051c4ef3752116812478f181b07a62

Independent verification:
  2960e0fffdda4f92881f5e6a686d1b0aa35f4b4d

Repair branch:
  pi-03-vf-01-repair-candidate

Repair candidate SHA:
  reported in the accompanying build handoff

Tree SHA:
  reported in the accompanying build handoff

PI-03-VF-01:
  CLOSED

Cross-controller resume failure classification:
  PASS

Cross-controller outcome:
  PGDR_TECHNICAL_FAILURE

Actual CPL persistence failure classification:
  PASS

CPL persistence outcome:
  CPL_PERSISTENCE_FAILURE

Failure categories distinct:
  PASS

Underlying PGDR cross-instance resume limitation:
  CARRIED (confirmed still present, not solved, not disguised)

Real PostgreSQL:
  PASS

Migration head:
  027

BLOCKED lifecycle:
  PASS

ESCALATED -> COMPLETED:
  PASS

No open transaction across wait:
  PASS

Exactly-once:
  PASS

Failure atomicity:
  PASS

VIR provenance:
  PASS

Full regression:
  102 passed / 0 failed (97 baseline + 5 new repair tests), reproduced 3x from fresh databases

CPL modifications:
  0

VIR modifications:
  0

PGDR modifications:
  0

COMMON_GAP:
  0

New blocking findings:
  0

Governance deviations:
  0

FINAL STATE:
  REPAIR_CANDIDATE_COMPLETE
```
