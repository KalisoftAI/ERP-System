"""Product-wise dispatch schedule / progress calculations (single source).

Every scheduled quantity is anchored to an ORDER LINE, never to the sum of an
order's products:

  * DispatchLine.schedule_qty  — schedule for THIS product/order line, resolved
    from SalesOrderLine (schedule_qty ?? quantity) via sales_order_line_id (or
    by order+product match). Stored at write time; NULL only on legacy rows
    that cannot be mapped reliably.
  * Dispatched (per line)      — cumulative sum of DispatchLine.quantity for the
    linked order line across ALL dispatches (dynamic — edits/deletes stay
    correct automatically). Manual lines (no order link) report their own qty.
  * Balance / % / status       — derived from schedule vs cumulative dispatched.

Dispatch header schedule_qty is maintained as the sum of its lines' schedules
(and kept as-is when no line has a schedule — historical planning-only rows).
Cross-dispatch aggregates must de-duplicate by order line so a schedule is never
counted twice when an order line is dispatched over multiple dispatches.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Dispatch, DispatchLine, SalesOrderLine

LINE_PENDING = "Pending"
LINE_PARTIAL = "Partially Dispatched"
LINE_COMPLETED = "Completed"


def order_line_schedule(sol: SalesOrderLine | None) -> float | None:
    """Schedule anchored to an order line: explicit schedule_qty wins, else the
    ordered quantity. None when there is no order line."""
    if sol is None:
        return None
    if sol.schedule_qty is not None:
        return float(sol.schedule_qty)
    return float(sol.quantity or 0)


def resolve_line_schedule(db: Session, sales_order_id: int | None,
                          product_id: int | None, sales_order_line_id: int | None,
                          explicit: float | None = None) -> float | None:
    """Best-effort schedule for one dispatch line.

    Priority: explicit value (manual entry) > linked order line > order+product
    match (sums same-product lines of that order — product-wise schedule).
    None when nothing can be resolved reliably.
    """
    if explicit is not None:
        return float(explicit)
    if sales_order_line_id:
        s = order_line_schedule(db.get(SalesOrderLine, sales_order_line_id))
        if s is not None:
            return s
    if sales_order_id and product_id:
        sols = db.scalars(
            select(SalesOrderLine)
            .where(SalesOrderLine.order_id == sales_order_id,
                   SalesOrderLine.product_id == product_id)
            .order_by(SalesOrderLine.id)
        ).all()
        if sols:
            return sum(order_line_schedule(s) or 0.0 for s in sols)
    return None


def line_dispatched_total(db: Session, ln: DispatchLine,
                          exclude_dispatch_id: int | None = None,
                          exclude_line_id: int | None = None) -> float:
    """Cumulative dispatched quantity for the line's order line across every
    dispatch (excluding the given dispatch/line during edits). Manual lines
    (no order-line link) report only their own quantity."""
    if ln.sales_order_line_id:
        stmt = (select(func.coalesce(func.sum(DispatchLine.quantity), 0))
                .where(DispatchLine.sales_order_line_id == ln.sales_order_line_id))
        if exclude_dispatch_id is not None:
            stmt = stmt.where(DispatchLine.dispatch_id != exclude_dispatch_id)
        if exclude_line_id is not None:
            stmt = stmt.where(DispatchLine.id != exclude_line_id)
        return float(db.scalar(stmt) or 0)
    return float(ln.quantity or 0)


def line_progress(schedule: float | None, dispatched: float) -> dict:
    """Balance / completion % / per-line dispatch status, safe for zero or
    missing schedules. Status: Pending / Partially Dispatched / Completed."""
    if schedule is None:
        # Schedule unknown (legacy unmapped line): quantity alone cannot yield a
        # meaningful balance — report it as dispatched without a schedule.
        return {"balance_qty": None, "completion_pct": None,
                "status": LINE_PARTIAL if dispatched > 0 else LINE_PENDING}
    schedule = float(schedule or 0)
    dispatched = float(dispatched or 0)
    balance = schedule - dispatched
    pct = round(dispatched / schedule, 4) if schedule > 0 else (1.0 if dispatched > 0 else 0.0)
    if schedule > 0 and dispatched >= schedule:
        status = LINE_COMPLETED
    elif dispatched > 0:
        status = LINE_PARTIAL
    else:
        status = LINE_PENDING
    return {"balance_qty": balance, "completion_pct": pct, "status": status}


def order_line_remaining(db: Session, order_line_id: int | None,
                         exclude_dispatch_id: int | None = None,
                         exclude_line_id: int | None = None) -> float | None:
    """Remaining quantity still dispatchable on an order line:
    line schedule minus every dispatch entry already recorded against it.

    None when the order line does not exist. Negative only for legacy
    over-dispatched data (never allowed for new writes).
    """
    if order_line_id is None:
        return None
    sol = db.get(SalesOrderLine, order_line_id)
    if sol is None:
        return None
    schedule = order_line_schedule(sol) or 0.0
    stmt = (select(func.coalesce(func.sum(DispatchLine.quantity), 0))
            .where(DispatchLine.sales_order_line_id == order_line_id))
    if exclude_dispatch_id is not None:
        stmt = stmt.where(DispatchLine.dispatch_id != exclude_dispatch_id)
    if exclude_line_id is not None:
        stmt = stmt.where(DispatchLine.id != exclude_line_id)
    dispatched = float(db.scalar(stmt) or 0)
    return schedule - dispatched


def effective_dispatch_schedule(d: Dispatch) -> float:
    """Header schedule for one dispatch: sum of its lines' schedules when any
    line carries one; otherwise the stored header value (legacy rows with no
    line-level schedule are preserved as-is)."""
    scheds = [float(l.schedule_qty) for l in d.lines if l.schedule_qty is not None]
    if scheds:
        return float(sum(scheds))
    return float(d.schedule_qty or 0)


def aggregate_schedule(db: Session, dispatches: list[Dispatch]) -> float:
    """Total scheduled quantity across a set of dispatches WITHOUT counting any
    order line's schedule twice (the same order line dispatched over multiple
    dispatches contributes its schedule exactly once).

    Manual lines contribute their own schedule each (independent plans).
    Dispatches with no line-level schedule contribute their stored header value
    (legacy planning-only rows)."""
    seen_lines: set[int] = set()
    total = 0.0
    for d in dispatches:
        any_line_schedule = False
        for ln in d.lines:
            if ln.sales_order_line_id:
                any_line_schedule = True
                if ln.sales_order_line_id not in seen_lines:
                    seen_lines.add(ln.sales_order_line_id)
                    total += order_line_schedule(db.get(SalesOrderLine, ln.sales_order_line_id)) or 0.0
            elif ln.schedule_qty is not None:
                any_line_schedule = True
                total += float(ln.schedule_qty)
        if not any_line_schedule:
            total += float(d.schedule_qty or 0)
    return total
