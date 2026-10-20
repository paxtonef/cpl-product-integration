"""Test support for the PGDR V1 notice parcours in the product: a FICTIVE
notice package (every text and image invented, written to a temporary
directory at test time) and a FAKE sorting transport. Nothing here comes from
a real manufacturer manual; nothing here analyses an image."""
from __future__ import annotations

import hashlib
import json
import struct
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from pgdr.adapters.manifest_notice_repository import content_fingerprint
from pgdr import v1_propositions as vp

RECIPIENT = "Composant de tri d'essai (faux transport)"
ORDER = ["fn_red_fluid", "fn_amber_sensor", "fn_green_lamps", "fn_white_cruise"]
GREEN_MEANING = "The fictive green light shows that the fictive lamps are on."
# What VIR's simulated fixture resolves for a VF3… VIN (resolved): the fictive notice is declared for it.
SIMULATED_VEHICLE = {"manufacturer": "Peugeot", "model": "3008", "generation": "II"}


def png(rgb: tuple[int, int, int], size: int = 6) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b""))


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def photo_with_metadata(plate: str, vin: str) -> bytes:
    """A dashboard 'photo' (fictive PNG) whose metadata names a plate, a VIN and a position."""
    base = png((10, 20, 30), 8)
    meta = _chunk(b"tEXt", b"Comment\x00" + plate.encode()) + _chunk(b"eXIf", b"MM\x00*GPS 48.85N " + vin.encode())
    return base[:33] + meta + base[33:]


def build_notice(root: Path, vehicle: dict, *, applicability_established: bool = True) -> Path:
    (root / "images").mkdir(parents=True, exist_ok=True)
    files = {"manual.pdf": b"%PDF-1.4\n% FICTIVE manual for tests only\n%%EOF\n",
             "images/red.png": png((200, 0, 0)), "images/amber.png": png((230, 150, 0)),
             "images/green.png": png((0, 160, 0)), "images/white.png": png((240, 240, 240))}
    for name, data in files.items():
        (root / name).write_bytes(data)
    h = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}

    def entry(entry_id, designation, colour, image, meaning, page, **extra):
        e = {"entry_id": entry_id, "manufacturer_designation": designation, "symbol_descriptor": None,
             "colour": colour, "state": "fixed", "displayed_message": None, "audible_signal": None,
             "documented_meaning": meaning, "documented_instruction": None, "combined_with_entry_ids": [],
             "image_file": image, "image_sha256": h[image], "pdf_page": page, "page_reference": f"F-{page}",
             "where_provided": False, "documented_startup_check": None, "linked_warnings": [],
             "inline_pictograms": [], "notes": [], "field_sources": {}}
        e.update(extra)
        return e

    entries = [
        entry("fn_red_fluid", "FICTIVE LOW FLUID", "red", "images/red.png",
              "The fictive red light switches on when the fictive brake fluid is low.", 1,
              documented_instruction="Stop the fictive vehicle."),
        entry("fn_amber_sensor", "FICTIVE SENSOR FAULT", "amber", "images/amber.png",
              "The fictive amber symbol means a fictive sensor fault.", 2),
        entry("fn_green_lamps", "FICTIVE LAMPS ON", "green", "images/green.png", GREEN_MEANING, 2),
        entry("fn_white_cruise", "FICTIVE CRUISE", "white", "images/white.png",
              "The fictive white symbol shows the fictive cruise mode.", 3),
    ]
    d = {"schema_version": 2, "document_id": "FICTIVE-PI-NOTICE-001", "title": "FICTIVE OWNER HANDBOOK",
         "edition": "Fictive edition 1", "source_authority": "manufacturer_official",
         "source_locator": "fictive fixture only", "vehicle": dict(vehicle),
         "applicability_period_start": None, "applicability_period_end": None, "applicability_period_note": None,
         "manual_file": "manual.pdf", "manual_sha256": h["manual.pdf"], "language": "en",
         "applicability_vehicle_under_review": {"applicability_established": applicability_established},
         "entries": entries}
    d["review"] = {"status": "approved", "reviewer_id": "fictive-reviewer", "reviewer_name": "Fictive Reviewer",
                   "reviewed_at": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
                   "content_sha256": content_fingerprint(d)}
    path = root / "manifest.yaml"
    path.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def fake_sorter(ids=None, *, panne=False, raw=None, seen=None) -> vp.FauxTransportTri:
    """The FAKE sorting transport: a canned answer whatever the photo."""
    if panne:
        answer = {"panne": True}
    else:
        answer = {"texte": raw if raw is not None else json.dumps({"proposed_entry_ids": ids})}
    return vp.FauxTransportTri(RECIPIENT, {}, answer, observer=None if seen is None else seen.append)


def notice_parcours_opened() -> list[str]:
    """PGDR's parcours opened WITH a notice. A refusal opens none: only, beside it, a parcours without notice
    (fixed screen, then the safety instructions by colour; clôture PGDR V1)."""
    from pgdr import v1_parcours as v1
    return [pid for pid, p in v1._parcours.items() if p.sans_notice is None]
