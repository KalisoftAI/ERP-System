"""Sales order management (CRUD + lifecycle + status sync with dispatch)."""
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import CurrentUser, AllStaff, ManagerOrAdmin
from ..crud import apply_updates, get_or_404, write_audit
from ..database import get_db
from ..models import (
    Customer, Dispatch, DispatchLine, EmailLog, EmailType, OrderStatus, OrderType,
    Product, ProductSourceType, ProductionOrder, PurchaseRequirement, SalesOrder,
    SalesOrderLine, Salesperson, StockMovement, MovementType,
)
from ..schemas import (
    EmailPreviewOut, EmailSendIn,
    SalesOrderCreate, SalesOrderLineIn, SalesOrderLineUpdate, SalesOrderOut,
    SalesOrderUpdate,
)
from ..services.business import inventory_map, sync_purchase_shortages
from ..services.customers import get_or_create_customer
from ..services.email_service import is_valid_email, mail_config_ok, send_email
from ..services.import_common import (
    build_column_map, cell_num, is_blank_row, parse_date_value, read_table, row_to_dict,
)
from ..services.stock_service import resolve_or_create_product
from datetime import date

router = APIRouter(prefix="/orders", tags=["orders"])


def _resolve_salesperson(db: Session, name: str) -> Salesperson | None:
    """Find an existing salesperson by typed name (case-insensitive), creating
    one only when the name is genuinely new. Manual entry mirrors the customer
    auto-create flow and never duplicates a current name."""
    name = (name or "").strip()
    if not name:
        return None
    existing = db.scalar(select(Salesperson)
                         .where(func.lower(Salesperson.name) == name.lower())
                         .order_by(Salesperson.id).limit(1))
    if existing:
        return existing
    sp = Salesperson(name=name)
    db.add(sp)
    db.flush()
    return sp


def _line_stock_status(order_type, product, ordered: float, dispatched: float,
                       available: float) -> dict:
    """Stock-check a single order line against REAL inventory."""
    balance = ordered - dispatched
    if balance <= 0:
        status = "FULFILLED" if balance == 0 else "OVER_FULFILLED"
        return {"balance_qty": balance, "available_stock": available,
                "shortage_qty": 0.0, "readiness": status, "ready": False}
    shortage = balance - available
    if available >= balance:
        return {"balance_qty": balance, "available_stock": available,
                "shortage_qty": 0.0, "readiness": "READY_FOR_DISPATCH", "ready": True}
    if product is not None:
        st = product.source_type
        if st == ProductSourceType.trading:
            return {"balance_qty": balance, "available_stock": available,
                    "shortage_qty": shortage, "readiness": "PURCHASE_REQUIRED", "ready": False}
        if st == ProductSourceType.manufactured:
            return {"balance_qty": balance, "available_stock": available,
                    "shortage_qty": shortage, "readiness": "PRODUCTION_REQUIRED", "ready": False}
    return {"balance_qty": balance, "available_stock": available,
            "shortage_qty": shortage, "readiness": "MANUAL_DECISION_REQUIRED", "ready": False}


_ORDER_STOCK_ORDER = ("PURCHASE_REQUIRED", "PRODUCTION_REQUIRED",
                      "MANUAL_DECISION_REQUIRED", "READY_FOR_DISPATCH",
                      "FULFILLED", "OVER_FULFILLED")


def _order_stock_status(readiness: list[str]) -> str:
    """Order-level stock status = the most blocking line state."""
    for s in _ORDER_STOCK_ORDER:
        if s in readiness:
            return s
    return "NO_LINES"


def _serialize_order(db: Session, o: SalesOrder) -> dict:
    customer = o.customer
    inv = inventory_map(db)
    lines = []
    for ln in o.lines:
        # dispatched quantity for this order line
        d_qty = db.scalar(
            select(func.coalesce(func.sum(DispatchLine.quantity), 0))
            .select_from(Dispatch)
            .join(DispatchLine, DispatchLine.dispatch_id == Dispatch.id)
            .where(Dispatch.sales_order_id == o.id)
        ) if o.order_type == OrderType.oem else 0.0
        ordered = float(ln.quantity or 0)
        disp = float(d_qty or 0)
        available = inv.get(ln.product_id, 0.0) if ln.product_id else 0.0
        st = _line_stock_status(o.order_type, ln.product, ordered, disp, available)
        lines.append({
            "id": ln.id, "product_id": ln.product_id, "description": ln.description,
            "item_code": ln.item_code or (ln.product.item_code if ln.product else "") or "",
            "quantity": ordered, "customer_po_no": ln.customer_po_no,
            "schedule_qty": ln.schedule_qty,
            "ask_till_date": ln.ask_till_date,
            "completion_pct": ln.completion_pct,
            "balance_qty": ln.balance_qty,
            "opening_stock": ln.opening_stock,
            "unit_price": float(ln.unit_price) if ln.unit_price is not None else None,
            "less": float(ln.less) if ln.less is not None else None,
            "amount": float(ln.amount) if ln.amount is not None else None,
            "dispatched_qty": disp,
            "available_stock": st["available_stock"],
            "shortage_qty": st["shortage_qty"],
            "readiness": st["readiness"],
            "ready": st["ready"],
            "fulfilment": st["readiness"].replace("_", " ").title(),
            "product": {"id": ln.product.id, "model": ln.product.model,
                        "item_code": ln.product.item_code, "category": ln.product.category.value,
                        "source_type": ln.product.source_type.value if ln.product.source_type else None}
            if ln.product else None,
        })
    dispatch_qty = db.scalar(
        select(func.coalesce(func.sum(Dispatch.dispatched_qty), 0)).where(Dispatch.sales_order_id == o.id)
    )
    return {
        "id": o.id, "order_no": o.order_no, "so_no": o.so_no or "",
        "customer_id": o.customer_id,
        "customer_name": o.customer_name or "",
        "customer_contact": o.customer_contact or "",
        "customer_email": o.customer_email or "",
        "order_date": o.order_date, "required_delivery_date": o.required_delivery_date,
        "order_type": o.order_type.value, "customer_po_no": o.customer_po_no,
        "salesperson": {"id": o.salesperson.id, "name": o.salesperson.name} if o.salesperson else None,
        "status": o.status.value, "total_value": float(o.total_value), "remarks": o.remarks,
        "created_at": o.created_at,
        "customer": {"id": customer.id, "name": customer.name}
        if customer else ({"name": o.customer_name} if o.customer_name else None),
        "lines": lines,
        "dispatch_qty": float(dispatch_qty or 0),
        "stock_status": _order_stock_status([l["readiness"] for l in lines]),
        "ready": all(l["ready"] for l in lines) and bool(lines),
    }


