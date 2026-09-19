"""Local Orders - complete live workflow.

Local Orders are SalesOrder(order_type=LOCAL) + SalesOrderLine. This router:
  * Customer: manual name auto-creates/reuses the central Customer master.
  * Order Type (TRADING / MANUFACTURING) with per-type downstream routing on
    insufficient stock (Purchase vs Production requirement).
  * Size/Description, Order Qty, Rate, Less (stored as entered), Delivery Date,
    Total Amount (line Amount = Qty x Rate - authoritative backend calc, Less
    never subtracted).
  * Stock check at the Dispatch location -> "Ready for Dispatch" or the
    Trading/Manufacturing requirement path.
  * Partial dispatch is handled by the existing sales-order-driven Dispatch
    module (date-wise entries, edit/delete with stock reversal, per-line
    attribution via DispatchLine.sales_order_line_id). Pending is always derived
    from actual data; editing an order never overwrites dispatch history.
"""
import csv
import io
import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import Integer, delete, func, or_, select, update
from sqlalchemy.orm import Session

from ..auth import CurrentUser, AllStaff, ManagerOrAdmin
from ..crud import write_audit
from ..database import get_db
from ..models import (
    Customer, Dispatch, DispatchLine, ImportBatch, OrderStatus, OrderType, Plan,
    Product, ProductionOrder, PurchaseRequirement, SalesOrder,
    SalesOrderLine,
)
from ..schemas import LocalOrderCreate, LocalOrderUpdate
from ..services import reorder_alerts as re_alerts
from ..services.customers import get_or_create_customer
from ..services.import_common import (
    build_column_map, cell_num, is_blank_row, parse_date_value,
    read_table, row_to_dict,
)
from ..services.local_orders import (
    check_ready, normalize_local_type, serialize_local_order,
    sync_local_order_status,
)
from ..services.stock_service import resolve_or_create_product
from datetime import date

router = APIRouter(prefix="/local-orders", tags=["local-orders"])


def _local_no(db: Session) -> str:
    prefix = f"LOC-{date.today().strftime('%Y%m%d')}-"
    n = db.scalar(select(func.max(func.cast(func.substr(SalesOrder.order_no, len(prefix) + 1), Integer)))
                  .where(SalesOrder.order_no.like(f"{prefix}%"))) or 0
    return f"{prefix}{n + 1:03d}"


def _t(v) -> str:
    """Trim helper for imported text (None -> '', whitespace trimmed)."""
    return (v or "").strip()


LO_HEADER_ALIASES = {
    "customer": ["customer", "customer name", "party", "party name", "buyer",
                 "buyer name", "name"],
    "mobile": ["mobile", "mobile number", "mobile no", "phone", "phone number",
               "contact", "phone no"],
    "email": ["email", "email id", "email address", "mail"],
    "so_no": ["so number", "so no", "so", "sales order no", "sales order number"],
    "po_no": ["po number", "po no", "po", "customer po", "customer po no",
              "customer po number", "customer order no"],
    "order_type": ["order type", "local order type", "type"],
    "order_date": ["order date", "date", "date of order", "booking date"],
    "delivery_date": ["delivery date", "delivery", "required delivery date",
                      "required date", "due date", "delivery due date"],
    "item_code": ["item code", "itemcode", "code", "product code", "product id",
                  "item no"],
    "description": ["description", "size description", "size", "item", "item name",
                    "model", "material", "particulars", "product", "product name",
                    "article", "size / description"],
    "quantity": ["quantity", "qty", "order qty", "ordered qty", "quantity ordered",
                 "qty ordered"],
    "uom": ["uom", "unit", "units", "unit of measure"],
    "rate": ["rate", "unit rate", "price", "unit price", "rate per unit"],
    "less": ["less", "discount", "discount amount", "disc", "less percent",
             "deduction"],
    "remarks": ["remarks", "remark", "notes", "note", "narration", "commitment"],
}


def _csv_response(headers, rows, filename):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    w.writerows(rows)
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode("utf-8-sig")),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _recalc_local_total(db: Session, o: SalesOrder, lines: list[SalesOrderLine]):
    """Authoritative local-order pricing: Amount = Qty x Rate per line.
    Less is preserved but not subtracted (per business rule). Lines scheduled
    for deletion (replaced id-less) are excluded from the totals."""
    kept = [l for l in lines if l not in db.deleted]
    for l in kept:
        rate = float(l.unit_price or 0)
        l.amount = rate * float(l.quantity or 0)
    o.total_value = sum(float(l.amount or 0) for l in kept)


