"""Block B1.5 — PI-side tests: real upload, storage, security boundary,
resolver round-trip, and end-to-end integration with the existing B1
diagnostic-start transport.
"""
from __future__ import annotations

import hashlib
import shutil
import tempfile
import uuid

import httpx
import pytest

from product_integration.media.resolver_adapter import LocalMediaResolverAdapter
from product_integration.media.storage import LocalMediaStorage, MediaNotFoundError, MediaValidationError
from pgdr.ports.media_resolver import MediaResolutionError, MediaResolverPort

BASE_URL = "http://127.0.0.1:8000"

_REAL_JPEG_BYTES = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300"
    + "10" * 61
    + "ffd9"
)  # a tiny, syntactically-real (if minimal) JPEG byte sequence


def _register_and_resolve() -> str:
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        vehicle = client.post(
            "/vehicles",
            json={
                "contact_idempotency_key": f"b15-c-{uuid.uuid4().hex[:10]}",
                "asset_idempotency_key": f"b15-a-{uuid.uuid4().hex[:10]}",
            },
        ).json()
        case = client.post(
            "/cases",
            json={
                "contact_id": vehicle["contact_id"], "asset_id": vehicle["asset_id"],
                "request_id": f"b15-case-{uuid.uuid4().hex[:10]}",
                "vin": "VF3XXXXXXXXXXXXXX",
                "case_idempotency_key": f"b15-case-idem-{uuid.uuid4().hex[:10]}",
                "consent": {"external_lookup_allowed": True},
            },
        )
        assert case.status_code == 201, case.text
        return case.json()["case_id"]


class TestB15Storage:
    def test_store_and_read_round_trip(self, tmp_path):
        storage = LocalMediaStorage(tmp_path)
        content = b"\xff\xd8\xff" + b"\x00" * 100  # jpeg-ish bytes
        media_id = storage.store(content, "image/jpeg")
        read_back, content_type = storage.read(media_id)
        assert read_back == content
        assert content_type == "image/jpeg"

    def test_media_id_is_opaque_uuid_hex_not_related_to_content(self, tmp_path):
        storage = LocalMediaStorage(tmp_path)
        media_id = storage.store(b"\xff\xd8\xff" + b"\x00" * 50, "image/png")
        import re
        assert re.match(r"^[0-9a-f]{32}$", media_id)

    def test_rejects_unsupported_content_type(self, tmp_path):
        storage = LocalMediaStorage(tmp_path)
        with pytest.raises(MediaValidationError):
            storage.store(b"not an image", "application/pdf")

    def test_rejects_empty_content(self, tmp_path):
        storage = LocalMediaStorage(tmp_path)
        with pytest.raises(MediaValidationError):
            storage.store(b"", "image/jpeg")

    def test_rejects_oversized_content(self, tmp_path):
        storage = LocalMediaStorage(tmp_path)
        oversized = b"\x00" * (16 * 1024 * 1024)
        with pytest.raises(MediaValidationError):
            storage.store(oversized, "image/jpeg")

    @pytest.mark.parametrize("malicious_ref", [
        "../../etc/passwd", "/etc/passwd", "../../../etc/shadow",
        "file:///etc/passwd", "..%2F..%2Fetc%2Fpasswd", "not-even-hex-at-all",
        "27c9d9a4-1a3d-4695-ba7a-059ce1782d65",  # dashed UUID, not accepted format
    ])
    def test_rejects_path_traversal_and_malformed_references(self, tmp_path, malicious_ref):
        storage = LocalMediaStorage(tmp_path)
        with pytest.raises(MediaNotFoundError):
            storage.read(malicious_ref)


class TestB15ResolverAdapter:
    def test_resolver_implements_pgdr_port_structurally(self, tmp_path):
        storage = LocalMediaStorage(tmp_path)
        resolver = LocalMediaResolverAdapter(storage)
        assert isinstance(resolver, MediaResolverPort)

    def test_resolve_round_trip_matches_stored_content(self, tmp_path):
        storage = LocalMediaStorage(tmp_path)
        resolver = LocalMediaResolverAdapter(storage)
        content = b"\xff\xd8\xff" + b"\x01" * 200
        media_id = storage.store(content, "image/jpeg")
        resolved = resolver.resolve(media_id)
        assert resolved.content == content
        assert resolved.reference == media_id

    def test_resolve_unknown_reference_raises_pgdr_error_type(self, tmp_path):
        storage = LocalMediaStorage(tmp_path)
        resolver = LocalMediaResolverAdapter(storage)
        with pytest.raises(MediaResolutionError):
            resolver.resolve("a" * 32)  # well-formed but never stored


