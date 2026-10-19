"""Operator command for PI accounts (run on the server, never over the web).

  python -m product_integration.auth.cli migrate
  python -m product_integration.auth.cli create-account --login alice [--display-name "Alice"]
        password typed twice with masked input; --password-stdin reads one
        line from standard input instead (for scripted provisioning)
  python -m product_integration.auth.cli reset-password --login alice
        new password typed twice with masked input (or --password-stdin);
        every session of the account is revoked; Account and Contact unchanged
  python -m product_integration.auth.cli disable-account --login alice
  python -m product_integration.auth.cli enable-account --login alice
  python -m product_integration.auth.cli purge-sessions
  python -m product_integration.auth.cli downgrade --confirm-drop-pi-auth

No password is ever printed, logged or accepted as a command-line argument.
Every reset, success or failure, leaves one audit line on standard error
(product_integration.audit: date, operation, result, actor ``operator``,
target account id or ``-``; never a password nor a login).
"""
from __future__ import annotations

import argparse
import getpass
import sys

from app.db.engine import engine

from product_integration import audit
from product_integration.auth import accounts, schema
from product_integration.auth.passwords import PasswordPolicyError


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        password = sys.stdin.readline().rstrip("\n")
        if not password:
            raise accounts.AccountError("no password on standard input")
        return password
    first = getpass.getpass("Password: ")
    second = getpass.getpass("Password (again): ")
    if first != second:
        raise accounts.AccountError("the two passwords differ")
    return first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="product_integration.auth.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    down = sub.add_parser("downgrade")
    down.add_argument("--confirm-drop-pi-auth", action="store_true", required=True)
    create = sub.add_parser("create-account")
    create.add_argument("--login", required=True)
    create.add_argument("--display-name")
    create.add_argument("--password-stdin", action="store_true")
    reset = sub.add_parser("reset-password")
    reset.add_argument("--login", required=True)
    reset.add_argument("--password-stdin", action="store_true")
    for name in ("disable-account", "enable-account"):
        sub.add_parser(name).add_argument("--login", required=True)
    sub.add_parser("purge-sessions")
    args = parser.parse_args(argv)

    try:
        if args.command == "migrate":
            with engine.begin() as conn:
                print(f"pi_auth schema version {schema.upgrade(conn)}")
        elif args.command == "downgrade":
            with engine.begin() as conn:
                schema.downgrade(conn)
            print("pi_auth schema dropped")
        elif args.command == "create-account":
            password = _read_password(args.password_stdin)
            account_id = accounts.create_account(args.login, password, display_name=args.display_name)
            print(f"account created: {account_id}")
        elif args.command == "reset-password":
            try:
                password = _read_password(args.password_stdin)
            except accounts.AccountError:
                audit.record("password_reset", "refused_input", actor=audit.OPERATOR, target=audit.UNRESOLVED)
                raise
            account_id = accounts.reset_password(args.login, password)
            print(f"password reset, sessions revoked: {account_id}")
        elif args.command in ("disable-account", "enable-account"):
            accounts.set_account_status(args.login, "DISABLED" if args.command == "disable-account" else "ACTIVE")
            print("account status updated")
        elif args.command == "purge-sessions":
            print(f"expired sessions removed: {accounts.purge_expired_sessions()}")
    except (accounts.AccountError, PasswordPolicyError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
