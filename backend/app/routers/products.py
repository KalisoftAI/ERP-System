"""Product catalogue management (CRUD)."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import CurrentUser, ManagerOrAdmin
from ..crud import apply_updates, get_or_404, write_audit
from ..database import get_db
from ..models import Inventory, Product, ProductCategory
from ..schemas import ProductCreate, ProductOut, ProductUpdate

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=dict)
def list_products(
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
    search: str = "",
    category: str = "",
    include_inactive: bool = Query(False, description="Also list deactivated products"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
):
    stmt = select(Product)
    if not include_inactive:
        stmt = stmt.where(Product.is_active.is_(True))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(Product.model.ilike(like), Product.item_code.ilike(like), Product.name.ilike(like)))
    if category:
        stmt = stmt.where(Product.category == category)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Product.category, Product.model)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [ProductOut.model_validate(p).model_dump() for p in rows],
            "total": total, "page": page, "page_size": page_size}


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(body: ProductCreate, db: Annotated[Session, Depends(get_db)],
                   user: ManagerOrAdmin):
    p = Product(**body.model_dump())
    db.add(p)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise status.HTTP_409_CONFLICT
    db.refresh(p)
    write_audit(db, user, "CREATE", "products", p.id, f"Created product {p.model}")
    return p


@router.get("/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Annotated[Session, Depends(get_db)],
                _: CurrentUser):
    return get_or_404(db, Product, product_id)


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(product_id: int, body: ProductUpdate, db: Annotated[Session, Depends(get_db)],
                   user: ManagerOrAdmin):
    p = get_or_404(db, Product, product_id)
    apply_updates(p, body)
    db.commit()
    db.refresh(p)
    write_audit(db, user, "UPDATE", "products", p.id, f"Updated product {p.model}")
    return p


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(product_id: int, db: Annotated[Session, Depends(get_db)],
                   user: ManagerOrAdmin):
    p = get_or_404(db, Product, product_id)
    if db.scalar(select(func.count()).select_from(Inventory).where(Inventory.product_id == product_id)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Cannot delete product: it has inventory/stock records. Deactivate it instead.")
    try:
        db.delete(p)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Cannot delete product: referenced by other records. Deactivate it instead.")
    write_audit(db, user, "DELETE", "products", product_id, f"Deleted product {p.model}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)