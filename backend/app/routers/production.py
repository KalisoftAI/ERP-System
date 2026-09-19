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
from ..services.import_common import normalize_header, read_table
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


def _normalize_header(h: str) -> str:
    """Normalize a header name for flexible column mapping."""
    return normalize_header(h)


def _parse_production_import(headers: list[str], rows: list[list[str]]) -> tuple[list[dict], list[dict]]:
    """Parse imported production plan rows.
    
    Returns (valid_rows, error_rows) where each row dict has mapped field names.
    """
    # Column name mapping (normalized -> field name)
    col_map = {
        # Item Code variations
        "item code": "item_code",
        "item_code": "item_code",
        "itemcode": "item_code",
        "item": "item_code",
        # Model variations
        "model": "model",
        # Schedule Quantity variations
        "schedule": "schedule_qty",
        "schedule qty": "schedule_qty",
        "schedule quantity": "schedule_qty",
        # Ask Till Date variations
        "ask till date": "ask_till_date",
        "ask_till_date": "ask_till_date",
        # Production Qty variations
        "production qty": "produced_qty",
        "production quantity": "produced_qty",
        "qty": "produced_qty",
        # % Comp variations
        "% comp": "completion_pct",
        "% completion": "completion_pct",
        # Balance Qty variations
        "balance qty": "balance_qty",
        "balance quantity": "balance_qty",
        # Status variations (must match ProductionStatus exactly)
        "status": "status",
        # Remarks
        "remarks": "remarks",
    }
    
    # Build a mapping from column index to field name
    field_map: dict[int, str] = {}
    for idx, header in enumerate(headers):
        norm = normalize_header(header)
        if norm in col_map:
            field_map[idx] = col_map[norm]
    
    valid_rows = []
    error_rows = []
    
    for row_idx, row in enumerate(rows, start=1):
        row_errors = []
        row_data = {}
        
        for col_idx, cell_value in enumerate(row):
            if col_idx in field_map:
                field_name = field_map[col_idx]
                if field_name in ("schedule_qty", "produced_qty", "completion_pct", "balance_qty"):
                    try:
                        row_data[field_name] = float(cell_value) if cell_value else 0.0
                    except (ValueError, TypeError):
                        row_data[field_name] = 0.0
                elif field_name == "ask_till_date":
                    if cell_value:
                        row_data[field_name] = str(cell_value)
                    else:
                        row_data[field_name] = None
                else:
                    row_data[field_name] = str(cell_value) if cell_value else ""
        
        # Validate
        has_item = row_data.get("item_code", "").strip() != ""
        has_model = row_data.get("model", "").strip() != ""
        has_schedule = row_data.get("schedule_qty", 0) > 0
        valid_statuses = [s.value for s in ProductionStatus]
        has_valid_status = row_data.get("status", "").strip() in valid_statuses
        
        item_code = row_data.get("item_code", "").strip()
        model = row_data.get("model", "").strip()
        
        if not has_item and not has_model:
            row_errors.append("Missing item code or model")
        
        if not has_schedule:
            row_errors.append("Missing or invalid schedule quantity")
        
        if not has_valid_status:
            row_errors.append(f"Invalid status. Must be one of: {', '.join(valid_statuses)}")
        
        if row_errors:
            error_rows.append({
                "row": row_idx,
                "errors": row_errors,
                "data": {k: v for k, v in row_data.items() if k in ("item_code", "model", "schedule_qty", "ask_till_date", "produced_qty", "completion_pct", "balance_qty", "status", "remarks")},
            })
        else:
            # Resolve product
            prod = resolve_or_create_product(
                db=None,
                item_code=item_code if item_code else None,
                model=model if model else None,
                allow_blank=True,
            )
            
            valid_rows.append({
                "item_code": item_code,
                "model": model if model else None,
                "schedule_qty": row_data.get("schedule_qty", 0) or 0,
                "ask_till_date": row_data.get("ask_till_date"),
                "produced_qty": row_data.get("produced_qty", 0) or 0,
                "completion_pct": row_data.get("completion_pct"),
                "balance_qty": row_data.get("balance_qty"),
                "status": row_data.get("status", "Planned"),
                "remarks": row_data.get("remarks", "") or "",
            })
    
    return valid_rows, error_rows


@router.post("/import", response_model=dict)
async def import_production_plans(
    file: Annotated[UploadFile, File(...)],
    db: Annotated[Session, Depends(get_db)],
    user: AllStaff,
):
    """Import Production Plans from CSV or Excel file.
    
    Supported columns (any order, flexible naming):
    - Item Code / Model / Schedule / Ask Till Date / Production Qty / % Comp / Balance Qty / Status
    - Extra columns are ignored.
    - Column headers are case-insensitive and space/underscore tolerant.
    
    Preview is shown first; user confirms to save.
    Partial import with row-level error reporting.
    """
    content = await file.read()
    filename = file.filename or "production_import.csv"
    
    try:
        headers, rows = read_table(filename, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Could not read file: {e}")
    
    valid_rows, error_rows = _parse_production_import(headers, rows)
    
    preview = {
        "total_rows": len(rows),
        "valid_rows": len(valid_rows),
        "error_rows": len(error_rows),
        "mapped_columns": {normalize_header(h): i for i, h in enumerate(headers)},
        "headers": headers,
        "valid_data": valid_rows,
        "error_details": error_rows,
    }
    
    return {
        "preview": preview,
        "message": "Review the import preview above. Confirm to proceed with import.",
    }