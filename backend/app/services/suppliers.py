"""Supplier helpers for the supplier master.

Any module that accepts free-text supplier details promotes the supplier to the
Supplier table so the record is reusable across the whole ERP. Auto-creation is
case-insensitive and GSTIN-aware to avoid duplicate supplier records.
"""
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import Supplier


def _norm(s: str | None) -> str:
    return (s or "").strip()


def get_or_create_supplier(
    db: Session,
    name: str,
    gstin: str = "",
    address: str = "",
    phone: str = "",
    email: str = "",
) -> Supplier | None:
    """Return the supplier for the given details, creating it in the master if new.

    Matching order:
      1. Non-empty GSTIN exact match (after normalisation).
      2. Case-insensitive name exact match (after trimming).

    When an existing supplier is found, empty master fields are only populated
    from the provided values so typed PO data never overwrites existing data.
    Returns None when no name is given.
    """
    name = _norm(name)
    if not name:
        return None

    gstin = _norm(gstin)
    address = _norm(address)
    phone = _norm(phone)
    email = _norm(email)

    supplier = None
    if gstin:
        supplier = db.scalars(
            select(Supplier).where(func.lower(Supplier.gstin) == gstin.lower()).limit(1)
        ).first()

    if supplier is None:
        supplier = db.scalars(
            select(Supplier).where(func.lower(Supplier.name) == name.lower()).limit(1)
        ).first()

    if supplier is None:
        supplier = Supplier(
            name=name,
            gstin=gstin,
            address=address,
            phone=phone,
            email=email,
        )
        db.add(supplier)
        db.flush()
        return supplier

    # Safe-first enrichment: only fill master fields that are currently blank.
    if gstin and not _norm(supplier.gstin):
        supplier.gstin = gstin
    if phone and not _norm(supplier.phone):
        supplier.phone = phone
    if email and not _norm(supplier.email):
        supplier.email = email
    if address and not _norm(supplier.address):
        supplier.address = address

    return supplier
