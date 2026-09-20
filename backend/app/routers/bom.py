from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import AllStaff, CurrentUser, ManagerOrAdmin
from ..database import get_db
from ..models import BOM, BillOfMaterial, Product, ProductCategory
from ..schemas import BOMCreate, BOMGroupIn, BOMUpdate

router = APIRouter(prefix="/bom", tags=["BOM"])


def _product_name(db: Session, product_id: int) -> str:
    p = db.get(Product, product_id)
    return p.model if p else "Unknown"


def _resolve_product(db: Session, product_id, product_name, category: ProductCategory) -> Product:
    """Select an existing product by id, or by typed name (manual input).
    A typed name that matches no existing product is auto-created (mirroring the
    customer auto-create flow) so manual entry is never forced to a selection."""
    if product_id:
        p = db.get(Product, int(product_id))
        if not p:
            raise HTTPException(404, f"Product {product_id} not found")
        return p
    name = (product_name or "").strip()
    if not name:
        raise HTTPException(400, "A product is required — select one or type a name")
    p = db.query(Product).filter(func.lower(Product.model) == name.lower()).first()
    if p is None:
        p = db.query(Product).filter(func.lower(Product.name) == name.lower()).first()
    if p is None:
        p = Product(model=name, name=name, category=category, uom="Each", is_active=True)
        db.add(p)
        db.flush()
    return p


def _serialize_line(db: Session, line: BillOfMaterial) -> dict:
    return {
        "id": line.id,
        "raw_material_product_id": line.raw_material_product_id,
        "raw_material_name": _product_name(db, line.raw_material_product_id),
        "quantity_per_unit": line.quantity_per_unit,
        "uom": line.uom,
        "is_active": line.is_active,
    }


def _serialize_group(db: Session, bom: BOM) -> dict:
    lines = (
        db.query(BillOfMaterial)
        .filter(BillOfMaterial.bom_id == bom.id)
        .order_by(BillOfMaterial.id)
        .all()
    )
    return {
        "id": bom.id,
        "bom_code": bom.bom_code,
        "product_id": bom.product_id,
        "product_name": _product_name(db, bom.product_id),
        "effective_date": bom.effective_date.isoformat() if bom.effective_date else None,
        "version": bom.version,
        "notes": bom.notes or "",
        "is_active": bom.is_active,
        "created_at": bom.created_at.isoformat() if bom.created_at else None,
        "updated_at": bom.updated_at.isoformat() if bom.updated_at else None,
        "lines": [_serialize_line(db, l) for l in lines],
    }


def _serialize_legacy(db: Session, line: BillOfMaterial) -> dict:
    """Historical single-line BOM with no header — shown safely, never modified."""
    return {
        "id": None,
        "bom_code": "",
        "product_id": line.product_id,
        "product_name": _product_name(db, line.product_id),
        "effective_date": line.effective_date.isoformat() if line.effective_date else None,
        "version": line.version,
        "notes": line.notes or "",
        "is_active": line.is_active,
        "created_at": line.created_at.isoformat() if line.created_at else None,
        "updated_at": line.updated_at.isoformat() if line.updated_at else None,
        "lines": [_serialize_line(db, line)],
    }


def _bom_with_names(db: Session, bom: BillOfMaterial) -> dict:
    """Serialize BOM line with product names resolved."""
    return {
        "id": bom.id,
        "bom_id": bom.bom_id,
        "bom_code": bom.bom.bom_code if bom.bom else "",
        "product_id": bom.product_id,
        "raw_material_product_id": bom.raw_material_product_id,
        "quantity_per_unit": bom.quantity_per_unit,
        "uom": bom.uom,
        "effective_date": bom.effective_date.isoformat() if bom.effective_date else None,
        "version": bom.version,
        "notes": bom.notes or "",
        "is_active": bom.is_active,
        "created_at": bom.created_at.isoformat() if bom.created_at else None,
        "updated_at": bom.updated_at.isoformat() if bom.updated_at else None,
        "product_name": _product_name(db, bom.product_id),
        "raw_material_name": _product_name(db, bom.raw_material_product_id),
    }