def _recalc_total(o: SalesOrder, lines: list[SalesOrderLine]):
    """Total Amount = Qty x Rate per line (authoritative). Less is recorded
    and displayed only; it never feeds the total (per business rule)."""
    for l in lines:
        if l.amount is None:
            l.amount = float(l.unit_price or 0) * float(l.quantity or 0)
    o.total_value = sum(float(l.amount or 0) for l in lines)


def _auto_status(o: SalesOrder):
    dispatch_total = o.total_value
    lines_total = sum(float(l.amount or 0) for l in o.lines)
    if o.status in (OrderStatus.completed, OrderStatus.cancelled):
        return


# ---------------------------------------------------------------------------
# Bulk import helpers
# ---------------------------------------------------------------------------
ORDER_IMPORT_ALIASES = {
    "customer": [
        "customer", "customer name", "cust name", "client", "party", "buyer",
        "customer_name", "cust_name", "client_name", "party_name",
    ],
    "so_no": [
        "so no", "so number", "so_no", "so number", "sales order no", "sales order number",
        "sales_order_no", "so", "order no", "order number", "order_no",
    ],
    "po_no": [
        "po no", "po number", "po_no", "po number", "purchase order no", "customer po",
        "customer_po", "po", "purchase_order_no", "po_no", "p.o. no", "p.o.",
    ],
    "item_code": [
        "item code", "itemcode", "item_code", "item no", "part code", "part no",
        "product code", "sku", "item", "code",
    ],
    "model": [
        "model", "product model", "model no", "model name", "description", "product",
        "size", "product_model", "model_name", "model_no",
    ],
    "schedule": [
        "schedule", "schedule qty", "schedule quantity", "qty", "quantity", "order qty",
        "scheduled qty", "order quantity", "schedule_qty", "scheduled_quantity",
        "scheduleqty", "qty.",
    ],
    "ask_till_date": [
        "ask till date", "ask_till_date", "ask till", "till date", "ask date",
        "asktilldate", "due date", "delivery date", "expected date", "promised date",
    ],
    "dispatch": [
        "dispatch", "dispatched", "dispatch qty", "dispatched qty", "dispatched quantity",
        "dispatch_qty", "dispatched_qty", "already dispatch", "already dispatched",
    ],
    "completion_pct": [
        "completion %", "completion pct", "% comp", "percent comp", "completion_percent",
        "completionpct", "% completion", "comp %", "completion", "percent complete",
    ],
    "balance_qty": [
        "balance qty", "balance quantity", "balance", "remaining qty", "remaining quantity",
        "balance_qty", "balanceqty", "pending qty", "pending quantity",
    ],
    "opening_stock": [
        "opening stock", "opening_stock", "opning stock", "open stock", "stock",
        "opening qty", "opening quantity", "openingstock", "current stock",
    ],
    "order_date": [
        "order date", "order_date", "date", "so date", "po date", "order dt",
    ],
    "order_type": [
        "order type", "order_type", "type", "so type", "order category",
    ],
    "unit_price": [
        "unit price", "unit_price", "rate", "price", "unit rate", "sale price",
    ],
    "salesperson": [
        "salesperson", "sales person", "salesman", "sales rep", "sales officer",
        "sales_person", "salesrep",
    ],
    "remarks": [
        "remarks", "note", "notes", "comment", "comments", "narration",
    ],
}


def _t(value) -> str:
    return "" if value is None else str(value).strip()


def _parse_pct(value) -> float | None:
    """Parse a percentage value that may be 0-1 (fraction) or 0-100 (percent)."""
    if value is None or value == "":
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v < 0:
        return 0.0
    if v > 1:
        return round(v / 100, 4)
    return round(v, 4)


def _parse_order_type(value) -> OrderType:
    if value is None or value == "":
        return OrderType.trading
    v = str(value).strip().upper()
    if v in ("OEM", "MANUFACTURING", "MANUFACTURE"):
        return OrderType.oem
    if v in ("TRADING", "TRADE"):
        return OrderType.trading
    if v in ("LOCAL"):
        return OrderType.local
    return OrderType.trading


def _resolve_import_salesperson(db: Session, name: str) -> Salesperson | None:
    """Reuse the existing salesperson resolver for imports."""
    return _resolve_salesperson(db, name)


