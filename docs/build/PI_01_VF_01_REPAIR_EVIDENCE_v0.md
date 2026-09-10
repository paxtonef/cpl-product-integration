# PI_01_VF_01_REPAIR_EVIDENCE_v0

## 1. Identity

```text
Original candidate SHA:           1050d5357d354634f3ca6f67e5d7f280cedfd18b
Independent verification commit:      dc3ac3283cc3c5cb274171b11fd39a613c370189
Repair branch:                            pi-01-vf-01-repair-candidate
Repair parent SHA:                            dc3ac3283cc3c5cb274171b11fd39a613c370189
                                                 (the candidate branch tip — implementation + verification
                                                 report — repair branches from here, not from the bare
                                                 original implementation commit, preserving full lineage)
New candidate SHA:                                reported in the accompanying build handoff, per this
                                                     project's established materialization protocol

CPL software baseline (unchanged):                    6181dabb9239e281974c368ad8f5df80350cabf1
VIR full baseline (unchanged):                            a342aba7cc2fc517621f4fc79c3191bdfdc9e10b
```

---

## 2. Exact defect repaired

**PI-01-VF-01** (independent verification, `dc3ac32`): no code path existed to persist an already-clarified
VIR resolution through CPL. `register_vir_execution` always called `vir_client.resolve()` internally, and
VIR's own clarification mechanism produces a genuinely new `resolution_id` distinct from the original —
confirmed directly during independent verification — so there was no way, using only the original candidate's
public interface, to get a clarified VIR resolution persisted into CPL at all.

---

## 3. Implementation approach

Per §4 of the repair instruction, "VIR invocation" is now separated from "CPL registration of a VIR result":

```text
BEFORE:
  register_vir_execution(...)  — the only entry point; always calls resolve() itself, then persists inline.

AFTER:
  _admit_and_prepare(...)          — shared TX1 (admission + transition to RUNNING)
  _persist_vir_resolution(...)     — shared TX2 (artifact + resolution + detail + report), the single
                                        canonical persistence path
  register_vir_execution(...)      — Path A: calls VIR's resolve() itself, then delegates to the two
                                        shared functions above. Outward behavior byte-for-byte unchanged
                                        from the original candidate (verified: all 32 original tests pass
                                        unmodified).
  register_vir_resolution_result(...) — Path B (NEW): accepts an ALREADY-OBTAINED VehicleIdentityResolution
                                           (e.g. the output of VIRClient.submit_clarification(), called by the
                                           CALLER before this function, never inside it). Never calls
                                           resolve(). Delegates to the exact same two shared functions Path A
                                           uses. Uses the given resolution's own resolution_id as the
                                           admission idempotency_key — never substituted, never discarded,
                                           never regenerated.
```

