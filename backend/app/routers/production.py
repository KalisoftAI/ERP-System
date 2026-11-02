"""Production management (CRUD + daily movements + status lifecycle)."""
import csv
import io
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy import Integer, func, or_, select
from sqlalchemy.orm import Session

from ..auth import CurrentUser, AllStaff, ManagerOrAdmin
from ..crud import apply_updates, get_or_404, write_audit
from ..database import get_db
from ..models import (
    Customer, MovementType, Plant, Product, ProductCategory,
    ProductionMovement, ProductionOrder, ProductionStatus, SalesOrder, StockMovement,
    Plan, PlanType, ProductSourceType,
)
from ..schemas import ProductionOrderCreate, ProductionOrderOut, ProductionOrderUpdate
from ..services.business import sync_purchase_shortages
from ..services.customers import get_or_create_customer
from ..services.reorder_alerts import refresh_reorder_alert
from ..services.local_orders import sync_local_order_production_completion
from ..services.stock_service import (
    apply_movement, reconvert_document, reverse_and_remove_ref,
    _unique_blank_model,
)
from ..services.import_common import (
    build_column_map, cell_num, cell_text, is_blank_row, parse_date_value,
    read_table, row_to_dict,
)
import re
from datetime import date, datetime, timedelta

router = APIRouter(prefix="/production", tags=["production"])


def _next_no(db: Session) -> str:
    today = date.today()
    prefix = f"PO-{today.strftime('%Y%m%d')}-"
    n = db.scalar(
        select(func.coalesce(func.max(func.cast(func.substr(ProductionOrder.order_no, len(prefix) + 1), Integer)), 0))
        .where(ProductionOrder.order_no.like(f"{prefix}%"))
    )
    return f"{prefix}{n + 1:03d}"


def _serialize_po(db: Session, o: ProductionOrder) -> dict:
    product = o.product
    customer = o.customer
    sales_order = o.sales_order
    line = o.sales_order_line
    return {
        "id": o.id, "order_no": o.order_no, "product_id": o.product_id,
        "customer_id": o.customer_id,
        "sales_order_id": o.sales_order_id,
        "sales_order_no": sales_order.order_no if sales_order else None,
        "sales_order_line_id": o.sales_order_line_id,
        "sales_order_line": {
            "id": line.id,
            "description": line.description,
            "item_code": line.item_code,
            "quantity": line.quantity,
        } if line else None,
        "section": o.section, "schedule_qty": o.schedule_qty, "ask_till_date": o.ask_till_date,
        "produced_qty": o.produced_qty, "completion_pct": o.completion_pct,
        "balance_qty": o.balance_qty, "opening_stock": o.opening_stock,
        "status": o.status.value, "start_date": o.start_date, "completion_date": o.completion_date,
        "report_date": o.report_date, "remarks": o.remarks,
        "product": {"id": product.id, "model": product.model, "item_code": product.item_code,
                    "name": product.name, "category": product.category.value,
                    "source_type": product.source_type.value if product.source_type else None} if product else None,
        "customer": {"id": customer.id, "name": customer.name} if customer else None,
        "movements": [{"id": m.id, "production_order_id": m.production_order_id,
                       "quantity": m.quantity, "production_date": m.production_date} for m in o.movements],
    }


def _recalc_status(o: ProductionOrder):
    if o.schedule_qty:
        o.completion_pct = round(o.produced_qty / o.schedule_qty, 4)
        o.balance_qty = o.schedule_qty - o.produced_qty
    else:
        o.completion_pct = 0.0
        o.balance_qty = 0.0
    if o.status == ProductionStatus.planned and o.produced_qty > 0:
        o.status = ProductionStatus.in_production
    if o.schedule_qty > 0 and o.produced_qty >= o.schedule_qty:
        o.status = ProductionStatus.completed
        o.completion_date = date.today()


def _sync_completed_to_local_order(db: Session, o: ProductionOrder):
    """When a ProductionOrder linked to a Manufacturing Local Order changes,
    re-evaluate whether all per-line production plans are completed and update
    the Local Order status accordingly."""
    if not o.sales_order_id:
        return
    sync_local_order_production_completion(db, o.sales_order_id)