def _resolve_import_product(db: Session, item_code: str, model: str) -> Product | None:
    """Resolve a product for import. Item code is authoritative; model is
    used as the product description. When no item code is supplied, model is
    used to create a unique stock-trackable placeholder."""
    ic = (item_code or "").strip()
    md = (model or "").strip()
    if not ic and not md:
        return None
    if ic:
        return resolve_or_create_product(db, ic, md)
    # No item code but model provided: create a unique placeholder product.
    return resolve_or_create_product(db, "", md, allow_blank=True)


def _detect_duplicate_order(db: Session, customer_id: int | None, so_no: str,
                            po_no: str, order_date: date, line_signatures: list[dict]) -> SalesOrder | None:
    """Return an existing order that matches the key identifiers.

    Matching is conservative: same customer + same SO + same PO + same date.
    If SO is blank, PO must match. Line signatures are checked loosely by
    product/item code so a re-upload of an already-imported file is caught.
    """
    if not customer_id:
        return None
    stmt = select(SalesOrder).where(
        SalesOrder.customer_id == customer_id,
        SalesOrder.order_date == order_date,
    )
    if (so_no or "").strip():
        stmt = stmt.where(SalesOrder.order_no == so_no.strip())
    elif (po_no or "").strip():
        stmt = stmt.where(SalesOrder.customer_po_no == po_no.strip())
    else:
        # No SO and no PO is too vague to call a duplicate.
        return None

    candidates = db.scalars(stmt).all()
    if not candidates:
        return None

    # Prefer exact match on any line signature.
    sigs = {(s.get("product_id"), (s.get("item_code") or "").strip().lower(),
             (s.get("model") or "").strip().lower()) for s in line_signatures}
    for cand in candidates:
        for ln in cand.lines:
            key = (
                ln.product_id,
                (ln.item_code or "").strip().lower(),
                ((ln.product.model if ln.product else None) or ln.description or "").strip().lower(),
            )
            if key in sigs:
                return cand
    # If no line matched but SO+PO+date+customer matched, still flag as duplicate.
    return candidates[0]


def _lookup_import_customer(db: Session, name: str) -> Customer | None:
    """Lookup-only customer resolution for preview (no creation)."""
    if not name:
        return None
    return db.scalars(
        select(Customer).where(func.lower(Customer.name) == name.lower()).limit(1)
    ).first()


def _lookup_import_product(db: Session, item_code: str, model: str) -> Product | None:
    """Lookup-only product resolution for preview (no creation)."""
    ic = (item_code or "").strip()
    md = (model or "").strip()
    if not ic and not md:
        return None
    if ic:
        p = db.scalars(select(Product).where(Product.item_code == ic).limit(1)).first()
        if p:
            return p
    if md:
        p = db.scalars(select(Product).where(Product.model == md).limit(1)).first()
        if p:
            return p
    return None


def _parse_import_rows(db: Session, headers: list[str], rows: list[list[Any]], filename: str, resolve: bool = False):
    colmap = build_column_map(headers, ORDER_IMPORT_ALIASES)
    mapped_headers = {canon: headers[idx] for idx, canon in colmap.items()}

    parsed: list[dict] = []
    errors: list[dict] = []
    warnings: list[dict] = []

    for r_i, raw in enumerate(rows):
        mapped = row_to_dict(colmap, raw)
        if is_blank_row(mapped):
            continue
        row_no = r_i + 2  # 1-based header + data offset
        row_errs: list[str] = []
        row_warns: list[str] = []

        customer_name = _t(mapped.get("customer"))
        so_no = _t(mapped.get("so_no"))
        po_no = _t(mapped.get("po_no"))
        item_code = _t(mapped.get("item_code"))
        model = _t(mapped.get("model"))
        schedule = cell_num(mapped.get("schedule"))
        order_date = parse_date_value(mapped.get("order_date")) or date.today()
        ask_till = cell_num(mapped.get("ask_till_date"))
        dispatch = cell_num(mapped.get("dispatch"))
        pct = _parse_pct(mapped.get("completion_pct"))
        balance = cell_num(mapped.get("balance_qty"))
        opening = cell_num(mapped.get("opening_stock"))
        unit_price = cell_num(mapped.get("unit_price"))
        order_type = _parse_order_type(mapped.get("order_type"))
        salesperson = _t(mapped.get("salesperson"))
        remarks = _t(mapped.get("remarks"))

        if not customer_name:
            row_errs.append("Customer is required")
        if not item_code and not model:
            row_errs.append("Item Code or Model is required")
        if schedule is None or schedule <= 0:
            row_errs.append("Schedule/Quantity must be a positive number")
        if mapped.get("order_date") and parse_date_value(mapped.get("order_date")) is None:
            row_errs.append("Order Date is not a valid date")

        # Resolve customer & product (lookup only in preview, create during import).
        customer = None
        product = None
        if customer_name:
            if resolve:
                customer = get_or_create_customer(db, customer_name)
            else:
                customer = _lookup_import_customer(db, customer_name)
                if customer is None:
                    row_warns.append(f"Customer '{customer_name}' not found; a new customer will be created")
        if item_code or model:
            if resolve:
                product = _resolve_import_product(db, item_code, model)
            else:
                product = _lookup_import_product(db, item_code, model)
                if product is None:
                    row_warns.append("Product not found; a new product will be created if Item Code or Model is provided")
            if product and model and not item_code:
                if product.model.lower() != model.lower():
                    row_warns.append(f"Model '{model}' linked to existing product '{product.model}'")

        if pct is not None and pct > 1:
            row_warns.append("Completion % treated as >1 and normalised")

        row_out = {
            "row": row_no,
            "customer_name": customer_name,
            "customer_id": customer.id if customer else None,
            "so_no": so_no,
            "po_no": po_no,
            "item_code": item_code,
            "model": model,
            "product_id": product.id if product else None,
            "quantity": schedule,
            "schedule_qty": schedule,
            "ask_till_date": ask_till,
            "dispatch": dispatch,
            "completion_pct": pct,
            "balance_qty": balance,
            "opening_stock": opening,
            "order_date": order_date.isoformat(),
            "order_type": order_type.value,
            "unit_price": unit_price,
            "salesperson": salesperson,
            "remarks": remarks,
            "errors": row_errs,
            "warnings": row_warns,
        }

        if row_errs:
            errors.append(row_out)
        else:
            parsed.append(row_out)
            if row_warns:
                warnings.append(row_out)

    # --- group valid rows into candidate orders and detect duplicates ---
    duplicate_orders: list[dict] = []
    for row in parsed:
        dup = _detect_duplicate_order(
            db,
            row["customer_id"],
            row["so_no"],
            row["po_no"],
            date.fromisoformat(row["order_date"]),
            [{"product_id": row["product_id"], "item_code": row["item_code"], "model": row["model"]}],
        )
        if dup:
            row["duplicate_of"] = {"order_id": dup.id, "order_no": dup.order_no}
            duplicate_orders.append(row)

    sample = parsed[:10] + errors[:5]
    return {
        "file_name": filename,
        "total_rows": len(parsed) + len(errors),
        "valid_rows": len(parsed),
        "error_rows": len(errors),
        "warning_rows": len(warnings),
        "duplicate_rows": len(duplicate_orders),
        "mapped_columns": mapped_headers,
        "sample_rows": sample,
        "errors": errors,
        "warnings": warnings,
        "parsed": parsed,
        "can_import": len(parsed) > 0,
    }


