"""PI -> PGDR Photo-First intake handoff: a real VIR resolution, translated
by map_resolution(), handed to the real PGDR web app over HTTP (ASGI
transport, in-process) with the real persisted Peugeot knowledge."""
from __future__ import annotations

import secrets

import httpx

from pgdr import web_app as pgdr_web
from vir.adapters.registration_provider_adapter import FrenchRegistrationProviderAdapter
from vir.application.resolve_vehicle import ResolveVehicleUseCase
from vir.domain.models import ConsentInput, RegistrationInput, VehicleIdentityRequest

from product_integration.knowledge.repository_adapter import PersistedKnowledgeRepositoryAdapter
from product_integration.knowledge.seed_peugeot_3008 import seed_peugeot_3008_knowledge
from product_integration.pgdr import photo_intake
from product_integration.pgdr.handoff_mapper import map_resolution


class _UnusedInterpretationProvider:
    """PGDR requires a configured provider to accept a Photo-First intake; the
    handoff itself never interprets anything, so this is never called."""

    def interpret(self, media, reference_set):
        raise AssertionError("the identity handoff must not interpret any image")


async def test_real_vir_resolution_becomes_a_pgdr_photo_intake_through_map_resolution(monkeypatch):
    seed_peugeot_3008_knowledge()
    resolution = await ResolveVehicleUseCase(providers=[FrenchRegistrationProviderAdapter()]).execute(
        VehicleIdentityRequest(
            request_id="PI-PHOTO-INTAKE", consent=ConsentInput(external_lookup_allowed=True),
            registration=RegistrationInput(registration_number="AB-123-CD", country_code="FR"),
        )
    )

    mapped_calls = []
    monkeypatch.setattr(photo_intake, "map_resolution", lambda r: mapped_calls.append(r) or map_resolution(r))
    monkeypatch.setenv(photo_intake.PGDR_BASE_URL_ENV, "http://pgdr.test")
    token = secrets.token_hex(16)   # per run, supplied to both sides only via environment variables
    monkeypatch.setenv(photo_intake.PGDR_HANDOFF_TOKEN_ENV, token)
    monkeypatch.setenv(pgdr_web.IDENTITY_HANDOFF_TOKEN_ENV, token)
    monkeypatch.setattr(pgdr_web, "_photo_wiring", pgdr_web.PhotoWiring(
        interpretation_provider=_UnusedInterpretationProvider(),
        knowledge_repository=PersistedKnowledgeRepositoryAdapter(),
    ))
    pgdr_web._photo_intakes.clear()
    pgdr_web._sessions.clear()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=pgdr_web.app)) as client:
        url = await photo_intake.request_photo_first_intake(resolution, http_client=client)

        assert mapped_calls == [resolution]
        intake_id = url.removeprefix("http://pgdr.test/?intake=")
        intake = pgdr_web._photo_intakes[intake_id]
        assert intake.identity == map_resolution(resolution)          # verbatim, not reconstructed
        assert intake.reference_set.applicability_status.value == "reference_set_available"
        assert len(intake.reference_set.entries) == 11
        assert not intake.consent_media_analysis and not pgdr_web._sessions   # no PGDR session before the photo

        # The handoff is authenticated: a wrong token creates nothing.
        monkeypatch.setenv(photo_intake.PGDR_HANDOFF_TOKEN_ENV, "wrong")
        try:
            await photo_intake.request_photo_first_intake(resolution, http_client=client)
            raise AssertionError("a wrong token must be refused")
        except photo_intake.PhotoIntakeRefusedError as exc:
            assert exc.status == "http_403"
        assert list(pgdr_web._photo_intakes) == [intake_id]
    pgdr_web._photo_intakes.clear()
