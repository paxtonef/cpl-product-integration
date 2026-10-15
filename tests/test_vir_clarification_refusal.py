"""VIR V1 clarification refusal — VIR (clarify_resolution.py, commit
6bdd958) now refuses an answer it cannot apply (e.g. a power that is not a
positive number) with VIR-ERR-016 and leaves the resolution unchanged. PI-05
must surface that as its typed VIR failure, never as an unhandled 500, and
must record nothing new for the Case.

HTTP only, real VIR (ASGI), real PostgreSQL; fictitious identifiers."""
from __future__ import annotations

from tests.test_product_api import _register_vehicle, _start_case_vir, api_client, vir_isolated_store  # noqa: F401


class TestVIRClarificationRefusal:

    async def test_refused_answer_is_a_typed_vir_failure_and_nothing_is_recorded(self, api_client):
        veh = await _register_vehicle(api_client)
        case = await _start_case_vir(api_client, veh, vin=None, registration_number="AM-BIG-01")
        assert case["vir_resolution_status"] == "AMBIGUOUS"

        r = await api_client.get(f"/executions/{case['vir_execution_id']}/artifact")
        questions = r.json()["payload"].get("clarification_questions", [])
        power = [q for q in questions if q.get("target_field") == "engine.power_kw"]
        assert power, "VIR's ambiguous fixture is expected to ask for the power"

        r = await api_client.post(f"/cases/{case['case_id']}/vir/clarifications", json={
            "answers": [{"question_id": power[0]["question_id"], "value": "not-a-number"}],
        })
        assert r.status_code == 502, r.text
        body = r.json()
        assert body["error_category"] == "VIR_TECHNICAL_FAILURE"
        assert body["vir_error_code"] == "VIR-ERR-016"
        assert "Traceback" not in r.text

        r = await api_client.get(f"/cases/{case['case_id']}/history")
        assert r.status_code == 200
        vir_execs = [e for e in r.json()["executions"] if e["runner_type"] == "VIR"]
        assert len(vir_execs) == 1  # the refused answer created no clarified execution
