# PI_02_VIR_PGDR_HANDOFF_CANDIDATE_EVIDENCE_v0

## 1. Identity

```text
Product-integration baseline SHA:  2b9cf211c759f377e0095e570864493889f4f75c  (PI-01 closure, main)
Candidate branch:                      pi-02-vir-pgdr-handoff-candidate
Candidate SHA:                             reported in the accompanying build handoff, per this project's
                                              established materialization protocol
Tree SHA:                                      reported in the accompanying build handoff

VIR full SHA:      a342aba7cc2fc517621f4fc79c3191bdfdc9e10b (resolved fresh via git ls-remote/rev-parse,
                      confirmed identical to every prior PI-01 reference — no drift across the entire
                      PI-01/PI-02 lifecycle so far)
PGDR full SHA:          0580b1a5ba5867a607a33197372fcaf4164f0fb6 (resolved fresh the same way — this is the
                          first time this candidate lineage has needed PGDR's source directly)
```

---

## 2. Model paths and symbols used

```text
VIR (src/vir/, pinned a342aba):
  vir.domain.models.DiagnosticIdentityContext    (src/vir/domain/models.py:255)
  vir.domain.models.VehicleIdentityResolution        (src/vir/domain/models.py:234)
  vir.domain.models.Contradiction                        (src/vir/domain/models.py:111)
  vir.domain.models.ContradictionValue                        (src/vir/domain/models.py:105)
  vir.domain.models.Confidence                                    (src/vir/domain/models.py:156)
  vir.domain.models.CanonicalVehicleIdentity
  vir.domain.enums.ResolutionStatus                                    (src/vir/domain/enums.py:4)
  vir.domain.enums.ConfidenceLevel                                         (src/vir/domain/enums.py:15)
  vir.application.build_handoff.HandoffBuilder.build_diagnostic_context      (src/vir/application/
                                                                                build_handoff.py — read
                                                                                directly to determine exactly
                                                                                what data DiagnosticIdentity
                                                                                Context actually carries)

PGDR (src/pgdr/, pinned 0580b1a):
  pgdr.models.VehicleIdentityContext     (src/pgdr/models.py:33)
  pgdr.models.ConfidenceScore                (src/pgdr/models.py:28)
  pgdr.enums.ResolutionStatus                    (src/pgdr/enums.py:5)
```

No model was redefined locally. No field name or semantic was assumed from memory — every field used below
was confirmed by directly reading the source files listed above, at the pinned SHAs, during this build.

---

## 3. A correction to the Reality Check's own phrasing (not contract drift)

The Reality Check's §14 states VIR's confidence data is "DERIVABLE... even though `DiagnosticIdentityContext`
doesn't carry it directly," implying the richer `VehicleIdentityResolution` object was required for
confidence. Reading `HandoffBuilder.build_diagnostic_context` directly showed this is not quite accurate:
`diagnostic_constraints` (a field that genuinely exists on `DiagnosticIdentityContext`) is populated with
`confidence_score` (float) and `confidence_level` (already `.value`-extracted to a plain string) and
`unresolved_fields` (the real list, not a placeholder) — all present on `DiagnosticIdentityContext` itself,
just nested inside a dict rather than exposed as top-level typed fields. This is **not** `CONTRACT_DRIFT`
(nothing about the actual models disagrees with what the Reality Check anticipated could be built) — it is a
looser phrasing in a document written before this field-level inspection, now corrected by direct evidence.
The one genuine limitation the Reality Check correctly anticipated stands: `diagnostic_constraints` only ever
carries a `has_contradictions` **boolean**, never the underlying per-contradiction detail — the richer
`VehicleIdentityResolution` path really is required for real contradiction flattening, exactly as §14 said.

---

## 4. Exact enum values (derived from source, not this instruction's prose)

```text
VIR vir.domain.enums.ResolutionStatus — 8 values:
  resolved, provisionally_resolved, ambiguous, insufficient_data, contradictory,
  unsupported_country, provider_unavailable, invalid_identifier

PGDR pgdr.enums.ResolutionStatus — 5 values:
  resolved, provisionally_resolved, ambiguous, insufficient_data, contradictory

Refused (VIR-only) — 3 values:
  unsupported_country, provider_unavailable, invalid_identifier
```

`PGDR ⊂ VIR`, confirmed both by direct set-comparison at module-import time (assertions in
`handoff_mapper.py` itself — the module fails to import if this relationship is ever broken by a future VIR
or PGDR change) and by a dedicated test class (`TestEnumDerivation`).

---

