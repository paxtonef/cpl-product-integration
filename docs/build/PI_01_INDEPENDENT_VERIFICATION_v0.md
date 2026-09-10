# PI_01_INDEPENDENT_VERIFICATION_v0

## 1. Candidate identity

```text
Repository:        https://github.com/paxtonef/cpl-product-integration.git
Branch:                pi-01-vir-integration-candidate
Pinned SHA:                1050d5357d354634f3ca6f67e5d7f280cedfd18b

git checkout --detach 1050d5357d354634f3ca6f67e5d7f280cedfd18b
git rev-parse HEAD    -> 1050d5357d354634f3ca6f67e5d7f280cedfd18b   MATCH
git status --short    -> (empty)                                    CLEAN
```

`CANDIDATE_SHA = PASS`.

---

## 2. Environment (entirely fresh, no reuse of any builder state)

```text
OS:              Linux 6.18.44-fc-v24 x86_64
Python:          3.12.3
PostgreSQL:      16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)
pip:              24.0
New PostgreSQL role:   pi01iv (created fresh; the builder's `pi01` role was never touched or reused)
New database:              pi01_iv_test (dropped and recreated multiple times during this verification)
New venv:                      /home/claude/pi01_iv/venv (never shared with the builder's venv)
```

---

## 3. Pinned dependencies — independently resolved and verified

```text
CPL software baseline:   6181dabb9239e281974c368ad8f5df80350cabf1
  Fresh clone of paxtonef/cpl, `git checkout 6181dab...` -> confirmed via `git log -1`:
  "6181dab merge: integrate accepted B6 Execution/Artifact Governance candidate 365f0e3"
  — this is genuinely the merge commit, not governance HEAD. MATCH.

VIR baseline:            a342aba7cc2fc517621f4fc79c3191bdfdc9e10b
  Independently resolved from the short form "a342aba" via a fresh clone of
  paxtonef/vehicle-identity-resolver: `git rev-parse a342aba` ->
  a342aba7cc2fc517621f4fc79c3191bdfdc9e10b. Also confirmed this is still VIR's
  current `origin/HEAD` (checked via `git ls-remote`) — no newer VIR revision
  exists, so no compatibility-observation caveat is needed; the candidate-pinned
  baseline and the current baseline are identical.
```

---

## 4. Candidate evidence audit

Every material claim in `docs/build/PI_01_VIR_INTEGRATION_CANDIDATE_EVIDENCE_v0.md` was checked against the
actual candidate, independently:

| Claim | Independently verified |
|---|---|
| Candidate SHA / tree SHA | SHA matches (§1). Tree SHA not independently re-derived as a separate value (git guarantees tree identity follows from commit identity; re-deriving would be redundant, not a gap). |
| CPL baseline 6181dab, not governance HEAD | CONFIRMED via fresh clone + `git log -1` (§3) |
| VIR baseline a342aba... | CONFIRMED, resolved independently (§3) |
| PostgreSQL version | Builder reported 16.15 — this verification's own fresh install is also 16.15. MATCH |
| Migration head 027 | CONFIRMED via fresh `alembic upgrade head` + `alembic current` on an empty DB (§7) |
| Files changed (14 code/test files + evidence doc) | CONFIRMED — file listing matches exactly, git diff against fresh cpl/vir clones shows zero changes to either dependency |
| Test counts 32/32 | CONFIRMED, reproduced exactly, twice, in a genuinely fresh environment |
| 8/8 status mapping coverage | CONFIRMED independently against VIR's and CPL's actual source enums (§8) |
| Real VIR mechanism (ASGI transport, not mocks, for the definitive test) | CONFIRMED by reading `tests/conftest.py` directly — the `vir_client` fixture is bound to `httpx.ASGITransport(app=vir_routes.app)`, VIR's real FastAPI app object |
| Database linkage evidence | CONFIRMED, reproduced independently (§14) |
| Blocking findings: 0 (builder's claim) | **NOT CONFIRMED — see §16. This verification found one.** |
| Governance deviations: 0 | CONFIRMED — no CPL modification found anywhere |

One documentary discrepancy found: the builder's evidence §10 self-classifies the clarification-flow
limitation as a "test-coverage gap." This verification found it is not merely a coverage gap but a genuine
missing capability (§16) — the builder's own characterization understated its severity. This is a
`GOVERNANCE_RELEVANT` discrepancy per §39 of the verification instruction's classification scheme (it affects
whether `PI_01_VERIFIED` can be granted), not a `DOCUMENTARY_ONLY` one.

---

## 5. Code-scope audit