**Execution identity decision** (§7 of the repair instruction — explicitly required not to be guessed):
each distinct VIR `resolution_id` (whether from a fresh `resolve()` or a clarification) is registered as its
own `RunnerExecution`. This follows directly from applying B6's own, unmodified rules — `NEW EXECUTION
ATTEMPT → NEW RUNNEREXECUTION` (REQ-B6-004) and `CORRECTION OF EXECUTION REPRESENTATION ≠ REWRITING
HISTORICAL EXECUTION OCCURRENCE` (REQ-B6-062) — to VIR's own observed, confirmed behavior (a clarification
produces a new resolution_id, not an update to the original). Retrofitting the clarified content onto the
original, already-`COMPLETED` execution's artifact would have violated REQ-B6-062 directly. No new CPL
execution semantics were invented; existing rules were applied to a fact established by direct testing, not
assumed.

**Linkage** (§7's "do not silently treat as unrelated"): `register_vir_resolution_result` accepts optional
`clarifies_execution_id`/`clarifies_resolution_id` parameters. When supplied, they are recorded in
`AssetIdentityResolution.provenance_payload` — an existing JSONB field the original candidate already used
for VIR-resolution-ID tracking (`{"vir_resolution_id": ...}`), simply extended with two more keys when
present. No new CPL column, table, or schema element. `parent_execution_id` is never touched by this path
(confirmed by a dedicated test, §11 below) — its prohibition (REQ-B6-006/043) remains exactly as it was.

**No duplicate persistence logic** (§4/§5): `_persist_vir_resolution` is the single function both paths call.
Proven by a dedicated test inspecting the actual call graph (not just trusting a comment) — see §11, test
`c01`.

---

## 4. Files changed

```text
M  src/product_integration/cpl_registration.py   (280 insertions, 73 deletions — the repair itself)
A  tests/test_vf01_repair.py                        (353 insertions — new tests, §11 below)
```

No other file touched. `vehicle_detail_writer.py`, `vir/client.py`, `vir/schemas.py`, `vir/errors.py`,
`vir/status_mapping.py`, `vir/authority.py`, `vir/outcomes.py`, `tests/conftest.py`,
`tests/test_cpl_registration.py`, `tests/test_status_mapping.py`, `tests/test_vir_client.py` — all
byte-identical to the original candidate. `PI-01-VF-02` (artifact schema logic) and `PI-01-VF-03` (edge-case
coverage in files this repair didn't touch) are genuinely untouched, not merely undiscussed.

---

## 5. Tests added

```text
tests/test_vf01_repair.py — 9 new tests:

A. Clarification result persistence
   test_a01_clarification_result_persists_through_pi01
   test_a02_resolved_clarification_writes_vehicle_detail

B. Resolution ID correctness
   test_b01_persisted_data_uses_clarified_resolution_id_not_original
   test_b02_execution_idempotency_key_is_clarified_resolution_id
   test_b03_provenance_linkage_recorded_when_supplied

C. Shared-path proof
   test_c01_path_a_and_path_b_share_identical_persistence_function
   test_c02_both_paths_produce_structurally_identical_artifact_shape

D. No second resolve() proof
   test_d01_no_resolve_call_occurs_after_clarification

Definitive repair acceptance scenario (§12 of the repair instruction, all 15 steps)
   test_e01_definitive_repair_acceptance_full_linked_state_survives_restart
```

All against real VIR (via `httpx.ASGITransport` wrapping VIR's actual FastAPI app, same isolation pattern
used throughout this repository — never a faked response) and real PostgreSQL.

---

## 6. Test commands and results

```text
Command: python -m pytest tests/ -v          (real PostgreSQL 16, fresh database)

Original 32 tests (test_cpl_registration.py, test_status_mapping.py, test_vir_client.py): 32/32 PASS,
  unmodified, byte-identical to the accepted-then-repaired candidate — proves the repair did not regress
  Path A's existing, already-verified behavior.
New 9 tests (test_vf01_repair.py): 9/9 PASS.

