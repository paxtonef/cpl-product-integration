"""Block B1.5 — local, application-managed media storage.

Deliberately NOT S3/MinIO/cloud object storage (explicitly out of scope
for this stage, per the mandate's own instruction). The storage location
on disk is a pure implementation detail -- callers never see or supply a
filesystem path; they only ever receive or provide an opaque `media_id`,
always server-generated (uuid4 hex), never derived from caller input.

Security boundary: `media_id` is validated with a strict format check
(_MEDIA_ID_PATTERN) before ever being used to construct a path, on every
read. A caller supplying "../../etc/passwd", "/Users/...", "file://...",
or any string containing a path separator can never reach the filesystem
through this module -- MediaNotFoundError is raised instead of attempting
the lookup.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

_MEDIA_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")  # uuid4().hex format only

_SUPPORTED_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
}

_MAX_MEDIA_BYTES = 15 * 1024 * 1024  # 15 MB -- generous for a phone camera photo


class MediaValidationError(Exception):
    """Raised when uploaded content fails validation (unsupported type,
    empty, or oversized) -- before anything is written to storage."""


class MediaNotFoundError(Exception):
    """Raised when a media_id does not resolve to stored content -- either
    because it was never stored, or because it failed the opaque-identifier
    format check (never because a path was "almost" valid; the format check
    is binary, not a fuzzy match)."""


class LocalMediaStorage:
    """Application-managed local filesystem storage. The base directory is
    fixed at construction time and never influenced by any per-request
    caller input."""

    def __init__(self, base_dir: str | Path):
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def store(self, content: bytes, content_type: str) -> str:
        """Validates and stores `content`, returning a fresh, opaque,
        server-generated media_id. Never accepts a caller-supplied
        identifier -- the identifier a caller later uses is exactly, and
        only, what this method returns."""
        if content_type not in _SUPPORTED_CONTENT_TYPES:
            raise MediaValidationError(f"unsupported media type: {content_type!r}")
        if not content:
            raise MediaValidationError("empty media content")
        if len(content) > _MAX_MEDIA_BYTES:
            raise MediaValidationError(f"media exceeds maximum size of {_MAX_MEDIA_BYTES} bytes")

        media_id = uuid.uuid4().hex
        extension = _SUPPORTED_CONTENT_TYPES[content_type]
        target = self._path_for(media_id, extension)
        target.write_bytes(content)
        # Persist the content type alongside the bytes, keyed by the same
        # media_id, so resolution can report a real MediaType without
        # re-sniffing the file.
        (self._base_dir / f"{media_id}.contenttype").write_text(content_type)
        return media_id

    def read(self, media_id: str) -> tuple[bytes, str]:
        """Returns (content, content_type) for a previously stored
        media_id. Raises MediaNotFoundError for anything that does not
        pass the strict opaque-identifier format check, or that the
        format check passes but no matching stored asset exists."""
        if not _MEDIA_ID_PATTERN.match(media_id):
            raise MediaNotFoundError(f"not a valid media identifier: {media_id!r}")

        content_type_path = self._base_dir / f"{media_id}.contenttype"
        if not content_type_path.is_file():
            raise MediaNotFoundError(f"no stored media for identifier: {media_id!r}")
        content_type = content_type_path.read_text().strip()

        extension = _SUPPORTED_CONTENT_TYPES.get(content_type)
        if extension is None:
            raise MediaNotFoundError(f"stored content type no longer supported: {content_type!r}")

        target = self._path_for(media_id, extension)
        if not target.is_file():
            raise MediaNotFoundError(f"no stored media for identifier: {media_id!r}")
        return target.read_bytes(), content_type

    def _path_for(self, media_id: str, extension: str) -> Path:
        # media_id is only ever a value this class itself generated (store)
        # or a value that has already passed the strict format check
        # (read) -- never constructed from arbitrary caller input.
        return self._base_dir / f"{media_id}{extension}"
