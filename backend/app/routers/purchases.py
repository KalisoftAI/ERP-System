"""Purchase order management (CRUD + receipt updates)."""
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import CurrentUser, ManagerOrAdmin
from ..crud import apply_updates, get_or_404, write_audit
from ..database import get_db
from ..models import (
    MovementType, Product, ProductCategory,
    PurchaseOrder, PurchaseOrderLine, PurchaseStatus, Supplier,
    ImportBatch,
)
from ..services.business import sync_purchase_shortages
from ..services.import_common import (
    build_column_map, cell_num, is_blank_row, normalize_header, parse_date_value,
    read_table, row_to_dict,
)
from ..services.reorder_alerts import refresh_reorder_alert
from ..services.rm_service import add_rm_inward, match_raw_material
from ..services.stock_service import apply_movement, resolve_or_create_product, reverse_and_remove_ref
from ..schemas import (
    PurchaseOrderCreate, PurchaseOrderLineIn, PurchaseOrderUpdate,
)
from datetime import date
import json

router = APIRouter(prefix="/purchases", tags=["purchases"])


def _serialize_po(db: Session, po: PurchaseOrder) -> dict:
    supplier = po.supplier
    lines = []
    for ln in po.lines:
        lines.append({
            "id": ln.id, "product_id": ln.product_id, "description": ln.description,
            "item_code": ln.item_code or (ln.product.item_code if ln.product else ""),
            "quantity": ln.quantity, "received_qty": ln.received_qty,
            "rate": float(ln.rate) if ln.rate is not None else None,
            "amount": float(ln.amount) if ln.amount is not None else None,
            "uom": ln.uom or (ln.product.uom if ln.product else ""),
            "tax_percent": float(ln.tax_percent) if ln.tax_percent is not None else None,
            "discount_percent": float(ln.discount_percent) if ln.discount_percent is not None else None,
            "product": {"id": ln.product.id, "model": ln.product.model, "item_code": ln.product.item_code,
                        "category": ln.product.category.value} if ln.product else None,
        })
    return {
        "id": po.id, "po_number": po.po_number, "supplier_id": po.supplier_id,
        "supplier_name": po.supplier_name or "",
        "order_date": po.order_date, "status": po.status.value,
        "total_amount": float(po.total_amount), "notes": po.notes,
        "created_at": po.created_at,
        "supplier": {"id": supplier.id, "name": supplier.name}
        if supplier else ({"name": po.supplier_name} if po.supplier_name else None),
        "lines": lines,
    }


def _recalc(po: PurchaseOrder, lines: list[PurchaseOrderLine]):
    total = sum(float(l.amount or 0) for l in lines)
    po.total_amount = total
    received = all(float(l.received_qty or 0) >= float(l.quantity or 0) and float(l.quantity or 0) > 0 for l in lines if l.quantity)
    partial = any(float(l.received_qty or 0) > 0 for l in lines)
    if lines and received:
        po.status = PurchaseStatus.received
    elif partial:
        po.status = PurchaseStatus.partially_received
    else:
        po.status = PurchaseStatus.ordered


def _attach_stock_warnings(result: dict, lines):
    """Add a `warnings` list only for received lines that truly cannot be
    stock-tracked (no linked product, no Item Code AND no description).

    Blank-item-code lines with a description get their own tracked Product via
    `_resolve_line_product` (internal ID), so they never appear here."""
    flagged = [ln for ln in lines
               if ln.product_id is None
               and not (ln.item_code or "").strip()
               and not (ln.description or "").strip()
               and float(ln.received_qty or 0) > 0]
    if flagged:
        result["warnings"] = [
            f"Line {ln.id} has no Item Code, no description and no linked product — "
            "its quantity could not be mapped to a Product, so stock was NOT updated. "
            "Add a description (or an Item Code, or select a product) to track stock."
            for ln in flagged]


def _resolve_line_product(db: Session, line: PurchaseOrderLine) -> Product | None:
    """Return the Product that owns inventory/stock for a PO line.

    Catalogue-linked lines resolve directly (their internal Product ID is the
    definitive tracker). Manual lines with no linked product are resolved via
    `resolve_or_create_product` with `allow_blank=True`: an Item Code matches/
    creates a Product keyed on (item_code, model), and a blank Item Code with a
    description gets its own fresh Product so stock is always tracked. Two
    blank-code lines with the same description are never merged — each keeps a
    distinct internal ID. If a blank-code line later gets an Item Code, the code
    is written onto the same Product ID so stock history is preserved. Returns
    None only when there is genuinely nothing to identify (blank code and
    description, no linked product).
    """
    if line.product_id:
        p = db.get(Product, line.product_id)
        ic = (line.item_code or "").strip()
        if p is not None and ic and not (p.item_code or "").strip():
            conflict = db.scalar(select(Product.id).where(
                Product.item_code == ic, Product.id != p.id).limit(1))
            if conflict is None:
                p.item_code = ic
        return p
    p = resolve_or_create_product(db, line.item_code, line.description, allow_blank=True)
    if p:
        line.product_id = p.id
    return p


