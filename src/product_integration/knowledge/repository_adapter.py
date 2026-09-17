"""Block B2-K — Knowledge Persistence Implementation Mandate v1, §16.

Concrete, storage-backed implementation of
pgdr.ports.knowledge_repository.KnowledgeRepositoryPort, owned entirely
by the PI/CPL persistence side (never imported by PGDR itself). Reads
from the new, non-execution-scoped `cpl.manufacturer_knowledge_documents`
/ `cpl.manufacturer_knowledge_dashboard_entries` tables (migration 028) --
deliberately not `cpl.runner_artifacts`, whose `execution_id` is NOT NULL
and would falsely couple reusable manufacturer knowledge to one
diagnostic case.

Translates ORM rows into PGDR's own frozen domain types on every read --
no SQLAlchemy model, session, or row object is ever handed back to
calling PGDR code.
"""
from __future__ import annotations

from typing import Optional

from app.cpl.models.manufacturer_knowledge_dashboard_entry import ManufacturerKnowledgeDashboardEntry
from app.cpl.models.manufacturer_knowledge_document import ManufacturerKnowledgeDocument
from app.db.engine import SessionLocal

from pgdr.domain.dashboard_knowledge import (
    ApplicabilityPeriod, DashboardReferenceEntry, IndicatorState, KnowledgeLifecycleStatus,
    ManufacturerDocumentReference, SourceAuthority, VehicleApplicabilityContext,
)


def _row_to_document(row: ManufacturerKnowledgeDocument) -> ManufacturerDocumentReference:
    applicability_period = None
    if row.applicability_period_start or row.applicability_period_end or row.applicability_period_note:
        applicability_period = ApplicabilityPeriod(
            start_date=row.applicability_period_start,
            end_date=row.applicability_period_end,
            note=row.applicability_period_note,
        )
    return ManufacturerDocumentReference(
        manufacturer=row.manufacturer,
        document_id=row.document_id,
        document_title=row.document_title,
        edition=row.edition,
        applicability_period=applicability_period,
        source_authority=SourceAuthority(row.source_authority),
        source_locator=row.source_locator,
        lifecycle_status=KnowledgeLifecycleStatus(row.lifecycle_status.lower()),
        verified_at=row.verified_at.isoformat() if row.verified_at else None,
        supersedes_document_id=None,  # resolved by document_id, not document_row_id -- see _resolve_supersedes below
    )


def _row_to_entry(row: ManufacturerKnowledgeDashboardEntry, document: ManufacturerDocumentReference) -> DashboardReferenceEntry:
    return DashboardReferenceEntry(
        entry_id=row.entry_id,
        manufacturer_designation=row.manufacturer_designation,
        symbol_descriptor=row.symbol_descriptor,
        colour=row.colour,
        state=IndicatorState(row.state) if row.state else None,
        displayed_message=row.displayed_message,
        audible_signal=row.audible_signal,
        documented_meaning=row.documented_meaning,
        documented_instruction=row.documented_instruction,
        applicability=document,
        combined_with_entry_ids=list(row.combined_with_entry_ids or []),
    )


class PersistedKnowledgeRepositoryAdapter:
    """Implements pgdr.ports.knowledge_repository.KnowledgeRepositoryPort
    structurally (confirmed via isinstance() against the real Port in the
    PI-side integration test suite)."""

    def __init__(self, session_factory=SessionLocal):
        self._session_factory = session_factory

    def find_applicable_documents(self, vehicle: VehicleApplicabilityContext) -> list[ManufacturerDocumentReference]:
        session = self._session_factory()
        try:
            rows = session.query(ManufacturerKnowledgeDocument).filter(
                ManufacturerKnowledgeDocument.applicability_manufacturer == vehicle.manufacturer,
                ManufacturerKnowledgeDocument.applicability_model == vehicle.model,
                ManufacturerKnowledgeDocument.applicability_generation == vehicle.generation,
                ManufacturerKnowledgeDocument.lifecycle_status == "ACTIVE",
            ).all()
            return [self._resolve_supersedes(session, row) for row in rows]
        finally:
            session.close()

    def entries_for_document(self, document_id: str) -> list[DashboardReferenceEntry]:
        session = self._session_factory()
        try:
            doc_row = session.query(ManufacturerKnowledgeDocument).filter(
                ManufacturerKnowledgeDocument.document_id == document_id,
            ).first()
            if doc_row is None:
                return []
            document = self._resolve_supersedes(session, doc_row)
            entry_rows = session.query(ManufacturerKnowledgeDashboardEntry).filter(
                ManufacturerKnowledgeDashboardEntry.document_row_id == doc_row.document_row_id,
            ).all()
            return [_row_to_entry(row, document) for row in entry_rows]
        finally:
            session.close()

    def get_document_by_id(self, document_id: str) -> Optional[ManufacturerDocumentReference]:
        session = self._session_factory()
        try:
            doc_row = session.query(ManufacturerKnowledgeDocument).filter(
                ManufacturerKnowledgeDocument.document_id == document_id,
            ).first()
            if doc_row is None:
                return None
            return self._resolve_supersedes(session, doc_row)
        finally:
            session.close()

    @staticmethod
    def _resolve_supersedes(session, row: ManufacturerKnowledgeDocument) -> ManufacturerDocumentReference:
        document = _row_to_document(row)
        if row.supersedes_document_row_id is None:
            return document
        predecessor = session.query(ManufacturerKnowledgeDocument).filter(
            ManufacturerKnowledgeDocument.document_row_id == row.supersedes_document_row_id,
        ).first()
        if predecessor is None:
            return document
        return document.model_copy(update={"supersedes_document_id": predecessor.document_id})
