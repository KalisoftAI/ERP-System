"""Salespeople master (read + list for dropdowns)."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import CurrentUser, ManagerOrAdmin
from ..crud import get_or_404, write_audit
from ..database import get_db
from ..models import Salesperson
from ..schemas import CustomerOut

router = APIRouter(prefix="/salespersons", tags=["salespersons"])


@router.get("", response_model=dict)
def list_salespersons(
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
    search: str = "",
):
    stmt = select(Salesperson).order_by(Salesperson.name)
    if search:
        stmt = stmt.where(Salesperson.name.ilike(f"%{search}%"))
    rows = db.scalars(stmt).all()
    return {"items": [{"id": s.id, "name": s.name, "is_active": s.is_active} for s in rows],
            "total": len(rows)}


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_salesperson(name: str, db: Annotated[Session, Depends(get_db)],
                       user: ManagerOrAdmin):
    if db.scalar(select(Salesperson).where(Salesperson.name == name)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Salesperson already exists")
    s = Salesperson(name=name)
    db.add(s)
    db.commit()
    db.refresh(s)
    write_audit(db, user, "CREATE", "salespersons", s.id, f"Salesperson {s.name}")
    return {"id": s.id, "name": s.name}
