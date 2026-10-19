"""PI-05 — end-user login, logout and session routes.

The session token travels only in an HttpOnly, Secure, SameSite=Strict
cookie; JavaScript only ever sees the CSRF token derived from it. Every
failed login gets the same answer (unknown login, wrong password, locked
or disabled account). PI_COOKIE_SECURE=0 drops the Secure flag, for a
plain-http loopback test only.
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
from product_integration.auth.accounts import Principal

router = APIRouter()


class LoginRequest(BaseModel):
    login: str = Field(max_length=256)
    password: str = Field(max_length=1024)


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


@router.post("/auth/login", response_model=SessionResponse)
def login_route(body: LoginRequest, response: Response):
    response.headers["Cache-Control"] = "no-store"
    new_session = accounts.authenticate(body.login, body.password)
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
    response.delete_cookie(SESSION_COOKIE, path="/", secure=_cookie_secure(), httponly=True, samesite="strict")
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
