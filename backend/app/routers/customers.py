"""Customer management (CRUD)."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import CurrentUser, ManagerOrAdmin
from ..crud import apply_updates, get_or_404, write_audit
from ..database import get_db
from ..models import Customer, Dispatch, SalesOrder
from ..schemas import CustomerCreate, CustomerOut, CustomerUpdate

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("", response_model=dict)
def list_customers(
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
    search: str = "",
    is_plant: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
):
    stmt = select(Customer)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(Customer.name.ilike(like), Customer.company.ilike(like),
                              Customer.code.ilike(like), Customer.phone.ilike(like)))
    if is_plant in ("true", "false"):
        stmt = stmt.where(Customer.is_plant == (is_plant == "true"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Customer.name).offset((page - 1) * page_size).limit(page_size)).all()

    items = []
    for c in rows:
        order_count = db.scalar(select(func.count()).select_from(SalesOrder).where(SalesOrder.customer_id == c.id))
        order_value = db.scalar(select(func.coalesce(func.sum(SalesOrder.total_value), 0)).where(SalesOrder.customer_id == c.id))
        dispatch_count = db.scalar(select(func.count()).select_from(Dispatch).where(Dispatch.customer_id == c.id))
        items.append({
            **CustomerOut.model_validate(c).model_dump(),
            "stats": {"total_orders": order_count, "total_value": float(order_value or 0),
                      "total_dispatches": dispatch_count},
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
def create_customer(body: CustomerCreate, db: Annotated[Session, Depends(get_db)],
                    user: ManagerOrAdmin):
    cust = Customer(**body.model_dump())
    db.add(cust)
    db.commit()
    db.refresh(cust)
    write_audit(db, user, "CREATE", "customers", cust.id, f"Created customer {cust.name}")
    return cust


@router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: int, db: Annotated[Session, Depends(get_db)],
                 _: CurrentUser):
    return get_or_404(db, Customer, customer_id)


@router.patch("/{customer_id}", response_model=CustomerOut)
def update_customer(customer_id: int, body: CustomerUpdate, db: Annotated[Session, Depends(get_db)],
                    user: ManagerOrAdmin):
    cust = get_or_404(db, Customer, customer_id)
    changes = apply_updates(cust, body)
    db.commit()
    db.refresh(cust)
    write_audit(db, user, "UPDATE", "customers", cust.id, f"Updated customer {cust.name}",
                changes=changes)
    return cust


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer(customer_id: int, db: Annotated[Session, Depends(get_db)],
                    user: ManagerOrAdmin):
    cust = get_or_404(db, Customer, customer_id)
    refs = []
    if db.scalar(select(func.count()).select_from(SalesOrder).where(SalesOrder.customer_id == customer_id)):
        refs.append("orders")
    if db.scalar(select(func.count()).select_from(Dispatch).where(Dispatch.customer_id == customer_id)):
        refs.append("dispatches")
    if refs:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete customer: referenced by existing {' and '.join(refs)}. Deactivate instead."
        )
    try:
        db.delete(cust)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Cannot delete customer: referenced by other records.")
    write_audit(db, user, "DELETE", "customers", customer_id, f"Deleted customer {cust.name}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)