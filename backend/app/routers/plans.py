"""Production & dispatch plans (from the PLANE sheet) - CRUD."""
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import CurrentUser, AllStaff, ManagerOrAdmin
from ..crud import apply_updates, get_or_404, write_audit
from ..database import get_db
from ..models import (
    Customer, MovementType, Plan, PlanType, Plant, Product, ProductCategory,
    ProductSourceType, SalesOrder, StockMovement,
)
from ..schemas import PlanCreate, PlanOut, PlanUpdate
from ..services.customers import get_or_create_customer
from ..services.reorder_alerts import refresh_reorder_alert
from ..services.stock_service import (
    apply_movement, get_or_create_inventory, reverse_and_remove_ref,
)

router = APIRouter(prefix="/plans", tags=["plans"])


def _post_plan_output(db: Session, p: Plan) -> None:
    """Post finished-goods stock when a production plan is COMPLETED.

    A `Plan` of type PRODUCTION_PLAN records the finished-goods output of the
    planned `quantity`. Completing it posts that qty as a PRODUCTION_OUTPUT
    movement to the Main Store (plant_id = NULL) through the shared
    `apply_movement` pipeline, which raises Inventory and records the
    StockMovement. Idempotent: a completed plan that already posted its output
    (ref_type='plan' / ref_id) is never posted again, so re-saving a completed
    plan (or a retried completion) cannot duplicate stock.
    """
    if p.plan_type != PlanType.production:
        return
    if (p.status or "").strip().upper() != "COMPLETED":
        return
    if not p.product_id or not p.quantity or float(p.quantity or 0) <= 0:
        return
    already = db.scalar(select(StockMovement.id).where(
        StockMovement.ref_type == "plan",
        StockMovement.ref_id == p.id,
    ).limit(1))
    if not already:
        apply_movement(
            db, p.product_id, MovementType.production_output, float(p.quantity),
            p.plan_date or date.today(),
            ref_type="plan", ref_id=p.id,
            remarks=f"Production output {p.model}",
            plant_id=None,
        )
        if p.product_id:
            refresh_reorder_alert(db, p.product_id)
    # NOTE: production output deliberately does NOT touch Local Order status.
    # Local Order status is user-controlled; completing a production plan only
    # posts finished-goods stock (below) and never auto-advances any order.


def _plan_output_movements(db: Session, plan_id: int) -> list[StockMovement]:
    return db.scalars(select(StockMovement).where(
        StockMovement.ref_type == "plan",
        StockMovement.ref_id == plan_id,
    )).all()


def _reverse_plan_output(db: Session, p: Plan) -> None:
    """Reverse a posted production-plan output (delete / un-complete, C2).

    When a COMPLETED production plan is deleted or moved back to a
    non-COMPLETED status, the PRODUCTION_OUTPUT it posted to the Main Store is
    reversed through the shared `reverse_and_remove_ref` pipeline (the same
    mechanism transfers / dispatches use), so Inventory and StockMovement stay
    consistent. Idempotent: a plan with no posted movements is a no-op, and a
    retry after a partial failure can never double-reverse.

    Guard: reversal is ONLY allowed if it does not drive any affected location's
    stock negative (i.e. the produced quantity has not already been fully
    dispatched / transferred / consumed downstream). In that case a business
    error is returned and NOTHING is reversed — the caller must fix the
    downstream stock first instead of silently corrupting balances.
    """
    if p.plan_type != PlanType.production:
        return
    movements = _plan_output_movements(db, p.id)
    if not movements:
        return
    for m in movements:
        qty = float(m.quantity or 0)
        inv = get_or_create_inventory(db, m.product_id, m.plant_id)
        current = float(inv.current_stock or 0)
        resulting = current - qty
        if resulting < 0:
            location = "Main Store"
            if m.plant_id is not None:
                plant = db.get(Plant, m.plant_id)
                location = plant.name if plant else f"plant {m.plant_id}"
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(f"Cannot undo plan {p.id}: reversing {qty:g} at {location} would bring "
                        f"stock to {resulting:g}. The produced quantity has already been "
                        f"dispatched/used downstream — post an inbound receipt or adjust the "
                        f"downstream document first."),
            )
    reverse_and_remove_ref(db, "plan", p.id)
    if p.product_id:
        refresh_reorder_alert(db, p.product_id)


def _resolve_product(db: Session, product_id, model) -> Product | None:
    """Pick the plan's product: by explicit id, or by typed model name.

    A typed model that matches no existing product is auto-created in the
    central product master (mirroring the customer auto-create flow) so manual
    entry is never forced to a dropdown pick.
    """
    if product_id:
        return get_or_404(db, Product, int(product_id))
    name = (model or "").strip()
    if not name:
        return None
    p = db.scalar(select(Product).where(func.lower(Product.model) == name.lower()).limit(1))
    if p is None:
        p = Product(model=name, name=name, category=ProductCategory.finished,
                    uom="Each", source_type=ProductSourceType.manufactured, is_active=True)
        db.add(p)
        db.flush()
    return p