@router.get("", response_model=dict)
def list_purchases(
    db: Annotated[Session, Depends(get_db)],
    _: CurrentUser,
    search: str = "",
    supplier_id: int | None = None,
    status_: str = Query(default="", alias="status"),
    date_from: str = "",
    date_to: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=500),
):
    stmt = select(PurchaseOrder)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(PurchaseOrder.po_number.ilike(like), PurchaseOrder.notes.ilike(like)))
    if supplier_id:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
    if status_:
        stmt = stmt.where(PurchaseOrder.status == status_)
    if date_from:
        stmt = stmt.where(PurchaseOrder.order_date >= date.fromisoformat(date_from))
    if date_to:
        stmt = stmt.where(PurchaseOrder.order_date <= date.fromisoformat(date_to))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(PurchaseOrder.order_date.desc(), PurchaseOrder.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_serialize_po(db, p) for p in rows],
            "total": total, "page": page, "page_size": page_size}


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_purchase(body: PurchaseOrderCreate, db: Annotated[Session, Depends(get_db)],
                    user: ManagerOrAdmin):
    if body.supplier_id is not None and not db.get(Supplier, body.supplier_id):
        raise HTTPException(status_code=400, detail=f"Supplier {body.supplier_id} not found")
    po = PurchaseOrder(po_number=body.po_number, supplier_id=body.supplier_id,
                       supplier_name=(body.supplier_name or "").strip(),
                       order_date=body.order_date, notes=body.notes)
    lines = [PurchaseOrderLine(**ln.model_dump()) for ln in body.lines]
    po.lines = lines
    _recalc(po, lines)
    db.add(po)
    db.commit()
    db.refresh(po)
    write_audit(db, user, "CREATE", "purchase_orders", po.id, f"Created PO {po.po_number}")
    return _serialize_po(db, po)


@router.get("/{po_id}", response_model=dict)
def get_purchase(po_id: int, db: Annotated[Session, Depends(get_db)],
                 _: CurrentUser):
    po = get_or_404(db, PurchaseOrder, po_id)
    return _serialize_po(db, po)


@router.patch("/{po_id}", response_model=dict)
def update_purchase(po_id: int, body: PurchaseOrderUpdate, db: Annotated[Session, Depends(get_db)],
                    user: ManagerOrAdmin):
    po = get_or_404(db, PurchaseOrder, po_id)
    if body.po_number is not None and body.po_number != po.po_number:
        po.po_number = body.po_number
    if body.supplier_id is not None and not db.get(Supplier, body.supplier_id):
        raise HTTPException(status_code=400, detail=f"Supplier {body.supplier_id} not found")
    apply_updates(po, body, exclude={"lines", "po_number"})
    if body.lines is not None:
        # Reverse every previously received quantity before replacing the
        # line set, so editing a received PO never leaves stale stock.
        reverse_and_remove_ref(db, "purchase_order", po.id)
        db.query(PurchaseOrderLine).filter(PurchaseOrderLine.po_id == po.id).delete()
        lines = [PurchaseOrderLine(**ln.model_dump()) for ln in body.lines]
        for ln in lines:
            if ln.received_qty and ln.received_qty > float(ln.quantity or 0):
                raise HTTPException(status_code=400,
                                    detail="Received quantity cannot exceed ordered quantity")
        po.lines = lines
        for ln in lines:
            if ln.received_qty:
                product = _resolve_line_product(db, ln)
                if product:
                    apply_movement(db, product.id, MovementType.receipt, ln.received_qty,
                                   date.today(), ref_type="purchase_order", ref_id=po.id,
                                   remarks=f"Receipt against PO {po.po_number}")
                    refresh_reorder_alert(db, product.id)
        _recalc(po, lines)
    db.commit()
    db.refresh(po)
    write_audit(db, user, "UPDATE", "purchase_orders", po.id, f"Updated PO {po.po_number}")
    result = _serialize_po(db, po)
    _attach_stock_warnings(result, po.lines)
    return result


