# PI_01_VF_01_INDEPENDENT_REVERIFICATION_v0

## 1. Repair candidate identity

```text
Repository:              https://github.com/paxtonef/cpl-product-integration.git
Branch:                      pi-01-vf-01-repair-candidate
Repair candidate SHA:            f2477cd7d197f6f8c8798ef92ce7cbdf646777c5

git checkout --detach f2477cd7d197f6f8c8798ef92ce7cbdf646777c5
git rev-parse HEAD    -> f2477cd7d197f6f8c8798ef92ce7cbdf646777c5   MATCH
git status --short    -> (empty)                                    CLEAN

Original candidate:      1050d5357d354634f3ca6f67e5d7f280cedfd18b
Previous verification:       dc3ac3283cc3c5cb274171b11fd39a613c370189
```

---

## 2. Fresh environment

```text
Entirely new workspace: /home/claude/pi01_reverify — no reuse of the repair builder's venv, database, role,
  or any file from either the original PI-01 build or its own prior informal push-confirmation.
New PostgreSQL role:      pi01rv
New database:                 pi01_rv_test (dropped and recreated 3 times during this pass)
New venv:                         fresh install of CPL, VIR, and the candidate, each from a fresh git clone
Fresh CPL clone at:                   6181dabb9239e281974c368ad8f5df80350cabf1
Fresh VIR clone at:                       a342aba7cc2fc517621f4fc79c3191bdfdc9e10b (confirmed still VIR's
                                             current origin/HEAD — no drift since either verification pass)
```

---

## 3. Scope audit

```text
git diff --stat 1050d53..f2477cd:
  docs/build/PI_01_INDEPENDENT_VERIFICATION_v0.md   +505  (the prior verification report, already on the branch)
  docs/build/PI_01_VF_01_REPAIR_EVIDENCE_v0.md       +285  (new, this repair's own evidence)
  src/product_integration/cpl_registration.py        +280/-73  (the actual repair)
  tests/test_vf01_repair.py                              +353  (new tests)

Files NOT touched (confirmed by diff, not by trusting the evidence doc's claim):
  src/product_integration/vehicle_detail_writer.py   — unchanged
  src/product_integration/vir/client.py                  — unchanged
  src/product_integration/vir/schemas.py                     — unchanged
  src/product_integration/vir/errors.py                          — unchanged
  src/product_integration/vir/status_mapping.py                      — unchanged
  src/product_integration/vir/authority.py                               — unchanged
  src/product_integration/vir/outcomes.py                                    — unchanged
  tests/conftest.py, test_cpl_registration.py, test_status_mapping.py,
  test_vir_client.py                                                             — unchanged

grep for PGDR/frontend/B7 leakage: zero unexpected hits.
Migration files in the repo: zero.
CPL/VIR dependency checkouts: git status clean in both — neither repository touched.

SCOPE_VIOLATION: NONE FOUND
```

PI-01-VF-02 and PI-01-VF-03 concern exactly the files confirmed untouched above — their status is therefore
unchanged by this repair, confirmed structurally, not merely asserted.

---

## 4. Regression — actual counts, not assumed

```text
python -m pytest tests/ -v   (fresh database, run 3 times)

Run 1: 41 passed, 0 failed, 0 skipped
Run 2: 41 passed, 0 failed, 0 skipped
Run 3: 41 passed, 0 failed, 0 skipped

Breakdown: 32 original PI-01 tests (test_cpl_registration.py, test_status_mapping.py, test_vir_client.py) +
9 repair-specific tests (test_vf01_repair.py) = 41.
```

Independently confirmed, not copied from the repair evidence document.

---

## 5. Primary question — is PI-01-VF-01 closed?

```text
PI-01-VF-01: CLOSED
```

Confirmed by direct code inspection (`register_vir_resolution_result` exists, accepts an already-obtained
`VehicleIdentityResolution`, never calls `resolve()`) and by independent runtime proof (§7 below) — not
merely by re-reading the repair's own claim.

---

## 6. Both paths verified

**Path A (normal):** re-ran `test_c01`/`test_g_definitive_acceptance...` — unchanged, 32/32 pass, byte-
identical behavior to the original accepted candidate.

