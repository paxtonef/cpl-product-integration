"""Block B2-K — Knowledge Persistence, PI/CPL-side integration tests
(§30 of the Knowledge Persistence Implementation Mandate v1).

Run against a real, migrated PostgreSQL database -- no mocks for the
persistence layer itself, matching this project's own established
discipline.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from app.cpl.models.manufacturer_knowledge_dashboard_entry import ManufacturerKnowledgeDashboardEntry
from app.cpl.models.manufacturer_knowledge_document import ManufacturerKnowledgeDocument
from app.db.engine import SessionLocal

from pgdr.adapters.peugeot_dashboard_knowledge import PeugeotDashboardKnowledgeAdapter
from pgdr.domain.dashboard_knowledge import ApplicabilityStatus, KnowledgeLifecycleStatus, VehicleApplicabilityContext
from pgdr.ports.knowledge_repository import KnowledgeRepositoryPort

from product_integration.knowledge.repository_adapter import PersistedKnowledgeRepositoryAdapter
from product_integration.knowledge.seed_peugeot_3008 import seed_peugeot_3008_knowledge


def _peugeot_vehicle(**overrides) -> VehicleApplicabilityContext:
    base = dict(manufacturer="Peugeot", model="3008", generation="II", production_year=2020)
    base.update(overrides)
    return VehicleApplicabilityContext(**base)


@pytest.fixture(autouse=True)
def _ensure_seeded():
    """Idempotent -- safe to call at the start of every test in this
    module regardless of execution order."""
    seed_peugeot_3008_knowledge()
    yield


class TestB2KPersistenceMigrationAndSchema:
    def test_tables_exist_and_are_queryable(self):
        session = SessionLocal()
        try:
            # A successful query (even zero rows) proves the migration
            # actually created these tables in this database.
            session.query(ManufacturerKnowledgeDocument).count()
            session.query(ManufacturerKnowledgeDashboardEntry).count()
        finally:
            session.close()


class TestB2KDocumentPersistence:
    def test_seeded_document_is_a_real_row(self):
        session = SessionLocal()
        try:
            row = session.query(ManufacturerKnowledgeDocument).filter(
                ManufacturerKnowledgeDocument.document_id == "9999_9999_326_en-GB",
                ManufacturerKnowledgeDocument.lifecycle_status == "ACTIVE",
            ).first()
            assert row is not None
            assert row.manufacturer == "Peugeot"
            assert row.source_authority == "manufacturer_official"
        finally:
            session.close()


class TestB2KDashboardEntryPersistence:
    def test_all_eleven_entries_are_real_rows(self):
        session = SessionLocal()
        try:
            doc = session.query(ManufacturerKnowledgeDocument).filter(
                ManufacturerKnowledgeDocument.document_id == "9999_9999_326_en-GB",
                ManufacturerKnowledgeDocument.lifecycle_status == "ACTIVE",
            ).first()
            count = session.query(ManufacturerKnowledgeDashboardEntry).filter(
                ManufacturerKnowledgeDashboardEntry.document_row_id == doc.document_row_id,
            ).count()
            assert count == 11
        finally:
            session.close()


class TestB2KProvenanceRoundTrip:
    def test_provenance_survives_the_full_round_trip(self):
        repo = PersistedKnowledgeRepositoryAdapter()
        adapter = PeugeotDashboardKnowledgeAdapter(repository=repo)
        result = adapter.get_dashboard_reference_set(_peugeot_vehicle(first_registration_date="2020-09-15"))
        doc = result.candidate_documents[0]
        assert doc.manufacturer == "Peugeot"
        assert doc.document_id == "9999_9999_326_en-GB"
        assert doc.source_locator == "Peugeot Service Box, document 9999_9999_326_en-GB.pdf"
        for entry in result.entries:
            assert entry.applicability.document_id == "9999_9999_326_en-GB"


class TestB2KApplicabilityRoundTrip:
    def test_real_seed_needs_no_first_registration_date(self):
        """VIR -> PGDR identity boundary correction (owner decision 3): the
        date is required only when it discriminates between period-bound
        candidates. The real seed has one document with no issue period,
        so VIR's identity alone (which carries no such date) resolves it."""
        repo = PersistedKnowledgeRepositoryAdapter()
        adapter = PeugeotDashboardKnowledgeAdapter(repository=repo)
        result = adapter.get_dashboard_reference_set(_peugeot_vehicle())  # no first_registration_date
        assert result.applicability_status == ApplicabilityStatus.REFERENCE_SET_AVAILABLE
        assert len(result.entries) == 11

    def test_resolved_vehicle_gets_real_reference_set(self):
        repo = PersistedKnowledgeRepositoryAdapter()
        adapter = PeugeotDashboardKnowledgeAdapter(repository=repo)
        result = adapter.get_dashboard_reference_set(_peugeot_vehicle(first_registration_date="2020-09-15"))
        assert result.applicability_status == ApplicabilityStatus.REFERENCE_SET_AVAILABLE
        assert len(result.entries) == 11


