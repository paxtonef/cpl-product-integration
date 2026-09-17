"""Block B2-K — Knowledge Persistence Implementation Mandate v1, §17.

Controlled, deterministic, idempotent initial ingestion of the already
corrected and verified Peugeot 3008/5008 handbook content (document
9999_9999_326_en-GB.pdf) into the new durable, non-execution-scoped
persistence introduced by migration 028.

This is NOT a crawler and does NOT acquire anything from the Internet --
the content below is transcribed exactly, losslessly, from the same
corrected fixture previously verified in
pgdr.adapters.peugeot_dashboard_knowledge (prior to this pass's refactor,
which moved this content out of PGDR's own package and into durable
storage). Running this function twice with unchanged content is a no-op
(idempotent) -- verified by content_hash comparison against the current
ACTIVE generation for this manufacturer+document_id, never by attempting
a naive INSERT and catching a constraint violation.
"""
from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from app.cpl.models.manufacturer_knowledge_dashboard_entry import ManufacturerKnowledgeDashboardEntry
from app.cpl.models.manufacturer_knowledge_document import ManufacturerKnowledgeDocument
from app.db.engine import SessionLocal

_MANUFACTURER = "Peugeot"
_DOCUMENT_ID = "9999_9999_326_en-GB"
_DOCUMENT_TITLE = "MY PEUGEOT 3008 / MY PEUGEOT 5008 HANDBOOK"
_SOURCE_LOCATOR = "Peugeot Service Box, document 9999_9999_326_en-GB.pdf"

# The verified content itself. Kept as plain dicts (not PGDR Pydantic
# objects) since this module belongs to PI/persistence, not PGDR --
# PGDR domain types are never imported here; this data is written
# straight to CPL's own ORM rows.
_ENTRIES = [
    dict(entry_id="oil-pressure-warning", manufacturer_designation="Engine oil pressure",
         symbol_descriptor=None, colour="red", state="fixed", displayed_message=None, audible_signal=None,
         documented_meaning="Fault with the engine lubrication system.",
         documented_instruction=(
             "(1) Stop the vehicle as soon as it is safe to do so and switch off the ignition. "
             "(2) Contact a PEUGEOT dealer or a qualified workshop."
         ), combined_with_entry_ids=[]),
    dict(entry_id="engine-diag-fixed", manufacturer_designation="Engine self-diagnostic system",
         symbol_descriptor=None, colour="orange", state="fixed", displayed_message=None, audible_signal=None,
         documented_meaning="Fault in the emissions control system. The warning lamp should go off "
                             "when the engine is started.",
         documented_instruction="Go to a PEUGEOT dealer or a qualified workshop without delay.",
         combined_with_entry_ids=[]),
    dict(entry_id="engine-diag-flashing", manufacturer_designation="Engine self-diagnostic system",
         symbol_descriptor=None, colour="orange", state="flashing", displayed_message=None, audible_signal=None,
         documented_meaning="Fault in the engine management system. Risk of catalytic-converter "
                             "destruction.",
         documented_instruction="Contact a PEUGEOT dealer or a qualified workshop.",
         combined_with_entry_ids=[]),
    dict(entry_id="adblue-level-state-a", manufacturer_designation="AdBlue\u00ae (BlueHDi)",
         symbol_descriptor="Illuminates for approximately 30 seconds when starting", colour="orange",
         state=None, displayed_message="Driving-range message: 1,500\u2013500 miles (2,400\u2013800 km) remaining",
         audible_signal=None,
         documented_meaning="AdBlue\u00ae driving-range warning: 1,500\u2013500 miles (2,400\u2013800 km) "
                             "of range remaining.",
         documented_instruction="Top up AdBlue\u00ae.", combined_with_entry_ids=[]),
    dict(entry_id="adblue-level-state-b", manufacturer_designation="AdBlue\u00ae (BlueHDi)",
         symbol_descriptor=None, colour="orange", state="fixed",
         displayed_message="Driving-range message: 500\u201362 miles (800\u2013100 km) remaining",
         audible_signal="Yes (further detail not specified in the supplied source)",
         documented_meaning="AdBlue\u00ae driving-range warning: 500\u201362 miles (800\u2013100 km) of "
                             "range remaining.",
         documented_instruction="Promptly top up AdBlue\u00ae, or go to a PEUGEOT dealer or a qualified "
                                 "workshop.", combined_with_entry_ids=[]),
    dict(entry_id="adblue-level-state-c", manufacturer_designation="AdBlue\u00ae (BlueHDi)",
         symbol_descriptor=None, colour="orange", state="flashing",
         displayed_message="Driving-range message: less than 62 miles (100 km) remaining",
         audible_signal="Yes (further detail not specified in the supplied source)",
         documented_meaning="Risk that engine starting will be prevented.",
         documented_instruction="Top up AdBlue\u00ae to avoid engine starting being prevented, or go to "
                                 "a PEUGEOT dealer or a qualified workshop.", combined_with_entry_ids=[]),
    dict(entry_id="adblue-level-state-d", manufacturer_designation="AdBlue\u00ae (BlueHDi)",
         symbol_descriptor=None, colour="orange", state="flashing",
         displayed_message="Message indicating that starting is prevented (exact wording not specified "
                            "in the supplied source for this state)",
         audible_signal="Yes (further detail not specified in the supplied source)",
         documented_meaning="AdBlue\u00ae tank empty. The legally required engine immobiliser prevents "
                             "engine starting.",
         documented_instruction="Top up AdBlue\u00ae (at least 5 litres) or contact a PEUGEOT dealer or "
                                 "a qualified workshop.", combined_with_entry_ids=[]),
    dict(entry_id="service-warning-lamp-fixed", manufacturer_designation="Service warning lamp",
         symbol_descriptor=None, colour=None, state="fixed", displayed_message=None, audible_signal=None,
         documented_meaning="Documented only as part of the confirmed SCR emissions-control-system "
                             "malfunction combination (see combined_with_entry_ids); the supplied "
                             "source gives this lamp no independent standalone meaning.",
         documented_instruction=None, combined_with_entry_ids=["scr-malfunction-confirmed-countdown"]),
    dict(entry_id="scr-malfunction-detected", manufacturer_designation="SCR emissions control system (BlueHDi)",
         symbol_descriptor=None, colour=None, state="fixed", displayed_message=None,
         audible_signal="Yes (further detail not specified in the supplied source)",
         documented_meaning="SCR emissions-control-system malfunction detected. An audible signal and a "
                             "display message are documented for this state; the supplied source does "
                             "not include the exact message wording for this initial phase. The alert "
                             "disappears if exhaust emissions return to normal.",
         documented_instruction=None, combined_with_entry_ids=["scr-malfunction-confirmed-countdown"]),
    dict(entry_id="scr-malfunction-confirmed-countdown",
         manufacturer_designation="SCR emissions control system (BlueHDi) -- confirmed malfunction",
         symbol_descriptor="Combination: AdBlue\u00ae warning lamp flashing, together with the Service "
                            "warning lamp and Engine self-diagnostics warning lamp both fixed",
         colour=None, state=None,
         displayed_message="Emissions control fault: starting prevented in X miles (kms)",
         audible_signal="Yes",
         documented_meaning=(
             "Confirmed SCR emissions-control-system malfunction, reached after the initial fault "
             "indication has remained permanently displayed for 31 miles / 50 km of driving. Up to "
             "685 miles / 1,100 km may remain before engine immobilisation, counting down from that "
             "point."
         ),
         documented_instruction="Have the vehicle checked by a PEUGEOT dealer or qualified workshop "
                                 "without delay to avoid starting being prevented.",
         combined_with_entry_ids=["service-warning-lamp-fixed", "engine-diag-fixed",
                                   "scr-malfunction-detected", "scr-starting-prevented"]),
    dict(entry_id="scr-starting-prevented",
         manufacturer_designation="SCR emissions control system (BlueHDi) -- starting prevented",
         symbol_descriptor=None, colour=None, state=None,
         displayed_message="Emissions control fault: Starting prevented", audible_signal=None,
         documented_meaning="Starting prevention has been activated.",
         documented_instruction="Contact a PEUGEOT dealer or a qualified workshop.",
         combined_with_entry_ids=["scr-malfunction-confirmed-countdown"]),
]


