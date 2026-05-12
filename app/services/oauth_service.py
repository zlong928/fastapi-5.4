from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import OAuthAccount, User


def get_or_create_oauth_user(
    db: Session,
    provider: str,
    provider_user_id: str,
    email: str,
    username: str,
    avatar_url: str | None = None,
) -> User:
    del avatar_url
    normalized_email = email.lower()
    normalized_username = _clean_username(username) or normalized_email.split("@", maxsplit=1)[0]

    account = db.scalar(
        select(OAuthAccount).where(
            OAuthAccount.provider == provider,
            OAuthAccount.provider_user_id == provider_user_id,
        )
    )
    if account:
        return account.user

    user = db.scalar(select(User).where(User.email == normalized_email))
    if user is None:
        user = User(
            email=normalized_email,
            username=_unique_username(db, normalized_username),
            hashed_password=None,
            is_active=True,
        )
        db.add(user)
        db.flush()

    account = OAuthAccount(
        user_id=user.id,
        provider=provider,
        provider_user_id=provider_user_id,
        provider_email=normalized_email,
    )
    db.add(account)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(OAuthAccount).where(
                OAuthAccount.provider == provider,
                OAuthAccount.provider_user_id == provider_user_id,
            )
        )
        if existing:
            return existing.user
        raise
    db.refresh(user)
    return user


def _clean_username(value: str) -> str:
    return "".join(character for character in value.strip() if character.isalnum() or character in {"_", "-"}).strip("_-")[:80]


def _unique_username(db: Session, base_username: str) -> str:
    candidate = base_username[:80] or "user"
    index = 1
    while db.scalar(select(User).where(User.username == candidate)):
        suffix = f"-{index}"
        candidate = f"{base_username[: 80 - len(suffix)]}{suffix}"
        index += 1
    return candidate