class TestB2KSeedIdempotency:
    def test_seeding_twice_creates_no_duplicate_active_generation(self):
        first = seed_peugeot_3008_knowledge()
        second = seed_peugeot_3008_knowledge()
        assert second["action"] == "noop"
        assert second["document_row_id"] == first["document_row_id"]

        session = SessionLocal()
        try:
            active_count = session.query(ManufacturerKnowledgeDocument).filter(
                ManufacturerKnowledgeDocument.document_id == "9999_9999_326_en-GB",
                ManufacturerKnowledgeDocument.lifecycle_status == "ACTIVE",
            ).count()
            assert active_count == 1
        finally:
            session.close()


class TestB2KSupersession:
    def test_synthetic_supersession_preserves_history(self):
        """Synthetic repository lifecycle test data, per the mandate's own
        §22 instruction -- not fabricated Peugeot production facts. Uses a
        run-unique synthetic manufacturer name so repeated test runs never
        collide with rows left behind by a prior run."""
        run_marker = uuid4().hex[:8]
        synthetic_manufacturer = f"SynthMfr-Supersession-{run_marker}"
        session = SessionLocal()
        try:
            doc_a_id = uuid4()
            session.add(ManufacturerKnowledgeDocument(
                document_row_id=doc_a_id, manufacturer=synthetic_manufacturer,
                document_id=f"SYNTH-A-{doc_a_id}", document_title="Synthetic Gen A",
                applicability_manufacturer=synthetic_manufacturer, applicability_model="TestModel",
                applicability_generation="I", source_authority="manufacturer_official",
                source_locator="synthetic-test-locator-a", lifecycle_status="ACTIVE", content_hash="hash-a",
            ))
            session.commit()

            row_a = session.query(ManufacturerKnowledgeDocument).filter(
                ManufacturerKnowledgeDocument.document_row_id == doc_a_id,
            ).first()
            row_a.lifecycle_status = "SUPERSEDED"
            doc_b_id = uuid4()
            session.add(ManufacturerKnowledgeDocument(
                document_row_id=doc_b_id, manufacturer=synthetic_manufacturer,
                document_id=f"SYNTH-B-{doc_b_id}", document_title="Synthetic Gen B",
                applicability_manufacturer=synthetic_manufacturer, applicability_model="TestModel",
                applicability_generation="I", source_authority="manufacturer_official",
                source_locator="synthetic-test-locator-b", lifecycle_status="ACTIVE",
                supersedes_document_row_id=doc_a_id, content_hash="hash-b",
            ))
            session.commit()
            doc_a_business_id, doc_b_business_id = f"SYNTH-A-{doc_a_id}", f"SYNTH-B-{doc_b_id}"
        finally:
            session.close()

        repo = PersistedKnowledgeRepositoryAdapter()
        vehicle = VehicleApplicabilityContext(
            manufacturer=synthetic_manufacturer, model="TestModel", generation="I",
            first_registration_date="2022-01-01",
        )
        current = repo.find_applicable_documents(vehicle)
        assert [d.document_id for d in current] == [doc_b_business_id]

        historical = repo.get_document_by_id(doc_a_business_id)
        assert historical is not None
        assert historical.lifecycle_status == KnowledgeLifecycleStatus.SUPERSEDED

        current_doc = repo.get_document_by_id(doc_b_business_id)
        assert current_doc.supersedes_document_id == doc_a_business_id