def _create_orders_from_rows(db: Session, rows: list[dict], user: AllStaff):
    """Group rows into orders and persist them. Opening stock stays as order
    data only — no inventory movement is created."""
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        key = (
            row["customer_id"],
            row["so_no"],
            row["po_no"],
            row["order_date"],
            row["order_type"],
        )
        # Rows with no SO and no PO are grouped by customer+date+type.
        if not row["so_no"] and not row["po_no"]:
            key = (row["customer_id"], "", "", row["order_date"], row["order_type"])
        groups.setdefault(key, []).append(row)

    created: list[dict] = []
    skipped: list[dict] = []

    for (customer_id, so_no, po_no, order_date_str, order_type), grp in groups.items():
        order_date = date.fromisoformat(order_date_str)
        customer = db.get(Customer, customer_id) if customer_id else None
        salesperson_name = _t(grp[0].get("salesperson"))
        salesperson = _resolve_import_salesperson(db, salesperson_name) if salesperson_name else None

        o = SalesOrder(
            order_no=so_no,
            customer_id=customer.id if customer else None,
            customer_name=customer.name if customer else (grp[0]["customer_name"] if grp else ""),
            order_type=OrderType(order_type),
            customer_po_no=po_no,
            salesperson_id=salesperson.id if salesperson else None,
            order_date=order_date,
            remarks=_t(grp[0].get("remarks")),
            status=OrderStatus.new,
        )
        lines: list[SalesOrderLine] = []
        for row in grp:
            product = db.get(Product, row["product_id"]) if row["product_id"] else None
            description = row["model"] or (product.model if product else "")
            qty = float(row["quantity"] or 0)
            rate = row["unit_price"]
            amount = (rate * qty) if rate is not None else None
            lines.append(SalesOrderLine(
                product_id=product.id if product else None,
                description=description,
                item_code=row["item_code"],
                quantity=qty,
                schedule_qty=row["schedule_qty"] if row["schedule_qty"] is not None else qty,
                ask_till_date=row["ask_till_date"],
                completion_pct=row["completion_pct"],
                balance_qty=row["balance_qty"],
                opening_stock=row["opening_stock"],
                unit_price=rate,
                amount=amount,
            ))
        o.lines = lines
        _recalc_total(o, lines)
        db.add(o)
        db.flush()
        created.append({
            "order_id": o.id,
            "order_no": o.order_no,
            "customer": customer.name if customer else o.customer_name,
            "lines": len(lines),
            "order_date": o.order_date.isoformat(),
        })
        write_audit(db, user, "IMPORT", "sales_orders", o.id,
                    f"Bulk-imported {o.order_type.value} order {o.order_no} ({len(lines)} lines)")

    sync_purchase_shortages(db)
    return created, skipped