def _content_hash() -> str:
    """Deterministic hash of the full generation's content -- the basis
    for idempotent seeding. Sorted keys, stable separators: identical
    content always hashes identically regardless of dict insertion order."""
    payload = json.dumps(
        {"document_id": _DOCUMENT_ID, "document_title": _DOCUMENT_TITLE, "entries": _ENTRIES},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def seed_peugeot_3008_knowledge(session_factory=SessionLocal) -> dict:
    """Idempotent. Returns {"action": "inserted" | "noop" | "superseded",
    "document_row_id": <uuid>, "content_hash": <str>}."""
    content_hash = _content_hash()
    session = session_factory()
    try:
        existing_active = session.query(ManufacturerKnowledgeDocument).filter(
            ManufacturerKnowledgeDocument.manufacturer == _MANUFACTURER,
            ManufacturerKnowledgeDocument.document_id == _DOCUMENT_ID,
            ManufacturerKnowledgeDocument.lifecycle_status == "ACTIVE",
        ).first()

        if existing_active is not None and existing_active.content_hash == content_hash:
            return {"action": "noop", "document_row_id": existing_active.document_row_id, "content_hash": content_hash}

        supersedes_row_id = None
        if existing_active is not None:
            existing_active.lifecycle_status = "SUPERSEDED"
            supersedes_row_id = existing_active.document_row_id

        new_row = ManufacturerKnowledgeDocument(
            document_row_id=uuid4(),
            manufacturer=_MANUFACTURER,
            document_id=_DOCUMENT_ID,
            document_title=_DOCUMENT_TITLE,
            edition=None,
            applicability_manufacturer="Peugeot",
            applicability_model="3008",
            applicability_generation="II",
            applicability_period_start=None,
            applicability_period_end=None,
            applicability_period_note=None,
            source_authority="manufacturer_official",
            source_locator=_SOURCE_LOCATOR,
            lifecycle_status="ACTIVE",
            # Explicit, never inferred from verified_at (which stays None
            # here -- no verification timestamp has actually been
            # supplied for this POC seed).
            freshness_status="VERIFIED_CURRENT",
            supersedes_document_row_id=supersedes_row_id,
            content_hash=content_hash,
        )
        session.add(new_row)
        session.flush()

        for entry in _ENTRIES:
            session.add(ManufacturerKnowledgeDashboardEntry(
                entry_row_id=uuid4(),
                document_row_id=new_row.document_row_id,
                **entry,
            ))

        session.commit()
        return {
            "action": "superseded" if supersedes_row_id else "inserted",
            "document_row_id": new_row.document_row_id,
            "content_hash": content_hash,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
