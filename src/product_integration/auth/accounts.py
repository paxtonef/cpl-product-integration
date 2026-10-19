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

Passwords are changed by their owner (current password required) or reset by
the operator command; either way only the PI credential changes: the CPL
Account and Contact keep their ids and status, and every web session of the
account is revoked in the same transaction.

Failed password attempts are throttled per (login, origin), per origin and
per login (pi_auth.login_throttle, digests only). A guessing origin is
stopped after MAX_FAILED_ATTEMPTS on one login without locking that login
from any other origin; an origin trying many logins is stopped after
ORIGIN_MAX_FAILURES; guessing one login from many origins is stopped after
ACCOUNT_MAX_FAILURES. Every lock is temporary (LOCKOUT).

The digests are HMAC-SHA256 with a server secret given at run time
(PI_LOGIN_THROTTLE_SECRET, at least 32 characters; never in the repository,
never logged), so a copy of the table does not let anyone test candidate
logins or addresses. Rotation: the new secret becomes PI_LOGIN_THROTTLE_SECRET
and the former one PI_LOGIN_THROTTLE_SECRET_PREVIOUS for at least
FAILURE_WINDOW + LOCKOUT; locks under the former secret stay in force, counts
are only ever written under the current one, and once the former secret is
withdrawn its counters no longer apply and are purged when their window and
lock are over (purge_expired_sessions). A rotation never locks anyone; it
can at most give one window of extra attempts across the switch.

Residual risk, not accepted by anyone here: guessing one login from many
origins (a distributed attack) still locks that login for every origin after
ACCOUNT_MAX_FAILURES, its owner included, for LOCKOUT.
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

from product_integration import audit
from product_integration.auth.passwords import (
    PasswordPolicyError, burn_verification, check_policy, hash_password, verify_password,
)

AUTH_PROVIDER = "pi-local-password"
_LOGIN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._@+-]{2,127}$")
MAX_FAILED_ATTEMPTS = 5          # per (login, origin)
ORIGIN_MAX_FAILURES = 50         # per origin, any login
ACCOUNT_MAX_FAILURES = 100       # per login, any origin
FAILURE_WINDOW = timedelta(minutes=15)
LOCKOUT = timedelta(minutes=15)

# Only the account-creation command holds this context.
_OPERATOR_AUTHORITY = AuthorityContext(
    granted=frozenset({Authority.CREATE_CONTACT, Authority.ATTACH_ACCOUNT}),
    actor_reference="pi-operator-account-command",
)


class AccountError(Exception):
    pass


class ThrottleSecretMissing(RuntimeError):
    """PI_LOGIN_THROTTLE_SECRET absent or shorter than THROTTLE_SECRET_MIN_LENGTH."""


class PasswordChangeRefused(Exception):
    """Wrong current password, or too many attempts: one answer for both."""


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


# -- throttling --------------------------------------------------------------

THROTTLE_SECRET_ENV = "PI_LOGIN_THROTTLE_SECRET"
THROTTLE_PREVIOUS_SECRET_ENV = "PI_LOGIN_THROTTLE_SECRET_PREVIOUS"
THROTTLE_SECRET_MIN_LENGTH = 32


def throttle_secrets() -> list[bytes]:
    """[current] or [current, former]. Raises ThrottleSecretMissing without a usable current secret."""
    current = os.environ.get(THROTTLE_SECRET_ENV, "")
    if len(current) < THROTTLE_SECRET_MIN_LENGTH:
        raise ThrottleSecretMissing(f"{THROTTLE_SECRET_ENV} must be set (at least {THROTTLE_SECRET_MIN_LENGTH} characters)")
    keys = [current.encode("utf-8")]
    previous = os.environ.get(THROTTLE_PREVIOUS_SECRET_ENV, "")
    if len(previous) >= THROTTLE_SECRET_MIN_LENGTH and previous != current:
        keys.append(previous.encode("utf-8"))
    return keys


def _digest(kind: str, value: str, key: Optional[bytes] = None) -> str:
    return hmac.new(key or throttle_secrets()[0], f"pi-throttle-{kind}:{value}".encode("utf-8"),
                    hashlib.sha256).hexdigest()


def _throttle_keys(login: str, origin: str, key: Optional[bytes] = None) -> list[tuple[str, str, str, int]]:
    """(scope, subject_hash, origin_hash, max failures) for one attempt, under `key` (default: the current secret)."""
    subject, place = _digest("login", login, key), _digest("origin", origin or "unknown", key)
    return [
        ("login_origin", subject, place, MAX_FAILED_ATTEMPTS),
        ("origin", "", place, ORIGIN_MAX_FAILURES),
        ("login", subject, "", ACCOUNT_MAX_FAILURES),
    ]


