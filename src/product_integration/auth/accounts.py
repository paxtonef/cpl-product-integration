"""End-user accounts and server-side web sessions.

An end user is a CPL Contact with a CPL Account (``auth_provider`` =
``pi-local-password``, ``provider_subject_id`` = an opaque random value), plus
a PI credential row. Account creation goes through CPL's own primitives
(``create_contact``, ``attach_account``) under an operator authority that
exists only in the account-creation command, never in a web request.

Sessions are random 256-bit tokens; only their SHA-256 is stored. The
CSRF token of a session is derived from its session token (it cannot be
computed without the HttpOnly cookie), so it can be served again after a
page reload without being stored. Expiry: an idle timeout and an absolute
lifetime, both enforced server-side.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import text

from app.cpl.identity.accounts import attach_account
from app.cpl.identity.authority import Authority, AuthorityContext
from app.cpl.identity.contacts import create_contact
from app.cpl.identity.outcomes import OperationOutcome
from app.db.engine import session_scope

from product_integration.auth.passwords import burn_verification, check_policy, hash_password, verify_password

AUTH_PROVIDER = "pi-local-password"
_LOGIN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._@+-]{2,127}$")
MAX_FAILED_ATTEMPTS = 5
LOCKOUT = timedelta(minutes=15)

# Only the account-creation command holds this context.
_OPERATOR_AUTHORITY = AuthorityContext(
    granted=frozenset({Authority.CREATE_CONTACT, Authority.ATTACH_ACCOUNT}),
    actor_reference="pi-operator-account-command",
)


class AccountError(Exception):
    pass


@dataclass(frozen=True)
class Principal:
    """The authenticated end user, as fixed by the server for one request."""
    account_id: UUID
    contact_id: UUID
    csrf_token: str

    @property
    def actor_reference(self) -> str:
        return f"pi-account:{self.account_id}"


@dataclass(frozen=True)
class NewSession:
    token: str
    csrf_token: str
    principal: Principal


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _csrf_for(token: str) -> str:
    return hashlib.sha256(b"pi-csrf-v1:" + token.encode("utf-8")).hexdigest()


def idle_timeout() -> timedelta:
    return timedelta(minutes=int(os.environ.get("PI_SESSION_IDLE_MINUTES", "30")))


def absolute_lifetime() -> timedelta:
    return timedelta(hours=int(os.environ.get("PI_SESSION_MAX_HOURS", "12")))


def normalize_login(login: str) -> str:
    normalized = login.strip().lower()
    if not _LOGIN_PATTERN.match(normalized):
        raise AccountError("login must be 3-128 characters: letters, digits and . _ @ + -")
    return normalized


def create_account(login: str, password: str, *, display_name: Optional[str] = None) -> UUID:
    """Creates Contact + Account (CPL) and the credential (PI) in one
    transaction. Returns the account id."""
    login = normalize_login(login)
    check_policy(password, login=login)
    password_hash = hash_password(password)
    with session_scope() as session:
        taken = session.execute(text("SELECT 1 FROM pi_auth.credentials WHERE login = :l"), {"l": login}).first()
        if taken:
            raise AccountError("this login already exists")
        contact = create_contact(
            session, contact_type="PERSON", display_name=display_name, authority=_OPERATOR_AUTHORITY,
            idempotency_key=f"pi-account-contact-{uuid.uuid4()}",
        )
        if contact.outcome != OperationOutcome.SUCCESS:
            session.rollback()
            raise AccountError(f"contact creation failed ({contact.outcome})")
        account = attach_account(
            session, contact_id=contact.object_id, auth_provider=AUTH_PROVIDER,
            provider_subject_id=secrets.token_hex(16), authority=_OPERATOR_AUTHORITY,
        )
        if account.outcome != OperationOutcome.SUCCESS:
            session.rollback()
            raise AccountError(f"account creation failed ({account.outcome})")
        session.execute(
            text("INSERT INTO pi_auth.credentials(account_id, login, password_hash) VALUES (:a, :l, :h)"),
            {"a": account.object_id, "l": login, "h": password_hash},
        )
        session.commit()
        return account.object_id


def set_account_status(login: str, status: str) -> None:
    """DISABLED/ACTIVE through CPL's own account status; sessions dropped."""
    if status not in ("ACTIVE", "DISABLED"):
        raise AccountError("status must be ACTIVE or DISABLED")
    with session_scope() as session:
        row = session.execute(
            text("SELECT account_id FROM pi_auth.credentials WHERE login = :l"), {"l": normalize_login(login)},
        ).first()
        if row is None:
            raise AccountError("unknown login")
        session.execute(
            text("UPDATE cpl.accounts SET account_status = :s, disabled_at = CASE WHEN :s = 'DISABLED' THEN now() END "
                 "WHERE account_id = :a"),
            {"s": status, "a": row.account_id},
        )
        session.execute(text("DELETE FROM pi_auth.web_sessions WHERE account_id = :a"), {"a": row.account_id})
        session.commit()


