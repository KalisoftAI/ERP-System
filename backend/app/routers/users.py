"""User management (admin only)."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import AdminUser, hash_password, require_roles
from ..crud import apply_updates, get_or_404, write_audit
from ..database import get_db
from ..models import User, UserRole
from ..schemas import UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=dict)
def list_users(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles(UserRole.admin, UserRole.manager))],
    search: str = "",
    role: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    stmt = select(User)
    if search:
        stmt = stmt.where(User.username.ilike(f"%{search}%") | User.full_name.ilike(f"%{search}%"))
    if role:
        stmt = stmt.where(User.role == role)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(User.id).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [UserOut.model_validate(u).model_dump() for u in rows],
            "total": total, "page": page, "page_size": page_size}


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, db: Annotated[Session, Depends(get_db)],
                admin: AdminUser):
    if db.query(User).filter((User.username == body.username) | (User.email == body.email)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Username or email already exists")
    user = User(username=body.username, email=body.email, full_name=body.full_name,
                role=body.role, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    write_audit(db, admin, "CREATE", "users", user.id, f"Created user {user.username}")
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, db: Annotated[Session, Depends(get_db)],
                admin: AdminUser):
    user = get_or_404(db, User, user_id)
    data = body.model_dump(exclude_unset=True)
    changes = {}
    if data.get("email") is not None:
        duplicate = db.scalar(select(User.id).where(
            User.email == data["email"], User.id != user_id).limit(1))
        if duplicate:
            raise HTTPException(status.HTTP_409_CONFLICT, "Email already exists")
    if "password" in data and data["password"]:
        user.password_hash = hash_password(data.pop("password"))
        changes["password"] = {"old": "********", "new": "********"}
    if "role" in data and admin.role != UserRole.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can change roles")
    for k, v in data.items():
        if v is not None:
            old = getattr(user, k)
            if old != v:
                changes[k] = {"old": old, "new": v}
            setattr(user, k, v)
    db.commit()
    db.refresh(user)
    write_audit(db, admin, "UPDATE", "users", user.id, f"Updated user {user.username}",
                changes=changes)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, db: Annotated[Session, Depends(get_db)],
                admin: AdminUser):
    user = get_or_404(db, User, user_id)
    if user.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot delete your own account")
    db.delete(user)
    db.commit()
    write_audit(db, admin, "DELETE", "users", user_id, f"Deleted user {user.username}")