def _resolve_customer(db: Session, customer_id, customer_name) -> int | None:
    """Pick the plan's customer by typed name (auto-create), else explicit id."""
    name = (customer_name or "").strip()
    if name:
        c = get_or_create_customer(db, name)
        return c.id if c else None
    if customer_id:
        return get_or_404(db, Customer, int(customer_id)).id
    return None


def _resolve_sales_order(db: Session, sales_order_id) -> int | None:
    """Validates the plan's linked sales order (Local Order or standard SO).
    None clears the link."""
    if sales_order_id is None:
        return None
    o = db.get(SalesOrder, int(sales_order_id))
    if o is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Sales order {sales_order_id} not found")
    return o.id


@router.get("", response_model=dict)
def list_plans(
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
    plan_type: str = "",
    status_: str = Query(default="", alias="status"),
    search: str = "",
    date_from: str = "",
    date_to: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
):
    stmt = select(Plan)
    if plan_type:
        stmt = stmt.where(Plan.plan_type == plan_type)
    if status_:
        stmt = stmt.where(Plan.status == status_)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(Plan.model.ilike(like))
    if date_from:
        stmt = stmt.where(Plan.plan_date >= date.fromisoformat(date_from))
    if date_to:
        stmt = stmt.where(Plan.plan_date <= date.fromisoformat(date_to))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Plan.plan_date.desc(), Plan.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [PlanOut.model_validate(p).model_dump() for p in rows],
            "total": total, "page": page, "page_size": page_size}


@router.post("", response_model=PlanOut, status_code=status.HTTP_201_CREATED)
def create_plan(body: PlanCreate, db: Annotated[Session, Depends(get_db)],
                user: AllStaff):
    data = body.model_dump()
    prod = _resolve_product(db, data.get("product_id"), data.get("model"))
    data["product_id"] = prod.id if prod else None
    if prod is not None and not (data.get("model") or "").strip():
        data["model"] = prod.model
    data["customer_id"] = _resolve_customer(db, data.get("customer_id"), data.get("customer_name", ""))
    data.pop("customer_name", None)
    data["sales_order_id"] = _resolve_sales_order(db, data.get("sales_order_id"))
    p = Plan(**data)
    db.add(p)
    db.commit()
    db.refresh(p)
    _post_plan_output(db, p)
    db.commit()
    write_audit(db, user, "CREATE", "plans", p.id, f"Created {p.plan_type.value} plan for {p.model}")
    return p


@router.patch("/{plan_id}", response_model=PlanOut)
def update_plan(plan_id: int, body: PlanUpdate, db: Annotated[Session, Depends(get_db)],
                user: AllStaff):
    p = get_or_404(db, Plan, plan_id)
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
    was_completed = (p.status or "").strip().upper() == "COMPLETED" and p.plan_type == PlanType.production
    if "model" in data or "product_id" in data:
        model = data.get("model", p.model)
        product_id = data.get("product_id", p.product_id)
        prod = _resolve_product(db, product_id, model)
        data["product_id"] = prod.id if prod else None
        if prod is not None and prod.id == p.product_id and not (model or "").strip():
            data["model"] = p.model
    if "customer_name" in data or "customer_id" in data:
        cname = data.get("customer_name", "")
        cid = data.get("customer_id", p.customer_id)
        data["customer_id"] = _resolve_customer(db, cid, cname)
    data.pop("customer_name", None)
    if "sales_order_id" in data:
        data["sales_order_id"] = _resolve_sales_order(db, data.get("sales_order_id"))
    valid = {k: v for k, v in data.items() if k in PlanUpdate.model_fields}
    apply_updates(p, PlanUpdate(**valid))
    now_completed = (p.status or "").strip().upper() == "COMPLETED" and p.plan_type == PlanType.production
    if was_completed and not now_completed:
        # Un-completing a production plan reverses its posted output (C2).
        _reverse_plan_output(db, p)
    else:
        # Post once on completion (idempotent); re-completing is a no-op.
        _post_plan_output(db, p)
    db.commit()
    db.refresh(p)
    write_audit(db, user, "UPDATE", "plans", p.id, f"Updated plan {p.id}")
    return p


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_plan(plan_id: int, db: Annotated[Session, Depends(get_db)],
                user: ManagerOrAdmin):
    p = get_or_404(db, Plan, plan_id)
    # Deleting a completed production plan reverses its posted output first
    # (guarded: never drives stock negative) (C2).
    _reverse_plan_output(db, p)
    db.delete(p)
    db.commit()
    write_audit(db, user, "DELETE", "plans", plan_id, f"Deleted plan {p.id}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)