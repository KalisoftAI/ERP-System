"""Dashboard analytics: KPIs, trends, and charts."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import CurrentUser
from ..database import get_db
from ..models import (
    Customer, Dispatch, DispatchLine, Inventory, OrderStatus, Plant, Product,
    ProductCategory, ProductionMovement, ProductionOrder, PurchaseOrder,
    RawMaterialBalance, SalesOrder, Supplier,
)
from datetime import date

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
def summary(
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
    report_date: str = "",
):
    rd = date.fromisoformat(report_date) if report_date else date.today()

    total_orders = db.scalar(select(func.count()).select_from(SalesOrder)) or 0
    new_today = db.scalar(select(func.count()).select_from(SalesOrder).where(SalesOrder.order_date == rd)) or 0
    pending = db.scalar(select(func.count()).select_from(SalesOrder).where(
        SalesOrder.status.in_([OrderStatus.new, OrderStatus.confirmed]))) or 0
    in_production = db.scalar(select(func.count()).select_from(SalesOrder).where(
        SalesOrder.status == OrderStatus.in_production)) or 0
    ready = db.scalar(select(func.count()).select_from(SalesOrder).where(
        SalesOrder.status == OrderStatus.ready)) or 0
    dispatched = db.scalar(select(func.count()).select_from(SalesOrder).where(
        SalesOrder.status == OrderStatus.dispatched)) or 0
    completed = db.scalar(select(func.count()).select_from(SalesOrder).where(
        SalesOrder.status == OrderStatus.completed)) or 0
    order_value = db.scalar(select(func.coalesce(func.sum(SalesOrder.total_value), 0)).select_from(SalesOrder)) or 0

    rm_count = db.scalar(select(func.count()).select_from(Product).where(Product.category == ProductCategory.raw_material)) or 0
    rm_balance = db.scalar(select(func.coalesce(func.sum(RawMaterialBalance.balance_qty), 0)).select_from(RawMaterialBalance)) or 0
    rm_stock = db.scalar(select(func.coalesce(func.sum(Inventory.current_stock), 0)).select_from(
        Inventory).where(Inventory.plant_id.is_(None))) or 0

    inv_rows = db.scalars(select(Inventory)).all()
    low = sum(1 for i in inv_rows if i.min_level is not None and 0 < i.current_stock < i.min_level)
    oos = sum(1 for i in inv_rows if i.min_level is not None and i.current_stock <= 0)

    prod = db.scalars(select(ProductionOrder)).all()
    planned = sum(o.schedule_qty for o in prod)
    produced = sum(o.produced_qty for o in prod)
    prod_pending = sum(o.balance_qty for o in prod)

    po_count = db.scalar(select(func.count()).select_from(PurchaseOrder)) or 0
    po_value = db.scalar(select(func.coalesce(func.sum(PurchaseOrder.total_amount), 0)).select_from(PurchaseOrder)) or 0

    disp = db.scalars(select(Dispatch)).all()
    # Schedule de-duplicated by order line: an order line shipped over several
    # dispatches contributes its schedule once, never per dispatch.
    from ..services.dispatch_calc import aggregate_schedule
    disp_sched = aggregate_schedule(db, disp)
    disp_done = sum(d.dispatched_qty for d in disp)
    disp_pending = disp_sched - disp_done

    supplier_count = db.scalar(select(func.count()).select_from(Supplier)) or 0
    customer_count = db.scalar(select(func.count()).select_from(Customer)) or 0
    plant_count = db.scalar(select(func.count()).select_from(Plant)) or 0
    product_count = db.scalar(select(func.count()).select_from(Product)) or 0
    store_items = db.scalar(select(func.count()).select_from(Product).where(Product.category == ProductCategory.store)) or 0

    return {
        "report_date": rd.isoformat(),
        "total_orders": total_orders, "new_orders_today": new_today, "pending_orders": pending,
        "completed_orders": completed, "orders_in_production": in_production,
        "ready_to_dispatch": ready, "orders_dispatched": dispatched, "order_value": float(order_value),
        "raw_material_count": rm_count, "raw_material_stock": float(rm_stock),
        "raw_material_balance": float(rm_balance),
        "low_stock_items": low, "out_of_stock_items": oos,
        "production_planned_qty": planned, "production_produced_qty": produced,
        "production_pending_qty": prod_pending,
        "purchase_count": po_count, "purchase_value": float(po_value),
        "dispatch_scheduled": disp_sched, "dispatch_done": disp_done, "dispatch_pending": disp_pending,
        "supplier_count": supplier_count, "customer_count": customer_count,
        "plant_count": plant_count, "product_count": product_count, "store_items": store_items,
    }


@router.get("/dispatch-by-plant")
def dispatch_by_plant(db: Annotated[Session, Depends(get_db)], _: CurrentUser):
    from ..services.dispatch_calc import aggregate_schedule
    rows = db.scalars(select(Dispatch)).all()
    by: dict = {}
    for d in rows:
        key = d.plant.name if d.plant else (d.customer.name if d.customer else "Unknown")
        by.setdefault(key, []).append(d)
    items = []
    for k, ds in sorted(by.items(), key=lambda x: -len(x[1])):
        sched = aggregate_schedule(db, ds)
        done = sum(float(d.dispatched_qty or 0) for d in ds)
        items.append({"plant": k, "scheduled": sched, "dispatched": done,
                      "pending": sched - done})
    items.sort(key=lambda x: -x["scheduled"])
    return {"items": items}


@router.get("/production-by-product")
def production_by_product(db: Annotated[Session, Depends(get_db)], _: CurrentUser):
    rows = db.scalars(select(ProductionOrder)).all()
    by = {}
    for o in rows:
        name = o.product.model if o.product else o.section or "Unknown"
        e = by.setdefault(name, {"planned": 0.0, "produced": 0.0, "pending": 0.0})
        e["planned"] += o.schedule_qty
        e["produced"] += o.produced_qty
        e["pending"] += o.balance_qty
    items = [{"product": k, **v} for k, v in sorted(by.items(), key=lambda x: -x[1]["produced"])]
    return {"items": items}


@router.get("/order-pipeline")
def order_pipeline(db: Annotated[Session, Depends(get_db)], _: CurrentUser):
    statuses = [s.value for s in OrderStatus]
    counts = {s: 0 for s in statuses}
    for s, c in db.execute(select(SalesOrder.status, func.count()).group_by(SalesOrder.status)).all():
        counts[s.value] = c
    return {"items": [{"status": s, "count": counts[s]} for s in statuses]}


@router.get("/inventory-status")
def inventory_status(db: Annotated[Session, Depends(get_db)], _: CurrentUser):
    rows = db.scalars(select(Inventory)).all()
    ok = low = oos = 0
    for i in rows:
        if i.min_level is None:
            ok += 1
        elif i.current_stock <= 0:
            oos += 1
        elif i.current_stock < i.min_level:
            low += 1
        else:
            ok += 1
    return {"items": [
        {"status": "Healthy", "count": ok},
        {"status": "Low Stock", "count": low},
        {"status": "Out of Stock", "count": oos},
    ]}


@router.get("/raw-material-stock")
def raw_material_stock(db: Annotated[Session, Depends(get_db)], _: CurrentUser):
    rows = db.scalars(select(RawMaterialBalance)).all()
    items = []
    for b in rows:
        items.append({
            "material": b.product.model if b.product else "?",
            "schedule": b.schedule_qty or 0, "inward": b.inward_qty or 0,
            "balance": b.balance_qty or 0, "opening": b.opening_stock or 0,
        })
    return {"items": items}


@router.get("/daily-trends")
def daily_trends(db: Annotated[Session, Depends(get_db)], _: CurrentUser):
    """Daily dispatch & production output trends (last 30 distinct days)."""
    d_rows = db.execute(
        select(DispatchLine.dispatch_date, func.sum(DispatchLine.quantity))
        .group_by(DispatchLine.dispatch_date).order_by(DispatchLine.dispatch_date)
    ).all()
    p_rows = db.execute(
        select(ProductionMovement.production_date, func.sum(ProductionMovement.quantity))
        .group_by(ProductionMovement.production_date).order_by(ProductionMovement.production_date)
    ).all()
    by = {}
    for dd, q in d_rows:
        by.setdefault(dd.isoformat(), {"dispatch": 0.0, "production": 0.0})["dispatch"] += float(q)
    for pd, q in p_rows:
        by.setdefault(pd.isoformat(), {"dispatch": 0.0, "production": 0.0})["production"] += float(q)
    items = [{"date": k, **v} for k, v in sorted(by.items())[-30:]]
    return {"items": items}


@router.get("/low-stock-list")
def low_stock_list(db: Annotated[Session, Depends(get_db)], _: CurrentUser, limit: int = 10):
    rows = db.scalars(select(Inventory)).all()
    items = []
    for i in rows:
        if i.min_level is not None and i.current_stock < i.min_level:
            items.append({
                "product": i.product.model if i.product else "?",
                "item_code": i.product.item_code if i.product else "",
                "current_stock": i.current_stock, "min_level": i.min_level,
                "plant": i.plant.name if i.plant else "Main Store",
                "status": "OUT_OF_STOCK" if i.current_stock <= 0 else "LOW",
            })
    items.sort(key=lambda x: x["current_stock"])
    return {"items": items[:limit]}