def _stocked(db: Session, order_id: int) -> bool:
    return (db.scalar(select(func.count()).select_from(StockMovement)
                      .where(StockMovement.ref_type == "production_order",
                             StockMovement.ref_id == order_id)) or 0) > 0


def _sync_production_stock(db: Session, o: ProductionOrder):
    """Reconcile Inventory/StockMovement with the order's actual production
    movements. produced_qty is always derived from the movement log."""
    o.produced_qty = sum(float(m.quantity or 0) for m in o.movements)
    _recalc_status(o)
    if not _stocked(db, o.id):
        return
    entries = [(o.product_id, MovementType.production_output, m.quantity,
                m.production_date, f"Production output {o.order_no}") for m in o.movements]
    reconvert_document(db, "production_order", o.id, entries)
    if o.product_id:
        refresh_reorder_alert(db, o.product_id)


@router.get("", response_model=dict)
def list_production(
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
    search: str = "",
    status_: str = Query(default="", alias="status"),
    product_id: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
):
    stmt = select(ProductionOrder)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(ProductionOrder.order_no.ilike(like), ProductionOrder.section.ilike(like)))
    if status_:
        stmt = stmt.where(ProductionOrder.status == status_)
    if product_id:
        stmt = stmt.where(ProductionOrder.product_id == product_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(ProductionOrder.report_date.desc(), ProductionOrder.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_serialize_po(db, o) for o in rows],
            "total": total, "page": page, "page_size": page_size}


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_production(body: ProductionOrderCreate, db: Annotated[Session, Depends(get_db)],
                      user: AllStaff):
    # Product may be picked from master (product_id) or typed as Item Code /
    # Model; a typed code/model is resolved against the product master and
    # created lazily so manual production planning never needs a dropdown pick.
    if body.product_id:
        get_or_404(db, Product, body.product_id)
        product_id = body.product_id
    else:
        prod = _resolve_production_product(
            db, body.item_code, (body.model or body.item_code or "").strip(),
            category=body.category or "Manufacturing",
        )
        if prod is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Item Code or Model is required to create a production order")
        product_id = prod.id
    if body.customer_name and body.customer_name.strip() and not body.customer_id:
        c = get_or_create_customer(db, body.customer_name)
        customer_id = c.id if c else None
    else:
        customer_id = body.customer_id
    o = ProductionOrder(
        order_no=body.order_no or _next_no(db), product_id=product_id,
        customer_id=customer_id,
        sales_order_id=body.sales_order_id,
        sales_order_line_id=body.sales_order_line_id,
        section=body.section, schedule_qty=body.schedule_qty, ask_till_date=body.ask_till_date,
        produced_qty=body.produced_qty, opening_stock=body.opening_stock,
        status=body.status, start_date=body.start_date, completion_date=body.completion_date,
        report_date=body.report_date, remarks=body.remarks,
    )
    _recalc_status(o)
    db.add(o)
    db.commit()
    db.refresh(o)
    write_audit(db, user, "CREATE", "production_orders", o.id, f"Created production order {o.order_no}")
    return _serialize_po(db, o)