# ---------------------------------------------------------------------------
# BOM groups: ONE BOM (unique BOM Code) with MULTIPLE raw material lines
# ---------------------------------------------------------------------------
@router.get("/groups")
def list_bom_groups(
    _: CurrentUser,
    product_id: int | None = None,
    is_active: bool | None = True,
    db: Session = Depends(get_db),
):
    out = []
    q = db.query(BOM).order_by(BOM.product_id, BOM.id)
    if product_id:
        q = q.filter(BOM.product_id == product_id)
    if is_active is not None:
        q = q.filter(BOM.is_active == is_active)
    for b in q.all():
        out.append(_serialize_group(db, b))
    # Historical single-line rows without a header — kept intact, listed as
    # their own (code-less) BOM so nothing is hidden or corrupted.
    lq = db.query(BillOfMaterial).filter(BillOfMaterial.bom_id.is_(None))
    if product_id:
        lq = lq.filter(BillOfMaterial.product_id == product_id)
    if is_active is not None:
        lq = lq.filter(BillOfMaterial.is_active == is_active)
    for l in lq.order_by(BillOfMaterial.product_id, BillOfMaterial.id).all():
        out.append(_serialize_legacy(db, l))
    return out


@router.get("/groups/{group_id}")
def get_bom_group(group_id: int, _: CurrentUser, db: Session = Depends(get_db)):
    bom = db.get(BOM, group_id)
    if not bom:
        raise HTTPException(404, "BOM group not found")
    return _serialize_group(db, bom)


@router.post("/groups", status_code=201)
def create_bom_group(body: BOMGroupIn, _: AllStaff, db: Session = Depends(get_db)):
    code = (body.bom_code or "").strip().upper()
    if not code:
        raise HTTPException(400, "BOM Code is required")
    dup = db.query(BOM).filter(func.lower(BOM.bom_code) == code.lower()).first()
    if dup:
        raise HTTPException(400, f"BOM Code '{body.bom_code}' already exists. Use a different code.")
    product = _resolve_product(db, body.product_id, body.product_name, ProductCategory.finished)
    if not body.lines:
        raise HTTPException(400, "Add at least one raw material line")
    bom = BOM(bom_code=code, product_id=product.id, effective_date=body.effective_date,
              version=body.version or 1, notes=body.notes or "", is_active=body.is_active)
    db.add(bom)
    db.flush()
    used_rm = set()
    for ln in body.lines:
        rm = _resolve_product(db, ln.raw_material_product_id, ln.raw_material_name,
                              ProductCategory.raw_material)
        if rm.id == product.id:
            raise HTTPException(400, "Finished product and raw material cannot be the same")
        if rm.id in used_rm:
            raise HTTPException(400, f"Duplicate raw material '{rm.model}' in the same BOM")
        used_rm.add(rm.id)
        if not (ln.quantity_per_unit > 0):
            raise HTTPException(400, "Each raw material quantity must be > 0")
        line = None
        if ln.id:
            existing = db.get(BillOfMaterial, ln.id)
            if existing:
                if existing.bom_id is not None:
                    raise HTTPException(400, f"Line {ln.id} already belongs to another BOM")
                line = existing  # legacy single-line upgrade — attach under this BOM
        if line is None:
            line = BillOfMaterial()
            db.add(line)
        line.bom_id = bom.id
        line.product_id = product.id
        line.raw_material_product_id = rm.id
        line.quantity_per_unit = ln.quantity_per_unit
        line.uom = (ln.uom or "KG").strip() or "KG"
        line.version = body.version or 1
        line.effective_date = body.effective_date
        line.is_active = body.is_active
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "Duplicate raw material line for this product/version")
    db.refresh(bom)
    return _serialize_group(db, bom)