def _resolve_customer(db: Session, body) -> tuple[int | None, str]:
    """Customer id is authoritative when given; otherwise a typed name is
    promoted into the central Customer master (auto-created, case-insensitive)."""
    if body.customer_id is not None:
        c = db.get(Customer, body.customer_id)
        if c is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f"Customer {body.customer_id} not found")
        return c.id, c.name
    if not (body.customer_name or "").strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Customer is required — select one or enter a new name")
    c = get_or_create_customer(db, body.customer_name,
                               body.customer_mobile or "",
                               body.customer_email or "")
    return (c.id, c.name) if c else (None, body.customer_name.strip())


def _resolve_line_products(db: Session, raw_lines) -> list[tuple[int | None, dict]]:
    """Local order ROOT FIX: every line must map to a real Product.

    A line that already carries a product_id is trusted as-is (never text
    matched — "production never runs by description/name alone"). A product-less
    line is resolved to an existing or lazily-created Product keyed on
    (item_code, model); with no Item Code the description gets its own fresh
    Product so the line is stock-trackable. Returns (rid, normalized_payload)
    pairs with product_id and item_code always populated. Raises 400 when a line
    has nothing to key on.
    """
    out: list[tuple[int | None, dict]] = []
    for raw in raw_lines:
        rid = getattr(raw, "id", None)
        data = (raw.model_dump(exclude={"id"}, exclude_none=True)
                if hasattr(raw, "model_dump") else dict(raw))
        pid = data.get("product_id")
        if pid is not None:
            prod = db.get(Product, int(pid))
            if prod is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                    detail=f"Product {pid} not found")
        else:
            prod = resolve_or_create_product(
                db, data.get("item_code") or "", data.get("description") or "",
                allow_blank=True)
            if prod is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Each order line needs a product — select one or enter an item code / size description")
        data["product_id"] = prod.id
        data["item_code"] = (data.get("item_code") or "").strip() or (prod.item_code or "")
        out.append((rid, data))
    return out


def _apply_lines(db: Session, o: SalesOrder, raw_lines) -> None:
    """In-place order-line update preserving line ids (so historical dispatch
    attribution keeps working). Lines with dispatch history cannot be removed."""
    existing = {ln.id: ln for ln in o.lines}
    seen = set()
    for rid, data in _resolve_line_products(db, raw_lines):
        if rid and rid in existing:
            ln = existing[rid]
            ln.product_id = data.get("product_id")
            ln.description = (data.get("description") or "").strip()
            ln.item_code = (data.get("item_code") or "").strip()
            ln.quantity = float(data.get("quantity") or 0)
            ln.uom = (data.get("uom") or "").strip()[:30]
            ln.unit_price = data.get("unit_price")
            ln.less = data.get("less")
            ln.customer_po_no = data.get("customer_po_no") or ""
            ln.amount = None
            seen.add(rid)
        else:
            o.lines.append(SalesOrderLine(
                product_id=data.get("product_id"),
                description=(data.get("description") or "").strip(),
                item_code=(data.get("item_code") or "").strip(),
                quantity=float(data.get("quantity") or 0),
                uom=(data.get("uom") or "").strip()[:30],
                unit_price=data.get("unit_price"),
                less=data.get("less"),
                customer_po_no=data.get("customer_po_no") or "",
            ))
            seen.add(None)
    for ln in list(existing.values()):
        if ln.id in seen:
            continue
        used = db.scalar(select(func.count()).select_from(DispatchLine)
                         .where(DispatchLine.sales_order_line_id == ln.id)) or 0
        if used:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail=f"Line '{ln.description or ln.id}' already has dispatch entries and cannot be removed")
        db.delete(ln)


def _serialize(db: Session, o: SalesOrder) -> dict:
    return serialize_local_order(db, o)