@router.get("/actual", response_model=dict)
def list_production_actual(
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
    product_id: int | None = None,
    date_from: str = "",
    date_to: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
):
    """Daily production output (actual) — never collapsed into monthly numbers."""
    stmt = (select(ProductionMovement)
            .join(ProductionOrder, ProductionOrder.id == ProductionMovement.production_order_id)
            .join(Product, Product.id == ProductionOrder.product_id, isouter=True))
    if product_id:
        stmt = stmt.where(ProductionOrder.product_id == product_id)
    if date_from:
        stmt = stmt.where(ProductionMovement.production_date >= date.fromisoformat(date_from))
    if date_to:
        stmt = stmt.where(ProductionMovement.production_date <= date.fromisoformat(date_to))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(ProductionMovement.production_date.desc(), ProductionMovement.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    items = []
    for m in rows:
        po = m.production_order
        p = po.product if po else None
        cust = po.customer if po else None
        items.append({
            "id": m.id, "production_order_id": m.production_order_id,
            "production_date": m.production_date, "quantity": m.quantity,
            "product_id": p.id if p else po.product_id,
            "model": p.model if p else None,
            "item_code": p.item_code if p else None,
            "customer_id": cust.id if cust else (po.customer_id if po else None),
            "customer": cust.name if cust else None,
            "ref": po.order_no if po else "",
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/plan-vs-actual", response_model=dict)
def plan_vs_actual(
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
    product_id: int | None = None,
):
    """Plan vs Actual for each ProductionOrder (reliable FK link to its daily
    movements). Plan-only `Plan` records with no production order are returned
    in `unlinked_plans` (no fabricated plan-to-actual relationship)."""
    stmt = select(ProductionOrder)
    if product_id:
        stmt = stmt.where(ProductionOrder.product_id == product_id)
    orders = db.scalars(stmt.order_by(ProductionOrder.id)).all()
    rows = []
    for po in orders:
        p = po.product
        cust = po.customer
        actual = float(po.produced_qty or 0)
        planned = float(po.schedule_qty or 0)
        remaining = planned - actual
        pct = round(actual / planned, 4) if planned else 0.0
        rows.append({
            "plan_id": po.id, "product_id": po.product_id,
            "model": p.model if p else None,
            "item_code": p.item_code if p else None,
            "customer_id": po.customer_id,
            "customer": cust.name if cust else None,
            "planned_qty": planned, "actual_qty": actual,
            "remaining_qty": remaining, "completion_pct": pct,
            "status": po.status.value, "report_date": po.report_date,
            "movement_count": len(po.movements),
        })
    unlinked = []
    prod_orders = {po.product_id for po in orders}
    plans = db.scalars(select(Plan).where(Plan.plan_type == PlanType.production)).all()
    for pl in plans:
        if pl.product_id in prod_orders:
            continue
        unlinked.append({
            "plan_id": pl.id, "product_id": pl.product_id, "model": pl.model,
            "customer": pl.customer.name if pl.customer else None,
            "owner": pl.owner, "planned_qty": pl.quantity,
            "plan_date": pl.plan_date, "status": pl.status, "remarks": pl.remarks,
            "linkage": "Plan only — no production order link",
        })
    rows.sort(key=lambda x: -x["completion_pct"])
    return {"items": rows, "unlinked_plans": unlinked, "total": len(rows)}


@router.get("/report/orders/csv")
def production_orders_csv(
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
    scope: str = Query("active", description="'active', 'completed' or 'all'"),
    product_id: int | None = None,
):
    """Production orders as a CSV report (one row per production plan),
    mirroring the Production table columns.

    scope=active    -> current (not-yet-completed) production plans (default)
    scope=completed -> completed production plans
    scope=all       -> every production plan
    """
    if scope not in ("active", "completed", "all"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="scope must be 'active', 'completed' or 'all'")
    stmt = select(ProductionOrder)
    if scope == "active":
        stmt = stmt.where(ProductionOrder.status != ProductionStatus.completed)
    elif scope == "completed":
        stmt = stmt.where(ProductionOrder.status == ProductionStatus.completed)
    if product_id:
        stmt = stmt.where(ProductionOrder.product_id == product_id)
    rows = db.scalars(
        stmt.order_by(ProductionOrder.report_date.desc(), ProductionOrder.id.desc())
    ).all()

    headers = ["Order No", "Item Code", "Model", "Category", "Customer",
               "Local Order", "Section", "Schedule Qty", "Ask Till Date",
               "Production Qty", "% Comp", "Balance Qty", "Opening Stock",
               "Status", "Start Date", "Completion Date", "Report Date", "Remarks"]
    data = []
    for o in rows:
        p = o.product
        cust = o.customer
        is_trading = bool(p and p.category == ProductCategory.trading)
        data.append([
            o.order_no,
            p.item_code if p else "",
            p.model if p else "",
            "Trading" if is_trading else "Manufacturing",
            cust.name if cust else "",
            o.sales_order.order_no if o.sales_order else "",
            o.section or "",
            o.schedule_qty if o.schedule_qty is not None else "",
            o.ask_till_date if o.ask_till_date is not None else "",
            o.produced_qty if o.produced_qty is not None else "",
            round(float(o.completion_pct or 0) * 100, 2),
            o.balance_qty if o.balance_qty is not None else "",
            o.opening_stock if o.opening_stock is not None else "",
            o.status.value,
            o.start_date or "",
            o.completion_date or "",
            o.report_date or "",
            o.remarks or "",
        ])

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    writer.writerows(data)
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode("utf-8-sig")),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=production_{scope}.csv"},
    )


@router.get("/{order_id}", response_model=dict)
def get_production(order_id: int, db: Annotated[Session, Depends(get_db)],
                   _: CurrentUser):
    return _serialize_po(db, get_or_404(db, ProductionOrder, order_id))


@router.patch("/{order_id}", response_model=dict)
def update_production(order_id: int, body: ProductionOrderUpdate,
                      db: Annotated[Session, Depends(get_db)], user: AllStaff):
    o = get_or_404(db, ProductionOrder, order_id)
    if body.product_id:
        get_or_404(db, Product, body.product_id)
    if body.customer_id and not body.customer_name:
        get_or_404(db, Customer, body.customer_id)
    if body.customer_name and body.customer_name.strip() and not body.customer_id:
        c = get_or_create_customer(db, body.customer_name)
        if c:
            o.customer_id = c.id
    changes = apply_updates(o, body, exclude={"produced_qty", "customer_name"})
    o.produced_qty = sum(float(m.quantity or 0) for m in o.movements)
    _recalc_status(o)
    _sync_completed_to_local_order(db, o)
    db.commit()
    db.refresh(o)
    write_audit(db, user, "UPDATE", "production_orders", o.id, f"Updated production order {o.order_no}",
                changes=changes)
    return _serialize_po(db, o)


@router.patch("/{order_id}/complete", response_model=dict)
def complete_production(order_id: int, db: Annotated[Session, Depends(get_db)], user: AllStaff):
    """Mark a production order as Completed.
    
    Sets status to Completed and completion_date to today if not already set.
    Does NOT create new production movements or stock entries - these are
    derived from the existing movement log via _recalc_status() and
    apply_movement() in add_movement().
    
    Idempotent: repeated calls have no additional effect beyond setting
    the status to Completed.
    """
    o = get_or_404(db, ProductionOrder, order_id)
    
    if o.status.value == 'Completed':
        return {"message": "Production order is already completed", "order_no": o.order_no}
    
    o.status = ProductionStatus.completed
    if not o.completion_date:
        o.completion_date = date.today()
    _recalc_status(o)
    _sync_completed_to_local_order(db, o)

    db.commit()
    db.refresh(o)
    write_audit(db, user, "UPDATE", "production_orders", o.id, f"Completed production order {o.order_no}")
    return {"message": "Production order marked as completed", "order_no": o.order_no, "completion_date": o.completion_date, "completion_pct": o.completion_pct}


@router.post("/{order_id}/movements", response_model=dict)
def add_movement(order_id: int, quantity: float, production_date: str,
                 db: Annotated[Session, Depends(get_db)], user: AllStaff):
    """Record a daily production output; updates produced qty + finished goods stock."""
    o = get_or_404(db, ProductionOrder, order_id)
    if quantity <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quantity must be greater than 0")
    d = date.fromisoformat(production_date)
    db.add(ProductionMovement(production_order_id=o.id, quantity=quantity, production_date=d))
    o.produced_qty += quantity
    _recalc_status(o)
    _sync_completed_to_local_order(db, o)
    # finished goods increase
    apply_movement(db, o.product_id, MovementType.production_output, quantity,
                   d, ref_type="production_order", ref_id=o.id,
                   remarks=f"Production output {o.order_no}")
    if o.product_id:
        refresh_reorder_alert(db, o.product_id)
    db.commit()
    db.refresh(o)
    write_audit(db, user, "CREATE", "production_movements", o.id, f"{quantity} output on {production_date}")
    sync_purchase_shortages(db)
    return _serialize_po(db, o)


@router.patch("/movements/{movement_id}", response_model=dict)
def update_movement(movement_id: int, quantity: float,
                    db: Annotated[Session, Depends(get_db)], user: AllStaff,
                    production_date: str = ""):
    """Edit a daily production output quantity (actual) + date."""
    m = get_or_404(db, ProductionMovement, movement_id)
    o = get_or_404(db, ProductionOrder, m.production_order_id)
    if quantity <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quantity must be greater than 0")
    m.quantity = quantity
    if production_date:
        m.production_date = date.fromisoformat(production_date)
    _sync_production_stock(db, o)
    db.commit()
    db.refresh(o)
    write_audit(db, user, "UPDATE", "production_movements", movement_id,
                f"Output {movement_id}: {m.quantity}")
    sync_purchase_shortages(db)
    return _serialize_po(db, o)


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_production(order_id: int, db: Annotated[Session, Depends(get_db)],
                      user: ManagerOrAdmin):
    o = get_or_404(db, ProductionOrder, order_id)
    reverse_and_remove_ref(db, "production_order", o.id)
    db.delete(o)
    db.commit()
    write_audit(db, user, "DELETE", "production_orders", order_id, f"Deleted production order {o.order_no}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Production Plan bulk import (CSV / Excel)
# ---------------------------------------------------------------------------
_PRODUCTION_IMPORT_ALIASES = {
    "item_code": ["Item Code", "ITEM CODE", "item_code", "ItemCode", "Item", "Code", "Product Code"],
    "model": ["Model", "MODEL", "Product Model", "Size / Description", "Description", "Size", "Product"],
    "customer": ["Customer", "CUSTOMER", "Customer Name", "Client", "Party", "Buyer"],
    "schedule_qty": ["Schedule", "SCHEDULE", "Schedule Qty", "Schedule Quantity", "Planned Qty", "Planned Quantity", "Qty", "Quantity"],
    "ask_till_date": ["Ask Till Date", "ASK TILL DATE", "Ask Till", "ask_till_date", "Till Date", "Ask Date"],
    "produced_qty": ["Production Qty", "PRODUCTION QTY", "Production Quantity", "Produced Qty", "Produced Quantity"],
    "completion_pct": ["% Comp", "% COMP", "Completion %", "Completion Percent", "% Completion", "Completion Percentage"],
    "balance_qty": ["Balance Qty", "BALANCE QTY", "Balance Quantity"],
    "status": ["Status", "STATUS"],
    "category": ["Category", "CATEGORY", "Type", "Product Type", "Source Type", "Source"],
    "remarks": ["Remarks", "REMARKS", "Notes", "Note", "Comments"],
}


def _excel_serial(d: date) -> float:
    """Convert a date to an Excel serial day number (1899-12-30 epoch)."""
    return (d - date(1899, 12, 30)).days


def _extract_leading_number(v: Any) -> float | None:
    """Parse a number, tolerating common unit suffixes such as '5 BOX' or '1000 kg'."""
    n = cell_num(v)
    if n is not None:
        return n
    s = cell_text(v)
    if not s:
        return None
    m = re.match(r"\s*(\d+(?:\.\d+)?)", s)
    if m:
        return float(m.group(1))
    return None


def _parse_ask_till_date(v: Any) -> tuple[float | None, str | None]:
    """Parse Ask Till Date as a numeric value. Supports plain numbers and
    common date formats (stored as Excel serial to fit the Float column)."""
    if v is None or v == "":
        return None, None
    if isinstance(v, datetime):
        return float(_excel_serial(v.date())), None
    if isinstance(v, date):
        return float(_excel_serial(v)), None
    num = cell_num(v)
    if num is not None:
        return num, None
    parsed = parse_date_value(v)
    if parsed:
        return float(_excel_serial(parsed)), None
    return None, f"Cannot parse '{v}' as a date or number"


def _parse_status(v: Any) -> tuple[str | None, str | None]:
    """Case-insensitive ProductionStatus value lookup."""
    s = cell_text(v)
    if not s:
        return "Planned", None
    target = s.lower()
    for member in ProductionStatus:
        if member.value.lower() == target:
            return member.value, None
    valid = ", ".join(m.value for m in ProductionStatus)
    return None, f"Invalid status '{v}'. Must be one of: {valid}"


def _parse_production_import(headers: list[str], rows: list[list[Any]]) -> tuple[list[dict], list[dict]]:
    """Parse uploaded Production Plan rows for preview.

    Returns (valid_rows, error_rows). Blank optional values are preserved as
    null/0 according to the model defaults; no values are invented.
    """
    colmap = build_column_map(headers, _PRODUCTION_IMPORT_ALIASES)
    valid_rows: list[dict] = []
    error_rows: list[dict] = []

    for row_idx, row in enumerate(rows, start=1):
        mapped = row_to_dict(colmap, row)
        if is_blank_row(mapped):
            continue

        row_data: dict[str, Any] = {}
        row_errors: list[str] = []

        item_code = cell_text(mapped.get("item_code"))
        model = cell_text(mapped.get("model"))
        row_data["item_code"] = item_code or None
        row_data["model"] = model or None

        # Product identity: at least one of item_code or model is required.
        if not item_code and not model:
            row_errors.append("Missing item code or model")

        # Customer is optional; keep blank if absent.
        row_data["customer"] = cell_text(mapped.get("customer")) or None

        # Schedule quantity: required positive number (tolerates '5 BOX').
        schedule_qty = _extract_leading_number(mapped.get("schedule_qty"))
        if schedule_qty is None or schedule_qty <= 0:
            row_errors.append("Missing or invalid schedule quantity")
        row_data["schedule_qty"] = schedule_qty

        # Ask Till Date: numeric / date parser.
        ask_till, ask_err = _parse_ask_till_date(mapped.get("ask_till_date"))
        if ask_err:
            row_errors.append(ask_err)
        row_data["ask_till_date"] = ask_till

        # Production Qty: optional numeric, blank stays null (tolerates units).
        produced_qty = _extract_leading_number(mapped.get("produced_qty"))
        row_data["produced_qty"] = produced_qty

        # % Comp: optional numeric, blank stays null.
        completion_pct = cell_num(mapped.get("completion_pct"))
        row_data["completion_pct"] = completion_pct

        # Balance Qty: optional numeric, blank stays null (tolerates units).
        balance_qty = _extract_leading_number(mapped.get("balance_qty"))
        row_data["balance_qty"] = balance_qty

        # Status: optional, defaults to Planned.
        status_value, status_err = _parse_status(mapped.get("status"))
        if status_err:
            row_errors.append(status_err)
        row_data["status"] = status_value

        # Category: optional, defaults to Manufacturing.
        cat_raw = cell_text(mapped.get("category")) or "Manufacturing"
        row_data["category"] = cat_raw

        # Remarks: optional text.
        row_data["remarks"] = cell_text(mapped.get("remarks")) or None

        if row_errors:
            error_rows.append({
                "row": row_idx,
                "errors": row_errors,
                "data": {k: v for k, v in row_data.items() if k in (
                    "item_code", "model", "customer", "schedule_qty", "ask_till_date",
                    "produced_qty", "completion_pct", "balance_qty", "status", "category", "remarks")},
            })
        else:
            valid_rows.append(row_data)

    return valid_rows, error_rows


def _resolve_production_product(
    db: Session, item_code: str, model: str, category: str = "Manufacturing"
) -> Product | None:
    """Resolve or create a product for a production plan/import.

    Existing products are always reused unchanged. New products are classified
    according to the chosen plan category:
      - Manufacturing -> category=finished, source_type=MANUFACTURED
      - Trading       -> category=trading,  source_type=TRADING
    """
    ic = (item_code or "").strip()
    md = (model or "").strip()
    if not ic and not md:
        return None

    # Reuse existing product by item code or model.
    if ic:
        existing = db.scalars(select(Product).where(Product.item_code == ic).limit(1)).first()
        if existing:
            return existing
    if md:
        existing = db.scalars(select(Product).where(Product.model == md).limit(1)).first()
        if existing:
            return existing

    # No match — create with the selected production category.
    is_trading = category.strip().lower() in ("trading", "trade", "trading goods")
    if not ic:
        md = _unique_blank_model(db, md)
    name = md or ic
    prod = Product(
        item_code=ic,
        model=md or name,
        name=name,
        category=ProductCategory.trading if is_trading else ProductCategory.finished,
        source_type=ProductSourceType.trading if is_trading else ProductSourceType.manufactured,
        uom="Each",
        is_active=True,
    )
    db.add(prod)
    db.flush()
    return prod


def _resolve_import_entities(db: Session, rows: list[dict]) -> list[dict]:
    """Resolve products and customers for parsed rows. Returns enriched rows
    with product_id, customer_id, and warnings."""
    for r in rows:
        item_code = r.get("item_code") or ""
        model = r.get("model") or ""
        category = r.get("category") or "Manufacturing"
        prod = _resolve_production_product(db, item_code, model, category)
        r["product_id"] = prod.id if prod else None
        r["product_model"] = prod.model if prod else (model or None)

        customer_name = r.get("customer") or ""
        if customer_name:
            cust = get_or_create_customer(db, customer_name, "", "")
            r["customer_id"] = cust.id if cust else None
            r["customer_name"] = cust.name if cust else customer_name
        else:
            r["customer_id"] = None
            r["customer_name"] = None
    return rows


def _find_duplicates(db: Session, rows: list[dict], report_date: date) -> list[dict]:
    """Return rows that appear to duplicate an existing ProductionOrder for
    the same product on the same report date with identical key fields.

    The key always includes product, report_date, schedule_qty and status.
    Optional fields (ask_till_date, produced_qty, completion_pct, balance_qty)
    are only compared when the import row actually supplies them, so blank
    optional cells do not prevent duplicate detection.
    """
    duplicates: list[dict] = []
    for r in rows:
        pid = r.get("product_id")
        if pid is None:
            continue
        status_member = ProductionStatus(r.get("status") or "Planned")
        filters = [
            ProductionOrder.product_id == pid,
            ProductionOrder.report_date == report_date,
            ProductionOrder.schedule_qty == (r.get("schedule_qty") or 0),
            ProductionOrder.status == status_member,
        ]
        if r.get("ask_till_date") is not None:
            filters.append(ProductionOrder.ask_till_date == r["ask_till_date"])
        if r.get("produced_qty") is not None:
            filters.append(ProductionOrder.produced_qty == r["produced_qty"])
        if r.get("completion_pct") is not None:
            filters.append(ProductionOrder.completion_pct == r["completion_pct"])
        if r.get("balance_qty") is not None:
            filters.append(ProductionOrder.balance_qty == r["balance_qty"])
        existing = db.scalar(select(ProductionOrder.id).where(*filters).limit(1))
        if existing:
            r["_duplicate"] = True
            duplicates.append(r)
    return duplicates


def _create_production_orders(db: Session, rows: list[dict], user, report_date: date) -> list[ProductionOrder]:
    """Create ProductionOrder records from validated, entity-resolved rows.

    Each order is flushed individually so the generated order_no sequence is
    visible to the next _next_no() call within the same transaction.
    """
    created: list[ProductionOrder] = []
    for r in rows:
        schedule = float(r.get("schedule_qty") or 0)
        produced = float(r.get("produced_qty") or 0)
        completion = r.get("completion_pct")
        balance = r.get("balance_qty")
        if balance is None:
            balance = schedule - produced
        status_val = r.get("status") or "Planned"
        status_member = ProductionStatus(status_val)
        o = ProductionOrder(
            order_no=_next_no(db),
            product_id=r.get("product_id"),
            customer_id=r.get("customer_id"),
            section="",
            schedule_qty=schedule,
            ask_till_date=r.get("ask_till_date"),
            produced_qty=produced,
            completion_pct=completion,
            balance_qty=balance,
            opening_stock=0,
            status=status_member,
            report_date=report_date,
            remarks=r.get("remarks") or "",
        )
        db.add(o)
        db.flush()
        created.append(o)
    return created


@router.post("/import", response_model=dict)
async def import_production_plans(
    file: Annotated[UploadFile, File(...)],
    db: Annotated[Session, Depends(get_db)],
    user: AllStaff,
    confirm: bool = Query(False, description="Set true to create records after preview"),
    force: bool = Query(False, description="Set true to create despite possible duplicates"),
):
    """Import Production Plans from CSV or Excel file.

    Supported columns (any order, flexible naming):
    - Item Code / Model / Customer / Schedule / Ask Till Date /
      Production Qty / % Comp / Balance Qty / Status / Remarks
    - Extra columns are ignored.
    - Column headers are case-insensitive and space/underscore tolerant.

    First call returns a preview. Call again with confirm=true to save.
    """
    content = await file.read()
    filename = file.filename or "production_import.csv"

    try:
        headers, rows = read_table(filename, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Could not read file: {e}")

    valid_rows, error_rows = _parse_production_import(headers, rows)
    report_date = date.today()

    if not confirm:
        return {
            "preview": {
                "filename": filename,
                "total_rows": len(rows),
                "valid_rows": len(valid_rows),
                "error_rows": len(error_rows),
                "mapped_columns": {headers[idx]: canon for idx, canon in build_column_map(headers, _PRODUCTION_IMPORT_ALIASES).items()},
                "detected_fields": list(build_column_map(headers, _PRODUCTION_IMPORT_ALIASES).values()),
                "headers": headers,
                "valid_data": valid_rows,
                "error_details": error_rows,
            },
            "message": "Review the preview and call again with confirm=true to import.",
        }

    if not valid_rows:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No valid rows to import")

    # Resolve products/customers and check duplicates on confirm (valid rows only).
    resolved = _resolve_import_entities(db, valid_rows)
    duplicates = _find_duplicates(db, resolved, report_date)

    if duplicates and not force:
        dup_summary = [
            {"row": i + 1, "item_code": d.get("item_code"), "model": d.get("model")}
            for i, d in enumerate(resolved) if d.get("_duplicate")
        ]
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": f"{len(duplicates)} row(s) match existing Production Orders. Pass force=true to create them anyway.",
                "duplicates": dup_summary,
            },
        )

    created = _create_production_orders(db, resolved, user, report_date)
    db.commit()
    for o in created:
        write_audit(db, user, "CREATE", "production_orders", o.id,
                    f"Imported production plan {o.order_no}")
    if error_rows:
        write_audit(db, user, "IMPORT", "production_orders", None,
                    f"Production import: {len(created)} created, {len(error_rows)} failed",
                    failed=len(error_rows))

    return {
        "created": len(created),
        "filename": filename,
        "message": f"Imported {len(created)} production plan(s). Skipped {len(error_rows)} invalid row(s)." if error_rows else f"Imported {len(created)} production plan(s).",
        "orders": [{"id": o.id, "order_no": o.order_no, "model": o.product.model if o.product else (o.product_id)} for o in created],
        "skipped_rows": len(error_rows),
        "errors": error_rows,
    }


@router.get("/import/template")
def download_production_import_template():
    """Download a blank Production Plan import template (CSV)."""
    import csv
    import io
    from fastapi.responses import StreamingResponse

    headers = ["Item Code", "Model", "Customer", "Schedule", "Ask Till Date",
               "Production Qty", "% Comp", "Balance Qty", "Status", "Remarks"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    w.writerow(["SF001", "Stretch Film", "", "100", "", "50", "", "", "Planned", ""])
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode("utf-8-sig")),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=production_plan_template.csv"},
    )
