"""Category A — VIR client tests, against VIR's REAL app (ASGI, real routes,
real request/response validation), per §24-A."""
import httpx
import pytest

from product_integration.vir.client import VIRClient
from product_integration.vir.errors import (
    VIRInvalidResponseError, VIRResolutionNotFoundError, VIRTechnicalFailureError,
    VIRTimeoutError, VIRTransportError,
)
from product_integration.vir.schemas import ClarificationAnswer, ClarificationRequest, ConsentInput, VehicleIdentityRequest
from tests.conftest import make_vin_request


class TestVIRClient:

    async def test_resolve_endpoint_success(self, vir_client: VIRClient):
        resolution = await vir_client.resolve(make_vin_request())
        assert resolution.resolution_id
        assert resolution.resolution_status in {
            "resolved", "provisionally_resolved", "ambiguous", "insufficient_data", "contradictory",
        }

    async def test_get_resolution_round_trips(self, vir_client: VIRClient):
        resolution = await vir_client.resolve(make_vin_request())
        fetched = await vir_client.get_resolution(resolution.resolution_id)
        assert fetched.resolution_id == resolution.resolution_id

    async def test_diagnostic_handoff_retrieval(self, vir_client: VIRClient):
        resolution = await vir_client.resolve(make_vin_request())
        handoff = await vir_client.get_diagnostic_handoff(resolution.resolution_id)
        assert handoff.resolution_id == resolution.resolution_id
        assert "confidence_score" in handoff.diagnostic_constraints

    async def test_clarification_operation(self, vir_client: VIRClient):
        # A manual-identity request with no strong identifier is the
        # realistic path to a resolution carrying real clarification
        # questions in VIR's own stub engine.
        # "AM-BIG-01" is VIR's own known ambiguous-plate fixture (confirmed
        # directly in VIR's tests/test_resolution.py and
        # src/vir/adapters/registration_provider_adapter.py at the pinned
        # baseline — deterministically produces AMBIGUOUS with >=1
        # clarification question, not a guess).
        request = VehicleIdentityRequest(
            request_id="PI01-CLARIFY-TEST",
            registration={"registration_number": "AM-BIG-01", "country_code": "FR"},
            consent=ConsentInput(external_lookup_allowed=True),
        )
        resolution = await vir_client.resolve(request)
        assert resolution.resolution_status == "ambiguous"
        assert len(resolution.clarification_questions) >= 1
        answer = ClarificationAnswer(
            question_id=resolution.clarification_questions[0].question_id, value="test-answer",
        )
        result = await vir_client.submit_clarification(
            resolution.resolution_id, ClarificationRequest(answers=[answer]),
        )
        assert result.resolution_id  # a resolution came back; VIR's own logic decides if it's new or same

    async def test_get_nonexistent_resolution_raises_not_found(self, vir_client: VIRClient):
        with pytest.raises(VIRResolutionNotFoundError):
            await vir_client.get_resolution("DOES-NOT-EXIST")

    async def test_invalid_request_raises_technical_failure(self, vir_client: VIRClient):
        # No identifier at all -> VIR's own MissingIdentifierError (VIR-ERR-001, HTTP 400)
        request = VehicleIdentityRequest(request_id="PI01-INVALID", consent=ConsentInput(external_lookup_allowed=True))
        with pytest.raises(VIRTechnicalFailureError) as exc_info:
            await vir_client.resolve(request)
        assert exc_info.value.error_code == "VIR-ERR-001"
        assert exc_info.value.http_status == 400

    async def test_transport_failure_raised_distinctly(self):
        transport = httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ConnectError("refused")))
        async with httpx.AsyncClient(transport=transport, base_url="http://vir.test") as http_client:
            client = VIRClient(http_client)
            with pytest.raises(VIRTransportError):
                await client.resolve(make_vin_request())

    async def test_timeout_raised_distinctly(self):
        def _raise_timeout(request):
            raise httpx.ReadTimeout("timed out", request=request)
        transport = httpx.MockTransport(_raise_timeout)
        async with httpx.AsyncClient(transport=transport, base_url="http://vir.test") as http_client:
            client = VIRClient(http_client, timeout_seconds=0.01)
            with pytest.raises(VIRTimeoutError):
                await client.resolve(make_vin_request())

    async def test_invalid_response_body_raised_distinctly(self):
        def _bad_body(request):
            return httpx.Response(200, json={"unexpected": "shape"})
        transport = httpx.MockTransport(_bad_body)
        async with httpx.AsyncClient(transport=transport, base_url="http://vir.test") as http_client:
            client = VIRClient(http_client)
            with pytest.raises(VIRInvalidResponseError):
                await client.resolve(make_vin_request())

    async def test_no_hidden_retry_on_transport_failure(self):
        call_count = 0
        def _count_and_fail(request):
            nonlocal call_count
            call_count += 1
            raise httpx.ConnectError("refused")
        transport = httpx.MockTransport(_count_and_fail)
        async with httpx.AsyncClient(transport=transport, base_url="http://vir.test") as http_client:
            client = VIRClient(http_client)
            with pytest.raises(VIRTransportError):
                await client.resolve(make_vin_request())
        assert call_count == 1  # exactly one attempt, no hidden retry