@router.put("/groups/{group_id}")
def update_bom_group(group_id: int, body: BOMGroupIn, _: AllStaff, db: Session = Depends(get_db)):
    bom = db.get(BOM, group_id)
    if not bom:
        raise HTTPException(404, "BOM group not found")
    code = (body.bom_code or "").strip().upper()
    if not code:
        raise HTTPException(400, "BOM Code is required")
    dup = db.query(BOM).filter(func.lower(BOM.bom_code) == code.lower(), BOM.id != bom.id).first()
    if dup:
        raise HTTPException(400, f"BOM Code '{body.bom_code}' already exists. Use a different code.")
    product = _resolve_product(db, body.product_id, body.product_name, ProductCategory.finished)
    if not body.lines:
        raise HTTPException(400, "Add at least one raw material line")
    existing = {l.id: l for l in db.query(BillOfMaterial).filter(BillOfMaterial.bom_id == bom.id).all()}
    keep = set()
    used_rm = set()
    for ln in body.lines:
        rm = _resolve_product(db, ln.raw_material_product_id, ln.raw_material_name,
                              ProductCategory.raw_material)
        if rm.id == product.id:
            raise HTTPException(400, "Finished product and raw material cannot be the same")
        if rm.id in used_rm:
            raise HTTPException(400, f"Duplicate raw material '{rm.model}' in the same BOM")
        used_rm.add(rm.id)
        if not (ln.quantity_per_unit > 0):
            raise HTTPException(400, "Each raw material quantity must be > 0")
        if ln.id and ln.id in existing:
            line = existing[ln.id]
            keep.add(ln.id)
        else:
            line = BillOfMaterial()
            db.add(line)
        line.bom_id = bom.id
        line.product_id = product.id
        line.raw_material_product_id = rm.id
        line.quantity_per_unit = ln.quantity_per_unit
        line.uom = (ln.uom or "KG").strip() or "KG"
        line.version = body.version or 1
        line.effective_date = body.effective_date
        line.is_active = body.is_active
    for lid, line in existing.items():
        if lid not in keep:
            db.delete(line)
    bom.bom_code = code
    bom.product_id = product.id
    bom.effective_date = body.effective_date
    bom.version = body.version or 1
    bom.notes = body.notes or ""
    bom.is_active = body.is_active
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "Duplicate raw material line for this product/version")
    db.refresh(bom)
    return _serialize_group(db, bom)


@router.delete("/groups/{group_id}")
def deactivate_bom_group(group_id: int, _: ManagerOrAdmin, db: Session = Depends(get_db)):
    bom = db.get(BOM, group_id)
    if not bom:
        raise HTTPException(404, "BOM group not found")
    bom.is_active = False
    for l in db.query(BillOfMaterial).filter(BillOfMaterial.bom_id == bom.id).all():
        l.is_active = False
    db.commit()
    return {"message": "BOM group deactivated", "id": group_id}


# ---------------------------------------------------------------------------
# Legacy single-line endpoints (kept for backward compatibility)
# ---------------------------------------------------------------------------


@router.get("")
def list_bom(_: CurrentUser, product_id: int | None = None, is_active: bool = True, db: Session = Depends(get_db)):
    q = db.query(BillOfMaterial).order_by(BillOfMaterial.product_id, BillOfMaterial.version)
    if product_id:
        q = q.filter(BillOfMaterial.product_id == product_id)
    if is_active is not None:
        q = q.filter(BillOfMaterial.is_active == is_active)
    items = q.all()
    return [_bom_with_names(db, b) for b in items]


@router.get("/by-product/{product_id}")
def bom_for_product(product_id: int, _: CurrentUser, db: Session = Depends(get_db)):
    """Get all active BOM lines for a finished product."""
    items = (
        db.query(BillOfMaterial)
        .filter(BillOfMaterial.product_id == product_id, BillOfMaterial.is_active == True)
        .order_by(BillOfMaterial.version, BillOfMaterial.id)
        .all()
    )
    return [_bom_with_names(db, b) for b in items]


