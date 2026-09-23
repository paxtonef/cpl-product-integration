"""VIR -> PGDR identity boundary correction, owner decision 5: VIR's
production.start_date is not a first-registration date and is never
written into VehicleDetail.first_registration_date."""
from __future__ import annotations

import uuid
from datetime import date

from app.automotive.models.vehicle_detail import VehicleDetail

from product_integration.vehicle_detail_writer import write_vehicle_detail

_IDENTITY = {
    "manufacturer": "Peugeot", "model": "3008", "variant": None,
    "production": {"year": 2020, "start_date": "2016-10-01", "end_date": None},
    "identifiers": {"registration_number": "AB-123-CD", "registration_country": "FR", "vin": None},
}


class _Session:
    """Just the two Session calls write_vehicle_detail makes."""

    def __init__(self, existing=None):
        self.existing, self.added = existing, []

    def get(self, model, key):
        return self.existing

    def add(self, obj):
        self.added.append(obj)


def test_new_detail_never_takes_production_start_date_as_first_registration():
    session = _Session()
    detail = write_vehicle_detail(session, asset_id=uuid.uuid4(), source_resolution_id=None,
                                  canonical_identity=_IDENTITY)
    assert session.added == [detail]
    assert detail.first_registration_date is None
    assert (detail.make, detail.model, detail.registration_display) == ("Peugeot", "3008", "AB-123-CD")


def test_update_neither_writes_nor_erases_first_registration_from_production_dates():
    existing = VehicleDetail(asset_id=uuid.uuid4(), first_registration_date=None)
    write_vehicle_detail(_Session(existing), asset_id=existing.asset_id, source_resolution_id=None,
                         canonical_identity=_IDENTITY)
    assert existing.first_registration_date is None

    genuine = date(2017, 3, 14)
    existing.first_registration_date = genuine
    write_vehicle_detail(_Session(existing), asset_id=existing.asset_id, source_resolution_id=None,
                         canonical_identity=_IDENTITY)
    assert existing.first_registration_date == genuine