@router.get("", response_model=dict)
def list_orders(
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
    search: str = "",
    status_: str = Query(default="", alias="status"),
    order_type: str = Query(default="", alias="order_type"),
    exclude_order_type: str = Query(default="", alias="exclude_order_type"),
    customer_id: int | None = None,
    date_from: str = "",
    date_to: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
):
    stmt = select(SalesOrder)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(SalesOrder.order_no.ilike(like))
    if status_:
        stmt = stmt.where(SalesOrder.status == status_)
    if order_type:
        try:
            stmt = stmt.where(SalesOrder.order_type == OrderType[order_type.lower()])
        except KeyError:
            pass
    if exclude_order_type:
        try:
            stmt = stmt.where(SalesOrder.order_type != OrderType[exclude_order_type.lower()])
        except KeyError:
            pass
    if customer_id:
        stmt = stmt.where(SalesOrder.customer_id == customer_id)
    if date_from:
        stmt = stmt.where(SalesOrder.order_date >= date.fromisoformat(date_from))
    if date_to:
        stmt = stmt.where(SalesOrder.order_date <= date.fromisoformat(date_to))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(SalesOrder.order_date.desc(), SalesOrder.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_serialize_order(db, o) for o in rows],
            "total": total, "page": page, "page_size": page_size}


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_order(body: SalesOrderCreate, db: Annotated[Session, Depends(get_db)],
                 user: AllStaff):
    if body.customer_id is None and not (body.customer_name or "").strip():
        raise HTTPException(status_code=400, detail="Customer is required (select an existing one or type a name)")
    if not (body.order_no or "").strip():
        raise HTTPException(status_code=400, detail="SO Number is required (enter the actual Sales Order number)")
    if not body.lines:
        raise HTTPException(status_code=400, detail="Add at least one order line")
    for ln in body.lines:
        if ln.product_id is None and not (ln.description or "").strip():
            raise HTTPException(status_code=400, detail="Each order line needs a product or a description")
        if (ln.quantity or 0) <= 0:
            raise HTTPException(status_code=400, detail="Each order line needs a quantity greater than 0")
    if body.customer_id is not None and not db.get(Customer, body.customer_id):
        raise HTTPException(status_code=400, detail=f"Customer {body.customer_id} not found")
    # A typed new customer is promoted into the central customer master.
    if body.customer_id is None and (body.customer_name or "").strip():
        c = get_or_create_customer(db, body.customer_name)
        body.customer_id = c.id if c else None
        body.customer_name = c.name if c else body.customer_name
    # A manually typed salesperson is resolved/reused (no duplicates).
    salesperson_id = body.salesperson_id
    if not salesperson_id and (body.salesperson_name or "").strip():
        sp = _resolve_salesperson(db, body.salesperson_name)
        salesperson_id = sp.id if sp else None
    lines = [SalesOrderLine(**ln.model_dump()) for ln in body.lines]
    order_no = (body.order_no or "").strip()[:120]
    o = SalesOrder(order_no=order_no,
                   so_no=order_no,
                   customer_id=body.customer_id,
                   customer_name=(body.customer_name or "").strip(),
                   customer_contact=(body.customer_contact or "").strip()[:60],
                   customer_email=(body.customer_email or "").strip()[:160],
                   order_type=body.order_type, customer_po_no=body.customer_po_no,
                   salesperson_id=salesperson_id,
                   order_date=body.order_date, required_delivery_date=body.required_delivery_date,
                   status=body.status, remarks=body.remarks, lines=lines)
    _recalc_total(o, lines)
    db.add(o)
    db.commit()
    db.refresh(o)
    write_audit(db, user, "CREATE", "sales_orders", o.id, f"Created {o.order_type.value} order {o.order_no}")
    sync_purchase_shortages(db)
    return _serialize_order(db, o)


@router.get("/pending", response_model=dict)
def pending_orders(
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
    mode: str = Query(default="all", alias="mode"),  # all | current | previous
    order_type: str = Query(default="", alias="order_type"),
    customer_id: int | None = None,
):
    """Pending PO / order ledger: ordered vs dispatched; balance determines
    Pending (>0, not yet dispatched), Partially Dispatched (>0, partly sent),
    Completed/Closed (=0), Over-fulfilled (<0). Negative balance is valid
    business data (over-dispatch preserved). 'current' = orders dated in the
    present calendar month (dynamic, no hard-coded year/month); 'previous' =
    anything before the current month (carried-forward pending balance)."""
    today = date.today()
    month_start = today.replace(day=1)
    next_month = (month_start.replace(year=month_start.year + 1, month=1)
                  if month_start.month == 12
                  else month_start.replace(month=month_start.month + 1))
    stmt = select(SalesOrder, SalesOrderLine)
    stmt = stmt.join(SalesOrderLine, SalesOrderLine.order_id == SalesOrder.id)
    if customer_id:
        stmt = stmt.where(SalesOrder.customer_id == customer_id)
    if order_type:
        try:
            stmt = stmt.where(SalesOrder.order_type == OrderType[order_type.lower()])
        except KeyError:
            pass
    if mode == "current":
        stmt = stmt.where(SalesOrder.order_date >= month_start,
                          SalesOrder.order_date < next_month)
    elif mode == "previous":
        stmt = stmt.where(SalesOrder.order_date < month_start)
    stmt = stmt.order_by(SalesOrder.order_date.desc(), SalesOrder.id.desc())
    rows = db.execute(stmt).all()
    items = []
    for o, ln in rows:
        d_qty = db.scalar(
            select(func.coalesce(func.sum(DispatchLine.quantity), 0))
            .select_from(Dispatch)
            .join(DispatchLine, DispatchLine.dispatch_id == Dispatch.id)
            .where(Dispatch.sales_order_id == o.id)
        ) or 0.0
        ordered = float(ln.quantity or 0)
        disp = float(d_qty or 0)
        balance = ordered - disp
        if balance > 0:
            pstatus = "Partially Dispatched" if disp > 0 else "Pending"
        elif balance == 0:
            pstatus = "Completed (Closed)" if o.status in (
                OrderStatus.completed, OrderStatus.cancelled) else "Completed"
        else:
            pstatus = "Over-fulfilled"
        items.append({
            "order_id": o.id, "order_no": o.order_no, "order_type": o.order_type.value,
            "customer_id": o.customer_id, "customer": o.customer.name if o.customer else None,
            "order_date": o.order_date, "period": f"{o.order_date.year}-{o.order_date.month:02d}",
            "line_id": ln.id, "product_id": ln.product_id,
            "model": ln.product.model if ln.product else None,
            "item_code": ln.product.item_code if ln.product else (ln.description or ""),
            "customer_po_no": ln.customer_po_no or o.customer_po_no or "",
            "ordered_qty": ordered, "dispatched_qty": disp, "balance_qty": balance,
            "status": pstatus,
        })
    return {"items": items, "total": len(items), "mode": mode,
            "current_month": f"{month_start.year}-{month_start.month:02d}"}