class TestB2KStalenessLifecycleState:
    def test_lifecycle_status_and_verified_at_are_real_persisted_columns(self):
        session = SessionLocal()
        try:
            doc = session.query(ManufacturerKnowledgeDocument).filter(
                ManufacturerKnowledgeDocument.document_id == "9999_9999_326_en-GB",
                ManufacturerKnowledgeDocument.lifecycle_status == "ACTIVE",
            ).first()
            assert doc.lifecycle_status == "ACTIVE"
            assert doc.verified_at is None  # not yet set for this POC seed -- never fabricated
        finally:
            session.close()

    def test_seeded_peugeot_is_owner_attested_unverified_never_verified_current(self):
        """PRE-INTEGRATION REPAIR: freshness_status is a separate,
        independently-settable column from lifecycle_status -- confirmed
        via the real, seeded row. B2 source-veracity correction: the Peugeot
        rows are owner-attested, not independently verified, so they must
        never assert VERIFIED_CURRENT while verified_at is None."""
        session = SessionLocal()
        try:
            doc = session.query(ManufacturerKnowledgeDocument).filter(
                ManufacturerKnowledgeDocument.document_id == "9999_9999_326_en-GB",
                ManufacturerKnowledgeDocument.lifecycle_status == "ACTIVE",
            ).first()
            assert doc.freshness_status == "OWNER_ATTESTED_UNVERIFIED"
            assert doc.verified_at is None
            assert not (doc.freshness_status == "VERIFIED_CURRENT" and doc.verified_at is None)
            # source attribution is unchanged (Option 1): eligibility unaffected
            assert doc.source_authority == "manufacturer_official"
        finally:
            session.close()

    def test_applicable_document_can_be_stale_through_real_persistence(self):
        """§10 B, via a real database round trip: setting freshness_status
        to STALE on the real, currently-ACTIVE, applicable Peugeot
        document does not change its applicability -- the repository
        still resolves it as REFERENCE_SET_AVAILABLE, while
        freshness_status correctly reports STALE."""
        session = SessionLocal()
        try:
            doc = session.query(ManufacturerKnowledgeDocument).filter(
                ManufacturerKnowledgeDocument.document_id == "9999_9999_326_en-GB",
                ManufacturerKnowledgeDocument.lifecycle_status == "ACTIVE",
            ).first()
            original_freshness = doc.freshness_status
            doc.freshness_status = "STALE"
            session.commit()
        finally:
            session.close()

        try:
            repo = PersistedKnowledgeRepositoryAdapter()
            adapter = PeugeotDashboardKnowledgeAdapter(repository=repo)
            result = adapter.get_dashboard_reference_set(_peugeot_vehicle(first_registration_date="2020-09-15"))
            assert result.applicability_status == ApplicabilityStatus.REFERENCE_SET_AVAILABLE
            from pgdr.domain.dashboard_knowledge import KnowledgeFreshnessStatus
            assert result.candidate_documents[0].freshness_status == KnowledgeFreshnessStatus.STALE
        finally:
            # restore, since other tests in this module rely on the
            # seeded fixture's default freshness state
            session = SessionLocal()
            try:
                doc = session.query(ManufacturerKnowledgeDocument).filter(
                    ManufacturerKnowledgeDocument.document_id == "9999_9999_326_en-GB",
                ).first()
                doc.freshness_status = original_freshness
                session.commit()
            finally:
                session.close()


class TestB2KReconstructionAfterRestart:
    def test_freshly_constructed_adapter_and_repository_see_the_same_data(self):
        """§19: brand-new Python objects, no shared in-memory state with
        any earlier test in this module -- the only thing connecting them
        is the real database."""
        fresh_repo = PersistedKnowledgeRepositoryAdapter()
        fresh_adapter = PeugeotDashboardKnowledgeAdapter(repository=fresh_repo)
        result = fresh_adapter.get_dashboard_reference_set(_peugeot_vehicle(first_registration_date="2020-09-15"))
        assert result.applicability_status == ApplicabilityStatus.REFERENCE_SET_AVAILABLE
        assert len(result.entries) == 11


class TestB2KMultiCaseReuse:
    def test_two_independent_cases_reuse_the_same_generation_without_duplication(self):
        repo_case_a = PersistedKnowledgeRepositoryAdapter()
        adapter_case_a = PeugeotDashboardKnowledgeAdapter(repository=repo_case_a)
        result_a = adapter_case_a.get_dashboard_reference_set(
            _peugeot_vehicle(first_registration_date="2020-05-01")
        )

        repo_case_b = PersistedKnowledgeRepositoryAdapter()
        adapter_case_b = PeugeotDashboardKnowledgeAdapter(repository=repo_case_b)
        result_b = adapter_case_b.get_dashboard_reference_set(
            _peugeot_vehicle(first_registration_date="2021-11-01")
        )

        assert result_a.candidate_documents[0].document_id == result_b.candidate_documents[0].document_id

        session = SessionLocal()
        try:
            count = session.query(ManufacturerKnowledgeDocument).filter(
                ManufacturerKnowledgeDocument.document_id == "9999_9999_326_en-GB",
                ManufacturerKnowledgeDocument.lifecycle_status == "ACTIVE",
            ).count()
            assert count == 1
        finally:
            session.close()


class TestB2KCaseExecutionSeparation:
    def test_no_execution_or_case_column_exists_on_either_table(self):
        """§21/§27: manufacturer knowledge tables contain no execution_id/
        case_id/diagnostic_id column at all -- confirmed by inspecting the
        real ORM model's own columns, not merely by absence of a foreign
        key."""
        document_columns = {c.name for c in ManufacturerKnowledgeDocument.__table__.columns}
        entry_columns = {c.name for c in ManufacturerKnowledgeDashboardEntry.__table__.columns}
        forbidden = {"execution_id", "case_id", "diagnostic_id"}
        assert forbidden.isdisjoint(document_columns)
        assert forbidden.isdisjoint(entry_columns)


class TestB2KRepositoryPortConformance:
    def test_concrete_adapter_satisfies_the_pgdr_port_structurally(self):
        repo = PersistedKnowledgeRepositoryAdapter()
        assert isinstance(repo, KnowledgeRepositoryPort)
