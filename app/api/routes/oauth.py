from urllib.parse import urlencode

import httpx
from authlib.integrations.base_client import OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import FRONTEND_URL, is_allowed_frontend_origin, normalize_url
from app.core.oauth import oauth
from app.core.security import create_access_token
from app.db.session import get_db
from app.services.oauth_service import get_or_create_oauth_user

router = APIRouter(prefix="/auth", tags=["oauth"])


@router.get("/github/login")
async def github_login(request: Request, frontend_origin: str | None = None):
    _store_oauth_frontend_origin(request, frontend_origin)
    redirect_uri = request.url_for("github_callback")
    try:
        return await oauth.github.authorize_redirect(request, redirect_uri)
    except OAuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"GitHub OAuth failed: {exc.error}") from exc


@router.get("/github/callback", name="github_callback")
async def github_callback(request: Request, db: Session = Depends(get_db)):
    try:
        token = await oauth.github.authorize_access_token(request)
        github_user = (await oauth.github.get("user", token=token)).json()
        emails = (await oauth.github.get("user/emails", token=token)).json()
    except (OAuthError, httpx.HTTPError) as exc:
        detail = exc.error if isinstance(exc, OAuthError) else "GitHub OAuth token exchange failed."
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"GitHub OAuth failed: {detail}") from exc

    primary_email = next((item["email"] for item in emails if item.get("primary") and item.get("verified")), None)
    if not primary_email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="GitHub account has no verified primary email.")

    provider_user_id = str(github_user["id"])
    username = github_user.get("login") or github_user.get("name") or primary_email.split("@", maxsplit=1)[0]
    try:
        user = get_or_create_oauth_user(
            db,
            provider="github",
            provider_user_id=provider_user_id,
            email=primary_email,
            username=username,
            avatar_url=github_user.get("avatar_url"),
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not persist GitHub account.") from exc

    return _redirect_with_token(request, create_access_token(str(user.id)))


@router.get("/google/login")
async def google_login(request: Request, frontend_origin: str | None = None):
    _store_oauth_frontend_origin(request, frontend_origin)
    redirect_uri = request.url_for("google_callback")
    try:
        return await oauth.google.authorize_redirect(request, redirect_uri)
    except (OAuthError, httpx.HTTPError) as exc:
        detail = exc.error if isinstance(exc, OAuthError) else "Google OAuth metadata is unavailable."
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Google OAuth failed: {detail}") from exc


@router.get("/google/callback", name="google_callback")
async def google_callback(request: Request, db: Session = Depends(get_db)):
    try:
        token = await oauth.google.authorize_access_token(request)
    except (OAuthError, httpx.HTTPError) as exc:
        detail = exc.error if isinstance(exc, OAuthError) else "Google OAuth token exchange failed."
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Google OAuth failed: {detail}") from exc

    userinfo = token.get("userinfo")
    if userinfo is None:
        userinfo = await oauth.google.parse_id_token(request, token)

    email = userinfo.get("email")
    if not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google account did not return an email.")
    if userinfo.get("email_verified") is not True:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google email is not verified.")

    provider_user_id = str(userinfo["sub"])
    username = userinfo.get("name") or email.split("@", maxsplit=1)[0]
    try:
        user = get_or_create_oauth_user(
            db,
            provider="google",
            provider_user_id=provider_user_id,
            email=email,
            username=username,
            avatar_url=userinfo.get("picture"),
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not persist Google account.") from exc

    return _redirect_with_token(request, create_access_token(str(user.id)))


def _store_oauth_frontend_origin(request: Request, frontend_origin: str | None) -> None:
    origin = frontend_origin if frontend_origin and is_allowed_frontend_origin(frontend_origin) else FRONTEND_URL
    request.session["oauth_frontend_origin"] = normalize_url(origin)


def _get_oauth_frontend_origin(request: Request) -> str:
    origin = request.session.pop("oauth_frontend_origin", None)
    if origin and is_allowed_frontend_origin(origin):
        return normalize_url(origin)
    return normalize_url(FRONTEND_URL)


def _redirect_with_token(request: Request, access_token: str) -> RedirectResponse:
    query = urlencode({"token": access_token})
    frontend_origin = _get_oauth_frontend_origin(request)
    return RedirectResponse(url=f"{frontend_origin}/oauth/callback?{query}")
