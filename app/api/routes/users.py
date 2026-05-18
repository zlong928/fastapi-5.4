from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.api.routes.auth import to_user_read
from app.models import User
from app.schemas.auth import UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead)
def get_me(current_user: User = Depends(get_current_user)) -> UserRead:
    return to_user_read(current_user)