```text
Diff of cpl_baseline (fresh clone) against the pinned SHA: zero changes.
Diff of vir_baseline (fresh clone) against the pinned SHA: zero changes.
grep for PGDR/frontend/B7 across src/ and tests/: 3 hits, all inside docstrings explicitly EXCLUDING that
  scope ("does NOT implement/predict PGDR..."), none are leaked implementation.
grep for FastAPI app/route definitions in src/: zero — no product HTTP API introduced.
Search for vendored copies of CPL/VIR source inside the candidate repo: none found (the one false-positive
  path match was the candidate's own product_integration/vir/ submodule, confirmed by diffing file content
  against VIR's real source — genuinely independent authorship, not a copy).
Migration files in the candidate repo: zero.

SCOPE_VIOLATION: NONE FOUND
```

---

## 6. VIR HTTP boundary

Confirmed by direct source read of `src/product_integration/vir/client.py` and `schemas.py`: the client
imports nothing from the `vir` package (`import vir...` does not appear anywhere in the client or schema
modules) — every request/response model is independently defined, matching VIR's JSON wire shape by
inspection rather than by Python-class reuse. All four confirmed Reality Check endpoints are wrapped:
`resolve`, `submit_clarification`, `get_resolution`, `get_diagnostic_handoff`. No fifth endpoint invented.

`VIR HTTP BOUNDARY = PASS`

---

## 7. Real PostgreSQL verification

```text
Fresh database, fresh role, migrations applied from empty: `alembic upgrade head` -> 001 through 027 in
  sequence, `alembic current` -> "027 (head)".
Schema inspected directly (`\dt cpl.*`): all expected CPL tables present, including
  runner_governance_decisions, runner_artifact_schema_definitions, runner_execution_corrections (B6) and
  asset_identity_resolutions, vehicle_details (the tables PI-01 writes to).
Historical migrations 001-026: never touched by PI-01 (PI-01's own repository contains zero migration
  files, confirmed by `find`).

REAL POSTGRESQL = PASS
```

---

## 8. Status-mapping verification (independent, not trusting the implementation table)

Cross-checked three independent sources against each other: the Reality Check's characterization, VIR's own
`src/vir/domain/enums.py::ResolutionStatus` (8 values, read directly from the fresh VIR clone), CPL's own
`app/cpl/models/asset_identity_resolution.py`'s CHECK constraint (6 values, read directly from the fresh CPL
clone), and the candidate's `status_mapping.py` table.

```text
resolved                -> RESOLVED               CONFIRMED (direct semantic match)
provisionally_resolved  -> PARTIALLY_RESOLVED      CONFIRMED (reasoned, defensible)
ambiguous                -> AMBIGUOUS               CONFIRMED (direct semantic match)
insufficient_data        -> UNRESOLVED              CONFIRMED (reasoned, defensible)
contradictory            -> CONTRADICTORY           CONFIRMED (direct semantic match)
unsupported_country      -> FAILED                  CONFIRMED — independently traced through VIR's source
                                                        (resolution.py): this value is imported but never
                                                        actually assigned anywhere in the current VIR code
                                                        path — structurally unreachable today, but the
                                                        mapping is still correctly defined defensively
provider_unavailable     -> FAILED                  CONFIRMED — independently traced: this IS reachable as a
                                                        genuine 200-OK governed outcome (not only via a raised
                                                        exception), with vehicle_identity=None confirmed in
                                                        VIR's own source — FAILED is the correct CPL target
invalid_identifier       -> FAILED                  CONFIRMED — same reasoning, independently re-derived
                                                        from VIR's resolution.py, not merely trusted from the
                                                        candidate's own code comments
unknown/unrecognized value -> raises UnknownVIRStatusError, confirmed by direct test execution — explicit
                                                        rejection, not silent coercion
```

All 8 tested independently via `pytest` re-run, and the two subtlest mappings (`provider_unavailable`,
`invalid_identifier`) independently re-traced against VIR's actual source rather than trusted from the
candidate's own code comments explaining them.

`8→6 MAPPING = PASS`

---

## 9. CPL reuse verification

Confirmed by direct import-graph inspection of `cpl_registration.py`: `admit_execution`, `transition_status`,
`persist_runner_report`, `register_artifact` (all from `app.cpl.runners.*`), `record_asset_identity_resolution`
(from `app.cpl.assets.resolution`) are imported and called, never redefined locally. `create_asset` is not
called by PI-01 directly (the candidate's fixtures/tests create Assets via the same function for test setup,
but `register_vir_execution` itself takes a pre-existing `asset_id` — this is consistent with the Reality
Check's own PI-04 boundary, which was scoped to own the actual Asset-creation orchestration; PI-01 correctly
scoped itself to identity *resolution*, not identity *creation*). No local replacement model or service
duplicates any of these concepts anywhere in the candidate.

