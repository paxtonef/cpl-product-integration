"""Password hashing for PI end-user accounts (standard library scrypt).

Stored format: ``scrypt$<n>$<r>$<p>$<salt b64>$<hash b64>``. No default
password exists anywhere; a password is only ever set by its owner through
the account-creation command (masked input).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

_N, _R, _P, _DKLEN = 2**15, 8, 1, 32
_MAXMEM = 64 * 1024 * 1024

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 1024


class PasswordPolicyError(ValueError):
    pass


def check_policy(password: str, *, login: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"password must contain at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError("password is too long")
    if password.strip().lower() == login.strip().lower():
        raise PasswordPolicyError("password must differ from the login")


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=_DKLEN, maxmem=_MAXMEM)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = _derive(password, salt, _N, _R, _P)
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return f"scrypt${_N}${_R}${_P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = _derive(password, base64.b64decode(salt), int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# Verified against when the login is unknown, so an unknown login and a wrong
# password cost the same time.
_DUMMY_HASH = hash_password(base64.b64encode(os.urandom(18)).decode("ascii"))


def burn_verification(password: str) -> None:
    verify_password(password, _DUMMY_HASH)