def _throttled(session, login: str, origin: str, now: datetime) -> bool:
    """A lock under the current secret or, during a rotation, under the former one."""
    for key in throttle_secrets():
        for scope, subject, place, _ in _throttle_keys(login, origin, key):
            locked = session.execute(text(
                "SELECT locked_until FROM pi_auth.login_throttle "
                "WHERE scope = :s AND subject_hash = :h AND origin_hash = :o"
            ), {"s": scope, "h": subject, "o": place}).scalar()
            if locked is not None and locked > now:
                return True
    return False


def _record_failure(session, keys, now: datetime) -> None:
    """Counts one failure on every key; a key reaching its maximum within
    the window is locked for LOCKOUT and starts a new window."""
    for scope, subject, place, maximum in keys:
        failures = session.execute(text(
            "INSERT INTO pi_auth.login_throttle(scope, subject_hash, origin_hash, failures, window_started_at) "
            "VALUES (:s, :h, :o, 1, :t) "
            "ON CONFLICT (scope, subject_hash, origin_hash) DO UPDATE SET "
            "failures = CASE WHEN login_throttle.window_started_at <= :start THEN 1 "
            "ELSE login_throttle.failures + 1 END, "
            "window_started_at = CASE WHEN login_throttle.window_started_at <= :start THEN :t "
            "ELSE login_throttle.window_started_at END "
            "RETURNING failures"
        ), {"s": scope, "h": subject, "o": place, "t": now, "start": now - FAILURE_WINDOW}).scalar()
        if failures >= maximum:
            session.execute(text(
                "UPDATE pi_auth.login_throttle SET failures = 0, window_started_at = :t, locked_until = :u "
                "WHERE scope = :s AND subject_hash = :h AND origin_hash = :o"
            ), {"s": scope, "h": subject, "o": place, "t": now, "u": now + LOCKOUT})


def _clear_failures(session, login: str, origin: str) -> None:
    """A success from an origin clears that origin's failures on this login
    only (never the origin-wide nor the login-wide counters)."""
    for key in throttle_secrets():
        scope, subject, place, _ = _throttle_keys(login, origin, key)[0]
        session.execute(text(
            "DELETE FROM pi_auth.login_throttle WHERE scope = :s AND subject_hash = :h AND origin_hash = :o"
        ), {"s": scope, "h": subject, "o": place})


def authenticate(login: str, password: str, origin: str = "unknown") -> Optional[NewSession]:
    """Returns a new session, or None. The caller answers every None the
    same way (unknown login, wrong password, throttled or disabled account).
    `origin` is the client address as seen by the server; only its digest
    is stored."""
    now = _now()
    throttle_secrets()  # no attempt is examined without the throttling secret
    try:
        login = normalize_login(login)
    except AccountError:
        burn_verification(password)
        with session_scope() as session:
            _record_failure(session, _throttle_keys("", origin)[1:2], now)
            session.commit()
        return None
    keys = _throttle_keys(login, origin)
    with session_scope() as session:
        if _throttled(session, login, origin, now):
            burn_verification(password)
            session.commit()
            return None
        row = session.execute(text(
            "SELECT c.account_id, c.password_hash, a.contact_id, a.account_status "
            "FROM pi_auth.credentials c JOIN cpl.accounts a ON a.account_id = c.account_id "
            "WHERE c.login = :l FOR UPDATE OF c"
        ), {"l": login}).first()
        if row is None:
            burn_verification(password)
            _record_failure(session, keys, now)
            session.commit()
            return None
        if not verify_password(password, row.password_hash):
            _record_failure(session, keys, now)
            session.commit()
            return None
        if row.account_status != "ACTIVE":
            session.commit()
            return None
        token = secrets.token_urlsafe(32)
        expires = min(now + idle_timeout(), now + absolute_lifetime())
        _clear_failures(session, login, origin)
        session.execute(text("UPDATE cpl.accounts SET last_authenticated_at = :t WHERE account_id = :a"),
                        {"t": now, "a": row.account_id})
        session.execute(text(
            "INSERT INTO pi_auth.web_sessions(session_hash, account_id, created_at, last_seen_at, expires_at) "
            "VALUES (:s, :a, :t, :t, :e)"
        ), {"s": _sha256(token), "a": row.account_id, "t": now, "e": expires})
        session.commit()
        return NewSession(token, _csrf_for(token), Principal(row.account_id, row.contact_id, _csrf_for(token)))


# -- password change and reset -------------------------------------------------

