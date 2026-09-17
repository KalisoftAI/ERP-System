"""Raw-material shared helpers: identity matching + inward (schedule) sync.

Identity rule: a raw material is a Product with category=raw_material. Matching
always prefers an existing RAW MATERIAL product (item_code first, then
normalized model/name) so imports and purchase flows never duplicate the fixed
master identities (LLDPE SLIP, LLDPE NON SLIP, HDPE, FILLER, …) or silently
create a TRADING product for a known raw material.

`add_rm_inward` keeps RawMaterialBalance (schedule/inward tracking) in sync
with physical receipts. It NEVER posts a StockMovement — physical stock stays
sourced from Inventory via the stock-movement pipeline only.
"""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Product, ProductCategory, RawMaterialBalance

_WS_RE = re.compile(r"\s+")


def normalize_key(s: str) -> str:
    """Case/whitespace-insensitive comparison key: 'LLDPE  Slip' -> 'lldpe slip'."""
    return _WS_RE.sub(" ", (s or "").strip().lower())


def squash_key(s: str) -> str:
    """Fully space-insensitive key: '3518DC MACHINE GRADE / MK' ~= '3518DC MACHINE GRADE/MK'."""
    return re.sub(r"\s+", "", (s or "").lower())


def match_raw_material(db: Session, item_code: str = "", model: str = "") -> Product | None:
    """Find the best existing Product for a raw-material reference.

    Matching intentionally ignores is_active: repurchasing or re-importing a
    soft-deleted material must resolve to the SAME identity (never a fresh
    duplicate). Deactivated products stay hidden from lists/options, but once
    matched again they are resurrected by `get_or_create_raw_material`.

    Order: exact item_code(+model) among raw materials -> item_code among raw
    materials -> normalized model among raw materials -> space-insensitive model
    among raw materials -> item_code on any product -> normalized model on any
    product. Returns None when nothing reliable matches.
    """
    ic = (item_code or "").strip()
    mdl = (model or "").strip()
    rms = db.scalars(select(Product).where(
        Product.category == ProductCategory.raw_material)).all()

    if ic:
        ic_l = ic.lower()
        for p in rms:
            if (p.item_code or "").strip().lower() == ic_l and (
                    not mdl or normalize_key(p.model) == normalize_key(mdl)):
                return p
        for p in rms:
            if (p.item_code or "").strip().lower() == ic_l:
                return p
    if mdl:
        for p in rms:
            if normalize_key(p.model) == normalize_key(mdl):
                return p
        for p in rms:
            if squash_key(p.model) == squash_key(mdl):
                return p
    if ic:
        p = db.scalar(select(Product).where(
            func.lower(Product.item_code) == ic.lower()).limit(1))
        if p is not None:
            return p
    if mdl:
        for p in db.scalars(select(Product)).all():
            if normalize_key(p.model) == normalize_key(mdl) or squash_key(p.model) == squash_key(mdl):
                return p
    return None


def get_or_create_raw_material(db: Session, item_code: str, model: str,
                               uom: str = "kg") -> tuple[Product, bool]:
    """Match an existing product (RM-first); create category=raw_material only
    when nothing matches. Never creates a TRADING duplicate of a known RM. A
    soft-deleted (inactive) match is resurrected — the user is actively using
    the material again."""
    found = match_raw_material(db, item_code, model)
    if found is not None:
        if not found.is_active:
            found.is_active = True
            db.flush()
        return found, False
    name = (model or "").strip() or (item_code or "").strip()
    p = Product(item_code=(item_code or "").strip(), model=name,
                category=ProductCategory.raw_material, uom=(uom or "kg").strip() or "kg")
    db.add(p)
    db.flush()
    return p, True


def _recalc_balance(b: RawMaterialBalance) -> None:
    """Mirror of routers.raw_materials._recalc (kept here so services never
    import routers). Balance = Schedule - Inward; % = Inward / Schedule."""
    if b.schedule_qty is None:
        return
    sched = float(b.schedule_qty)
    inward = float(b.inward_qty or 0)
    b.balance_qty = round(sched - inward, 4)
    b.completion_pct = round(inward / sched, 4) if sched else 0.0


def add_rm_inward(db: Session, product_id: int, delta: float,
                  report_date: date | None = None) -> RawMaterialBalance | None:
    """Add a purchase-receipt delta to the raw material's inward tracking.

    Updates ONLY RawMaterialBalance (schedule/inward layer). No StockMovement
    is created here — the caller's apply_movement is the single physical
    stock effect. The receipt lands on the most recent balance row (the active
    tracking period); a fresh row for `report_date` (default today) is created
    only when the product has no balance yet. Returns the balance row, or None
    for non-RM products.
    """
    if not delta:
        return None
    product = db.get(Product, product_id)
    if product is None or product.category != ProductCategory.raw_material:
        return None
    b = db.scalars(select(RawMaterialBalance).where(
        RawMaterialBalance.product_id == product_id)
        .order_by(RawMaterialBalance.report_date.desc())
        .limit(1)).first()
    if b is None:
        rd = report_date or date.today()
        b = RawMaterialBalance(product_id=product_id, report_date=rd, inward_qty=0)
        db.add(b)
    b.inward_qty = round(float(b.inward_qty or 0) + float(delta), 4)
    _recalc_balance(b)
    db.flush()
    return b
