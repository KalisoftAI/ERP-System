"""Shared helpers: pagination, audit, generic CRUD service."""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import User
from .models import AuditLog


def paginate(
    db: Session,
    stmt,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
    order_by=None,
) -> dict:
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    if order_by is not None:
        stmt = stmt.order_by(order_by)
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": rows, "total": total, "page": page, "page_size": page_size}


def write_audit(db: Session, user: Optional[User], action: str, entity: str,
                entity_id: Optional[int] = None, details: str = "", ip: str = "",
                changes: dict | None = None, created: int = 0,
                updated: int = 0, failed: int = 0) -> None:
    db.add(AuditLog(
        user_id=user.id if user else None,
        action=action,
        entity=entity,
        entity_id=entity_id,
        details=details[:4000],
        ip=ip,
        changes=json.dumps(changes, cls=JSONEncoder) if changes else "",
        created_count=created,
        updated_count=updated,
        failed_count=failed,
    ))
    db.commit()


def apply_updates(obj: Any, payload: BaseModel, exclude: set[str] | None = None) -> dict:
    """Apply Pydantic fields onto a model instance, ignoring None values.

    Returns the actual old/new field changes so callers can store them on the
    audit trail. Non-mapped objects are fine; only real value changes count.
    """
    changes: dict[str, dict[str, Any]] = {}
    for key, value in payload.model_dump(exclude_unset=True).items():
        if exclude and key in exclude:
            continue
        if value is not None and hasattr(obj, key):
            old = getattr(obj, key)
            if old == value:
                continue
            changes[key] = {"old": old, "new": value}
            setattr(obj, key, value)
    return changes


def get_or_404(db: Session, model, obj_id: int):
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{model.__name__} {obj_id} not found")
    return obj


def parse_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if hasattr(o, "value"):  # enum
            return o.value
        if hasattr(o, "isoformat"):
            return o.isoformat()
        return str(o)