def _store_new_password(session, account_id: UUID, password_hash: str) -> None:
    session.execute(text(
        "UPDATE pi_auth.credentials SET password_hash = :h, password_changed_at = now() WHERE account_id = :a"
    ), {"h": password_hash, "a": account_id})


def _revoke_all_sessions(session, account_id: UUID) -> int:
    return session.execute(text("DELETE FROM pi_auth.web_sessions WHERE account_id = :a"),
                           {"a": account_id}).rowcount


def change_password(principal: Principal, current_password: str, new_password: str, origin: str = "unknown") -> None:
    """The signed-in user's own change: current password required (and
    throttled like a sign-in), new one checked against the policy and
    different from the current one, then stored and every session of the
    account revoked, all in one transaction. Only the PI credential changes.
    Raises PasswordChangeRefused or PasswordPolicyError; nothing is changed
    then. No password ever reaches a message or a log."""
    ref = audit.account(principal.account_id)
    try:
        _change_password(principal, current_password, new_password, origin)
    except PasswordChangeRefused:
        audit.record("password_change", "refused", actor=ref, target=ref)
        raise
    except PasswordPolicyError:
        audit.record("password_change", "refused_policy", actor=ref, target=ref)
        raise
    except Exception:
        audit.record("password_change", "failure", actor=ref, target=ref)
        raise
    audit.record("password_change", "success", actor=ref, target=ref)


def _change_password(principal: Principal, current_password: str, new_password: str, origin: str) -> None:
    now = _now()
    with session_scope() as session:
        row = session.execute(text(
            "SELECT login, password_hash FROM pi_auth.credentials WHERE account_id = :a FOR UPDATE"
        ), {"a": principal.account_id}).first()
        if row is None:
            burn_verification(current_password)
            raise PasswordChangeRefused()
        keys = _throttle_keys(row.login, origin)
        if _throttled(session, row.login, origin, now):
            burn_verification(current_password)
            session.commit()
            raise PasswordChangeRefused()
        if not verify_password(current_password, row.password_hash):
            _record_failure(session, keys, now)
            session.commit()
            raise PasswordChangeRefused()
        check_policy(new_password, login=row.login)
        if verify_password(new_password, row.password_hash):
            raise PasswordPolicyError("the new password must differ from the current one")
        _store_new_password(session, principal.account_id, hash_password(new_password))
        _revoke_all_sessions(session, principal.account_id)
        _clear_failures(session, row.login, origin)
        session.commit()


def reset_password(login: str, new_password: str) -> UUID:
    """Operator reset (server command, masked input): new password checked
    against the policy, stored, every session revoked and the login's
    throttling cleared, in one transaction. The CPL Account and Contact are
    untouched. Returns the account id. Every outcome leaves an audit line
    (product_integration.audit), with the account id only."""
    target = audit.UNRESOLVED
    try:
        login = normalize_login(login)
        with session_scope() as session:
            account_id = session.execute(text(
                "SELECT account_id FROM pi_auth.credentials WHERE login = :l FOR UPDATE"
            ), {"l": login}).scalar()
            if account_id is None:
                raise AccountError("unknown login")
            target = audit.account(account_id)
            check_policy(new_password, login=login)
            _store_new_password(session, account_id, hash_password(new_password))
            _revoke_all_sessions(session, account_id)
            for key in throttle_secrets():
                session.execute(text("DELETE FROM pi_auth.login_throttle WHERE subject_hash = :h"),
                                {"h": _digest("login", login, key)})
            session.commit()
    except AccountError:
        audit.record("password_reset", "refused_unknown_login", actor=audit.OPERATOR, target=target)
        raise
    except PasswordPolicyError:
        audit.record("password_reset", "refused_policy", actor=audit.OPERATOR, target=target)
        raise
    except Exception:
        audit.record("password_reset", "failure", actor=audit.OPERATOR, target=target)
        raise
    audit.record("password_reset", "success", actor=audit.OPERATOR, target=target)
    return account_id


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
    """Expired sessions, and throttling rows whose window and lock are over."""
    with session_scope() as session:
        count = session.execute(text("DELETE FROM pi_auth.web_sessions WHERE expires_at <= now()")).rowcount
        session.execute(text(
            "DELETE FROM pi_auth.login_throttle WHERE window_started_at <= :start "
            "AND (locked_until IS NULL OR locked_until <= now())"
        ), {"start": _now() - FAILURE_WINDOW})
        session.commit()
        return count


def display_name(principal: Principal) -> Optional[str]:
    with session_scope() as session:
        return session.execute(
            text("SELECT display_name FROM cpl.contacts WHERE contact_id = :c"), {"c": principal.contact_id},
        ).scalar()
