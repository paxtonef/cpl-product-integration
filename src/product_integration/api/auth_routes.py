"""PI-05 — end-user login, logout, session and password-change routes.

The session token travels only in an HttpOnly, Secure, SameSite=Strict
cookie; JavaScript only ever sees the CSRF token derived from it. Every
failed login gets the same answer (unknown login, wrong password, throttled
or disabled account). PI_COOKIE_SECURE=0 drops the Secure flag, for a
plain-http loopback test only.

The origin used for throttling is the client address the server sees
(request.client); behind a TLS proxy, uvicorn's --proxy-headers with
--forwarded-allow-ips set to that proxy gives the real client address.
"""
from __future__ import annotations

import os
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from product_integration.api.deps import SESSION_COOKIE, get_principal
from product_integration.api.errors import ProductAPIError, ProductAPIErrorCategory
from product_integration.auth import accounts
from product_integration.auth.accounts import PasswordChangeRefused, Principal
from product_integration.auth.passwords import MAX_PASSWORD_LENGTH, PasswordPolicyError

router = APIRouter()


class LoginRequest(BaseModel):
    login: str = Field(max_length=256)
    password: str = Field(max_length=1024)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(max_length=MAX_PASSWORD_LENGTH)
    new_password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class SessionResponse(BaseModel):
    account_id: UUID
    contact_id: UUID
    csrf_token: str


class MeResponse(BaseModel):
    account_id: UUID
    contact_id: UUID
    display_name: Optional[str] = None


def _cookie_secure() -> bool:
    return os.environ.get("PI_COOKIE_SECURE", "1") != "0"


def _origin(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _drop_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=_cookie_secure(), httponly=True, samesite="strict")


@router.post("/auth/login", response_model=SessionResponse)
def login_route(body: LoginRequest, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    new_session = accounts.authenticate(body.login, body.password, _origin(request))
    if new_session is None:
        raise ProductAPIError(ProductAPIErrorCategory.AUTHENTICATION_REQUIRED, "invalid login or password")
    response.set_cookie(
        SESSION_COOKIE, new_session.token, max_age=int(accounts.absolute_lifetime().total_seconds()),
        path="/", secure=_cookie_secure(), httponly=True, samesite="strict",
    )
    principal = new_session.principal
    return SessionResponse(account_id=principal.account_id, contact_id=principal.contact_id, csrf_token=new_session.csrf_token)


@router.post("/auth/logout", status_code=204)
def logout_route(request: Request, principal: Principal = Depends(get_principal)):
    accounts.end_session(request.cookies.get(SESSION_COOKIE))
    response = Response(status_code=204)
    _drop_cookie(response)
    return response


@router.post("/auth/password", status_code=204)
def change_password_route(body: PasswordChangeRequest, request: Request, principal: Principal = Depends(get_principal)):
    """The signed-in user's own change (session + CSRF required, current
    password required). On success every session of the account, this one
    included, is revoked: the user signs in again with the new password."""
    try:
        accounts.change_password(principal, body.current_password, body.new_password, _origin(request))
    except PasswordChangeRefused:
        raise ProductAPIError(
            ProductAPIErrorCategory.PASSWORD_CHANGE_REFUSED,
            "current password incorrect, or too many attempts: try again later",
        ) from None
    except PasswordPolicyError as exc:
        raise ProductAPIError(ProductAPIErrorCategory.PASSWORD_POLICY, str(exc)) from None
    response = Response(status_code=204)
    response.headers["Cache-Control"] = "no-store"
    _drop_cookie(response)
    return response


@router.get("/auth/session", response_model=SessionResponse)
def session_route(response: Response, principal: Principal = Depends(get_principal)):
    """Lets the page recover its CSRF token after a reload."""
    response.headers["Cache-Control"] = "no-store"
    return SessionResponse(account_id=principal.account_id, contact_id=principal.contact_id, csrf_token=principal.csrf_token)


@router.get("/me", response_model=MeResponse)
def me_route(principal: Principal = Depends(get_principal)):
    return MeResponse(account_id=principal.account_id, contact_id=principal.contact_id,
                      display_name=accounts.display_name(principal))