@router.post("", status_code=201)
def create_bom(body: BOMCreate, _: AllStaff, db: Session = Depends(get_db)):
    if body.product_id == body.raw_material_product_id:
        raise HTTPException(400, "Finished product and raw material cannot be the same")
    product = db.get(Product, body.product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    rm = db.get(Product, body.raw_material_product_id)
    if not rm:
        raise HTTPException(404, "Raw material product not found")
    if body.quantity_per_unit <= 0:
        raise HTTPException(400, "Quantity per unit must be > 0")
    dup = (
        db.query(BillOfMaterial)
        .filter(
            BillOfMaterial.product_id == body.product_id,
            BillOfMaterial.raw_material_product_id == body.raw_material_product_id,
            BillOfMaterial.version == body.version,
            BillOfMaterial.is_active == True,
        )
        .first()
    )
    if dup:
        raise HTTPException(400, "Duplicate active BOM line for this product/raw material/version")
    bom = BillOfMaterial(**body.model_dump())
    db.add(bom)
    db.commit()
    db.refresh(bom)
    return _bom_with_names(db, bom)


@router.put("/{bom_id}")
def update_bom(bom_id: int, body: BOMUpdate, _: AllStaff, db: Session = Depends(get_db)):
    bom = db.get(BillOfMaterial, bom_id)
    if not bom:
        raise HTTPException(404, "BOM line not found")
    if body.product_id is not None and body.raw_material_product_id is not None:
        if body.product_id == body.raw_material_product_id:
            raise HTTPException(400, "Finished product and raw material cannot be the same")
    prod_id = body.product_id if body.product_id is not None else bom.product_id
    rm_id = body.raw_material_product_id if body.raw_material_product_id is not None else bom.raw_material_product_id
    if not db.get(Product, prod_id):
        raise HTTPException(404, "Product not found")
    if not db.get(Product, rm_id):
        raise HTTPException(404, "Raw material product not found")
    if body.quantity_per_unit is not None and body.quantity_per_unit <= 0:
        raise HTTPException(400, "Quantity per unit must be > 0")
    if body.product_id is not None or body.raw_material_product_id is not None:
        version = body.version if body.version is not None else bom.version
        dup = (
            db.query(BillOfMaterial)
            .filter(
                BillOfMaterial.product_id == prod_id,
                BillOfMaterial.raw_material_product_id == rm_id,
                BillOfMaterial.version == version,
                BillOfMaterial.is_active == True,
                BillOfMaterial.id != bom_id,
            )
            .first()
        )
        if dup:
            raise HTTPException(400, "Duplicate active BOM line for this product/raw material/version")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(bom, k, v)
    db.commit()
    db.refresh(bom)
    return _bom_with_names(db, bom)


@router.patch("/{bom_id}")
def patch_bom(bom_id: int, body: BOMUpdate, _: AllStaff, db: Session = Depends(get_db)):
    """Alias for PUT - partial update."""
    return update_bom(bom_id, body, db)


@router.delete("/{bom_id}")
def delete_bom(bom_id: int, _: ManagerOrAdmin, db: Session = Depends(get_db)):
    """Soft-delete by deactivating."""
    bom = db.get(BillOfMaterial, bom_id)
    if not bom:
        raise HTTPException(404, "BOM line not found")
    bom.is_active = False
    db.commit()
    return {"message": "BOM line deactivated", "id": bom_id}


@router.get("/validate")
def validate_bom_data(_: CurrentUser, db: Session = Depends(get_db)):
    """Return validation summary for all active BOMs."""
    boms = db.query(BillOfMaterial).filter(BillOfMaterial.is_active == True).all()
    issues = []
    for b in boms:
        product = db.get(Product, b.product_id)
        rm = db.get(Product, b.raw_material_product_id)
        if not product:
            issues.append(f"BOM#{b.id}: product_id {b.product_id} not found")
        if not rm:
            issues.append(f"BOM#{b.id}: raw_material_product_id {b.raw_material_product_id} not found")
        if b.quantity_per_unit <= 0:
            issues.append(f"BOM#{b.id}: quantity_per_unit must be > 0")
    return {"total_boms": len(boms), "issues": issues}
