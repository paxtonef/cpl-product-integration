"""Category B — status mapping tests (§24-B): all 8 VIR values proven,
unknown status explicitly rejected."""
import pytest

from product_integration.vir.status_mapping import (
    VIR_TO_CPL_RESOLUTION_STATUS,
    UnknownVIRStatusError,
    map_vir_status_to_cpl,
)


class TestStatusMapping:

    @pytest.mark.parametrize("vir_status,expected_cpl_status", [
        ("resolved", "RESOLVED"),
        ("provisionally_resolved", "PARTIALLY_RESOLVED"),
        ("ambiguous", "AMBIGUOUS"),
        ("insufficient_data", "UNRESOLVED"),
        ("contradictory", "CONTRADICTORY"),
        ("unsupported_country", "FAILED"),
        ("provider_unavailable", "FAILED"),
        ("invalid_identifier", "FAILED"),
    ])
    def test_all_eight_vir_statuses_mapped_explicitly(self, vir_status, expected_cpl_status):
        assert map_vir_status_to_cpl(vir_status) == expected_cpl_status

    def test_exactly_eight_values_in_table(self):
        assert len(VIR_TO_CPL_RESOLUTION_STATUS) == 8

    def test_target_values_are_within_cpl_six_value_vocabulary(self):
        cpl_admissible = {"RESOLVED", "PARTIALLY_RESOLVED", "AMBIGUOUS", "CONTRADICTORY", "UNRESOLVED", "FAILED"}
        assert set(VIR_TO_CPL_RESOLUTION_STATUS.values()) <= cpl_admissible
        assert len(cpl_admissible) == 6  # no 7th CPL value introduced

    def test_unknown_vir_status_rejected_explicitly(self):
        with pytest.raises(UnknownVIRStatusError):
            map_vir_status_to_cpl("some_status_vir_never_defined")