@router.post("/{po_id}/receive", response_model=dict)
def receive_purchase(po_id: int, line_id: int, received_qty: float,
                     db: Annotated[Session, Depends(get_db)],
                     user: ManagerOrAdmin):
    """Record receipt of goods against a PO line; updates inventory + movements.

    `received_qty` is the ABSOLUTE CUMULATIVE quantity received for the line,
    not the per-input increment. Over-receipt beyond the ordered quantity or
    into negative territory is rejected. Receipts on raw-material lines also
    update the RM schedule/inward tracking (see `add_rm_inward`)."""
    po = get_or_404(db, PurchaseOrder, po_id)
    line = db.get(PurchaseOrderLine, line_id)
    if line is None or line.po_id != po.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Line not found on PO")
    if received_qty < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Received qty cannot be negative")
    ordered = float(line.quantity or 0)
    if ordered > 0 and received_qty > ordered:
        remaining = max(ordered - float(line.received_qty or 0), 0)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot receive {received_qty:g} against ordered quantity {ordered:g} "
                   f"(remaining {remaining:g}). Received qty is the CUMULATIVE total, "
                   "not the quantity for this receipt.")
    delta = received_qty - float(line.received_qty or 0)
    line.received_qty = received_qty
    product = _resolve_line_product(db, line)
    if product:
        if delta:
            apply_movement(db, product.id, MovementType.receipt, delta,
                           date.today(), ref_type="purchase_order", ref_id=po.id,
                           remarks=f"Receipt against PO {po.po_number}")
            refresh_reorder_alert(db, product.id)
            if product.category == ProductCategory.raw_material:
                add_rm_inward(db, product.id, delta)
    _recalc(po, po.lines)
    db.commit()
    db.refresh(po)
    write_audit(db, user, "RECEIVE", "purchase_orders", po.id, f"Received {received_qty} for line {line_id}")
    sync_purchase_shortages(db)
    result = _serialize_po(db, po)
    _attach_stock_warnings(result, po.lines)
    return result


