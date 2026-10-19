"""Password audit lines (bloc 3A, point 3).

One line per password change by its owner and per operator reset, success and
failure, on standard error through this module's own handler -- uvicorn
configures only its own loggers, so a record left to the root logger is
dropped under the production launch:

  <time> product_integration.audit INFO audit date=<UTC> operation=<op> result=<result> actor=<ref> target=<ref>

``actor`` and ``target`` are opaque: ``account:<CPL account id>``, the fixed
label ``operator`` for the server command, or ``-`` when no account was
resolved. ``operation`` and ``result`` come from fixed sets. Never a
password, a token, a cookie, a login or an address.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from product_integration.stderr_log import stderr_logger

logger = stderr_logger("product_integration.audit")

OPERATOR = "operator"
UNRESOLVED = "-"
OPERATIONS = frozenset({"password_change", "password_reset"})
RESULTS = frozenset({"success", "refused", "refused_policy", "refused_unknown_login", "refused_input", "failure"})


def account(account_id: Optional[UUID]) -> str:
    return f"account:{account_id}" if account_id is not None else UNRESOLVED


def record(operation: str, result: str, *, actor: str, target: str) -> None:
    if operation not in OPERATIONS or result not in RESULTS:
        raise ValueError("audit operation and result come from fixed sets")
    date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.info("audit date=%s operation=%s result=%s actor=%s target=%s", date, operation, result, actor, target)
