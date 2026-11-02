"""Shared Local Order helpers (readiness + exact per-line dispatch tracking).

Local Orders are SalesOrder(order_type=LOCAL) + SalesOrderLine. Their ACTUAL
dispatch is appenda to the existing sales-order-driven `Dispatch` module
(Dispatch.sales_order_id -> the local order). Each dispatch is an independent
date-wise historical transaction; per-line attribution uses the existing
DispatchLine.sales_order_line_id column (Integer, additive).

Readiness = enough stock at the Dispatch location (seeded Plant named
"Dispatch", Main Store plant_id NULL). Insufficient stock routes by order type:
TRADING -> Purchase / Stock Required, MANUFACTURING -> Production Required.

Status is user-controlled for the pre-dispatch lifecycle (New, Production
Required, Production Completed, Ready for Dispatch, Purchase / Stock Required,
Cancelled). Only actual dispatch events drive the order to Partially
Dispatched / Completed; stock/state derivation is a fallback for orders that
have not been given an explicit manual status.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..models import (
    Dispatch, DispatchLine, Inventory, OrderStatus, OrderType, Plant, ProductionOrder,
    ProductionStatus, SalesOrder, SalesOrderLine,
)
from .dispatch_calc import order_line_remaining as _calc_order_line_remaining

LOCAL_TYPES = ("TRADING", "MANUFACTURING")
DEFAULT_LOCAL_TYPE = "TRADING"

_STATUS_MAP = {
    "Ready for Dispatch": OrderStatus.ready,
    "Stock Transfer Required": OrderStatus.confirmed,
    "Purchase / Stock Required": OrderStatus.confirmed,
    "Production Required": OrderStatus.in_production,
    "Production In Process": OrderStatus.production_in_process,
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
    OrderStatus.production_in_process: "Production In Process",
    OrderStatus.production_completed: "Production Completed",
    OrderStatus.ready: "Ready for Dispatch",
    OrderStatus.dispatched: "Partially Dispatched",
    OrderStatus.completed: "Completed",
    OrderStatus.cancelled: "Cancelled",
}

# User-controlled manual statuses. Once a user explicitly sets one of these,
# stock/state derivation must NOT silently overwrite it; only actual dispatch
# events (Partially Dispatched / Completed) or a user Cancelled may change it.
_USER_CONTROLLED_STATUSES = {
    OrderStatus.new,
    OrderStatus.confirmed,
    OrderStatus.in_production,
    OrderStatus.production_in_process,
    OrderStatus.production_completed,
    OrderStatus.ready,
    OrderStatus.cancelled,
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
    # Canonical implementation lives in services.dispatch_calc and is
    # schedule-aware (SalesOrderLine.schedule_qty ?? quantity). Local order
    # lines have no explicit schedule_qty, so behaviour is unchanged for them.
    return _calc_order_line_remaining(db, order_line_id,
                                      exclude_dispatch_id=exclude_dispatch_id,
                                      exclude_line_id=exclude_line_id)


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
    # Manual user-controlled statuses take precedence over stock derivation.
    # Once a user explicitly sets a status (New, Production Required,
    # Production Completed, Ready for Dispatch, Purchase / Stock Required,
    # Cancelled), it is displayed as-is. Only actual dispatch events move the
    # order to Partially Dispatched / Completed.
    if o.status in _USER_CONTROLLED_STATUSES:
        return _STATUS_LABEL_REVERSE.get(o.status, o.status.value)
    # Fallback derivation for orders that have no explicit manual status yet.
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
    """Persist the order status based on dispatch reality, respecting manual
    user-controlled statuses.

    Rules:
      - Cancelled orders are never touched.
      - Fully dispatched -> Completed.
      - Partially dispatched -> Partially Dispatched.
      - Explicit user-controlled statuses (New, Production Required,
        Production Completed, Ready for Dispatch, Purchase / Stock Required)
        are preserved; stock/state derivation does NOT overwrite them.
      - Only orders without an explicit manual status fall back to stock-based
        derivation (legacy / default-New behaviour).
    """
    if o.status == OrderStatus.cancelled:
        return
    per_line, total = dispatched_map(db, o)
    order_qty = sum(float(l.quantity or 0) for l in o.lines)
    if order_qty > 0 and total >= order_qty:
        derived = OrderStatus.completed
    elif total > 0:
        derived = OrderStatus.dispatched
    elif o.status in _USER_CONTROLLED_STATUSES and o.status != OrderStatus.new:
        # Explicit manual status set by the user — do not re-derive from stock.
        return
    else:
        # Default/New orders or legacy statuses fall back to stock derivation.
        derived = db_status_for(friendly_status(db, o, (per_line, total)))
    if o.status != derived:
        o.status = derived
        db.flush()


def sync_local_order_production_completion(db: Session, sales_order_id: int) -> None:
    """Synchronize a Manufacturing Local Order status with its production plans.

    If the Local Order has per-line ProductionOrders, it is marked
    Production Completed only when every manufacturing line has a completed
    plan. If any per-line plan is not completed, the order is moved back to
    Production In Process when it was previously Production Completed.

    Historical aggregate plans without a line link are handled as a fallback
    for existing records: they are ignored when per-line plans exist, and
    treated as covering the whole order when no per-line plans are present.
    """
    so = db.get(SalesOrder, sales_order_id)
    if so is None:
        return
    if so.order_type != OrderType.local:
        return
    if so.status == OrderStatus.cancelled:
        return
    if normalize_local_type(so.local_order_type) != "MANUFACTURING":
        return
    # Only toggle between these two production-specific statuses.
    if so.status not in (OrderStatus.production_in_process, OrderStatus.production_completed):
        return

    per_line_plans = db.scalars(
        select(ProductionOrder)
        .where(
            ProductionOrder.sales_order_id == so.id,
            ProductionOrder.sales_order_line_id.is_not(None),
        )
    ).all()

    if per_line_plans:
        line_ids = {ln.id for ln in so.lines}
        if not line_ids:
            return
        planned_line_ids = {po.sales_order_line_id for po in per_line_plans}
        all_completed = all(po.status == ProductionStatus.completed for po in per_line_plans)
        all_lines_have_plan = planned_line_ids == line_ids
        if all_lines_have_plan and all_completed:
            target = OrderStatus.production_completed
        else:
            target = OrderStatus.production_in_process
    else:
        aggregate_plans = db.scalars(
            select(ProductionOrder)
            .where(
                ProductionOrder.sales_order_id == so.id,
                ProductionOrder.sales_order_line_id.is_(None),
            )
        ).all()
        if not aggregate_plans:
            return
        target = (
            OrderStatus.production_completed
            if all(po.status == ProductionStatus.completed for po in aggregate_plans)
            else OrderStatus.production_in_process
        )

    if so.status != target:
        so.status = target
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

    # Production plans linked to this manufacturing local order, including the
    # specific order line each plan belongs to.
    production_plans = []
    if normalize_local_type(o.local_order_type) == "MANUFACTURING":
        plans = db.scalars(
            select(ProductionOrder)
            .where(ProductionOrder.sales_order_id == o.id)
            .order_by(ProductionOrder.id)
            .options(selectinload(ProductionOrder.sales_order_line))
        ).all()
        for po in plans:
            line = po.sales_order_line
            production_plans.append({
                "id": po.id,
                "order_no": po.order_no,
                "product_id": po.product_id,
                "product_model": po.product.model if po.product else "",
                "line_id": po.sales_order_line_id,
                "line_description": line.description if line else (po.product.model if po.product else ""),
                "schedule_qty": float(po.schedule_qty or 0),
                "produced_qty": float(po.produced_qty or 0),
                "balance_qty": float(po.balance_qty or 0),
                "completion_pct": float(po.completion_pct or 0),
                "status": po.status.value,
            })

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
        "transport_name": o.transport_name or "",
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
            "transfer_required": transfer_qty > 0,
        },
        "production_plans": production_plans,
        "dispatches": order_dispatches(db, o),
        "created_at": o.created_at,
    }


def sync_local_orders_for_products(db: Session, product_ids: list) -> int:
    """Refreshes derived status of every LOCAL order that references any of the
    given products (used after stock transfers / receipts reposition stock).

    Only orders without an explicit manual user-controlled status are re-derived
    from stock; manual statuses are preserved.

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
        if o.status in _USER_CONTROLLED_STATUSES and o.status != OrderStatus.new:
            continue
        derived = db_status_for(friendly_status(db, o))
        if o.status != derived:
            o.status = derived
            changed += 1
    if orders or changed:
        db.commit()
    return changed