---

## 10. VehicleDetail verification

Independently tested (beyond the candidate's own `test_f01`/`test_f02`):
- Initial write: confirmed via the candidate's own passing test, re-run in this fresh environment.
- Repeat/update path: `VehicleDetail.asset_id` is confirmed (by direct schema inspection) to be the table's
  own primary key, making the write function's create-or-update logic structurally an upsert — genuinely
  deterministic, not merely claimed to be.
- Wrong-Asset isolation: confirmed via `test_f02`, re-run.
- Invalid payload path: not separately probed with a malformed `canonical_identity` dict in this
  verification pass (the function's own defensive `.get()` usage throughout means a missing/malformed field
  degrades to `None` rather than raising — reviewed by direct source read, judged adequate, not exercised
  with a dedicated adversarial test in this pass — noted as a minor coverage gap, non-blocking).

---

## 11. RunnerExecution verification

Independently reproduced: `test_c01` (successful VIR call -> `COMPLETED`), `test_c02` (technical failure ->
`FAILED`, distinct from a governed non-resolution). Independently re-confirmed via a fresh script: a
successful HTTP 200 from VIR carrying `resolution_status=ambiguous` still yields `execution_status=COMPLETED`
— HTTP success and VIR domain success are genuinely decoupled, confirmed by direct testing, not merely by
reading the code's docstring claim.

---

## 12. RunnerArtifact verification

`vir_resolution` schema registration confirmed to use the existing `RunnerArtifactSchemaDefinition` table
(REQ-B6-089's actual mechanism, not a new registry — confirmed by schema inspection, §7). Artifact correctly
linked to its execution (`execution_id` FK, confirmed). Payload preserves the full `VehicleIdentityResolution`
dump (confirmed by direct row inspection during `test_d01`'s reproduction).

**New observation (`PI-01-VF-02`, below):** the `vir_resolution` schema's `required_fields` are exactly the
two non-optional fields (`resolution_id`, `resolution_status`) that VIR's own client-side Pydantic validation
already guarantees are present and string-typed before the payload ever reaches `register_artifact`. This
makes the artifact's own `REJECTED` status structurally unreachable for `vir_resolution` artifacts as
currently designed — not a bug, but worth recording, since it means B6's `artifact_status` vocabulary's
structural-rejection path is effectively dead code for this specific artifact producer.

---

## 13. Failure-atomicity test

Independently reproduced the candidate's own `test_h01` (failure injected inside
`record_asset_identity_resolution`), then went further: injected a failure at a **different** point
(`register_artifact` itself) that the candidate's own test suite does not cover. Result: identical
guarantee holds — `execution_status = FAILED`, zero artifact rows, zero resolution rows, no masquerading
partial-success state, confirmed from an independent session.

`FAILURE ATOMICITY = PASS`

---

## 14. Definitive end-to-end test

Independently executed the full 20-step scenario (§14 of this verification instruction) against a
completely fresh PostgreSQL database, migrated from empty, using the pinned CPL and VIR baselines, the
pinned candidate SHA: `RunnerExecution`, `RunnerArtifact`, `AssetIdentityResolution`, and `VehicleDetail` all
created and correctly linked; verified from a brand-new SQLAlchemy session (simulating process restart);
linkage survived. Result reproduced the candidate's own `test_g` exactly.

`END-TO-END = PASS`

---

## 15. Concurrency — beyond the candidate's own coverage

The candidate's own test suite only exercises **sequential** replay (`test_d02`). This verification fired
**5 genuinely concurrent** `register_vir_execution()` calls (via `asyncio.gather`) at the same idempotency
key: zero raw exceptions surfaced, all 5 returned `SUCCESS`, all 5 converged on the exact same
`execution_id`, and exactly one `RunnerExecution` row exists for that key. This is a **stronger** result than
the candidate's own evidence claims — recorded as a positive independent finding, not merely a reproduction.

---

## 16. Clarification path — BLOCKING FINDING

Independently drove VIR's own known-ambiguous fixture (`AM-BIG-01`) through a real `resolve()` ->
`submit_clarification()` sequence via the candidate's own `VIRClient`. Both steps succeed at the client
level (consistent with the candidate's `test_clarification_operation`). **Then attempted to feed the
clarified resolution through `register_vir_execution` — and found no way to do so.**

`register_vir_execution`'s signature (confirmed by direct `inspect.signature()` call) accepts only a fresh
`VehicleIdentityRequest`; it always calls `vir_client.resolve()` internally. There is no parameter or code
path to accept an already-obtained `resolution_id` or a post-clarification `VehicleIdentityResolution` and
persist *that* into CPL. Calling `resolve()` again with the same input does not retrieve the clarified
result — VIR's own clarification mechanism produces a **new** `resolution_id` distinct from the original
(confirmed directly: `VIR-RES-C9C169AC6492` vs. the initial resolution's own ID), so there is structurally no
way, using only PI-01's current public interface, to get a clarified VIR resolution persisted into CPL at
all.

This is more severe than the candidate's own evidence (§10 of the evidence doc) characterizes it. The
evidence doc calls it "a genuine test-coverage gap" and states the underlying capability is "satisfied
structurally" because the response shapes are identical — but shape-compatibility is not the same as an
actual code path existing. No code path exists. This is a missing capability, not an untested one.

Per §23 of this verification instruction, `PI_01_VERIFIED` explicitly requires `clarification path PASS`.
It does not pass — there is nothing to test to a passing conclusion, because the feature the instruction's
own §16 asks to be verified end-to-end does not exist in the candidate.

```text
CLARIFICATION PATH = FAIL — BLOCKING
```

---

## 17. Diagnostic handoff boundary

Confirmed: `VIRClient.get_diagnostic_handoff()` exists and is tested (`test_diagnostic_handoff_retrieval`),
and no code anywhere in the candidate transforms `DiagnosticIdentityContext` into any PGDR-shaped structure —
grep for `PGDR`/`pgdr` confirms the only references are docstrings explicitly declining that scope (§5).

`DIAGNOSTIC HANDOFF BOUNDARY = PASS` (correctly out of scope, not leaked)

---

## 18. Regression

```text
Candidate's own suite, independently re-run in a fresh environment: 32 passed, 0 failed, 0 skipped — exact
  match to the builder's claim.
CPL's own test suite (unmodified, run against this verification's own fresh database): not independently
  re-run in this verification pass — the CPL software baseline itself was already independently re-verified
  end-to-end during B6's own independent verification and integration passes (227/227, multiple times); re-
  running the entire 227-test CPL suite again here would reproduce that same result without adding new
  evidence about PI-01 specifically, since PI-01 makes zero CPL code changes (confirmed by diff, §5). Not
  re-run, noted as a scope decision, not an oversight.
VIR's own test suite: not independently re-run in this verification pass, for the same reasoning (VIR
  unmodified, confirmed by diff).
```

`REGRESSION (candidate's own suite) = 32/32 PASS, MATCHES CANDIDATE CLAIM EXACTLY`

---

## 19. Adversarial checks performed

```text
Unexpected VIR status               -> tested (§8), explicit rejection confirmed
Malformed VIR response               -> reproduced candidate's own mock-based tests; not independently
                                           extended with a new malformation shape in this pass
Timeout                                  -> reproduced candidate's own test
Connection failure                           -> reproduced candidate's own test
Clarification flow                              -> independently driven end-to-end -> FOUND BLOCKING GAP (§16)
Duplicate/repeated request                          -> reproduced (sequential) + extended to 5-way concurrent
                                                          (§15) -> stronger result than candidate's own claim
Persistence failure                                     -> reproduced candidate's own injection point +
                                                              independently added a second injection point
                                                              (§13) -> both hold
Wrong Asset linkage                                         -> reproduced candidate's own test
Restart durability                                              -> reproduced candidate's own test (§14)
Invalid artifact schema                                            -> reasoned from source (§12) -> found
                                                                          REJECTED is structurally unreachable
                                                                          for this artifact type (observation,
                                                                          non-blocking)
Invalid VehicleDetail data                                              -> reviewed by source, not separately
                                                                              tested with a new malformed
                                                                              payload in this pass (§10, minor
                                                                              coverage gap noted)
```

---

## 20. Governance checks

```text
COMMON_GAP: still 0. The clarification-path finding (§16) is a product-integration capability gap — it
  belongs entirely inside PI-01's own repository (a new parameter/function accepting a pre-obtained
  resolution), not a CPL deficiency. CPL's RunnerExecution/RunnerArtifact/AssetIdentityResolution primitives
  are fully adequate to represent a clarified resolution exactly as they represent a direct one — nothing
  about CPL prevents this from being fixed entirely within PI-01.
CPL_REOPEN_REQUIRED: still NO.
B7: still NOT_DEMONSTRATED.
```

No `COMMON_GAP_CANDIDATE` is filed. This verification explicitly confirms the finding in §16 does not
implicate CPL.

---

## 21. Findings register

**PI-01-VF-01** — BLOCKING
Description: No code path exists in `register_vir_execution` (or anywhere else in the candidate) to accept
an already-obtained/clarified VIR resolution and persist it through the CPL registration path. The only
entry point re-submits `resolve()`, which VIR treats as a materially new call producing a new
`resolution_id`, never retrieving or building on the clarified one.
Evidence: `inspect.signature(register_vir_execution)` — no `resolution_id`/`existing_resolution` parameter;
direct HTTP trace showing VIR's clarified resolution carries a different `resolution_id` than the original.
Required for `PI_01_VERIFIED`: §23 explicitly requires `clarification path PASS`.
Severity: BLOCKING.

**PI-01-VF-02** — OBSERVATION, non-blocking
Description: The `vir_resolution` artifact's registered schema (`required_fields=["resolution_id",
"resolution_status"]`) can never actually fail structural validation for a real VIR response, since both
fields are already guaranteed present and string-typed by Pydantic validation at the VIR client boundary
before the payload reaches `register_artifact`. `REJECTED` is therefore unreachable for this artifact type as
currently designed.
Severity: OBSERVATION. Does not affect correctness — no incorrect state can result — but worth knowing for
anyone later auditing `artifact_status` distributions or wondering why `vir_resolution` artifacts never show
`REJECTED`.

**PI-01-VF-03** — OBSERVATION, non-blocking
Description: Invalid/malformed `VehicleDetail` payload handling and a dedicated adversarial malformed-VIR-
response shape (beyond the candidate's own single mock test) were reviewed by source reading but not
independently exercised with new tests in this verification pass.
Severity: OBSERVATION — reviewed and judged adequate by source inspection, not a demonstrated defect.

No `CRITICAL`/`MAJOR`/`MODERATE` findings beyond PI-01-VF-01 itself, which is classified `BLOCKING` per this
instruction's own explicit criterion (§22/§23).

---

## 22. Final verdict

```text
PI_01_REPAIR_REQUIRED
```

The candidate is a strong, largely correct piece of engineering — every claim in its own evidence document
was independently reproduced, and adversarial testing beyond the builder's own coverage (5-way true
concurrency, a second failure-injection point, independent status-mapping re-derivation from source) made the
candidate look *better* than claimed in every category except one. But `clarification path PASS` is an
explicit, named requirement for `PI_01_VERIFIED` (§23), and it does not pass — not because of a bug, but
because the capability doesn't exist yet. This is a repairable gap, entirely within PI-01's own scope, with
no CPL implication whatsoever.

---

## PI-01 INDEPENDENT VERIFICATION

```text
Repository:
  https://github.com/paxtonef/cpl-product-integration.git

Candidate:
  1050d5357d354634f3ca6f67e5d7f280cedfd18b

Candidate branch:
  pi-01-vir-integration-candidate

CPL baseline:
  6181dabb9239e281974c368ad8f5df80350cabf1

CPL migration head:
  027

VIR baseline:
  a342aba7cc2fc517621f4fc79c3191bdfdc9e10b

Environment:
  Fresh clone/venv/PostgreSQL role+DB, Linux, Python 3.12.3, PostgreSQL 16.15, pip 24.0 — zero reuse of
  builder state

Fresh clone:
  PASS

Candidate SHA:
  PASS

Scope audit:
  PASS

VIR HTTP boundary:
  PASS

4 VIR endpoints:
  PASS

8→6 mapping:
  PASS

Real PostgreSQL:
  PASS

RunnerExecution:
  PASS

RunnerArtifact:
  PASS

AssetIdentityResolution:
  PASS

VehicleDetail:
  PASS

Linked persistence:
  PASS

Clarification:
  FAIL

Failure atomicity:
  PASS

Restart durability:
  PASS

Candidate tests:
  32 passed / 0 failed / 0 skipped (candidate's own suite, independently reproduced)

Independent tests:
  Additional adversarial scripts run: 5-way concurrency (PASS, stronger than candidate claim), second
  failure-injection point (PASS), independent status-mapping source re-derivation (PASS), clarification
  end-to-end probe (FAIL — finding PI-01-VF-01)

Blocking findings:
  1 (PI-01-VF-01)

Non-blocking findings:
  2 (PI-01-VF-02, PI-01-VF-03, both OBSERVATION)

Governance deviations:
  0

COMMON_GAP:
  0

CPL_REOPEN_REQUIRED:
  NO

FINAL VERDICT:
  PI_01_REPAIR_REQUIRED
```

## STOP

**STOP.** This verification does not repair the candidate, does not modify the candidate branch, does not
merge anything, does not start PI-02, and does not modify CPL, VIR, or PGDR.
