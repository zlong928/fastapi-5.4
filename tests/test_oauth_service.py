from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models import OAuthAccount, User
from app.services.oauth_service import get_or_create_oauth_user


def make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    return session_factory()


def test_get_or_create_oauth_user_creates_user_and_account():
    db = make_session()

    user = get_or_create_oauth_user(
        db,
        provider="github",
        provider_user_id="123",
        email="new@example.com",
        username="new-user",
    )

    assert user.id is not None
    assert user.email == "new@example.com"
    assert user.hashed_password is None
    account = db.query(OAuthAccount).one()
    assert account.user_id == user.id
    assert account.provider == "github"


def test_get_or_create_oauth_user_binds_existing_email_user():
    db = make_session()
    existing = User(email="existing@example.com", username="existing", hashed_password="hash")
    db.add(existing)
    db.commit()

    user = get_or_create_oauth_user(
        db,
        provider="google",
        provider_user_id="abc",
        email="existing@example.com",
        username="google-name",
    )

    assert user.id == existing.id
    assert db.query(User).count() == 1
    assert db.query(OAuthAccount).count() == 1


def test_get_or_create_oauth_user_reuses_existing_oauth_account():
    db = make_session()
    first = get_or_create_oauth_user(
        db,
        provider="github",
        provider_user_id="same",
        email="same@example.com",
        username="same",
    )

    second = get_or_create_oauth_user(
        db,
        provider="github",
        provider_user_id="same",
        email="other@example.com",
        username="other",
    )

    assert second.id == first.id
    assert db.query(User).count() == 1
    assert db.query(OAuthAccount).count() == 1
