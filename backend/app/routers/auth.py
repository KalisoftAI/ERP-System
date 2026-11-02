"""Authentication endpoints."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..auth import create_access_token, get_current_user, hash_password, verify_password
from ..config import settings
from ..database import get_db
from ..models import User
from ..schemas import LoginRequest, TokenOut, UserOut
from ..crud import write_audit

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
def login(body: LoginRequest, db: Annotated[Session, Depends(get_db)]):
    user = db.query(User).filter(User.username == body.username).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is disabled")
    write_audit(db, user, "LOGIN", "auth", None, f"User {user.username} logged in")
    return TokenOut(
        access_token=create_access_token(user),
        user=UserOut.model_validate(user),
        expires_in=settings.JWT_EXPIRE_MINUTES * 60,
        inactivity_seconds=settings.SESSION_INACTIVITY_MINUTES * 60,
    )


@router.post("/logout")
def logout(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Explicit logout.

    Access tokens are stateless JWTs, so the client discards its token; this
    endpoint records the event for auditing and is the hook for any future
    server-side token revocation. Only the caller's own session is ended.
    """
    write_audit(db, user, "LOGOUT", "auth", None, f"User {user.username} logged out")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: Annotated[User, Depends(get_current_user)]):
    return user


@router.post("/change-password")
def change_password(
    body: dict,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    old = body.get("old_password", "")
    new = body.get("new_password", "")
    if not verify_password(old, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    if len(new) < 6:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "New password too short")
    user.password_hash = hash_password(new)
    db.commit()
    write_audit(db, user, "CHANGE_PASSWORD", "users", user.id)
    return {"ok": True}