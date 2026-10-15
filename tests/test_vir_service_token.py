"""VIR V1 service access — VIR's JSON API (vir.security.service_auth, VIR
commit 7075bea) refuses every /v1 route unless the X-VIR-Service-Token
header matches VIR_SERVICE_TOKEN (fail closed when unset). PI-01's client
must present the token configured for PI (PI_VIR_SERVICE_TOKEN), against
VIR's REAL app (ASGI), and never expose it in an error.

Fictitious token values only (set by conftest's vir_service_env)."""
import httpx
import pytest

from product_integration.vir.client import SERVICE_TOKEN_HEADER, SERVICE_TOKEN_ENV, VIRClient
from product_integration.vir.errors import VIRClientError
from tests.conftest import make_vin_request


def _vir_app_client():
    import vir.api.routes as vir_routes
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=vir_routes.app), base_url="http://vir.test")


class TestVIRServiceToken:

    def test_header_name_matches_vir(self):
        from vir.security.service_auth import SERVICE_TOKEN_HEADER as VIR_HEADER
        assert SERVICE_TOKEN_HEADER == VIR_HEADER

    async def test_configured_token_is_accepted_by_real_vir(self, vir_isolated_store, vir_service_env):
        async with _vir_app_client() as http_client:
            resolution = await VIRClient(http_client).resolve(make_vin_request())
        assert resolution.resolution_id

    async def test_explicit_token_overrides_environment(self, vir_isolated_store, vir_service_env, monkeypatch):
        monkeypatch.delenv(SERVICE_TOKEN_ENV)
        async with _vir_app_client() as http_client:
            resolution = await VIRClient(http_client, service_token=vir_service_env).resolve(make_vin_request())
        assert resolution.resolution_id

    async def test_missing_token_is_refused_by_vir_and_fails_controlled(self, vir_isolated_store, vir_service_env,
                                                                         monkeypatch):
        monkeypatch.delenv(SERVICE_TOKEN_ENV)
        async with _vir_app_client() as http_client:
            with pytest.raises(VIRClientError):
                await VIRClient(http_client).resolve(make_vin_request())

    async def test_wrong_token_is_refused_and_never_echoed(self, vir_isolated_store, vir_service_env, monkeypatch):
        wrong = "fictive-wrong-token-0000"
        monkeypatch.setenv(SERVICE_TOKEN_ENV, wrong)
        async with _vir_app_client() as http_client:
            with pytest.raises(VIRClientError) as excinfo:
                await VIRClient(http_client).resolve(make_vin_request())
        assert wrong not in str(excinfo.value)
        assert vir_service_env not in str(excinfo.value)