@router.delete("/{po_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_purchase(po_id: int, db: Annotated[Session, Depends(get_db)],
                    user: ManagerOrAdmin):
    po = get_or_404(db, PurchaseOrder, po_id)
    reverse_and_remove_ref(db, "purchase_order", po.id)
    db.delete(po)
    db.commit()
    write_audit(db, user, "DELETE", "purchase_orders", po_id, f"Deleted PO {po.po_number}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


PO_HEADER_ALIASES = {
    "po_number": ["po number", "po no", "purchase order no", "purchase order number",
                  "po", "po#", "po#number", "tin po number"],
    "order_date": ["po date", "order date", "date", "purchase order date"],
    "supplier": ["supplier", "supplier name", "vendor", "vendor name",
                 "supplier company", "company"],
    "item_code": ["item code", "code", "sku", "item no", "item code no", "part no",
                  "item code number"],
    "description": ["item", "description", "product", "item description", "model",
                    "material", "material name", "particulars", "item name",
                    "product name", "article"],
    "quantity": ["quantity", "qty", "order qty", "po qty", "ordered qty"],
    "uom": ["uom", "unit", "units", "unit of measure"],
    "rate": ["rate", "unit rate", "price", "unit price", "unit price incl gst"],
    "tax_percent": ["tax", "tax %", "gst", "gst %", "tax percent", "gst percent"],
    "discount_percent": ["discount", "discount %", "disc", "discount percent"],
    "amount": ["amount", "line amount", "value", "total", "line total"],
    "remarks": ["remarks", "remark", "notes", "note", "narration"],
}


@router.post("/import", response_model=dict)
async def import_purchases(
    db: Annotated[Session, Depends(get_db)],
    user: ManagerOrAdmin,
    file: UploadFile = File(...),
    allow_duplicate: bool = Query(False, description="Allow creating POs whose number already exists"),
):
    """Bulk-create purchase orders from a CSV/Excel upload.

    Rows are grouped by PO number (each group becomes one PO with one line per
    row). Product matching is raw-material-aware: known raw materials always
    resolve to the existing RM master instead of spawning duplicates; anything
    else follows the normal catalogue resolution (existing product by Item
    Code / Model, else a fresh catalogue product). Returns per-PO results plus
    per-row validation errors; nothing is created for invalid or skipped rows.
    """
    content = await file.read()
    try:
        headers, rows = read_table(file.filename or "upload.xlsx", content)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if not rows:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No data rows found in file")
    colmap = build_column_map(headers, PO_HEADER_ALIASES)
    if not colmap:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="No recognized columns found. Expected PO Number, "
                                   "Supplier, Item Code / Description, Quantity, Rate, etc.")

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
        po_number = _t(mapped.get("po_number"))
        model = _t(mapped.get("description"))
        item_code = _t(mapped.get("item_code"))
        qty = cell_num(mapped.get("quantity"))
        if not po_number:
            errors.append("PO number is required")
        if not model and not item_code:
            errors.append("Item/Description or Item Code is required")
        if qty is None or not (qty > 0):
            errors.append("Quantity must be a positive number")
        parsed.append({
            "row": r_i + 2,
            "po_number": po_number,
            "model": model,
            "item_code": item_code,
            "qty": qty,
            "order_date": parse_date_value(mapped.get("order_date")),
            "supplier": _t(mapped.get("supplier")),
            "uom": _t(mapped.get("uom")),
            "rate": cell_num(mapped.get("rate")),
            "tax_percent": cell_num(mapped.get("tax_percent")),
            "discount_percent": cell_num(mapped.get("discount_percent")),
            "amount": cell_num(mapped.get("amount")),
            "remarks": _t(mapped.get("remarks")),
            "errors": errors,
        })

    if not parsed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No data rows found in file")

    errors_rows = [p for p in parsed if p["errors"]]
    valid = [p for p in parsed if not p["errors"]]

    groups: dict[str, list[dict]] = {}
    for p in valid:
        groups.setdefault(p["po_number"], []).append(p)

    created: list[dict] = []
    skipped: list[dict] = []
    line_count = 0
    for po_no, grp in groups.items():
        existing = db.scalars(select(PurchaseOrder).where(
            func.lower(PurchaseOrder.po_number) == po_no.lower())).first()
        if existing is not None and not allow_duplicate:
            skipped.append({"po_number": po_no, "reason": "PO already exists",
                            "po_id": existing.id, "rows": [g["row"] for g in grp]})
            continue

        supplier_name = grp[0]["supplier"]
        supplier = None
        if supplier_name:
            supplier = db.scalars(select(Supplier).where(
                (func.lower(Supplier.name) == supplier_name.lower()) |
                (func.lower(Supplier.company) == supplier_name.lower())
            ).limit(1)).first()

        lines = []
        for p in grp:
            product = match_raw_material(db, p["item_code"], p["model"])
            if product is None:
                product = resolve_or_create_product(db, p["item_code"], p["model"], allow_blank=True)
            rate = p["rate"]
            qty = float(p["qty"])
            amount = p["amount"]
            if amount is None and rate is not None:
                amount = round(rate * qty, 2)
            lines.append(PurchaseOrderLine(
                product_id=product.id,
                description=p["model"],
                item_code=p["item_code"],
                quantity=qty,
                rate=rate,
                amount=amount,
                uom=p["uom"],
                tax_percent=p["tax_percent"],
                discount_percent=p["discount_percent"],
            ))

        po = PurchaseOrder(
            po_number=po_no,
            supplier_id=supplier.id if supplier else None,
            supplier_name="" if supplier else supplier_name,
            order_date=grp[0]["order_date"] or date.today(),
            notes=grp[0]["remarks"] or "",
        )
        po.lines = lines
        _recalc(po, lines)
        db.add(po)
        db.flush()
        created.append({
            "po_id": po.id,
            "po_number": po_no,
            "supplier": supplier.name if supplier else supplier_name,
            "lines": len(lines),
            "order_date": po.order_date.isoformat() if po.order_date else None,
            "rows": [g["row"] for g in grp],
        })
        line_count += len(lines)

    for c in created:
        write_audit(db, user, "IMPORT", "purchase_orders", c["po_id"],
                    f"Bulk-imported PO {c['po_number']} ({c['lines']} lines)")
    batch.stats = json.dumps({
        "rows": len(parsed), "created": len(created), "skipped": len(skipped),
        "errors": len(errors_rows), "lines": line_count, "source": file.filename or "",
    })
    db.commit()
    return {
        "batch_id": batch.id,
        "summary": {"rows": len(parsed), "created": len(created),
                    "skipped": len(skipped), "errors": len(errors_rows),
                    "lines": line_count},
        "created": created,
        "skipped": skipped,
        "errors": [{"row": e["row"], "message": "; ".join(e["errors"])} for e in errors_rows],
    }


def _t(v) -> str:
    """Trim helper for imported text (None -> '', whitespace trimmed)."""
    return (v or "").strip()