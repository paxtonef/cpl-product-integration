"""E2E fixture setup for Acceptance Journey C (PI-02 refusal).

Not a backend modification -- calls PI-01's own real, existing Path B
function (register_vir_resolution_result) to persist a real refused VIR
result, the same established pattern used throughout this project's own
backend verification (VIR's real resolve() engine does not reach
provider_unavailable through its current stub providers, so this is the
only way to reach the fixture through real code rather than fabricating an
HTTP response). Requires PI-05's real backend (same DATABASE_URL) to
already be running. Prints the resulting case_id on stdout, and nothing
else, so the calling script can capture it directly.
"""
from __future__ import annotations

import sys
import uuid

import httpx

from app.cpl.identity.authority import Authority, AuthorityContext
from app.cpl.assets.authority import AssetAuthority
from app.cpl.cases.authority import CaseAuthority
from app.cpl.cases.lifecycle import create_case
from app.cpl.runners.authority import RunnerAuthority
from app.db.engine import SessionLocal
from product_integration.cpl_registration import VIRRegistrationOutcome, register_vir_resolution_result
from vir.domain.enums import ConfidenceLevel, ResolutionStatus as VIRStatus
from vir.domain.models import Confidence as VIRConfidence, VehicleIdentityResolution as VIRRes


def main() -> None:
    api_base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    client = httpx.Client(base_url=api_base_url)

    vehicle = client.post(
        "/vehicles",
        json={
            "contact_idempotency_key": f"e2e-refusal-c-{uuid.uuid4().hex[:10]}",
            "asset_idempotency_key": f"e2e-refusal-a-{uuid.uuid4().hex[:10]}",
        },
    ).json()

    authority = AuthorityContext(
        granted=frozenset(
            {
                Authority.CREATE_CONTACT,
                Authority.READ_IDENTITY,
                AssetAuthority.CREATE_ASSET,
                AssetAuthority.CONSUME_IDENTITY_RESOLUTION,
                CaseAuthority.CREATE_CASE,
                CaseAuthority.TRANSITION_CASE_STATUS,
                RunnerAuthority.ADMIT_EXECUTION,
                RunnerAuthority.TRANSITION_EXECUTION_STATUS,
                RunnerAuthority.REGISTER_ARTIFACT,
            }
        ),
        actor_reference="e2e-pi02-refusal-fixture-setup",
    )

    session = SessionLocal()
    case_result = create_case(
        session,
        primary_contact_id=uuid.UUID(vehicle["contact_id"]),
        asset_id=uuid.UUID(vehicle["asset_id"]),
        domain="AUTOMOTIVE",
        case_type="VEHICLE_DIAGNOSTIC",
        authority=authority,
        idempotency_key=f"e2e-refusal-case-{uuid.uuid4().hex[:10]}",
    )
    session.commit()
    case_id = case_result.object_id
    session.close()

    refused_resolution = VIRRes(
        request_id="E2E-PI02-REFUSAL",
        resolution_id=f"VIR-RES-{uuid.uuid4().hex[:12].upper()}",
        resolution_status=VIRStatus.PROVIDER_UNAVAILABLE,
        confidence=VIRConfidence(score=0.0, level=ConfidenceLevel.UNRESOLVED),
    )
    vir_result = register_vir_resolution_result(
        vir_resolution=refused_resolution,
        case_id=case_id,
        asset_id=uuid.UUID(vehicle["asset_id"]),
        authority=authority,
    )
    if vir_result.outcome != VIRRegistrationOutcome.SUCCESS:
        raise RuntimeError(f"fixture setup failed: {vir_result.outcome} {vir_result.detail}")

    # Trigger the actual PI-02 refusal (this is the real product behavior
    # under test elsewhere; here it's only executed once up front so the
    # Case's persisted state matches what a real user who already tried
    # starting a diagnostic and returned later would see).
    diagnostics = client.post(f"/cases/{case_id}/diagnostics", json={"complaint_text": "noise"}).json()
    if diagnostics.get("outcome") != "PI02_HANDOFF_REFUSED":
        raise RuntimeError(f"expected PI02_HANDOFF_REFUSED, got {diagnostics}")

    print(case_id)


if __name__ == "__main__":
    main()
