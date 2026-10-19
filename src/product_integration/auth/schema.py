"""PI-owned storage for end-user credentials, web sessions, media ownership
and sign-in throttling — schema ``pi_auth`` in the same PostgreSQL database
as CPL.

CPL already owns the identity binding (``cpl.accounts``: an Account is a
provider identity bound to a Contact). CPL stores no credential and no web
session, so PI keeps exactly those, plus which Contact uploaded which media
(PI's own media storage, Block B1.5). Nothing in the ``cpl`` schema is
altered; the foreign keys only point at CPL rows.

Forward migration: ``upgrade()``; rollback: ``downgrade()`` (drops the
schema, so every PI credential and session — use only before go-live or
after a backup). Both are idempotent.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

SCHEMA_VERSION = 4

_UPGRADE_V1 = [
    "CREATE SCHEMA IF NOT EXISTS pi_auth",
    """CREATE TABLE IF NOT EXISTS pi_auth.schema_version (
        version integer NOT NULL,
        applied_at timestamptz NOT NULL DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS pi_auth.credentials (
        account_id uuid PRIMARY KEY REFERENCES cpl.accounts(account_id) ON DELETE RESTRICT,
        login text NOT NULL UNIQUE CHECK (login = lower(login) AND length(login) BETWEEN 3 AND 128),
        password_hash text NOT NULL CHECK (password_hash LIKE 'scrypt$%'),
        failed_attempts integer NOT NULL DEFAULT 0,
        locked_until timestamptz NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        password_changed_at timestamptz NOT NULL DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS pi_auth.web_sessions (
        session_hash text PRIMARY KEY,
        account_id uuid NOT NULL REFERENCES pi_auth.credentials(account_id) ON DELETE CASCADE,
        created_at timestamptz NOT NULL DEFAULT now(),
        last_seen_at timestamptz NOT NULL DEFAULT now(),
        expires_at timestamptz NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS web_sessions_account_idx ON pi_auth.web_sessions(account_id)",
    "CREATE INDEX IF NOT EXISTS web_sessions_expiry_idx ON pi_auth.web_sessions(expires_at)",
    """CREATE TABLE IF NOT EXISTS pi_auth.media_ownership (
        media_id text PRIMARY KEY CHECK (media_id ~ '^[0-9a-f]{32}$'),
        contact_id uuid NOT NULL REFERENCES cpl.contacts(contact_id) ON DELETE RESTRICT,
        created_at timestamptz NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS media_ownership_contact_idx ON pi_auth.media_ownership(contact_id)",
]

# Version 2: failed password attempts are counted per (login, origin), per
# origin and per login, each with its own window and lock (see
# product_integration.auth.accounts). Only digests are stored: no login, no
# address (HMAC with a server secret since version 3). The per-account columns of credentials
# (failed_attempts, locked_until) are no longer written.
_UPGRADE_V2 = [
    """CREATE TABLE IF NOT EXISTS pi_auth.login_throttle (
        scope text NOT NULL CHECK (scope IN ('login_origin', 'origin', 'login')),
        subject_hash text NOT NULL,
        origin_hash text NOT NULL,
        failures integer NOT NULL DEFAULT 0,
        window_started_at timestamptz NOT NULL DEFAULT now(),
        locked_until timestamptz NULL,
        PRIMARY KEY (scope, subject_hash, origin_hash)
    )""",
    "CREATE INDEX IF NOT EXISTS login_throttle_subject_idx ON pi_auth.login_throttle(subject_hash)",
]


# Version 3 (bloc 3A): the digests become HMAC-SHA256 with a run-time server
# secret (product_integration.auth.accounts). The former bare SHA-256 counters
# (a copy of them lets anyone test candidate logins and addresses) are dropped;
# counting starts afresh, nobody is locked.
_UPGRADE_V3 = [
    "DELETE FROM pi_auth.login_throttle",
]


# Version 4 (conservation): the trace of each purge operation (policy and
# counts, never a purged value), which identifier copy was emptied by which
# operation, and when a medium's content was purged (the ownership row stays,
# so the reference reads as "no longer kept", never as unknown).
_UPGRADE_V4 = [
    """CREATE TABLE IF NOT EXISTS pi_auth.conservation_operations (
        operation_id uuid PRIMARY KEY,
        started_at timestamptz NOT NULL DEFAULT now(),
        finished_at timestamptz NULL,
        trigger text NOT NULL CHECK (trigger IN ('operator', 'after_restore')),
        policy jsonb NOT NULL,
        counts jsonb NOT NULL DEFAULT '{}'::jsonb,
        outcome text NOT NULL CHECK (outcome IN ('running', 'completed', 'interrupted')),
        error_class text NULL
    )""",
    """CREATE TABLE IF NOT EXISTS pi_auth.identifier_expunctions (
        target_kind text NOT NULL CHECK (target_kind IN ('asset_identity_resolution', 'vehicle_detail')),
        target_id uuid NOT NULL,
        fields text[] NOT NULL,
        anchor_at timestamptz NULL,
        operation_id uuid NOT NULL REFERENCES pi_auth.conservation_operations(operation_id) ON DELETE RESTRICT,
        expunged_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (target_kind, target_id)
    )""",
    "ALTER TABLE pi_auth.media_ownership ADD COLUMN IF NOT EXISTS content_purged_at timestamptz NULL",
    """ALTER TABLE pi_auth.media_ownership ADD COLUMN IF NOT EXISTS purge_operation_id uuid NULL
        REFERENCES pi_auth.conservation_operations(operation_id) ON DELETE RESTRICT""",
]


def current_version(conn: Connection) -> int:
    exists = conn.execute(text("SELECT to_regclass('pi_auth.schema_version')")).scalar()
    if exists is None:
        return 0
    return conn.execute(text("SELECT coalesce(max(version), 0) FROM pi_auth.schema_version")).scalar()


def upgrade(conn: Connection) -> int:
    if conn.execute(text("SELECT to_regclass('cpl.accounts')")).scalar() is None:
        raise RuntimeError("CPL schema missing: run the CPL migrations (alembic upgrade head) first")
    if current_version(conn) < 1:
        for statement in _UPGRADE_V1:
            conn.execute(text(statement))
        conn.execute(text("INSERT INTO pi_auth.schema_version(version) VALUES (1)"))
    if current_version(conn) < 2:
        for statement in _UPGRADE_V2:
            conn.execute(text(statement))
        conn.execute(text("INSERT INTO pi_auth.schema_version(version) VALUES (2)"))
    if current_version(conn) < 3:
        for statement in _UPGRADE_V3:
            conn.execute(text(statement))
        conn.execute(text("INSERT INTO pi_auth.schema_version(version) VALUES (3)"))
    if current_version(conn) < 4:
        for statement in _UPGRADE_V4:
            conn.execute(text(statement))
        conn.execute(text("INSERT INTO pi_auth.schema_version(version) VALUES (4)"))
    return current_version(conn)


def downgrade(conn: Connection) -> int:
    conn.execute(text("DROP SCHEMA IF EXISTS pi_auth CASCADE"))
    return 0