def authenticate(login: str, password: str) -> Optional[NewSession]:
    """Returns a new session, or None. The caller answers every None the
    same way (unknown login, wrong password, locked or disabled account)."""
    try:
        login = normalize_login(login)
    except AccountError:
        burn_verification(password)
        return None
    now = _now()
    with session_scope() as session:
        row = session.execute(text(
            "SELECT c.account_id, c.password_hash, c.failed_attempts, c.locked_until, a.contact_id, a.account_status "
            "FROM pi_auth.credentials c JOIN cpl.accounts a ON a.account_id = c.account_id "
            "WHERE c.login = :l FOR UPDATE OF c"
        ), {"l": login}).first()
        if row is None:
            burn_verification(password)
            return None
        if row.locked_until is not None and row.locked_until > now:
            burn_verification(password)
            return None
        if not verify_password(password, row.password_hash):
            attempts = row.failed_attempts + 1
            session.execute(text(
                "UPDATE pi_auth.credentials SET failed_attempts = :n, locked_until = :u WHERE account_id = :a"
            ), {"n": 0 if attempts >= MAX_FAILED_ATTEMPTS else attempts,
                "u": now + LOCKOUT if attempts >= MAX_FAILED_ATTEMPTS else None, "a": row.account_id})
            session.commit()
            return None
        if row.account_status != "ACTIVE":
            session.commit()
            return None
        token = secrets.token_urlsafe(32)
        expires = min(now + idle_timeout(), now + absolute_lifetime())
        session.execute(text(
            "UPDATE pi_auth.credentials SET failed_attempts = 0, locked_until = NULL WHERE account_id = :a"
        ), {"a": row.account_id})
        session.execute(text("UPDATE cpl.accounts SET last_authenticated_at = :t WHERE account_id = :a"),
                        {"t": now, "a": row.account_id})
        session.execute(text(
            "INSERT INTO pi_auth.web_sessions(session_hash, account_id, created_at, last_seen_at, expires_at) "
            "VALUES (:s, :a, :t, :t, :e)"
        ), {"s": _sha256(token), "a": row.account_id, "t": now, "e": expires})
        session.commit()
        return NewSession(token, _csrf_for(token), Principal(row.account_id, row.contact_id, _csrf_for(token)))


def resolve_session(token: Optional[str]) -> Optional[Principal]:
    """Valid, unexpired session of an ACTIVE account -> Principal (and the
    idle deadline slides, never past the absolute lifetime)."""
    if not token or len(token) > 256:
        return None
    now = _now()
    with session_scope() as session:
        row = session.execute(text(
            "SELECT s.session_hash, s.account_id, s.created_at, s.expires_at, a.contact_id, a.account_status "
            "FROM pi_auth.web_sessions s JOIN cpl.accounts a ON a.account_id = s.account_id "
            "WHERE s.session_hash = :s"
        ), {"s": _sha256(token)}).first()
        if row is None:
            return None
        if row.expires_at <= now or row.account_status != "ACTIVE":
            session.execute(text("DELETE FROM pi_auth.web_sessions WHERE session_hash = :s"), {"s": row.session_hash})
            session.commit()
            return None
        session.execute(text(
            "UPDATE pi_auth.web_sessions SET last_seen_at = :t, expires_at = :e WHERE session_hash = :s"
        ), {"t": now, "e": min(now + idle_timeout(), row.created_at + absolute_lifetime()), "s": row.session_hash})
        session.commit()
        return Principal(row.account_id, row.contact_id, _csrf_for(token))


def csrf_matches(principal: Principal, presented: Optional[str]) -> bool:
    return bool(presented) and hmac.compare_digest(presented.encode("utf-8"), principal.csrf_token.encode("utf-8"))


def end_session(token: Optional[str]) -> None:
    if not token:
        return
    with session_scope() as session:
        session.execute(text("DELETE FROM pi_auth.web_sessions WHERE session_hash = :s"), {"s": _sha256(token)})
        session.commit()


def purge_expired_sessions() -> int:
    with session_scope() as session:
        count = session.execute(text("DELETE FROM pi_auth.web_sessions WHERE expires_at <= now()")).rowcount
        session.commit()
        return count


def display_name(principal: Principal) -> Optional[str]:
    with session_scope() as session:
        return session.execute(
            text("SELECT display_name FROM cpl.contacts WHERE contact_id = :c"), {"c": principal.contact_id},
        ).scalar()