TOTAL: 41/41 PASS, 0 FAIL, 0 SKIP.
```

Run three times total from completely fresh, dropped-and-recreated databases during this repair session —
41/41 every time, no flakiness observed. Per §11-F of the repair instruction, no artificial count was
targeted; 41 is simply what resulted from 32 unmodified + 9 new.

---

## 7. Real PostgreSQL evidence

Fresh PostgreSQL 16.15 database, migrations applied from empty through 027, real role/credentials distinct
from any prior session. `test_e01`'s definitive scenario independently re-queries PostgreSQL from a
brand-new `SessionLocal()` (simulating process restart) and confirms all four entity classes
(`RunnerExecution`, `RunnerArtifact`, `AssetIdentityResolution`, `VehicleDetail` where applicable) remain
correctly linked and correspond to the *clarified* resolution specifically, not the original.

---

## 8. Clarification flow evidence

`test_a01` drives the exact real sequence: `vir_client.resolve()` against VIR's own known ambiguous fixture
(`AM-BIG-01`, confirmed in VIR's own test suite) → real `clarification_questions` returned → real
`vir_client.submit_clarification()` → real clarified `VehicleIdentityResolution` with its own new
`resolution_id` → `register_vir_resolution_result()` → full CPL linkage confirmed. No mock, no fake response,
anywhere in this path.

---

## 9. Proof no second resolve() occurs

`test_d01` and `test_e01` both monkeypatch `VIRClient.resolve` itself with a call-counting wrapper, call
`register_vir_resolution_result`, and assert the counter is exactly `0` — not inferred from code review, but
directly observed at runtime that the repaired persistence path never touches the VIR client at all.

---

## 10. Resolution_id evidence

`test_b01` explicitly asserts `clarified.resolution_id != initial.resolution_id` (VIR's own real behavior,
re-confirmed) and that every persisted record (`RunnerArtifact.payload["resolution_id"]`,
`VIRRegistrationResult.vir_resolution_id`) matches the *clarified* ID, never the original. `test_b02`
confirms the new `RunnerExecution.idempotency_key` is the clarified resolution's own ID.

---

## 11. Regression results

```text
Original PI-01 suite (32 tests): 32/32 PASS, unmodified files, byte-identical behavior.
```

The repair instruction's §11-F explicitly permits the repaired suite to exceed 32 without targeting an exact
count — 41 is the genuine result of 32 preserved + 9 added, not engineered to match any particular number.

CPL's and VIR's own test suites were not independently re-run in this repair session: neither repository was
touched (confirmed by diff, §4), and both were already independently re-verified multiple times across the
B6 and original PI-01 verification passes. Re-running either here would not add new evidence about this
repair specifically.

---

## 12. Blocking findings

None introduced by this repair.

---

## 13. Carried non-blocking findings (unchanged, not addressed in this cycle)

```text
PI-01-VF-02: REJECTED status structurally unreachable for vir_resolution artifacts (independent verification,
               dc3ac32). Not touched — the artifact-registration logic this observation concerns is
               unchanged, byte-for-byte, from the original candidate.
PI-01-VF-03: two minor untested edge cases (invalid VehicleDetail payload, an additional malformed-VIR-
               response shape). Not touched — vehicle_detail_writer.py and vir/client.py are unchanged,
               byte-for-byte, from the original candidate.
```

Per §13 of the repair instruction, neither was addressed, since repairing `PI-01-VF-01` did not require
touching the code either observation concerns.

---

## 14. Governance deviations

None. No CPL, VIR, or PGDR repository was modified. No CPL migration created. No new CPL ontology or
execution semantics invented — the execution-identity decision (§7) is a direct application of B6's own
existing, unmodified rules to an empirically observed VIR fact, not new CPL policy. `COMMON_GAP` remains `0`;
this repair is entirely product-integration-scoped, exactly as required.

---

## PI-01 VF-01 REPAIR

```text
Original candidate:
  1050d5357d354634f3ca6f67e5d7f280cedfd18b

Verification commit:
  dc3ac3283cc3c5cb274171b11fd39a613c370189

Repair branch:
  pi-01-vf-01-repair-candidate

Repair candidate SHA:
  reported in the accompanying build handoff

CPL baseline:
  6181dabb9239e281974c368ad8f5df80350cabf1

CPL migration head:
  027

VIR baseline:
  a342aba7cc2fc517621f4fc79c3191bdfdc9e10b

PI-01-VF-01:
  CLOSED

Clarification persistence:
  PASS

Fresh resolve after clarification:
  NO

Clarified resolution_id preserved:
  PASS

Real PostgreSQL:
  PASS

Full PI-01 suite:
  41 passed / 0 failed / 0 skipped (32 original, unmodified + 9 new)

Blocking findings:
  0

Carried observations:
  PI-01-VF-02
  PI-01-VF-03

COMMON_GAP:
  0

CPL_REOPEN_REQUIRED:
  NO

FINAL STATE:
  REPAIR_CANDIDATE_COMPLETE
```
