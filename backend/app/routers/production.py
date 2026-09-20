"""Production management (CRUD + daily movements + status lifecycle)."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status, UploadFile, File
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import CurrentUser, AllStaff, ManagerOrAdmin
from ..crud import apply_updates, get_or_404, write_audit
from ..database import get_db
from ..models import (
    Customer, MovementType, Plant, Product, ProductionMovement, ProductionOrder,
    ProductionStatus, StockMovement, Plan, PlanType,
)
from ..schemas import ProductionOrderCreate, ProductionOrderOut, ProductionOrderUpdate
from ..services.business import sync_purchase_shortages
from ..services.customers import get_or_create_customer
from ..services.reorder_alerts import refresh_reorder_alert
from ..services.stock_service import (
    apply_movement, reconvert_document, resolve_or_create_product, reverse_and_remove_ref,
)
from ..services.import_common import (
    build_column_map, cell_num, is_blank_row, read_table, row_to_dict,
)
from datetime import date

router = APIRouter(prefix="/production", tags=["production"])


def _next_no(db: Session) -> str:
    today = date.today()
    prefix = f"PO-{today.strftime('%Y%m%d')}-"
    n = db.scalar(select(func.count()).select_from(ProductionOrder).where(ProductionOrder.order_no.like(f"{prefix}%")))
    return f"{prefix}{n + 1:03d}"


def _serialize_po(db: Session, o: ProductionOrder) -> dict:
    product = o.product
    customer = o.customer
    return {
        "id": o.id, "order_no": o.order_no, "product_id": o.product_id,
        "customer_id": o.customer_id,
        "section": o.section, "schedule_qty": o.schedule_qty, "ask_till_date": o.ask_till_date,
        "produced_qty": o.produced_qty, "completion_pct": o.completion_pct,
        "balance_qty": o.balance_qty, "opening_stock": o.opening_stock,
        "status": o.status.value, "start_date": o.start_date, "completion_date": o.completion_date,
        "report_date": o.report_date, "remarks": o.remarks,
        "product": {"id": product.id, "model": product.model, "item_code": product.item_code,
                    "name": product.name, "category": product.category.value} if product else None,
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
        prod = resolve_or_create_product(
            db, body.item_code, (body.model or body.item_code or "").strip(), allow_blank=True,
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


# ---------------------------------------------------------------------------
# Flexible production plan import (CSV / Excel) — two-phase: preview -> import
# NOTE: registered BEFORE "/{order_id}" so the literal paths are not shadowed
# by the int path parameter.
# ---------------------------------------------------------------------------

PRODUCTION_IMPORT_ALIASES: dict[str, list[str]] = {
    "item_code": [
        "item code", "item_code", "itemcode", "item", "code",
        "item no", "item number", "part code", "part no",
    ],
    "model": [
        "model", "product model", "model name", "model no", "product", "description",
    ],
    "schedule": [
        "schedule", "schedule qty", "schedule quantity", "scheduled qty",
        "schedule_qty", "plan qty", "planned qty", "plan",
    ],
    "produced_qty": [
        "production qty", "production quantity", "produced qty", "produced quantity",
        "produced_qty", "actual qty", "actual production", "production", "prod qty",
    ],
    "completion_pct": [
        "% comp", "comp %", "completion %", "completion pct", "% completion",
        "completion percent", "completion", "percent complete", "completion_pct",
    ],
    "balance_qty": [
        "balance qty", "balance quantity", "balance", "balance_qty",
        "remaining qty", "pending qty",
    ],
    "status": ["status", "production status", "plan status"],
    "remarks": ["remarks", "remark", "notes", "note", "comment", "comments"],
}


def _t(value) -> str:
    return "" if value is None else str(value).strip()


def _parse_pct(value) -> float | None:
    """Parse a percentage that may be 0-1 (fraction) or 0-100 (percent)."""
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


def _lookup_import_product(db: Session, item_code: str, model: str) -> Product | None:
    """Lookup-only product resolution for preview (never creates)."""
    ic = (item_code or "").strip()
    md = (model or "").strip()
    if ic:
        p = db.scalars(select(Product).where(Product.item_code == ic).limit(1)).first()
        if p:
            return p
    if md:
        p = db.scalars(select(Product).where(Product.model == md).limit(1)).first()
        if p:
            return p
    return None


def _resolve_import_product(db: Session, item_code: str, model: str) -> Product | None:
    """Resolve a product for import via the existing product resolver —
    an existing item code/model is reused; a new one is created lazily."""
    ic = (item_code or "").strip()
    md = (model or "").strip()
    if not ic and not md:
        return None
    if ic:
        return resolve_or_create_product(db, ic, md)
    return resolve_or_create_product(db, "", md, allow_blank=True)


def _detect_duplicate_production(db: Session, product_id, item_code: str,
                                 model: str, schedule_qty) -> ProductionOrder | None:
    """Conservative re-upload guard: same product + same schedule qty with an
    existing production order dated in the current month. This is NOT a global
    uniqueness rule — the caller only warns and asks for user confirmation."""
    if product_id:
        stmt = select(ProductionOrder).where(ProductionOrder.product_id == product_id)
    else:
        ic = (item_code or "").strip()
        md = (model or "").strip()
        if not ic and not md:
            return None
        stmt = (select(ProductionOrder)
                .join(Product, Product.id == ProductionOrder.product_id))
        if ic:
            stmt = stmt.where(func.lower(Product.item_code) == ic.lower())
        if md:
            stmt = stmt.where(func.lower(Product.model) == md.lower())
    if schedule_qty:
        stmt = stmt.where(ProductionOrder.schedule_qty == schedule_qty)
    today = date.today()
    stmt = stmt.where(ProductionOrder.report_date >= date(today.year, today.month, 1))
    return db.scalars(stmt.order_by(ProductionOrder.id.desc())).first()


def _parse_production_import_rows(db: Session, headers: list[str], rows: list[list],
                                  filename: str, resolve: bool = False) -> dict:
    """Shared parser for preview and import. Preview uses lookup-only product
    resolution (nothing is created); import uses the real product resolver.
    % Comp / Balance Qty columns are accepted but the authoritative values are
    always derived by _recalc_status at create time."""
    colmap = build_column_map(headers, PRODUCTION_IMPORT_ALIASES)
    mapped_headers = {canon: headers[idx] for idx, canon in colmap.items()}
    valid_statuses = {s.value.lower(): s for s in ProductionStatus}

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

        item_code = _t(mapped.get("item_code"))
        model = _t(mapped.get("model"))
        schedule = cell_num(mapped.get("schedule"))
        produced = cell_num(mapped.get("produced_qty"))
        status_raw = _t(mapped.get("status"))
        remarks = _t(mapped.get("remarks"))
        # Parsed for compatibility; derived values win at create time.
        _parse_pct(mapped.get("completion_pct"))
        cell_num(mapped.get("balance_qty"))

        if not item_code and not model:
            row_errs.append("Item Code or Model is required")
        if schedule is None or schedule <= 0:
            row_errs.append("Schedule must be a positive number")
        if produced is not None and produced < 0:
            row_errs.append("Production Qty cannot be negative")

        status_enum = None
        if status_raw:
            status_enum = valid_statuses.get(status_raw.lower())
            if status_enum is None:
                row_errs.append(
                    f"Invalid status '{status_raw}'. Must be one of: "
                    + ", ".join(s.value for s in ProductionStatus)
                )

        product = None
        if item_code or model:
            if resolve:
                product = _resolve_import_product(db, item_code, model)
            else:
                product = _lookup_import_product(db, item_code, model)
                if product is None:
                    row_warns.append("Product not found; a new product will be created")

        row_out = {
            "row": row_no,
            "item_code": item_code,
            "model": model,
            "product_id": product.id if product else None,
            "schedule_qty": schedule,
            "produced_qty": produced or 0.0,
            "status": status_enum.value if status_enum else None,
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

    duplicate_rows = 0
    for row in parsed:
        dup = _detect_duplicate_production(db, row["product_id"], row["item_code"],
                                           row["model"], row["schedule_qty"])
        if dup:
            row["duplicate_of"] = {"production_id": dup.id, "order_no": dup.order_no}
            duplicate_rows += 1

    return {
        "file_name": filename,
        "total_rows": len(parsed) + len(errors),
        "valid_rows": len(parsed),
        "error_rows": len(errors),
        "warning_rows": len(warnings),
        "duplicate_rows": duplicate_rows,
        "mapped_columns": mapped_headers,
        "sample_rows": parsed[:10] + errors[:5],
        "errors": errors,
        "warnings": warnings,
        "parsed": parsed,
        "can_import": len(parsed) > 0,
    }


def _create_production_from_rows(db: Session, rows: list[dict], user) -> list[dict]:
    """Persist parsed rows as ProductionOrders. Schedule / Production Qty are
    stored as order data (same semantics as the Excel migration); completion %,
    balance and status auto-advance come from the authoritative _recalc_status.
    An import NEVER creates stock movements — physical finished-goods stock
    only enters Inventory through recorded daily production output."""
    created: list[dict] = []
    for row in rows:
        o = ProductionOrder(
            order_no=_next_no(db),
            product_id=row["product_id"],
            schedule_qty=row["schedule_qty"],
            produced_qty=row["produced_qty"] or 0,
            status=ProductionStatus(row["status"]) if row["status"] else ProductionStatus.planned,
            report_date=date.today(),
            remarks=row["remarks"],
        )
        _recalc_status(o)
        db.add(o)
        db.flush()
        created.append({
            "production_id": o.id, "order_no": o.order_no,
            "item_code": row["item_code"], "model": row["model"],
            "schedule_qty": o.schedule_qty, "produced_qty": o.produced_qty,
            "status": o.status.value,
        })
        write_audit(db, user, "IMPORT", "production_orders", o.id,
                    f"Bulk-imported production plan {o.order_no} (schedule {o.schedule_qty:g})")
    return created


@router.get("/import/template")
def production_import_template(_: CurrentUser):
    """CSV template with exactly the supported production import columns.
    Ask Till Date is intentionally NOT part of production import."""
    csv_text = (
        "Item Code,Model,Schedule,Production Qty,% Comp,Balance Qty,Status\n"
        "SAMPLE-001,Sample Model,100,0,0,100,Planned\n"
    )
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="production_import_template.csv"'},
    )


@router.post("/import-preview", response_model=dict)
async def preview_production_import(
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
    file: UploadFile = File(...),
):
    """Parse a CSV/Excel production plan upload and return a preview with
    validation, column mapping and duplicate warnings. Nothing is persisted."""
    content = await file.read()
    try:
        headers, rows = read_table(file.filename or "upload.xlsx", content)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if not rows:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No data rows found in file")

    preview = _parse_production_import_rows(db, headers, rows, file.filename or "upload")
    db.rollback()  # preview never persists incidental state
    return {k: v for k, v in preview.items() if k != "parsed"}


@router.post("/import", response_model=dict)
async def import_production_plans(
    db: Annotated[Session, Depends(get_db)],
    user: AllStaff,
    file: UploadFile = File(...),
    confirm_duplicates: bool = Query(False, description="Import rows even if they appear to duplicate existing production plans"),
):
    """Bulk-create production orders from a CSV/Excel upload (after preview)."""
    content = await file.read()
    try:
        headers, rows = read_table(file.filename or "upload.xlsx", content)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if not rows:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No data rows found in file")

    preview = _parse_production_import_rows(db, headers, rows, file.filename or "upload", resolve=True)
    valid = preview["parsed"]

    if preview["duplicate_rows"] and not confirm_duplicates:
        db.rollback()
        dup_details = [
            {"row": r["row"], "item_code": r["item_code"], "model": r["model"],
             "existing_order_no": r["duplicate_of"]["order_no"]}
            for r in valid if r.get("duplicate_of")
        ]
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": f"{preview['duplicate_rows']} row(s) appear to duplicate existing production plans from this month. Confirm to import anyway.",
                "duplicates": dup_details,
            },
        )

    created = _create_production_from_rows(db, valid, user)
    db.commit()
    return {
        "summary": {
            "total_rows": preview["total_rows"],
            "valid_rows": len(valid),
            "created": len(created),
            "errors": len(preview["errors"]),
            "warnings": preview["warning_rows"],
        },
        "created": created,
        "errors": preview["errors"],
    }


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
    apply_updates(o, body, exclude={"produced_qty", "customer_name"})
    o.produced_qty = sum(float(m.quantity or 0) for m in o.movements)
    _recalc_status(o)
    db.commit()
    db.refresh(o)
    write_audit(db, user, "UPDATE", "production_orders", o.id, f"Updated production order {o.order_no}")
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