**Path B (clarification):** independently drove the real sequence — `vir_client.resolve()` against VIR's own
known ambiguous fixture (`AM-BIG-01`) → real `clarification_questions` → real
`vir_client.submit_clarification()` → real clarified `VehicleIdentityResolution` with resolution_id
`VIR-RES-4CEB7AA92B65` (confirmed distinct from the initial resolution's own ID) → `register_vir_resolution_
result()` → full CPL linkage. Both paths converge on `_persist_vir_resolution` — confirmed via `test_c01`'s
object-identity assertion, independently re-run.

---

## 7. No second resolve — independent proof beyond the repair's own test

The repair's own `test_d01`/`test_e01` monkeypatch `VIRClient.resolve` and assert a call counter is zero.
This verification used a **structurally different mechanism**: wrapped VIR's actual ASGI app itself to log
every HTTP request `(method, path)` that reaches it, independent of which Python function initiated the
call. Result:

```text
HTTP requests before calling register_vir_resolution_result:
  [('POST', '/v1/vehicle-identities/resolve'), ('POST', '/v1/vehicle-identities/VIR-RES-.../clarifications')]
HTTP requests after calling register_vir_resolution_result:
  [IDENTICAL LIST — zero new entries]
Total /resolve calls across the entire scenario: 1 (the initial one only)
```

This is the strongest form of this proof available — not "the Python function we expected wasn't called,"
but "zero bytes of HTTP traffic reached VIR at all" during persistence.

`NO SECOND RESOLVE = CONFIRMED (independently, via a different mechanism than the repair's own test)`

---

## 8. Resolution ID trace

```text
VIR clarification response resolution_id:    VIR-RES-4CEB7AA92B65 (example run; varies per invocation, always
                                                distinct from the initiating resolution's own ID — VIR's own
                                                real, confirmed behavior)
RunnerExecution.idempotency_key:                  same value — confirmed via direct query
RunnerArtifact.payload["resolution_id"]:              same value — confirmed via direct query
VIRRegistrationResult.vir_resolution_id:                  same value — confirmed via direct inspection

Never equal to the ORIGINAL (pre-clarification) resolution_id at any point in the persisted state.
No locally-fabricated identifier found anywhere (execution admission's idempotency_key is literally VIR's
own string, not a generated UUID or hash).
```

`RESOLUTION ID = PASS`

---

## 9. Shared persistence path

`test_c01` re-run and independently re-derived: both `register_vir_execution` and
`register_vir_resolution_result` call the exact same `_persist_vir_resolution` function object (confirmed via
`is` identity check on the function object itself, not merely matching names). `test_c02` re-run: a Path-A-
registered artifact and a Path-B-registered artifact (same underlying VIR resolution shape) are structurally
identical in schema, classification, and payload key set.

`SHARED PERSISTENCE PATH = PASS`

---

## 10. CPL persistence — independently proven, real PostgreSQL

Re-ran `test_a01`/`test_e01` and independently re-derived the same result via a fresh ad-hoc script: a
clarified resolution produces exactly one linked `RunnerExecution` (`COMPLETED`,
`execution_purpose="vehicle_identity_resolution_clarification"`), one `RunnerArtifact`
(`artifact_type="vir_resolution"`, payload's `resolution_id` matching the clarified ID), one
`AssetIdentityResolution` (linked via `execution_id`), and — when the clarification resolves to a usable
identity — one `VehicleDetail` (`source_resolution_id` matching). All against real PostgreSQL 16.15, never
mocked.

`REAL POSTGRESQL = PASS`
`LINKED PERSISTENCE = PASS`

---

## 11. Transactional safety / failure atomicity — extended beyond the repair's own coverage

The repair's own suite has no dedicated failure-injection test for Path B specifically (its atomicity
coverage for the new path relies on the shared function already being proven for Path A). This verification
closed that gap independently: injected a failure inside `register_artifact` during a **Path B**
(`register_vir_resolution_result`) call. Result: `execution_status = FAILED`, zero artifact rows survive, no
masquerading partial-success state — identical guarantee to Path A, now confirmed for Path B specifically
too, not merely inferred from the shared-function claim.

`FAILURE ATOMICITY = PASS`

No external VIR HTTP wait was found inside an open PostgreSQL transaction anywhere in the repaired module
(confirmed by source read: `_admit_and_prepare` commits before any HTTP call in Path A, and Path B never
makes an HTTP call at all).

---

## 12. Additional adversarial findings (beyond the required checklist)

**Concurrency on the new path — not required by this instruction's checklist, tested anyway.** Fired 5
genuinely concurrent (`asyncio.gather` over `asyncio.to_thread`) calls to `register_vir_resolution_result`
with the identical clarified resolution: zero raw errors, all 5 `SUCCESS`, all 5 converged on the same
`execution_id`, exactly one `RunnerExecution` row for that idempotency key. Stronger evidence than the repair
provides on its own.

**CONFLICT on the new path — not tested by the repair's own suite.** Submitted the same clarified
`resolution_id` against two different Assets: first call `SUCCESS`, second call correctly `CONFLICT` (not
silently mislabeled as `AUTHORITY_REJECTION`, confirming the outcome-mapping fix from the original candidate
build extends correctly to Path B).

Neither finding is required by §13 of the re-verification instruction, but both directly strengthen
confidence in the repair beyond what its own test suite alone demonstrates.

---

## 13. Restart durability

Re-ran `test_e01`'s restart simulation (fresh `SessionLocal()`, no shared Python object) — linkage survives.
Independently re-confirmed the same pattern in the ad-hoc concurrency/failure scripts (each opened a
completely separate verification session after the fact).

`RESTART DURABILITY = PASS`

---

## 14. PI-01-VF-02 / PI-01-VF-03 status

```text
PI-01-VF-02 (REJECTED status structurally unreachable for vir_resolution artifacts):
  UNCHANGED, still OBSERVATION/non-blocking. The artifact-registration logic this concerns
  (register_artifact call inside _persist_vir_resolution) is unchanged in its structural-validation
  behavior — confirmed by diff (§3): the schema-registration function and its required_fields are
  byte-identical to the original candidate.

PI-01-VF-03 (two minor untested edge cases — invalid VehicleDetail payload, an additional malformed-VIR-
  response shape):
  UNCHANGED, still OBSERVATION/non-blocking. vehicle_detail_writer.py and vir/client.py are confirmed
  byte-identical to the original candidate (§3) — neither edge case was addressed nor needed to be for
  this repair.
```

Neither silently resolved, neither reclassified without evidence — confirmed by direct file-level diff, not
by trusting the repair evidence document's own claim.

---

## 15. Governance checks

```text
COMMON_GAP: 0, confirmed. Nothing about this repair implicates CPL — the execution-identity decision (§7 of
  the repair instruction) is a direct, documented application of B6's own existing, unmodified rules
  (REQ-B6-004, REQ-B6-062) to an empirically observed VIR fact, not new CPL policy. No CPL file was touched
  (confirmed, §3).
CPL_REOPEN_REQUIRED: NO, confirmed.
```

No `COMMON_GAP_CANDIDATE` filed.

---

## 16. Definitive repair test (§12 of the re-verification instruction, all 18 steps)

Independently executed the full scenario: fresh clone, exact SHA, fresh venv, fresh PostgreSQL database,
migrations through 027, pinned VIR — triggered a real ambiguous VIR resolution, submitted a real
clarification, received a real clarified resolution with its own resolution_id, persisted it through
`register_vir_resolution_result`, confirmed (via independent HTTP-transport instrumentation, §7) that
`resolve()` was never called again, queried PostgreSQL independently, verified all four linked entities and
that they correspond to the clarified result specifically (not the original), then re-queried from a fresh
session to confirm restart durability. All 18 steps passed.

`DEFINITIVE REPAIR TEST = PASS`

---

## 17. Findings register

No `BLOCKING` finding. No `NON_BLOCKING` finding beyond the two carried-forward observations (§14), which
are unchanged in status, not new. No `OBSERVATION` beyond what's already documented above.

---

## 18. Final verdict

```text
PI_01_REPAIR_VERIFIED
```

Every requirement in §13 of the re-verification instruction is met: `PI-01-VF-01` closed, no fresh `resolve()`
after clarification (proven two independent ways), clarified `resolution_id` preserved and traced end to end,
real PostgreSQL, linked persistence, restart durability, failure atomicity — all PASS, and full regression
(41/41, reproduced three times) shows no new blocking finding. This verification went beyond the required
checklist in three places (Path B concurrency, Path B failure-injection at an alternate point, Path B
CONFLICT handling) and the repair held up in every one.

---

## PI-01 VF-01 RE-VERIFICATION

```text
Candidate:
  f2477cd7d197f6f8c8798ef92ce7cbdf646777c5

Branch:
  pi-01-vf-01-repair-candidate

PI-01-VF-01:
  CLOSED

Fresh resolve after clarification:
  NO

Clarified resolution_id preserved:
  PASS

Shared persistence path:
  PASS

Real PostgreSQL:
  PASS

Linked persistence:
  PASS

Failure atomicity:
  PASS

Restart durability:
  PASS

Full suite:
  41 passed / 0 failed / 0 skipped (reproduced 3x from fresh databases)

Repair-specific tests:
  9 passed / 0 failed

PI-01-VF-02:
  UNCHANGED, non-blocking observation

PI-01-VF-03:
  UNCHANGED, non-blocking observation

Blocking findings:
  0

COMMON_GAP:
  0

CPL_REOPEN_REQUIRED:
  NO

FINAL VERDICT:
  PI_01_REPAIR_VERIFIED
```

## STOP

**STOP.** This re-verification does not repair, does not merge, and does not start PI-02.