## 5. §14 field mapping traceability

**Primary path — `map_diagnostic_context(DiagnosticIdentityContext) -> pgdr.models.VehicleIdentityContext`:**

| VIR source | Transform | PGDR destination | Classification |
|---|---|---|---|
| `resolution_id: str` | none | `resolution_id: str` | DIRECT |
| `identity_status: ResolutionStatus` | validated against PGDR's 5, refused if not admissible | `resolution_status: ResolutionStatus` | TRANSFORM |
| `vehicle: dict[str, Any]` | none — passed through exactly, including an empty dict | `vehicle_identity: Optional[dict]` | DIRECT |
| `diagnostic_constraints["confidence_score"]` + `["confidence_level"]` (both present) | constructs `ConfidenceScore(score=..., level=...)` | `confidence: Optional[ConfidenceScore]` | TRANSFORM |
| `diagnostic_constraints["unresolved_fields"]` (present) | none | `unresolved_fields: list[str]` | DIRECT |
| `diagnostic_constraints["has_contradictions"]` (boolean only) | never expanded into fabricated items | `contradictions: list[str]` | NOT_APPLICABLE (always `[]` on this path) |
| `diagnostic_constraints["exact_engine_code_known"]`, `["exact_factory_configuration_known"]` | — | no PGDR target | NOT_APPLICABLE |

**Richer path — `map_resolution(VehicleIdentityResolution) -> pgdr.models.VehicleIdentityContext`:**

| VIR source | Transform | PGDR destination | Classification |
|---|---|---|---|
| `resolution_id: str` | none | `resolution_id: str` | DIRECT |
| `resolution_status: ResolutionStatus` | validated/refused, same rule as primary path | `resolution_status: ResolutionStatus` | TRANSFORM |
| `vehicle_identity: CanonicalVehicleIdentity \| None` | `.model_dump()` if present; `None` preserved as `None` (not `{}`) | `vehicle_identity: Optional[dict]` | DERIVED_FROM_RICHER_VIR_RESULT |
| `confidence.score: float` | none | `confidence.score` | DERIVED_FROM_RICHER_VIR_RESULT |
| `confidence.level: ConfidenceLevel` | `.value` (enum → plain string) | `confidence.level: str` | DERIVED_FROM_RICHER_VIR_RESULT |
| `unresolved_fields: list[str]` | none | `unresolved_fields: list[str]` | DIRECT |
| `contradictions: list[Contradiction]` | each flattened to `.field_path` | `contradictions: list[str]` | DERIVED_FROM_RICHER_VIR_RESULT |

