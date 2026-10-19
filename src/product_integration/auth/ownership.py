"""Per-owner access to product objects, derived from CPL's own data.

CPL's authority model (``AuthorityContext``) is capability-based: it says
which operations a caller may perform, not on which rows. Ownership is
already recorded by CPL itself, so no schema change is needed:

  case       -> ``cpl.cases.primary_contact_id``
  vehicle    -> ``cpl.contact_asset_relationships`` (ACTIVE/UNVERIFIED, not
                ended); a vehicle shared through a CPL relationship is
                therefore reachable by every related contact
  execution  -> its case
  artifact   -> its execution
  media      -> ``pi_auth.media_ownership`` (PI's own media storage)

Every refusal is the same ``not found`` answer as for a missing object.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app.cpl.models.case import Case
from app.cpl.models.contact_asset_relationship import ContactAssetRelationship
from app.cpl.models.runner_execution import RunnerExecution

from product_integration.api.errors import ProductAPIError, ProductAPIErrorCategory
from product_integration.auth.accounts import Principal


def not_found() -> ProductAPIError:
    return ProductAPIError(ProductAPIErrorCategory.NOT_FOUND, "not found")


def scoped_key(principal: Principal, client_key: str) -> str:
    """A client-supplied idempotency key or request id, made private to its
    account: another user reusing the same value never replays (and so
    never reveals) this user's objects."""
    return "pi-" + hashlib.sha256(f"{principal.account_id}:{client_key}".encode("utf-8")).hexdigest()[:40]


def owned_case(session: Session, principal: Principal, case_id: UUID) -> Case:
    case = session.get(Case, case_id)
    if case is None or case.primary_contact_id != principal.contact_id:
        raise not_found()
    return case


def owned_execution(session: Session, principal: Principal, execution_id: UUID) -> RunnerExecution:
    execution = session.get(RunnerExecution, execution_id)
    if execution is None or execution.case_id is None:
        raise not_found()
    owned_case(session, principal, execution.case_id)
    return execution


def can_use_asset(session: Session, principal: Principal, asset_id: UUID) -> bool:
    now = datetime.now(timezone.utc)
    return session.query(ContactAssetRelationship.relationship_id).filter(
        ContactAssetRelationship.contact_id == principal.contact_id,
        ContactAssetRelationship.asset_id == asset_id,
        ContactAssetRelationship.relationship_status.in_(("ACTIVE", "UNVERIFIED")),
        or_(ContactAssetRelationship.valid_until.is_(None), ContactAssetRelationship.valid_until > now),
    ).first() is not None


def record_media_owner(session: Session, principal: Principal, media_id: str) -> None:
    session.execute(
        text("INSERT INTO pi_auth.media_ownership(media_id, contact_id) VALUES (:m, :c)"),
        {"m": media_id, "c": principal.contact_id},
    )


def owns_media(session: Session, principal: Principal, media_id: str) -> bool:
    return session.execute(
        text("SELECT 1 FROM pi_auth.media_ownership WHERE media_id = :m AND contact_id = :c"),
        {"m": media_id, "c": principal.contact_id},
    ).first() is not None
