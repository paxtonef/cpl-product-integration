"""PGDR V1 notice parcours in the authenticated product (block 2).

The parcours itself -- consent, optional photo, 1 to 3 proposed images,
complete catalogue, the driver's own selection and confirmation, exact
notice restitution, Premier Constat, colour fallback -- is PGDR's /v1,
unchanged and not rebuilt here. PI adds only what the product needs:

  * Opening: from a case the user owns, VIR's persisted resolution goes
    through PI-02's map_resolution() (whitelisted identity, no plate, no VIN,
    no registration date; a value resting on a driver confirmation alone is
    handed on as unknown, never as a decode) to PGDR's credentialed
    POST /api/v1/vir-handoff. PGDR decides: opened, or its own refusal
    (vehicle_identity_insufficient, notice_unavailable, vehicle_not_supported,
    applicability_not_confirmed) -- never a silently assumed notice.
  * Ownership: every opened parcours is recorded here with its case and the
    contact who opened it. The browser reaches PGDR only through PI, and only
    for its own parcours; another user's parcours is answered exactly like a
    missing one. PGDR stays on the loopback.
  * Relay: an explicit allow-list of PGDR /v1 parcours requests (no handoff,
    no development entry). The catalogue images, the photo and the result
    pass through PI only to the parcours' owner.
  * Photo: before PI forwards it, its metadata is removed again with PGDR's
    own strip_metadata (the page already re-encodes it). A photo that cannot
    be cleaned is never forwarded: PGDR receives an empty photo and answers
    with the explained catalogue. The photo is not stored by PI.

Process-local, like PGDR's parcours themselves (PGDR keeps them in memory):
both are lost on restart and the user opens a new parcours from the case.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import re
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from typing import Optional
from uuid import UUID

from pgdr.v1_propositions import PhotoRefusee, strip_metadata

PGDR_BASE_URL_ENV = "PI_PGDR_BASE_URL"
PGDR_HANDOFF_TOKEN_ENV = "PI_PGDR_IDENTITY_HANDOFF_TOKEN"
PGDR_HANDOFF_TOKEN_HEADER = "X-PGDR-Identity-Handoff-Token"

# PGDR's own refusals when it opens no parcours (pgdr.v1_parcours._open_parcours).
PGDR_REFUSALS = frozenset({"vehicle_identity_insufficient", "notice_unavailable", "vehicle_not_supported",
                           "applicability_not_confirmed"})

_PID = re.compile(r"^V1-[0-9a-f]{32}$")
_SHA = r"[0-9a-f]{64}"
# The parcours requests the page makes, and nothing else (method, sub-path after /api/v1/parcours/{pid}).
_ALLOWED = (
    ("GET", re.compile(r"^$")),
    ("GET", re.compile(r"^/catalogue$")),
    ("GET", re.compile(r"^/propositions$")),
    ("GET", re.compile(rf"^/asset/{_SHA}$")),
    ("POST", re.compile(r"^/(vir-seen|consent|propositions|selection|confirm|clarify|condition|no-match|colour|return)$")),
)
MAX_RELAY_BODY = 21_500_000  # a 15 MB photo in base64, plus the JSON around it


def allowed(method: str, sub_path: str) -> bool:
    return any(method == m and rx.match(sub_path) for m, rx in _ALLOWED)


def valid_parcours_id(pid: str) -> bool:
    return bool(_PID.match(pid))


@dataclass(frozen=True)
class ParcoursOwner:
    case_id: UUID
    contact_id: UUID


class NoticeParcoursRegistry:
    """parcours_id -> (case, owner). Process-local, bounded like PGDR's own
    parcours store; never persisted, never claims otherwise."""

    def __init__(self, limit: int = 1000) -> None:
        self._entries: "OrderedDict[str, ParcoursOwner]" = OrderedDict()
        self._limit = limit
        self._lock = Lock()

    def put(self, pid: str, owner: ParcoursOwner) -> None:
        with self._lock:
            self._entries[pid] = owner
            while len(self._entries) > self._limit:
                self._entries.popitem(last=False)

    def owner(self, pid: str) -> Optional[ParcoursOwner]:
        with self._lock:
            return self._entries.get(pid)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


default_notice_registry = NoticeParcoursRegistry()


def pgdr_base_url() -> str:
    return os.environ[PGDR_BASE_URL_ENV].rstrip("/")


def handoff_headers() -> dict[str, str]:
    return {PGDR_HANDOFF_TOKEN_HEADER: os.environ[PGDR_HANDOFF_TOKEN_ENV]}


def cleaned_propositions_body(raw: bytes) -> bytes:
    """The /propositions body with the photo's metadata removed. Anything
    that cannot be cleaned is replaced by an empty photo (PGDR then answers
    with the explained catalogue); a body that is not the expected JSON is
    refused (ValueError)."""
    body = json.loads(raw)
    if not isinstance(body, dict) or set(body) != {"recipient_consent", "photo_base64"} \
            or not all(isinstance(v, str) for v in body.values()):
        raise ValueError("unexpected propositions body")
    try:
        photo = base64.b64decode(body["photo_base64"], validate=True)
        clean = strip_metadata(photo)[0]
    except (binascii.Error, ValueError, PhotoRefusee):
        clean = b""
    body["photo_base64"] = base64.b64encode(clean).decode("ascii")
    return json.dumps(body).encode("utf-8")
