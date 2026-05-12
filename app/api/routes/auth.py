import hmac
import secrets
from hashlib import sha256

import redis
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import JWT_SECRET_KEY, REDIS_URL
from app.core.security import create_access_token, get_password_hash, verify_password
from app.db.session import get_db
from app.models import User
from app.schemas.auth import LoginRequest, MessageResponse, PasswordForgotRequest, PasswordResetRequest, RegisterRequest, TokenResponse, UserRead
from app.services.mail_service import send_password_reset_code_email

router = APIRouter(prefix="/auth", tags=["auth"])
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)

PASSWORD_RESET_MESSAGE = "If the email exists, a verification code has been sent."
INVALID_RESET_CODE_MESSAGE = "Invalid or expired verification code"
PASSWORD_RESET_TTL_SECONDS = 5 * 60
PASSWORD_RESET_COOLDOWN_SECONDS = 60


def to_user_read(user: User) -> UserRead:
    return UserRead(
        id=user.id,
        email=user.email,
        username=user.username,
        created_at=user.created_at.isoformat(),
    )


def normalize_email(email: str) -> str:
    return email.lower().strip()


def hash_reset_code(email: str, code: str) -> str:
    return hmac.new(JWT_SECRET_KEY.encode("utf-8"), f"{email}:{code}".encode("utf-8"), sha256).hexdigest()


def is_valid_new_password(password: str) -> bool:
    return len(password) >= 8 and any(character.isalpha() for character in password) and any(character.isdigit() for character in password)


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> UserRead:
    email = normalize_email(payload.email)
    username = payload.username.strip()
    existing = db.scalar(select(User).where((User.email == email) | (User.username == username)))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email or username already exists.")
    user = User(email=email, username=username, hashed_password=get_password_hash(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return to_user_read(user)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    # 邮箱正规化（统一处理）
    normalized_email = normalize_email(payload.email)
    
    # 查询用户
    user = db.scalar(select(User).where(User.email == normalized_email))
    
    # 统一的错误消息（防止邮箱枚举攻击）
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")
    
    # 检查用户是否被禁用
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")
    
    # 检查密码是否已设置
    if user.hashed_password is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")
    
    # 验证密码
    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")
    
    # 生成 token
    return TokenResponse(access_token=create_access_token(str(user.id)))


@router.post("/password/forgot", response_model=MessageResponse)
def forgot_password(payload: PasswordForgotRequest, db: Session = Depends(get_db)) -> MessageResponse:
    email = normalize_email(payload.email)
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        return MessageResponse(message=PASSWORD_RESET_MESSAGE)

    cooldown_key = f"password_reset_cooldown:{email}"
    if redis_client.get(cooldown_key):
        return MessageResponse(message=PASSWORD_RESET_MESSAGE)

    code = f"{secrets.randbelow(1_000_000):06d}"
    redis_client.setex(f"password_reset:{email}", PASSWORD_RESET_TTL_SECONDS, hash_reset_code(email, code))
    redis_client.setex(cooldown_key, PASSWORD_RESET_COOLDOWN_SECONDS, "1")
    send_password_reset_code_email(email, code)
    return MessageResponse(message=PASSWORD_RESET_MESSAGE)


@router.post("/password/reset", response_model=MessageResponse)
def reset_password(payload: PasswordResetRequest, db: Session = Depends(get_db)) -> MessageResponse:
    email = normalize_email(payload.email)
    stored_code_hash = redis_client.get(f"password_reset:{email}")
    if stored_code_hash is None or not hmac.compare_digest(stored_code_hash, hash_reset_code(email, payload.code)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=INVALID_RESET_CODE_MESSAGE)

    if not is_valid_new_password(payload.new_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must be at least 8 characters and include letters and numbers.")

    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=INVALID_RESET_CODE_MESSAGE)

    # 生成新的密码哈希
    new_hashed_password = get_password_hash(payload.new_password)
    
    # 验证哈希值是否有效（防止哈希生成失败）
    if not new_hashed_password or len(new_hashed_password) < 20:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to hash password.")
    
    # 更新密码
    user.hashed_password = new_hashed_password
    db.add(user)
    db.commit()
    
    # 确保数据被持久化（关键修复）
    db.refresh(user)
    
    # 删除重置码
    redis_client.delete(f"password_reset:{email}")
    
    return MessageResponse(message="Password reset successfully.")


@router.get("/me", response_model=UserRead)
def me(current_user: User = Depends(get_current_user)) -> UserRead:
    return to_user_read(current_user)
