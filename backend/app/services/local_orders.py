"""Shared Local Order helpers (readiness + exact per-line dispatch tracking).

Local Orders are SalesOrder(order_type=LOCAL) + SalesOrderLine. Their ACTUAL
dispatch is appenda to the existing sales-order-driven `Dispatch` module
(Dispatch.sales_order_id -> the local order). Each dispatch is an independent
date-wise historical transaction; per-line attribution uses the existing
DispatchLine.sales_order_line_id column (Integer, additive).

Readiness = enough stock at the Dispatch location (seeded Plant named
"Dispatch", Main Store plant_id NULL). Insufficient stock routes by order type:
TRADING -> Purchase / Stock Required, MANUFACTURING -> Production Required.

Status is always derived from actual data (ordered vs dispatched vs stock),
never hardcoded by the UI.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..models import (
    Dispatch, DispatchLine, Inventory, OrderStatus, OrderType, Plant, SalesOrder,
    SalesOrderLine,
)

LOCAL_TYPES = ("TRADING", "MANUFACTURING")
DEFAULT_LOCAL_TYPE = "TRADING"

_STATUS_MAP = {
    "Ready for Dispatch": OrderStatus.ready,
    "Stock Transfer Required": OrderStatus.confirmed,
    "Purchase / Stock Required": OrderStatus.confirmed,
    "Production Required": OrderStatus.in_production,
    "Production Completed": OrderStatus.production_completed,
    "Partially Dispatched": OrderStatus.dispatched,
    "Completed": OrderStatus.completed,
    "Cancelled": OrderStatus.cancelled,
}

# Reverse map: OrderStatus value → friendly label for manual status.
_STATUS_LABEL_REVERSE = {
    OrderStatus.new: "New",
    OrderStatus.confirmed: "Purchase / Stock Required",
    OrderStatus.in_production: "Production Required",
    OrderStatus.production_completed: "Production Completed",
    OrderStatus.ready: "Ready for Dispatch",
    OrderStatus.dispatched: "Partially Dispatched",
    OrderStatus.completed: "Completed",
    OrderStatus.cancelled: "Cancelled",
}


def normalize_local_type(value: str | None) -> str:
    v = (value or "").strip().upper()
    return v if v in LOCAL_TYPES else DEFAULT_LOCAL_TYPE


def dispatch_plant(db: Session) -> Plant | None:
    return db.scalar(select(Plant).where(Plant.name == "Dispatch"))


def stock_at(db: Session, product_id: int | None, plant_id: int | None) -> float:
    """Current Inventory balance for a product at a location
    (plant_id None = Main Store, existing convention)."""
    if product_id is None:
        return 0.0
    cond = (Inventory.plant_id.is_(None) if plant_id is None
            else Inventory.plant_id == plant_id)
    q = db.scalar(
        select(func.coalesce(func.sum(Inventory.current_stock), 0))
        .where(Inventory.product_id == product_id, cond)
    ) or 0
    return float(q)


def total_supply(db: Session, product_id: int | None) -> float:
    """Owned stock across ALL locations (Main Store + every plant).

    Used to distinguish a genuine supply shortage (company does not actually
    have the goods) from a location/positioning gap (goods exist, but are not
    yet at the Dispatch location and simply need a Main Store -> Dispatch
    transfer).
    """
    if product_id is None:
        return 0.0
    q = db.scalar(
        select(func.coalesce(func.sum(Inventory.current_stock), 0))
        .where(Inventory.product_id == product_id)
    ) or 0
    return float(q)


def dispatched_map(db: Session, o: SalesOrder) -> tuple[dict[int, float], float]:
    """Per-order-line dispatched qty (exact via sales_order_line_id) + total."""
    rows = db.execute(
        select(DispatchLine.sales_order_line_id,
               func.coalesce(func.sum(DispatchLine.quantity), 0))
        .join(Dispatch, Dispatch.id == DispatchLine.dispatch_id)
        .where(Dispatch.sales_order_id == o.id)
        .group_by(DispatchLine.sales_order_line_id)
    ).all()
    per_line = {rid: float(q) for rid, q in rows if rid}
    total = float(db.scalar(
        select(func.coalesce(func.sum(DispatchLine.quantity), 0))
        .select_from(Dispatch)
        .join(DispatchLine, DispatchLine.dispatch_id == Dispatch.id)
        .where(Dispatch.sales_order_id == o.id)
    ) or 0)
    return per_line, total


def order_line_remaining(db: Session, order_line_id: int | None,
                         exclude_dispatch_id: int | None = None,
                         exclude_line_id: int | None = None) -> float | None:
    """Remaining quantity still left to dispatch on an order line — exactly the
    \"Balance\" of Schedule (order line qty) minus every date-wise Dispatch
    entry already recorded against it.

    Negative when the line was historically over-dispatched (legacy data);
    None when the line does not exist / is not stock-attributed (dispatch
    entries without a sales_order_line_id are not balance-constrained).
    `exclude_*` let an in-progress edit discount its own entry.
    """
    if order_line_id is None:
        return None
    qty = db.scalar(select(SalesOrderLine.quantity)
                    .where(SalesOrderLine.id == order_line_id))
    if qty is None:
        return None
    stmt = (select(func.coalesce(func.sum(DispatchLine.quantity), 0))
            .where(DispatchLine.sales_order_line_id == order_line_id))
    if exclude_dispatch_id is not None:
        stmt = stmt.where(DispatchLine.dispatch_id != exclude_dispatch_id)
    if exclude_line_id is not None:
        stmt = stmt.where(DispatchLine.id != exclude_line_id)
    dispatched = db.scalar(stmt) or 0
    return float(qty) - float(dispatched)


def check_ready(db: Session, o: SalesOrder) -> dict:
    """Per-line stock check at the Dispatch location.

    A line without a linked product cannot be confirmed ready (no stock
    tracking); the order then needs the item code / product link resolved.
    """
    dp = dispatch_plant(db)
    dp_id = dp.id if dp else None
    lines = []
    all_ready = True
    any_tracked = False
    for ln in o.lines:
        rec = {
            "line_id": ln.id,
            "product_id": ln.product_id,
            "required": float(ln.quantity or 0),
            "available_dispatch": 0.0,
            "available_main": 0.0,
            "tracked": False,
            "ready": None,
        }
        if ln.product_id:
            rec["available_dispatch"] = stock_at(db, ln.product_id, dp_id)
            rec["available_main"] = stock_at(db, ln.product_id, None)
            rec["tracked"] = True
            rec["ready"] = rec["available_dispatch"] >= rec["required"]
            any_tracked = True
            if not rec["ready"]:
                all_ready = False
        else:
            all_ready = False
        lines.append(rec)
    return {"ready": bool(any_tracked) and all_ready, "lines": lines}


def friendly_status(db: Session, o: SalesOrder, dmap: tuple | None = None,
                    ready: dict | None = None) -> str:
    if o.status == OrderStatus.cancelled:
        return "Cancelled"
    per_line, total = dmap if dmap is not None else dispatched_map(db, o)
    order_qty = sum(float(l.quantity or 0) for l in o.lines)
    if order_qty > 0 and total >= order_qty:
        return "Completed"
    if total > 0:
        return "Partially Dispatched"
    # Manual gate: once the user has marked production as completed the order
    # stays in that state until real dispatch moves it on. Production/stock
    # changes never auto-advance it (the user stays in control).
    if o.status == OrderStatus.production_completed:
        return "Production Completed"
    ck = ready if ready is not None else check_ready(db, o)
    if ck["ready"]:
        return "Ready for Dispatch"
    # Not stocked at the Dispatch location. Check whether the company actually
    # owns enough stock somewhere (Main Store + all plants) to cover the
    # requirement. If yes, the goods just need to be positioned at Dispatch via
    # a Main Store -> Dispatch transfer — NOT a purchase. Orders with an
    # untracked (product-less) line cannot be resolved by a transfer — they fall
    # through to the shortage / requirement state so the line gets resolved.
    if all(ln.product_id is not None for ln in o.lines):
        supplied = _order_total_supply(db, o)
        if supplied >= order_qty:
            return "Stock Transfer Required"
    if normalize_local_type(o.local_order_type) == "MANUFACTURING":
        return "Production Required"
    return "Purchase / Stock Required"


def _order_total_supply(db: Session, o: SalesOrder) -> float:
    """Sum of owned supply (Main Store + all plants) across all tracked lines."""
    return sum(total_supply(db, ln.product_id) for ln in o.lines)


def db_status_for(friendly: str) -> OrderStatus:
    return _STATUS_MAP.get(friendly, OrderStatus.new)


def sync_local_order_status(db: Session, o: SalesOrder) -> None:
    """Persist the derived order status (keeps cross-module status consistent).

    Cancelled orders keep their status; otherwise the stored status is refreshed
    whenever the derived status changes (avoids needless writes).
    """
    if o.status == OrderStatus.cancelled:
        return
    derived = db_status_for(friendly_status(db, o))
    if o.status != derived:
        o.status = derived
        db.flush()


def order_dispatches(db: Session, o: SalesOrder) -> list[dict]:
    """Date-wise actual dispatch history for the local order (never rewritten)."""
    rows = db.scalars(
        select(Dispatch)
        .where(Dispatch.sales_order_id == o.id)
        .options(selectinload(Dispatch.lines))
        .order_by(Dispatch.dispatch_date.desc().nullslast(),
                  Dispatch.report_date.desc(), Dispatch.id.desc())
    ).all()
    out = []
    for d in rows:
        out.append({
            "id": d.id,
            "dispatch_no": d.dispatch_no,
            "dispatch_date": d.dispatch_date or d.report_date,
            "customer": d.customer.name if d.customer else (o.customer_name or ""),
            "status": d.status.value,
            "lines": [{
                "id": ln.id,
                "product_id": ln.product_id,
                "item_code": ln.product.item_code if ln.product else "",
                "description": ln.description or (ln.product.model if ln.product else ""),
                "quantity": float(ln.quantity or 0),
                "dispatch_date": ln.dispatch_date,
                "rate": float(ln.rate) if ln.rate is not None else None,
                "weight": ln.weight,
                "sales_order_line_id": ln.sales_order_line_id,
            } for ln in d.lines],
        })
    return out


def serialize_local_order(db: Session, o: SalesOrder) -> dict:
    per_line, total = dispatched_map(db, o)
    order_qty = sum(float(l.quantity or 0) for l in o.lines)
    ck = check_ready(db, o)
    friendly = friendly_status(db, o, (per_line, total), ready=ck)
    customer = o.customer
    lines = []
    for ln in o.lines:
        disp = per_line.get(ln.id, 0.0)
        lines.append({
            "id": ln.id,
            "product_id": ln.product_id,
            "model": ln.product.model if ln.product else (ln.description or ""),
            "item_code": ln.product.item_code if ln.product else "",
            "description": ln.description or (ln.product.model if ln.product else ""),
            "uom": ln.uom or (ln.product.uom if ln.product else ""),
            "quantity": float(ln.quantity or 0),
            "rate": float(ln.unit_price) if ln.unit_price is not None else None,
            "less": float(ln.less) if ln.less is not None else None,
            "amount": float(ln.amount or (float(ln.unit_price or 0) * float(ln.quantity or 0))),
            "dispatched_qty": disp,
            "balance_qty": float(ln.quantity or 0) - disp,
        })
    dispatch_stock = sum(float(l["available_dispatch"] or 0) for l in ck["lines"])
    main_stock = sum(float(l["available_main"] or 0) for l in ck["lines"])
    pending = max(order_qty - total, 0.0)
    transfer_qty = max(min(pending - dispatch_stock, main_stock), 0.0)
    return {
        "id": o.id,
        "order_no": o.order_no,
        "so_no": o.so_no or "",
        "customer_po_no": o.customer_po_no or "",
        "customer_id": o.customer_id,
        "customer": customer.name if customer else (o.customer_name or None),
        "customer_name": o.customer_name or (customer.name if customer else ""),
        "customer_mobile": customer.phone if customer else "",
        "customer_email": customer.email if customer else "",
        "order_type": normalize_local_type(o.local_order_type),
        "order_date": o.order_date,
        "delivery_date": o.required_delivery_date,
        "commitment": o.remarks,
        "remarks": o.remarks,
        "status": friendly,
        "order_status": o.status.value,
        "lines": lines,
        "quantity": order_qty,
        "dispatched_qty": total,
        "pending_qty": pending,
        "total_value": float(o.total_value),
        "stock": ck,
        "stock_summary": {
            "order_qty": order_qty,
            "dispatched_qty": total,
            "pending_qty": pending,
            "dispatch_stock": dispatch_stock,
            "main_store_stock": main_stock,
            "transfer_qty": transfer_qty,
            "transfer_required": friendly == "Stock Transfer Required",
        },
        "dispatches": order_dispatches(db, o),
        "created_at": o.created_at,
    }


def sync_local_orders_for_products(db: Session, product_ids: list) -> int:
    """Refreshes derived status of every LOCAL order that references any of the
    given products (used after stock transfers / receipts reposition stock).

    Returns the number of local orders whose status changed.
    """
    ids = {int(x) for x in (product_ids or []) if x}
    if not ids:
        return 0
    orders = db.scalars(
        select(SalesOrder)
        .join(SalesOrderLine, SalesOrderLine.order_id == SalesOrder.id)
        .where(
            SalesOrder.order_type == OrderType.local,
            SalesOrderLine.product_id.in_(ids),
        )
        .distinct()
    ).all()
    changed = 0
    for o in orders:
        if o.status == OrderStatus.cancelled:
            continue
        derived = db_status_for(friendly_status(db, o))
        if o.status != derived:
            o.status = derived
            changed += 1
    if orders or changed:
        db.commit()
    return changed