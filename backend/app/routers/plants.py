"""Plant / location management (CRUD)."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import CurrentUser, ManagerOrAdmin
from ..crud import apply_updates, get_or_404, write_audit
from ..database import get_db
from ..models import Customer, Dispatch, Inventory, Plant, StockMovement
from ..schemas import PlantCreate, PlantOut, PlantUpdate

router = APIRouter(prefix="/plants", tags=["plants"])


@router.get("", response_model=dict)
def list_plants(
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
    search: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
):
    stmt = select(Plant)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(Plant.name.ilike(like), Plant.code.ilike(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Plant.name).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [PlantOut.model_validate(p).model_dump() for p in rows],
            "total": total, "page": page, "page_size": page_size}


@router.post("", response_model=PlantOut, status_code=status.HTTP_201_CREATED)
def create_plant(body: PlantCreate, db: Annotated[Session, Depends(get_db)],
                 user: ManagerOrAdmin):
    p = Plant(**body.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    write_audit(db, user, "CREATE", "plants", p.id, f"Created plant {p.name}")
    return p


@router.patch("/{plant_id}", response_model=PlantOut)
def update_plant(plant_id: int, body: PlantUpdate, db: Annotated[Session, Depends(get_db)],
                 user: ManagerOrAdmin):
    p = get_or_404(db, Plant, plant_id)
    changes = apply_updates(p, body)
    db.commit()
    db.refresh(p)
    write_audit(db, user, "UPDATE", "plants", p.id, f"Updated plant {p.name}",
                changes=changes)
    return p


@router.delete("/{plant_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_plant(plant_id: int, db: Annotated[Session, Depends(get_db)],
                 user: ManagerOrAdmin):
    p = get_or_404(db, Plant, plant_id)
    refs = []
    if db.scalar(select(func.count()).select_from(Inventory).where(Inventory.plant_id == plant_id)):
        refs.append("inventory")
    if db.scalar(select(func.count()).select_from(StockMovement).where(StockMovement.plant_id == plant_id)):
        refs.append("stock movements")
    if db.scalar(select(func.count()).select_from(Dispatch).where(Dispatch.plant_id == plant_id)):
        refs.append("dispatches")
    if refs:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"Cannot delete plant: referenced by existing {' and '.join(refs)}.")
    db.delete(p)
    db.commit()
    write_audit(db, user, "DELETE", "plants", plant_id, f"Deleted plant {p.name}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)