@router.get("/{order_id}", response_model=dict)
def get_order(order_id: int, db: Annotated[Session, Depends(get_db)],
              _: CurrentUser):
    return _serialize_order(db, get_or_404(db, SalesOrder, order_id))


@router.patch("/lines/{line_id}", response_model=dict)
def update_order_line(line_id: int, body: SalesOrderLineUpdate,
                      db: Annotated[Session, Depends(get_db)], user: AllStaff):
    """Edit a single order line's permitted fields. Dispatch/Balance remain
    transaction-derived and are never directly editable. Purchase requirements
    + team alerts are re-synced after the change."""
    ln = get_or_404(db, SalesOrderLine, line_id)
    o = get_or_404(db, SalesOrder, ln.order_id)
    fields = body.model_fields_set
    if "product_id" in fields:
        ln.product_id = body.product_id
    if body.description is not None:
        ln.description = body.description
    if body.item_code is not None:
        ln.item_code = (body.item_code or "").strip()[:120]
    if body.quantity is not None:
        ln.quantity = body.quantity
    if body.schedule_qty is not None:
        ln.schedule_qty = body.schedule_qty
    if body.ask_till_date is not None:
        ln.ask_till_date = body.ask_till_date
    if body.completion_pct is not None:
        ln.completion_pct = body.completion_pct
    if body.balance_qty is not None:
        ln.balance_qty = body.balance_qty
    if body.opening_stock is not None:
        ln.opening_stock = body.opening_stock
    if body.unit_price is not None:
        ln.unit_price = body.unit_price
    if body.less is not None:
        ln.less = body.less
    if body.amount is not None:
        ln.amount = body.amount
    if body.customer_po_no is not None:
        ln.customer_po_no = body.customer_po_no
    _recalc_total(o, o.lines)
    db.commit()
    db.refresh(o)
    write_audit(db, user, "UPDATE", "sales_order_lines", line_id,
                f"Updated line {line_id} on order {o.order_no}")
    sync_purchase_shortages(db)
    return _serialize_order(db, o)


@router.patch("/{order_id}", response_model=dict)
def update_order(order_id: int, body: SalesOrderUpdate, db: Annotated[Session, Depends(get_db)],
                 user: AllStaff):
    o = get_or_404(db, SalesOrder, order_id)
    if "order_no" in body.model_fields_set and not (body.order_no or "").strip():
        raise HTTPException(status_code=400, detail="SO Number is required and cannot be blank")
    apply_updates(o, body, exclude={"lines"})
    if "order_no" in body.model_fields_set:
        o.so_no = (body.order_no or "").strip()[:120]
    if (body.customer_name or "").strip():
        c = get_or_create_customer(db, body.customer_name)
        if c:
            o.customer_id = c.id
            o.customer_name = c.name
    # Salesperson: explicit id wins; otherwise a typed name is reused/created.
    if body.salesperson_id is not None:
        o.salesperson_id = body.salesperson_id
    elif (body.salesperson_name or "").strip():
        sp = _resolve_salesperson(db, body.salesperson_name)
        o.salesperson_id = sp.id if sp else None
    if body.lines is not None:
        for ln in o.lines:
            used = db.scalar(select(func.count()).select_from(DispatchLine)
                             .where(DispatchLine.sales_order_line_id == ln.id)) or 0
            if used:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                    detail=f"Line '{ln.description or ln.id}' already has dispatch entries and cannot be removed")
        db.query(SalesOrderLine).filter(SalesOrderLine.order_id == o.id).delete()
        lines = [SalesOrderLine(**ln.model_dump()) for ln in body.lines]
        o.lines = lines
        _recalc_total(o, lines)
    db.commit()
    db.refresh(o)
    write_audit(db, user, "UPDATE", "sales_orders", o.id, f"Updated order {o.order_no}")
    sync_purchase_shortages(db)
    return _serialize_order(db, o)


