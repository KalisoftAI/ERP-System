"""Self-check for Import PO supplier snapshots + PO type.

Plain asserts (no pytest dependency). Run from the backend directory:

    python tests/test_import_po_supplier.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from starlette.responses import Response  # noqa: E402

from app.database import Base  # noqa: E402
from app.models import PurchaseOrder, Supplier  # noqa: E402
from app.routers import purchases as purchases_router  # noqa: E402
from app.schemas import PurchaseOrderCreate, PurchaseOrderLineIn, PurchaseOrderUpdate  # noqa: E402


class _User:
    id = 1
    full_name = "Buyer"
    username = "buyer"


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _with_silent_audit(fn):
    original = purchases_router.write_audit
    purchases_router.write_audit = lambda *a, **k: None
    try:
        return fn()
    finally:
        purchases_router.write_audit = original


def _create(db, **kwargs):
    body = PurchaseOrderCreate(
        lines=[PurchaseOrderLineIn(description="Bearing", quantity=2, rate=5)],
        **kwargs,
    )
    return _with_silent_audit(
        lambda: purchases_router.create_purchase(body, db, _User(), Response()))


def test_manual_import_supplier_stays_on_po():
    db = _session()
    out = _create(
        db, po_number="IPO-MANUAL", po_type="import",
        supplier_name="Manual Imports Co", supplier_address="12 Test Road",
        supplier_email="buy@manual.example", idempotency_key="manual-1")

    assert out["po_type"] == "import"
    assert out["supplier"] == {
        "id": None, "name": "Manual Imports Co", "gstin": "",
        "address": "12 Test Road", "phone": "", "email": "buy@manual.example",
    }
    assert db.query(Supplier).count() == 0

    po_id = out["id"]
    updated = _with_silent_audit(lambda: purchases_router.update_purchase(
        po_id,
        PurchaseOrderUpdate(
            po_type="import", supplier_name="Manual Imports Co",
            supplier_address="99 New Road", supplier_email="new@manual.example"),
        db, _User()))
    assert updated["supplier"]["address"] == "99 New Road"
    assert updated["supplier"]["email"] == "new@manual.example"
    assert db.query(Supplier).count() == 0
    assert db.get(PurchaseOrder, po_id).supplier_id is None


def test_selected_import_supplier_is_not_modified():
    db = _session()
    master = Supplier(name="Existing Supplier", address="Master Road",
                      email="master@example.com")
    db.add(master)
    db.flush()

    out = _create(
        db, po_number="IPO-SELECTED", po_type="import", supplier_id=master.id,
        supplier_name="Existing Supplier", supplier_address="Edited on PO",
        supplier_email="edited@example.com", idempotency_key="selected-1")

    assert out["po_type"] == "import"
    assert out["supplier"]["address"] == "Edited on PO"
    assert out["supplier"]["email"] == "edited@example.com"
    db.refresh(master)
    assert master.address == "Master Road"
    assert master.email == "master@example.com"


def test_regular_supplier_creation_unchanged():
    db = _session()
    out = _create(
        db, po_number="PO-REGULAR", supplier_name="New Regular Supplier",
        supplier_address="Regular Road", supplier_email="regular@example.com",
        idempotency_key="regular-1")

    assert out["po_type"] == "regular"
    assert db.query(Supplier).count() == 1
    assert out["supplier"]["name"] == "New Regular Supplier"


if __name__ == "__main__":
    test_manual_import_supplier_stays_on_po()
    test_selected_import_supplier_is_not_modified()
    test_regular_supplier_creation_unchanged()
    print("Import PO supplier + type self-check passed.")