class TestB15EndToEnd:
    def test_ac01_ac02_ac03_real_upload_stores_and_returns_media_id(self):
        """B1.5-AC01/AC02/AC03: a real image can be uploaded through the
        product boundary, the system stores it, and the upload returns an
        opaque stable media reference."""
        with httpx.Client(base_url=BASE_URL, timeout=30) as client:
            resp = client.post("/media", files={"file": ("dashboard.jpg", _REAL_JPEG_BYTES, "image/jpeg")})
        assert resp.status_code == 201, resp.text
        media_id = resp.json()["media_id"]
        assert len(media_id) == 32
        assert all(c in "0123456789abcdef" for c in media_id)

    def test_ac04_media_id_accepted_by_existing_diagnostic_transport(self):
        """B1.5-AC04: the reference is accepted by the existing Primary
        Diagnostic Media transport (Block B1, unmodified)."""
        with httpx.Client(base_url=BASE_URL, timeout=30) as client:
            media_id = client.post(
                "/media", files={"file": ("d.jpg", _REAL_JPEG_BYTES, "image/jpeg")}
            ).json()["media_id"]
            case_id = _register_and_resolve()
            resp = client.post(
                f"/cases/{case_id}/diagnostics",
                json={"primary_diagnostic_media_reference": media_id},
            )
        assert resp.status_code in (200, 201), resp.text
        assert resp.json()["primary_diagnostic_media_reference"] == media_id

    def test_ac05_resolver_resolves_same_content_as_uploaded(self):
        """B1.5-AC05: the resolver can resolve that reference to the same
        actual media content -- real HTTP upload, then real resolution,
        byte-for-byte, hash-verified."""
        original_hash = hashlib.sha256(_REAL_JPEG_BYTES).hexdigest()
        with httpx.Client(base_url=BASE_URL, timeout=30) as client:
            media_id = client.post(
                "/media", files={"file": ("d.jpg", _REAL_JPEG_BYTES, "image/jpeg")}
            ).json()["media_id"]

        from product_integration.api.deps import get_media_storage
        storage = get_media_storage()
        resolver = LocalMediaResolverAdapter(storage)
        resolved = resolver.resolve(media_id)
        assert hashlib.sha256(resolved.content).hexdigest() == original_hash

    def test_ac08_rejects_unsupported_media_type_via_real_http(self):
        """B1.5-AC08: unsupported media is rejected."""
        with httpx.Client(base_url=BASE_URL, timeout=30) as client:
            resp = client.post("/media", files={"file": ("d.txt", b"not an image", "text/plain")})
        assert resp.status_code == 422

    def test_ac08_rejects_empty_upload_via_real_http(self):
        with httpx.Client(base_url=BASE_URL, timeout=30) as client:
            resp = client.post("/media", files={"file": ("d.jpg", b"", "image/jpeg")})
        assert resp.status_code == 422

    def test_ac09_upload_creates_no_evidence_observation_identification_confidence(self):
        """B1.5-AC09: upload/resolution creates no diagnostic meaning --
        confirmed by direct source scan of the new B1.5 code."""
        import inspect
        from product_integration.media import resolver_adapter, storage as storage_module
        for module in (resolver_adapter, storage_module):
            source = inspect.getsource(module)
            assert "Evidence(" not in source
            assert "Observation(" not in source
            assert "DashboardInterpretationResult(" not in source

    def test_ac10_q_evi_002_not_used(self):
        import inspect
        from product_integration.media import resolver_adapter, storage as storage_module
        for module in (resolver_adapter, storage_module):
            source = inspect.getsource(module)
            assert "submit_answer" not in source
            assert "media_upload" not in source.lower() or "Q-EVI" not in source

    def test_ac11_existing_text_only_path_still_works(self):
        """B1.5-AC11: existing text diagnostic path remains operational."""
        case_id = _register_and_resolve()
        with httpx.Client(base_url=BASE_URL, timeout=30) as client:
            resp = client.post(
                f"/cases/{case_id}/diagnostics",
                json={"complaint_text": "Bruit inhabituel au freinage."},
            )
        assert resp.status_code in (200, 201), resp.text

    def test_ac12_existing_b1_reference_only_transport_still_works(self):
        """B1.5-AC12: existing B1 media transport (an arbitrary reference
        string, not necessarily from a real upload) remains operational --
        B1.5 is additive, it does not require every reference to have come
        through /media."""
        case_id = _register_and_resolve()
        with httpx.Client(base_url=BASE_URL, timeout=30) as client:
            resp = client.post(
                f"/cases/{case_id}/diagnostics",
                json={"primary_diagnostic_media_reference": "legacy-block-a-style-reference"},
            )
        assert resp.status_code in (200, 201), resp.text