@router.post("/{order_id}/status", response_model=dict)
def set_order_status(order_id: int, order_status: OrderStatus,
                     db: Annotated[Session, Depends(get_db)], user: AllStaff):
    o = get_or_404(db, SalesOrder, order_id)
    o.status = order_status
    db.commit()
    db.refresh(o)
    write_audit(db, user, "STATUS", "sales_orders", o.id, f"Order {o.order_no} -> {order_status.value}")
    sync_purchase_shortages(db)
    return _serialize_order(db, o)


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_order(order_id: int, db: Annotated[Session, Depends(get_db)],
                 user: ManagerOrAdmin):
    o = get_or_404(db, SalesOrder, order_id)
    refs = []
    if db.scalar(select(func.count()).select_from(Dispatch).where(Dispatch.sales_order_id == o.id)):
        refs.append("dispatches")
    if db.scalar(select(func.count()).select_from(PurchaseRequirement)
                 .where(PurchaseRequirement.sales_order_id == o.id)):
        refs.append("purchase requirements")
    if db.scalar(select(func.count()).select_from(ProductionOrder)
                 .where(ProductionOrder.sales_order_id == o.id)):
        refs.append("production orders")
    if refs:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"Cannot delete order: referenced by existing {' and '.join(refs)}.")
    db.delete(o)
    db.commit()
    write_audit(db, user, "DELETE", "sales_orders", order_id, f"Deleted order {o.order_no}")
    sync_purchase_shortages(db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/import-preview", response_model=dict)
async def preview_order_import(
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
    file: UploadFile = File(...),
):
    """Parse a CSV/Excel order upload and return a preview with validation,
    mapping info, and duplicate warnings. Nothing is persisted."""
    content = await file.read()
    try:
        headers, rows = read_table(file.filename or "upload.xlsx", content)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if not rows:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No data rows found in file")

    preview = _parse_import_rows(db, headers, rows, file.filename or "upload")
    # Do not persist anything; rollback any incidental DB state.
    db.rollback()
    # Remove parsed data from response (keep only preview fields).
    return {
        "file_name": preview["file_name"],
        "total_rows": preview["total_rows"],
        "valid_rows": preview["valid_rows"],
        "error_rows": preview["error_rows"],
        "warning_rows": preview["warning_rows"],
        "duplicate_rows": preview["duplicate_rows"],
        "mapped_columns": preview["mapped_columns"],
        "sample_rows": preview["sample_rows"],
        "errors": preview["errors"],
        "warnings": preview["warnings"],
        "can_import": preview["can_import"],
    }


@router.post("/import", response_model=dict)
async def import_orders(
    db: Annotated[Session, Depends(get_db)],
    user: AllStaff,
    file: UploadFile = File(...),
    confirm_duplicates: bool = Query(False, description="Import rows even if they appear to duplicate existing orders"),
):
    """Bulk-create sales orders from a CSV/Excel upload."""
    content = await file.read()
    try:
        headers, rows = read_table(file.filename or "upload.xlsx", content)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if not rows:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No data rows found in file")

    preview = _parse_import_rows(db, headers, rows, file.filename or "upload", resolve=True)
    valid = [r for r in preview["parsed"] if not r["errors"]]

    if preview["duplicate_rows"] and not confirm_duplicates:
        db.rollback()
        dup_details = [
            {"row": r["row"], "so_no": r["so_no"], "po_no": r["po_no"],
             "customer": r["customer_name"], "existing_order_id": r["duplicate_of"]["order_id"]}
            for r in valid if r.get("duplicate_of")
        ]
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": f"{preview['duplicate_rows']} row(s) appear to duplicate existing orders. Confirm to import anyway.",
                "duplicates": dup_details,
            },
        )

    created, skipped = _create_orders_from_rows(db, valid, user)
    db.commit()
    return {
        "summary": {
            "total_rows": preview["total_rows"],
            "valid_rows": len(valid),
            "created_orders": len(created),
            "skipped_rows": len(skipped),
            "errors": len(preview["errors"]),
        },
        "created": created,
        "skipped": skipped,
        "errors": preview["errors"],
    }


# ---------------------------------------------------------------------------
# Email helpers and endpoints
# ---------------------------------------------------------------------------

def _order_default_recipient(o: SalesOrder, customer: Customer | None) -> str:
    return (o.customer_email or "").strip() or (customer.email or "").strip() if customer else (o.customer_email or "").strip()


def _confirmation_subject(o: SalesOrder) -> str:
    ref = o.so_no or o.customer_po_no or o.order_no or f"#{o.id}"
    return f"Order Confirmation - {ref}"


def _dispatch_subject(o: SalesOrder, d: Dispatch) -> str:
    ref = o.so_no or o.customer_po_no or o.order_no or f"#{o.id}"
    return f"Dispatch Notification - {ref}"


def _format_lines(lines: list[SalesOrderLine]) -> str:
    out = []
    for ln in lines:
        item = (ln.item_code or (ln.product.item_code if ln.product else "")) or "—"
        model = (ln.product.model if ln.product else None) or ln.description or "—"
        out.append(
            f"Item Code: {item}\n"
            f"Model: {model}\n"
            f"Schedule: {ln.schedule_qty if ln.schedule_qty is not None else ln.quantity}\n"
            f"Ask Till Date: {ln.ask_till_date if ln.ask_till_date is not None else '—'}\n"
        )
    return "\n".join(out)


def _build_confirmation_body(o: SalesOrder, customer: Customer | None) -> str:
    customer_name = customer.name if customer else o.customer_name or "—"
    body = (
        f"Dear Customer,\n\n"
        f"Please find your order confirmation below:\n\n"
        f"Customer: {customer_name}\n"
        f"PO No: {o.customer_po_no or '—'}\n"
        f"SO No: {o.so_no or '—'}\n"
        f"Order Date: {o.order_date or '—'}\n\n"
        f"Line Details:\n{_format_lines(o.lines)}\n\n"
        f"Regards,\nKalika Enterprises"
    )
    return body


