"""Minimum VehicleDetail write operation (Reality Check gap G-02).

VehicleDetail's primary key IS asset_id (app/automotive/models/
vehicle_detail.py, confirmed) — a 1:1 relationship with Asset. This makes
the write operation naturally an upsert: create the row if this Asset has
none yet, update it in place if it already does. No second VehicleDetail
schema is introduced; this function writes to the existing CPL model only.
Only the four VIR-sourceable fields present on VehicleDetail are populated
(vin_display, registration_display, registration_country, make, model,
variant, first_registration_date) — VIR's full CanonicalVehicleIdentity is
NOT embedded into CPL (per PI-01's own non-scope rule); the full identity
stays in the RunnerArtifact payload (see cpl_registration.py), and only
this small display/summary projection lives on VehicleDetail, matching
what the existing column set already defines as in scope.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.automotive.models.vehicle_detail import VehicleDetail


def write_vehicle_detail(
    session: Session,
    *,
    asset_id: UUID,
    source_resolution_id: Optional[UUID],
    canonical_identity: dict[str, Any],
) -> VehicleDetail:
    """Create-or-update the VehicleDetail row for `asset_id` from a VIR
    CanonicalVehicleIdentity dict (as produced by
    product_integration.vir.schemas.CanonicalVehicleIdentity.model_dump()).
    Never touches any Asset other than `asset_id` — no lookup by VIN/
    registration is performed here; the caller is responsible for having
    already resolved which Asset this identity belongs to (CPL's own
    Asset-identity authority, not this function's)."""
    identifiers = canonical_identity.get("identifiers") or {}
    production = canonical_identity.get("production") or {}

    existing = session.get(VehicleDetail, asset_id)
    now = datetime.now(timezone.utc)

    if existing is None:
        detail = VehicleDetail(
            asset_id=asset_id,
            vin_display=identifiers.get("vin"),
            registration_display=identifiers.get("registration_number"),
            registration_country=identifiers.get("registration_country"),
            make=canonical_identity.get("manufacturer"),
            model=canonical_identity.get("model"),
            variant=canonical_identity.get("variant"),
            first_registration_date=_parse_date(production.get("start_date")),
            source_resolution_id=source_resolution_id,
            created_at=now, updated_at=now,
        )
        session.add(detail)
        return detail

    existing.vin_display = identifiers.get("vin") or existing.vin_display
    existing.registration_display = identifiers.get("registration_number") or existing.registration_display
    existing.registration_country = identifiers.get("registration_country") or existing.registration_country
    existing.make = canonical_identity.get("manufacturer") or existing.make
    existing.model = canonical_identity.get("model") or existing.model
    existing.variant = canonical_identity.get("variant") or existing.variant
    parsed_date = _parse_date(production.get("start_date"))
    if parsed_date is not None:
        existing.first_registration_date = parsed_date
    if source_resolution_id is not None:
        existing.source_resolution_id = source_resolution_id
    existing.updated_at = now
    return existing


def _parse_date(value: Optional[str]):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None
