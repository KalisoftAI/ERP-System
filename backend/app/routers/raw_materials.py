"""Raw material management: master-data CRUD + balance tracking.

Master data is the existing Product model (category=raw_material) so
user-created raw materials immediately become available to every module that
selects materials (BOM, Purchase, Production, Inventory, Material
Requirements, Stock Movements …). Balance = Schedule - Inward and Inward % are
always recomputed server-side so the UI never stores stale calculated values.
MIN/MAX stock drive the existing Alerts centre. Current stock stays sourced
from Inventory / stock movements — POST /{id}/stock is the ONLY sanctioned way
to set the physical figure, routed through the movement pipeline so it feeds
every consumer (requirements, reorder alerts, dispatch, reports).

Delete safety: a raw material that is referenced by business records (BOM,
purchase, inventory, production, stock movements, requirements, …) is NEVER
cascade-deleted. Referenced materials are soft-deleted (is_active=False) so
history stays intact and the material stops appearing in fresh selections;
unreferenced materials are hard-deleted.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import CurrentUser, ManagerOrAdmin
from ..crud import apply_updates, get_or_404, write_audit
from ..database import get_db
from ..models import (
    BillOfMaterial, BOM, CustomerDispatchLine, DispatchLine, ImportBatch,
    Inventory, MovementType, Plan, Product, ProductAlias, ProductCategory,
    ProductionOrder, PurchaseOrderLine, PurchaseRequirement, RawMaterialBalance,
    SalesOrderLine, StockMovement, StockTransferLine,
)
from ..schemas import ProductCreate, ProductOut, ProductUpdate, RawMaterialBalanceOut, RawMaterialStockSet
from ..services.business import sync_purchase_shortages
from ..services.import_common import (
    build_column_map, cell_num, read_table, row_to_dict,
)
from ..services.reorder_alerts import refresh_reorder_alert
from ..services.rm_service import get_or_create_raw_material
from ..services.stock_service import apply_movement, get_or_create_inventory
from datetime import date
import json

router = APIRouter(prefix="/raw-materials", tags=["raw-materials"])


def _rm_product_stmt():
    return select(Product).where(Product.category == ProductCategory.raw_material)


def _recalc(b: RawMaterialBalance) -> None:
    """Server-side source of truth for Balance Qty + Inward %."""
    sched = b.schedule_qty
    inward = b.inward_qty
    if sched is None:
        # Schedule not set yet — leave user-entered values untouched.
        return
    sched = float(sched)
    inward = float(inward or 0)
    b.balance_qty = round(sched - inward, 4)
    b.completion_pct = round(inward / sched, 4) if sched else 0.0


def _validate_numeric(label: str, value: float | None) -> None:
    if value is not None and value < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"{label} cannot be negative")


def _referenced_by(db: Session, product_id: int) -> list[str]:
    """Return the modules whose records reference this product.

    A referenced raw material must never be cascade-deleted; the caller
    rejects the delete with the returned list so the user sees exactly where
    the material is used.
    """
    checks = [
        ("BOM", BOM, BOM.product_id),
        ("Purchase", PurchaseOrderLine, PurchaseOrderLine.product_id),
        ("Inventory / Stock", Inventory, Inventory.product_id),
        ("Stock Movements", StockMovement, StockMovement.product_id),
        ("Stock Transfers", StockTransferLine, StockTransferLine.product_id),
        ("Customer Dispatches", CustomerDispatchLine, CustomerDispatchLine.product_id),
        ("Production", ProductionOrder, ProductionOrder.product_id),
        ("Sales Orders", SalesOrderLine, SalesOrderLine.product_id),
        ("Dispatch", DispatchLine, DispatchLine.product_id),
        ("Plans", Plan, Plan.product_id),
        ("Material Requirements", PurchaseRequirement, PurchaseRequirement.product_id),
        ("Raw Material Balances", RawMaterialBalance, RawMaterialBalance.product_id),
        ("Product Aliases", ProductAlias, ProductAlias.product_id),
    ]
    refs = []
    for label, model, column in checks:
        if db.scalar(select(func.count()).select_from(model).where(column == product_id)):
            refs.append(label)
    if db.scalar(select(func.count()).select_from(BillOfMaterial).where(
            or_(BillOfMaterial.product_id == product_id,
                BillOfMaterial.raw_material_product_id == product_id))):
        if "BOM" not in refs:
            refs.append("BOM")
    return refs


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_raw_material(body: ProductCreate, db: Annotated[Session, Depends(get_db)],
                        user: ManagerOrAdmin):
    model_name = (body.model or "").strip()
    if not model_name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Material name is required")
    dup = db.scalar(select(Product.id).where(
        func.lower(Product.model) == model_name.lower()).limit(1))
    if dup:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Raw material '{model_name}' already exists. Duplicate records are not created.")
    data = body.model_dump()
    data["model"] = model_name
    data["category"] = ProductCategory.raw_material
    p = Product(**data)
    db.add(p)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Could not create raw material (item code / model already in use).")
    db.refresh(p)
    write_audit(db, user, "CREATE", "products", p.id, f"Created raw material {p.model}")
    return p


def _serialize_detail(db: Session, p: Product) -> dict:
    """Full detail for the View action (product master + latest balance keys)."""
    b = db.scalars(
        select(RawMaterialBalance).where(RawMaterialBalance.product_id == p.id)
        .order_by(RawMaterialBalance.report_date.desc()).limit(1)
    ).first()
    inv = db.scalars(select(Inventory).where(Inventory.product_id == p.id,
                                             Inventory.plant_id.is_(None))).first()
    return {
        **ProductOut.model_validate(p).model_dump(),
        "source_type": p.source_type.value if p.source_type else None,
        "family": p.family,
        "balance": RawMaterialBalanceOut.model_validate(b).model_dump() if b else None,
        "current_stock": inv.current_stock if inv else 0,
    }


@router.get("/{product_id}", response_model=dict)
def get_raw_material(product_id: int, db: Annotated[Session, Depends(get_db)],
                     _: CurrentUser):
    p = get_or_404(db, Product, product_id)
    if p.category != ProductCategory.raw_material:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Raw material not found")
    return _serialize_detail(db, p)


@router.patch("/{product_id}", response_model=ProductOut)
def update_raw_material(product_id: int, body: ProductUpdate,
                        db: Annotated[Session, Depends(get_db)],
                        user: ManagerOrAdmin):
    p = get_or_404(db, Product, product_id)
    if p.category != ProductCategory.raw_material:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Raw material not found")
    if body.model is not None:
        new_model = (body.model or "").strip()
        if not new_model:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Material name is required")
        dup = db.scalar(select(Product.id).where(
            func.lower(Product.model) == new_model.lower(),
            Product.id != product_id).limit(1))
        if dup:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"Another record already uses material name '{new_model}'.")
        p.model = new_model
    # Category stays raw_material (excluded from generic update).
    apply_updates(p, body, exclude={"model", "category"})
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Could not update raw material (item code / model already in use).")
    db.refresh(p)
    write_audit(db, user, "UPDATE", "products", p.id, f"Updated raw material {p.model}")
    return p


@router.delete("/{product_id}")
def delete_raw_material(product_id: int, db: Annotated[Session, Depends(get_db)],
                        user: ManagerOrAdmin):
    p = get_or_404(db, Product, product_id)
    if p.category != ProductCategory.raw_material or not p.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Raw material not found")
    refs = _referenced_by(db, product_id)
    if refs:
        # Soft delete: history stays intact, material hides from fresh uses.
        p.is_active = False
        db.commit()
        write_audit(db, user, "DEACTIVATE", "products", product_id,
                    f"Deactivated raw material {p.model} (referenced by {', '.join(refs)})")
        return JSONResponse({
            "deactivated": True, "id": product_id, "model": p.model,
            "reason": "referenced", "modules": refs,
        })
    try:
        db.delete(p)
        db.commit()
    except Exception:
        db.rollback()
        p.is_active = False
        db.commit()
        write_audit(db, user, "DEACTIVATE", "products", product_id,
                    f"Deactivated raw material {p.model} (hard delete failed)")
        return JSONResponse({"deactivated": True, "id": product_id, "model": p.model,
                             "reason": "delete_failed"})
    write_audit(db, user, "DELETE", "products", product_id, f"Deleted raw material {p.model}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("", response_model=dict)
def list_raw_materials(
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
    search: str = "",
    report_date: str = "",
    include_inactive: bool = Query(False, description="Also list soft-deleted materials"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    stmt = _rm_product_stmt()
    if not include_inactive:
        stmt = stmt.where(Product.is_active.is_(True))
    products = db.scalars(stmt.order_by(Product.model)).all()
    items = []
    for p in products:
        b = db.scalars(
            select(RawMaterialBalance).where(RawMaterialBalance.product_id == p.id)
            .order_by(RawMaterialBalance.report_date.desc()).limit(1)
        ).first()
        inv = db.scalars(select(Inventory).where(Inventory.product_id == p.id, Inventory.plant_id.is_(None))).first()
        balance = RawMaterialBalanceOut.model_validate(b).model_dump() if b else None
        current = inv.current_stock if inv else None
        # Reorder flag: current stock below configured MIN stock.
        reorder = False
        if balance is not None and balance.get("min_stock") is not None and current is not None:
            reorder = float(current or 0) < float(balance["min_stock"])
        items.append({
            **ProductOut.model_validate(p).model_dump(),
            "balance": balance,
            "current_stock": current,
            "reorder_required": reorder,
        })
    if search:
        items = [i for i in items if search.lower() in i["model"].lower() or search.lower() in (i["item_code"] or "").lower()]
    return {"items": items, "total": len(items), "page": page, "page_size": page_size}


@router.post("/balances", response_model=RawMaterialBalanceOut, status_code=status.HTTP_201_CREATED)
def upsert_balance(
    db: Annotated[Session, Depends(get_db)],
    user: ManagerOrAdmin,
    product_id: int, report_date: str, schedule_qty: float | None = None,
    ask_till_date: float | None = None, inward_qty: float | None = None,
    opening_stock: float | None = None,
    min_stock: float | None = None, max_stock: float | None = None,
):
    from datetime import date as _date
    rd = _date.fromisoformat(report_date)
    product = get_or_404(db, Product, product_id)

    for label, val in (("Schedule Quantity", schedule_qty), ("Inward Quantity", inward_qty),
                       ("Opening Stock", opening_stock), ("MIN STOCK", min_stock),
                       ("MAX STOCK", max_stock)):
        _validate_numeric(label, val)
    if min_stock is not None and max_stock is not None and max_stock < min_stock:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "MAX STOCK cannot be less than MIN STOCK")

    b = db.scalars(select(RawMaterialBalance).where(
        RawMaterialBalance.product_id == product_id, RawMaterialBalance.report_date == rd)).first()
    if b is None:
        b = RawMaterialBalance(product_id=product_id, report_date=rd)
        db.add(b)
    if schedule_qty is not None: b.schedule_qty = schedule_qty
    if ask_till_date is not None: b.ask_till_date = ask_till_date
    if inward_qty is not None: b.inward_qty = inward_qty
    if opening_stock is not None: b.opening_stock = opening_stock
    if min_stock is not None: b.min_stock = min_stock
    if max_stock is not None: b.max_stock = max_stock

    _recalc(b)  # balance + inward % recomputed from schedule/inward
    db.flush()
    refresh_reorder_alert(db, product_id, model_label=product.model)
    db.commit()
    db.refresh(b)
    write_audit(db, user, "UPSERT", "raw_material_balances", b.id)
    return b


@router.post("/{product_id}/stock", response_model=dict)
def set_raw_material_stock(product_id: int, body: RawMaterialStockSet,
                           db: Annotated[Session, Depends(get_db)],
                           user: ManagerOrAdmin):
    """Set the physical current stock (Main Store) for a raw material.

    The target is reconciled against the stored Inventory figure through the
    stock-movement pipeline (receipt/adjustment), so stock always stays
    consistent with movements, requirements and reorder alerts. This is the
    only sanctioned way to set RM stock — balances above stay schedule-layer
    only.
    """
    p = get_or_404(db, Product, product_id)
    if p.category != ProductCategory.raw_material:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Raw material not found")
    if body.current_stock < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Current stock cannot be negative")
    inv = get_or_create_inventory(db, product_id, None)
    cur = float(inv.current_stock or 0)
    target = float(body.current_stock)
    delta = round(target - cur, 4)
    if delta:
        movement_type = MovementType.receipt if delta > 0 else MovementType.adjustment
        remarks = (body.remarks or "").strip() or f"Raw material stock set to {target:g}"
        apply_movement(db, product_id, movement_type, abs(delta), date.today(),
                       remarks=remarks)
        db.flush()
        refresh_reorder_alert(db, product_id, model_label=p.model)
        sync_purchase_shortages(db)
    db.commit()
    write_audit(db, user, "SET", "inventory", inv.id,
                f"Raw material {p.model} stock {cur:g} -> {target:g}")
    return {"product_id": product_id, "model": p.model,
            "previous_stock": cur, "current_stock": target, "delta": delta}


RM_HEADER_ALIASES = {
    "item_code": ["Item Code", "Item Code No", "Code", "Item No", "Part No"],
    "model": ["Model", "Material", "Material Name", "Raw Material", "Item",
              "Item Name", "Description", "Product", "Product Name", "Article"],
    "uom": ["UOM", "Unit", "Units", "Unit of Measure"],
    "schedule_qty": ["Schedule", "Schedule Qty", "Scheduled Qty", "Plan Qty",
                     "Scheduled Quantity"],
    "inward_qty": ["Inward Qty", "Inward", "Received Qty", "Received",
                   "Receipt Qty"],
    "completion_pct": ["% COMP", "Completion", "Completion %", "% Complete",
                       "Comp %"],
    "balance_qty": ["Balance Qty", "Balance"],
    "opening_stock": ["Opening Stock", "Opng Stock"],
    "min_stock": ["MIN STOCK", "Minimum Stock"],
    "max_stock": ["MAX STOCK", "Maximum Stock"],
    "ask_till_date": ["Ask Till Date", "Ask-Till-Date", "Ask Till"],
}


@router.post("/import", response_model=dict)
async def import_raw_materials(
    db: Annotated[Session, Depends(get_db)],
    user: ManagerOrAdmin,
    file: UploadFile = File(...),
    report_date: str = Query("", description="Optional report date (YYYY-MM-DD); defaults to today"),
):
    """Bulk-import raw-material master + balance rows from CSV/Excel.

    Headers are matched flexibly (Item Code / Model / Schedule Qty / Inward Qty
    / % COMP / Balance / MIN STOCK / MAX STOCK …). Existing materials are always
    matched and updated (never duplicated); unknown materials are created as
    category=raw_material. Inward is derived from Schedule × % COMP or
    Schedule − Balance when not given directly; Balance and % COMP are then
    recomputed server-side. Returns per-row errors; invalid rows are skipped.
    """
    content = await file.read()
    try:
        headers, rows = read_table(file.filename or "upload.xlsx", content)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    if not rows:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "No data rows found in file")
    colmap = build_column_map(headers, RM_HEADER_ALIASES)
    if "model" not in colmap.values():
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "No Model/Material column recognized — expected a "
                            "header like Model, Material or Item Name")
    rd = date.fromisoformat(report_date) if report_date else date.today()

    batch = ImportBatch(source_file=file.filename or "",
                        period_label=rd.isoformat(), status="IMPORTED")
    db.add(batch)
    db.flush()

    created_ids: list[int] = []
    upserted_ids: list[int] = []
    row_errors: list[dict] = []
    for r_i, raw in enumerate(rows):
        mapped = row_to_dict(colmap, raw)
        if not any(_t(v) for v in mapped.values()):
            continue
        row_no = r_i + 2
        model = _t(mapped.get("model"))
        item_code = _t(mapped.get("item_code"))
        if not model and not item_code:
            row_errors.append({"row": row_no,
                               "message": "Model and Item Code are both empty"})
            continue
        numbers = {}
        errs = []
        for field in ("schedule_qty", "inward_qty", "completion_pct",
                      "balance_qty", "opening_stock", "min_stock", "max_stock",
                      "ask_till_date"):
            v = cell_num(mapped.get(field))
            if v is not None and v < 0:
                errs.append(f"{field.replace('_', ' ')} cannot be negative")
            numbers[field] = v
        if (numbers["min_stock"] is not None and numbers["max_stock"] is not None
                and numbers["max_stock"] < numbers["min_stock"]):
            errs.append("MAX STOCK cannot be less than MIN STOCK")
        if errs:
            row_errors.append({"row": row_no, "message": "; ".join(errs)})
            continue
        # Derive Inward from Schedule when it is not given directly, so
        # tracking-sheet exports (% COMP / Balance) land correctly.
        sched = numbers["schedule_qty"]
        inward = numbers["inward_qty"]
        if inward is None and sched is not None:
            if numbers["completion_pct"] is not None:
                inward = round(sched * numbers["completion_pct"], 4)
            elif numbers["balance_qty"] is not None:
                inward = round(sched - numbers["balance_qty"], 4)
        if inward is not None:
            numbers["inward_qty"] = inward

        p, created = get_or_create_raw_material(
            db, item_code, model, _t(mapped.get("uom")) or "kg")
        b = db.scalars(select(RawMaterialBalance).where(
            RawMaterialBalance.product_id == p.id,
            RawMaterialBalance.report_date == rd)).first()
        if b is None:
            b = RawMaterialBalance(product_id=p.id, report_date=rd)
            db.add(b)
        if numbers["schedule_qty"] is not None:
            b.schedule_qty = numbers["schedule_qty"]
        if numbers["inward_qty"] is not None:
            b.inward_qty = numbers["inward_qty"]
        if numbers["ask_till_date"] is not None:
            b.ask_till_date = numbers["ask_till_date"]
        if numbers["opening_stock"] is not None:
            b.opening_stock = numbers["opening_stock"]
        if numbers["min_stock"] is not None:
            b.min_stock = numbers["min_stock"]
        if numbers["max_stock"] is not None:
            b.max_stock = numbers["max_stock"]
        _recalc(b)
        db.flush()
        refresh_reorder_alert(db, p.id, model_label=p.model)
        if created:
            created_ids.append(p.id)
        upserted_ids.append(p.id)

    processed = len(upserted_ids) + len(row_errors)
    batch.stats = json.dumps({
        "rows": processed, "created": len(created_ids),
        "updated": len(upserted_ids), "errors": len(row_errors),
        "report_date": rd.isoformat(), "source": file.filename or "",
    })
    db.commit()
    write_audit(db, user, "IMPORT", "import_batches", batch.id,
                f"Raw material import: {len(created_ids)} created, "
                f"{len(upserted_ids) - len(created_ids)} matched, "
                f"{len(row_errors)} row errors")
    return {
        "batch_id": batch.id,
        "summary": {"rows": processed, "created": len(created_ids),
                    "updated": len(upserted_ids), "errors": len(row_errors),
                    "report_date": rd.isoformat()},
        "created_product_ids": created_ids,
        "errors": row_errors,
    }


def _t(v) -> str:
    """Trim helper for imported text (None -> '', collapsed whitespace)."""
    return " ".join((v or "").split())