No `DEFAULT` value is introduced anywhere that isn't either a field the PGDR model itself already defaults
(`unresolved_fields`/`contradictions` default to `[]` in PGDR's own model) or an explicit `None` when data is
genuinely absent — never guessed.

---

## 6. Contradiction flattening

Each VIR `Contradiction` (`contradiction_id`, `field_path`, `values: list[ContradictionValue]`, `severity`,
`resolution_action`) is flattened to its `field_path` string alone. Reasoning: PGDR's own contract fixes
`contradictions: list[str]` — a single string per item — so `severity`, `values`, and `resolution_action`
cannot be preserved without inventing an ad hoc serialization format nowhere specified. `field_path` is the
single stable, identifying piece of information per contradiction, matching the same "which fields" role
`unresolved_fields: list[str]` already plays in the same model. This information loss is inherent to PGDR's
own fixed schema, not a discretionary choice this mapper makes — disclosed here, not silently absorbed.

---

## 7. Files added

```text
src/product_integration/pgdr/__init__.py
src/product_integration/pgdr/errors.py             (VIRPGDRHandoffError)
src/product_integration/pgdr/handoff_mapper.py          (map_diagnostic_context, map_resolution, and the
                                                            shared _map_status/_build_pgdr_context/
                                                            _flatten_contradiction internals)
tests/test_pgdr_handoff_mapper.py                             (42 tests)
```

No CPL file touched. No VIR file touched. No PGDR file touched. No new migration. No new CPL primitive.

---

## 8. Tests and results

```text
Command: python -m pytest tests/test_pgdr_handoff_mapper.py -v

TestEnumDerivation:            4 tests  — §9 (8/5/3 derived from real enum classes, not prose)
TestStatusExhaustiveness:      9 tests  — §17 (5 admissible + 3 refused, individually parametrized, plus a
                                            coverage-completeness check)
TestFieldMapping:              9 tests  — §18
TestContradictionFlattening:   7 tests  — §19
TestRicherConfidencePath:      5 tests  — §20
TestPydanticContract:          3 tests  — §21
TestPurity:                    4 tests  — §22
TestFieldMapping (subset above already covers unresolved_fields/vehicle/no-extra-fields)

TOTAL: 42 passed, 0 failed, 0 skipped
```

**No-I/O proof (§23), the strongest form available:** the entire 42-test suite was run with
`DATABASE_URL` pointed at `192.0.2.1` (RFC 5737 TEST-NET-1 — guaranteed unroutable, not merely "probably
down") — 42/42 passed in 0.17 seconds, proving zero live-service dependency empirically, not merely by
review. (CPL itself is installed in the build venv only because `tests/conftest.py`, shared across the whole
repository since PI-01, imports it at collection time for PI-01's own fixtures — PI-02's own test file
imports nothing from `app.*` at all, confirmed by direct inspection of `test_pgdr_handoff_mapper.py`'s
import list.)

**Combined-suite regression:** with a real, reachable PostgreSQL database, the full repository suite —
PI-01's 41 tests plus PI-02's 42 — was run together: 83/83 passed. Zero regression to PI-01.

---

## 9. Coverage of all 8 statuses

```text
resolved                -> PASS (admissible)
provisionally_resolved   -> PASS (admissible)
ambiguous                 -> PASS (admissible)
insufficient_data          -> PASS (admissible)
contradictory                -> PASS (admissible)
unsupported_country            -> PASS (correctly refused, VIRPGDRHandoffError raised)
provider_unavailable              -> PASS (correctly refused, VIRPGDRHandoffError raised)
invalid_identifier                  -> PASS (correctly refused, VIRPGDRHandoffError raised)
```

Individually parametrized (`TestStatusExhaustiveness`), plus a structural test confirming the two sets
(admissible ∪ refused) equal exactly VIR's full enum — if a ninth VIR value is ever added, this test fails
immediately (neither set will contain it), forcing mapper review rather than silent omission.

---

## 10. Richer confidence path

`PASS`. Tested separately from the primary path (`TestRicherConfidencePath`), including the specific
anti-fabrication check: a `DiagnosticIdentityContext` lacking confidence data in `diagnostic_constraints`
produces `confidence=None`, never a guessed value, confirmed from both directions (§20's own explicit
requirement).

---

## 11. Blocking findings

None.

---

## 12. Non-blocking findings

None new. PI-01's carried findings (`PI-01-VF-02`, `PI-01-VF-03`) are unaffected — this candidate touches
none of the files they concern.

---

## 13. Governance deviations

None. No CPL, VIR, or PGDR modification anywhere. `PI-02` introduces no new CPL primitive, no new execution
semantics, no new persistence. `COMMON_GAP` remains `0`.

---

## 14. Contract drift status

```text
CONTRACT_DRIFT: NONE
```

The one discrepancy found (§3 above) was a phrasing imprecision in the Reality Check's own prose, not a
disagreement between the Reality Check and the actual pinned source models — the underlying data availability
the Reality Check anticipated (confidence eventually derivable, contradictions needing the richer path) holds
exactly, just through a slightly different field path (`diagnostic_constraints`, nested) than the loose
phrasing implied.

---

## PI-02 CANDIDATE

```text
Repository:
  https://github.com/paxtonef/cpl-product-integration.git

Base:
  2b9cf211c759f377e0095e570864493889f4f75c

Branch:
  pi-02-vir-pgdr-handoff-candidate

Candidate SHA:
  reported in the accompanying build handoff

Tree SHA:
  reported in the accompanying build handoff

VIR baseline:
  a342aba7cc2fc517621f4fc79c3191bdfdc9e10b

PGDR baseline:
  0580b1a5ba5867a607a33197372fcaf4164f0fb6

VIR statuses:
  8

PGDR admissible statuses:
  5

Explicitly refused VIR statuses:
  3

§14 field mapping:
  PASS

Contradiction flattening:
  PASS

Richer confidence path:
  PASS

Pydantic validation:
  PASS

Pure / no I/O:
  PASS (proven with an unroutable DATABASE_URL, 42/42 in 0.17s)

Deterministic:
  PASS

Source non-mutation:
  PASS

Tests:
  42 (PI-02 own suite) + 83 (combined with PI-01, real database, zero regression)

CPL modifications:
  0

VIR modifications:
  0

PGDR modifications:
  0

Contract drift:
  NONE

Blocking findings:
  0

Governance deviations:
  0

FINAL STATE:
  CANDIDATE_COMPLETE
```