@router.get("", response_model=dict)
def list_local(
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
    customer_id: int | None = None,
    status_: str = Query(default="", alias="status"),
    date_from: str = "",
    date_to: str = "",
    active_only: bool = Query(False, description="Exclude Completed orders (active/incomplete list)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    stmt = select(SalesOrder).where(SalesOrder.order_type == OrderType.local)
    if customer_id:
        stmt = stmt.where(SalesOrder.customer_id == customer_id)
    if date_from:
        try:
            from_date = date.fromisoformat(date_from)
        except ValueError:
            from_date = None
        if from_date:
            stmt = stmt.where(SalesOrder.order_date >= from_date)
    if date_to:
        try:
            to_date = date.fromisoformat(date_to)
        except ValueError:
            to_date = None
        if to_date:
            stmt = stmt.where(SalesOrder.order_date <= to_date)
    completed_total = db.scalar(
        select(func.count()).select_from(
            stmt.where(SalesOrder.status == OrderStatus.completed).subquery()))
    if active_only:
        stmt = stmt.where(SalesOrder.status != OrderStatus.completed)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(SalesOrder.order_date.desc(), SalesOrder.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    items = []
    for o in rows:
        sync_local_order_status(db, o)
        s = _serialize(db, o)
        if active_only and s["status"] == "Completed":
            continue
        if status_:
            if status_ == "ready" and s["status"] != "Ready for Dispatch":
                continue
            elif status_ == "partial" and s["status"] != "Partially Dispatched":
                continue
            elif status_ == "completed" and s["status"] != "Completed":
                continue
            elif status_ == "required" and s["status"] not in ("Purchase / Stock Required", "Production Required", "Stock Transfer Required"):
                continue
            elif status_ not in ("ready", "partial", "completed", "required"):
                continue
        items.append(s)
    db.commit()
    return {"items": items, "total": total, "completed_total": completed_total or 0,
            "page": page, "page_size": page_size}


@router.get("/plans", response_model=dict)
def local_plans(db: Annotated[Session, Depends(get_db)], _: CurrentUser):
    p = db.scalars(select(Plan).where(
        or_(Plan.plan_type == "PRODUCTION_PLAN",
            Plan.plan_type == "DISPATCH_PLAN"))
        .order_by(Plan.plan_date.desc(), Plan.id.desc())).all()
    items = [{
        "id": pl.id, "plan_type": pl.plan_type.value, "model": pl.model,
        "customer": pl.customer.name if pl.customer else None,
        "quantity": pl.quantity, "owner": pl.owner, "status": pl.status,
        "plan_date": pl.plan_date, "remarks": pl.remarks,
    } for pl in p]
    return {"items": items, "total": len(items)}


@router.post("/import", response_model=dict)
async def import_local_orders(
    db: Annotated[Session, Depends(get_db)],
    user: ManagerOrAdmin,
    file: UploadFile = File(...),
):
    """Bulk-create LOCAL orders from a CSV/Excel upload.

    Columns are flexible (aliases; any order / casing). Rows are grouped into one
    order per SO Number, or per PO Number when no SO Number is given, otherwise
    each row becomes its own order. SO Numbers are preserved exactly as typed —
    never renumbered or generated, and no global uniqueness is enforced. Per-row
    validation errors are collected and reported; invalid rows are skipped.
    """
    content = await file.read()
    try:
        headers, rows = read_table(file.filename or "upload.xlsx", content)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if not rows:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No data rows found in file")
    colmap = build_column_map(headers, LO_HEADER_ALIASES)
    if not colmap:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="No recognized columns found. Expected Customer, "
                                   "Size/Description or Item Code, Quantity, and optionally "
                                   "SO Number / PO Number, Order Date, Delivery Date, "
                                   "Order Type, Mobile, Email, Unit, Rate, Less, Remarks.")

    batch = ImportBatch(source_file=file.filename or "", period_label="",
                        status="IMPORTED")
    db.add(batch)
    db.flush()

    parsed: list[dict] = []
    for r_i, raw in enumerate(rows):
        mapped = row_to_dict(colmap, raw)
        if is_blank_row(mapped):
            continue
        errors = []
        customer = _t(mapped.get("customer"))
        item_code = _t(mapped.get("item_code"))
        description = _t(mapped.get("description"))
        qty = cell_num(mapped.get("quantity"))
        so_no = _t(mapped.get("so_no"))
        po_no = _t(mapped.get("po_no"))
        if not customer:
            errors.append("Customer is required")
        if not item_code and not description:
            errors.append("Size/Description or Item Code is required")
        if qty is None or not (qty > 0):
            errors.append("Quantity must be a positive number")
        parsed.append({
            "row": r_i + 2,
            "customer": customer,
            "mobile": _t(mapped.get("mobile")),
            "email": _t(mapped.get("email")),
            "so_no": so_no,
            "po_no": po_no,
            "order_type": _t(mapped.get("order_type")) or "TRADING",
            "order_date": parse_date_value(mapped.get("order_date")),
            "delivery_date": parse_date_value(mapped.get("delivery_date")),
            "item_code": item_code,
            "description": description,
            "qty": qty,
            "uom": _t(mapped.get("uom")),
            "rate": cell_num(mapped.get("rate")),
            "less": cell_num(mapped.get("less")),
            "remarks": _t(mapped.get("remarks")),
            "errors": errors,
        })

    if not parsed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No data rows found in file")

    errors_rows = [p for p in parsed if p["errors"]]
    valid = [p for p in parsed if not p["errors"]]

    groups: dict[str, list[dict]] = {}
    for p in valid:
        key = (f"so|{p['so_no']}" if p["so_no"]
               else f"po|{p['po_no']}" if p["po_no"]
               else f"row|{p['row']}")
        groups.setdefault(key, []).append(p)

    created: list[dict] = []
    line_count = 0
    for grp in groups.values():
        first = grp[0]
        c = get_or_create_customer(db, first["customer"], first["mobile"],
                                   first["email"])
        lines = []
        for p in grp:
            product = resolve_or_create_product(db, p["item_code"], p["description"],
                                                allow_blank=True)
            if product is None:
                continue
            lines.append(SalesOrderLine(
                product_id=product.id,
                description=p["description"],
                item_code=(p["item_code"] or "") or (product.item_code or ""),
                quantity=float(p["qty"]),
                uom=(p["uom"] or "")[:30],
                unit_price=p["rate"],
                less=p["less"],
                customer_po_no=p["po_no"] or "",
            ))
        if not lines:
            continue
        o = SalesOrder(
            order_no=_local_no(db),
            customer_id=c.id if c else None,
            customer_name=c.name if c else first["customer"],
            order_type=OrderType.local,
            local_order_type=normalize_local_type(first["order_type"]),
            so_no=first["so_no"][:120],
            customer_po_no=first["po_no"][:120],
            order_date=first["order_date"] or date.today(),
            required_delivery_date=first["delivery_date"],
            status=OrderStatus.new,
            remarks=first["remarks"] or "",
            import_batch_id=batch.id,
            lines=lines,
        )
        _recalc_local_total(db, o, lines)
        db.add(o)
        db.flush()
        sync_local_order_status(db, o)
        created.append({
            "order_id": o.id,
            "order_no": o.order_no,
            "so_no": o.so_no,
            "po_no": o.customer_po_no,
            "customer": c.name if c else first["customer"],
            "lines": len(lines),
            "order_date": o.order_date.isoformat() if o.order_date else None,
            "rows": [g["row"] for g in grp],
        })
        line_count += len(lines)

    for cr in created:
        write_audit(db, user, "IMPORT", "sales_orders", cr["order_id"],
                    f"Bulk-imported LOCAL order {cr['order_no']} ({cr['lines']} lines)")
    batch.stats = json.dumps({
        "rows": len(parsed), "created": len(created), "skipped": 0,
        "errors": len(errors_rows), "lines": line_count, "source": file.filename or "",
    })
    db.commit()
    return {
        "batch_id": batch.id,
        "summary": {"rows": len(parsed), "created": len(created),
                    "skipped": 0, "errors": len(errors_rows),
                    "lines": line_count},
        "created": created,
        "skipped": [],
        "errors": [{"row": e["row"], "message": "; ".join(e["errors"])} for e in errors_rows],
    }


@router.get("/report/orders")
def local_orders_report_csv(db: Annotated[Session, Depends(get_db)], _: CurrentUser,
                            scope: str = Query("completed", description="'completed' or 'all'")):
    """Completed (or all) LOCAL orders as a CSV report."""
    if scope not in ("completed", "all"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="scope must be 'completed' or 'all'")
    rows = db.scalars(select(SalesOrder)
                      .where(SalesOrder.order_type == OrderType.local)
                      .order_by(SalesOrder.order_date.desc(), SalesOrder.id.desc())).all()
    headers = ["Order No", "SO Number", "PO Number", "Customer", "Mobile", "Email",
               "Order Type", "Order Date", "Delivery Date", "Status", "Items",
               "Quantity", "Unit", "Rate", "Less", "Amount", "Dispatched", "Pending"]
    data = []
    for o in rows:
        sync_local_order_status(db, o)
        s = _serialize(db, o)
        if scope == "completed" and s["status"] != "Completed":
            continue
        lines = s.get("lines") or []
        first = lines[0] if lines else {}
        items = " | ".join((l.get("description") or l.get("model") or "")
                           for l in lines)
        data.append([
            s["order_no"], s.get("so_no") or "", s.get("customer_po_no") or "",
            s.get("customer") or "", s.get("customer_mobile") or "",
            s.get("customer_email") or "",
            s.get("order_type") or "", s.get("order_date") or "",
            s.get("delivery_date") or "", s.get("status") or "", items,
            s.get("quantity") or 0, first.get("uom") or "",
            first.get("rate") if first.get("rate") is not None else "",
            first.get("less") if first.get("less") is not None else "",
            s.get("total_value") or 0, s.get("dispatched_qty") or 0,
            s.get("pending_qty") or 0,
        ])
    db.commit()
    return _csv_response(headers, data, "local_orders_completed.csv")


@router.get("/report/plans")
def local_plans_report_csv(db: Annotated[Session, Depends(get_db)], _: CurrentUser):
    """Production / Dispatch Plans (Local) with linked order, production and
    dispatch progress as a CSV report."""
    plans = db.scalars(select(Plan).where(
        or_(Plan.plan_type == "PRODUCTION_PLAN",
            Plan.plan_type == "DISPATCH_PLAN"))
        .order_by(Plan.plan_date.desc(), Plan.id.desc())).all()
    so_ids = {p.sales_order_id for p in plans if p.sales_order_id}
    orders: dict[int, SalesOrder] = {}
    prods: dict[int, list[ProductionOrder]] = {}
    dispatched: dict[int, float] = {}
    if so_ids:
        orders = {o.id: o for o in db.scalars(
            select(SalesOrder).where(SalesOrder.id.in_(so_ids))).all()}
        for po in db.scalars(select(ProductionOrder)
                             .where(ProductionOrder.sales_order_id.in_(so_ids))).all():
            prods.setdefault(po.sales_order_id, []).append(po)
        for sid, tot in db.execute(
            select(Dispatch.sales_order_id,
                   func.coalesce(func.sum(DispatchLine.quantity), 0))
            .join(DispatchLine, DispatchLine.dispatch_id == Dispatch.id)
            .where(Dispatch.sales_order_id.in_(so_ids))
            .group_by(Dispatch.sales_order_id)):
            dispatched[sid] = float(tot or 0)

    headers = ["Plan Type", "Model", "Customer", "Order No", "SO Number",
               "PO Number", "Plan Date", "Plan Qty", "Rate", "Weight", "Owner",
               "Plan Status", "Scheduled", "Produced", "% Comp", "Balance",
               "Dispatched", "Remarks"]
    data = []
    for p in plans:
        o = orders.get(p.sales_order_id) if p.sales_order_id else None
        prod_rows = prods.get(p.sales_order_id, [])
        scheduled = sum(po.schedule_qty or 0 for po in prod_rows) or (p.quantity or 0)
        produced = sum(po.produced_qty or 0 for po in prod_rows)
        balance = sum(po.balance_qty or 0 for po in prod_rows)
        comp = round(produced / scheduled * 100, 2) if scheduled else 0
        data.append([
            p.plan_type.value if hasattr(p.plan_type, "value") else p.plan_type,
            p.model,
            (o.customer_name if o else "") or (p.customer.name if p.customer else ""),
            o.order_no if o else "", o.so_no if o else "",
            o.customer_po_no if o else "",
            p.plan_date, p.quantity if p.quantity is not None else "",
            p.rate if p.rate is not None else "", p.weight if p.weight is not None else "",
            p.owner or "", p.status or "", round(scheduled, 4), round(produced, 4),
            comp, round(balance, 4),
            round(dispatched.get(p.sales_order_id, 0), 4), p.remarks or "",
        ])
    return _csv_response(headers, data, "local_plans.csv")


@router.get("/{order_id}", response_model=dict)
def get_local_order(order_id: int, db: Annotated[Session, Depends(get_db)],
                    _: CurrentUser):
    o = db.get(SalesOrder, order_id)
    if o is None or o.order_type != OrderType.local:
        raise HTTPException(status_code=404, detail="Local order not found")
    sync_local_order_status(db, o)
    db.commit()
    return _serialize(db, o)


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_local_order(body: LocalOrderCreate, db: Annotated[Session, Depends(get_db)],
                       user: AllStaff):
    if not body.lines or any((ln.quantity or 0) <= 0 for ln in body.lines):
        raise HTTPException(status_code=400,
                            detail="Add at least one order line with a quantity greater than 0")
    customer_id, customer_name = _resolve_customer(db, body)
    resolved = _resolve_line_products(db, body.lines)
    lines = [SalesOrderLine(**data) for _, data in resolved]
    o = SalesOrder(order_no=body.order_no or _local_no(db),
                   customer_id=customer_id, customer_name=customer_name,
                   order_type=OrderType.local,
                   local_order_type=normalize_local_type(body.local_order_type),
                   so_no=(body.so_no or "").strip()[:120],
                   customer_po_no=(body.customer_po_no or "").strip()[:120],
                   order_date=body.order_date or date.today(),
                   required_delivery_date=body.required_delivery_date,
                   status=OrderStatus.new, remarks=body.remarks or "",
                   lines=lines)
    _recalc_local_total(db, o, lines)
    db.add(o)
    db.flush()
    sync_local_order_status(db, o)
    db.commit()
    db.refresh(o)
    write_audit(db, user, "CREATE", "sales_orders", o.id, f"Created LOCAL order {o.order_no}")
    return _serialize(db, o)


@router.patch("/{order_id}", response_model=dict)
def update_local_order(order_id: int, body: LocalOrderUpdate,
                       db: Annotated[Session, Depends(get_db)], user: AllStaff):
    o = db.get(SalesOrder, order_id)
    if o is None or o.order_type != OrderType.local:
        raise HTTPException(status_code=404, detail="Local order not found")
    data = body.model_dump(exclude_unset=True)

    if "customer_id" in data:
        o.customer_id, o.customer_name = _resolve_customer(db, body)
    elif "customer_name" in data and body.customer_name is not None:
        o.customer_id, o.customer_name = _resolve_customer(db, body)

    # Contact enrichment for the linked Customer: fill master phone/email only
    # when currently empty (never clobber existing master contact data).
    if o.customer_id is not None:
        cust = db.get(Customer, o.customer_id)
        if cust is not None:
            mobile = (data.get("customer_mobile") or "").strip()
            email = (data.get("customer_email") or "").strip()
            if mobile and not (cust.phone or "").strip():
                cust.phone = mobile
            if email and not (cust.email or "").strip():
                cust.email = email

    if "local_order_type" in data:
        o.local_order_type = normalize_local_type(body.local_order_type)
    if "so_no" in data:
        o.so_no = (body.so_no or "").strip()[:120]
    if "customer_po_no" in data:
        o.customer_po_no = (body.customer_po_no or "").strip()[:120]
    if "order_date" in data and body.order_date is not None:
        o.order_date = body.order_date
    if "required_delivery_date" in data:
        o.required_delivery_date = body.required_delivery_date
    if "remarks" in data and body.remarks is not None:
        o.remarks = body.remarks
    # Status is user-controlled: an explicit status in the request is stored
    # as-is and is never re-derived by stock/Production side effects.
    manual_status = "status" in data and body.status is not None
    if manual_status:
        o.status = body.status

    if body.lines is not None:
        if any((ln.quantity or 0) <= 0 for ln in body.lines):
            raise HTTPException(status_code=400,
                                detail="Each order line needs a quantity greater than 0")
        _apply_lines(db, o, body.lines)
        _recalc_local_total(db, o, o.lines)

    if not manual_status and o.status != OrderStatus.cancelled:
        sync_local_order_status(db, o)
    db.commit()
    db.refresh(o)
    write_audit(db, user, "UPDATE", "sales_orders", o.id, f"Updated LOCAL order {o.order_no}")
    return _serialize(db, o)


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_local_order(order_id: int, db: Annotated[Session, Depends(get_db)],
                       user: ManagerOrAdmin):
    o = db.get(SalesOrder, order_id)
    if o is None or o.order_type != OrderType.local:
        raise HTTPException(status_code=404, detail="Local order not found")
    if db.scalar(select(func.count()).select_from(Dispatch).where(Dispatch.sales_order_id == o.id)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Cannot delete local order: it has dispatches.")
    db.execute(update(ProductionOrder).where(ProductionOrder.sales_order_id == o.id)
               .values(sales_order_id=None))
    db.execute(update(Plan).where(Plan.sales_order_id == o.id).values(sales_order_id=None))
    db.execute(delete(PurchaseRequirement).where(PurchaseRequirement.sales_order_id == o.id))
    db.delete(o)
    db.commit()
    write_audit(db, user, "DELETE", "sales_orders", o.id, f"Deleted LOCAL order {o.order_no}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)