def _build_dispatch_body(o: SalesOrder, d: Dispatch, customer: Customer | None) -> str:
    customer_name = customer.name if customer else o.customer_name or "—"
    po_no = o.customer_po_no or "—"
    so_no = o.so_no or "—"
    remaining = d.balance_qty if d.balance_qty is not None else (d.schedule_qty - d.dispatched_qty)

    lines_text = []
    for ln in d.lines:
        item = (ln.product.item_code if ln.product else None) or "—"
        model = (ln.product.model if ln.product else None) or ln.description or "—"
        lines_text.append(
            f"Item Code: {item}\n"
            f"Model: {model}\n"
            f"Dispatch Qty: {ln.quantity}\n"
            f"Dispatch Date: {ln.dispatch_date or d.dispatch_date or '—'}\n"
        )

    body = (
        f"Dear Customer,\n\n"
        f"We are pleased to inform you that a dispatch has been made:\n\n"
        f"Customer: {customer_name}\n"
        f"PO No: {po_no}\n"
        f"SO No: {so_no}\n\n"
        f"Dispatch Details:\n{''.join(lines_text)}\n"
        f"Remaining Balance: {remaining}\n\n"
        f"Regards,\nKalika Enterprises"
    )
    return body


def _log_email(db: Session, email_type: EmailType, recipient: str, subject: str,
               status: str, error: str = "", sales_order_id: int | None = None,
               dispatch_id: int | None = None):
    log = EmailLog(
        email_type=email_type,
        recipient=recipient.strip(),
        subject=subject.strip(),
        status=status,
        error_message=error,
        sales_order_id=sales_order_id,
        dispatch_id=dispatch_id,
    )
    db.add(log)
    db.flush()


@router.get("/{order_id}/email-preview/confirmation", response_model=EmailPreviewOut)
def preview_order_confirmation(
    order_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
):
    o = get_or_404(db, SalesOrder, order_id)
    customer = db.get(Customer, o.customer_id) if o.customer_id else None
    return {
        "to": _order_default_recipient(o, customer),
        "subject": _confirmation_subject(o),
        "message": _build_confirmation_body(o, customer),
    }


@router.post("/{order_id}/send-confirmation", response_model=dict)
def send_order_confirmation(
    order_id: int,
    body: EmailSendIn,
    db: Annotated[Session, Depends(get_db)],
    user: AllStaff,
):
    o = get_or_404(db, SalesOrder, order_id)
    if not is_valid_email(body.to):
        detail = f"Invalid recipient email address: {body.to}"
        _log_email(db, EmailType.order_confirmation, body.to, body.subject, "failed", detail, sales_order_id=o.id)
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    ok, err = mail_config_ok()
    if not ok:
        _log_email(db, EmailType.order_confirmation, body.to, body.subject, "failed", err, sales_order_id=o.id)
        db.commit()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=err)

    success, error = send_email(body.to, body.subject, body.message)
    status_ = "sent" if success else "failed"
    _log_email(db, EmailType.order_confirmation, body.to, body.subject, status_, error, sales_order_id=o.id)
    db.commit()

    if not success:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=error)

    write_audit(db, user, "SEND_EMAIL", "sales_orders", o.id,
                f"Sent order confirmation email to {body.to}")
    db.commit()
    return {"success": True, "message": "Order confirmation email sent."}


@router.get("/{order_id}/email-preview/dispatch/{dispatch_id}", response_model=EmailPreviewOut)
def preview_dispatch_email(
    order_id: int,
    dispatch_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
):
    o = get_or_404(db, SalesOrder, order_id)
    d = db.get(Dispatch, dispatch_id)
    if d is None or d.sales_order_id != o.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispatch not found for this order")
    customer = db.get(Customer, o.customer_id) if o.customer_id else None
    return {
        "to": _order_default_recipient(o, customer),
        "subject": _dispatch_subject(o, d),
        "message": _build_dispatch_body(o, d, customer),
    }


@router.post("/{order_id}/send-dispatch-email/{dispatch_id}", response_model=dict)
def send_dispatch_email(
    order_id: int,
    dispatch_id: int,
    body: EmailSendIn,
    db: Annotated[Session, Depends(get_db)],
    user: AllStaff,
):
    o = get_or_404(db, SalesOrder, order_id)
    d = db.get(Dispatch, dispatch_id)
    if d is None or d.sales_order_id != o.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispatch not found for this order")

    if not is_valid_email(body.to):
        detail = f"Invalid recipient email address: {body.to}"
        _log_email(db, EmailType.dispatch_email, body.to, body.subject, "failed", detail, sales_order_id=o.id, dispatch_id=d.id)
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    ok, err = mail_config_ok()
    if not ok:
        _log_email(db, EmailType.dispatch_email, body.to, body.subject, "failed", err, sales_order_id=o.id, dispatch_id=d.id)
        db.commit()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=err)

    success, error = send_email(body.to, body.subject, body.message)
    status_ = "sent" if success else "failed"
    _log_email(db, EmailType.dispatch_email, body.to, body.subject, status_, error, sales_order_id=o.id, dispatch_id=d.id)
    db.commit()

    if not success:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=error)

    write_audit(db, user, "SEND_EMAIL", "dispatches", d.id,
                f"Sent dispatch email to {body.to} for order {o.order_no}")
    db.commit()
    return {"success": True, "message": "Dispatch email sent."}


@router.get("/{order_id}/email-history", response_model=dict)
def email_history(
    order_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
):
    get_or_404(db, SalesOrder, order_id)
    rows = db.scalars(
        select(EmailLog)
        .where(EmailLog.sales_order_id == order_id)
        .order_by(EmailLog.sent_at.desc())
    ).all()
    return {
        "items": [
            {
                "id": r.id,
                "email_type": r.email_type.value,
                "recipient": r.recipient,
                "subject": r.subject,
                "status": r.status,
                "error_message": r.error_message,
                "sent_at": r.sent_at.isoformat() if r.sent_at else None,
            }
            for r in rows
        ],
        "total": len(rows),
    }