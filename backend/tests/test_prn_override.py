"""Self-check for PRN stock overrides + PDF rendering.

Plain asserts (no pytest dependency). Run from the backend directory:

    python tests/test_prn_override.py

Proves the key data-integrity rules: a PRN stock override is stored on the PRN
line only and NEVER changes actual inventory.
"""
import os
import sys
from datetime import date
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.database import Base  # noqa: E402
from app.models import Inventory, PRN, PRNStatus, Product  # noqa: E402
from app.routers.prns import _apply_lines, _generate_prn_number, _validate_dates  # noqa: E402
from app.schemas import PRNLineIn  # noqa: E402
from app.services.prn_pdf import build_prn_pdf_bytes  # noqa: E402


class _User:
    id = 1
    full_name = "Requester"
    username = "req"


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _prn_with_stock(db, current=50.0):
    token = uuid4().hex[:8]
    product = Product(item_code=f"ITM-{token}", model=f"Steel Plate {token}", uom="Kg")
    db.add(product)
    db.flush()
    db.add(Inventory(product_id=product.id, opening_stock=current, current_stock=current))
    prn = PRN(prn_number=f"PRN-T-{token}", prn_date=date(2026, 10, 17))
    prn.status = PRNStatus.draft
    db.add(prn)
    db.flush()
    return product, prn


def test_override_stored_and_inventory_untouched():
    db = _session()
    product, prn = _prn_with_stock(db, current=50.0)

    changed = _apply_lines(db, prn, [PRNLineIn(
        material_id=product.id, material_code="ITM-001", description="Steel Plate",
        quantity=10, uom="Kg", stock_override=99)], _User())
    db.flush()

    ln = prn.lines[0]
    assert changed is True
    assert ln.stock_override == 99
    assert ln.available_stock == 50.0            # inventory snapshot preserved
    assert ln.stock_overridden_by_name == "Requester"
    assert ln.stock_overridden_at is not None
    # The actual inventory row is untouched by the PRN edit.
    inv = db.query(Inventory).filter_by(product_id=product.id).one()
    assert inv.current_stock == 50.0


def test_clearing_override_reverts_to_snapshot():
    db = _session()
    product, prn = _prn_with_stock(db, current=12.0)

    _apply_lines(db, prn, [PRNLineIn(
        material_id=product.id, description="Steel Plate", quantity=1,
        stock_override=30)], _User())
    db.flush()
    assert prn.lines[0].stock_override == 30

    changed = _apply_lines(db, prn, [PRNLineIn(
        id=prn.lines[0].id, material_id=product.id, description="Steel Plate",
        quantity=1, stock_override=None)], _User())
    db.flush()
    assert changed is True
    assert prn.lines[0].stock_override is None
    assert prn.lines[0].stock_overridden_by_name == ""
    assert prn.lines[0].available_stock == 12.0


def test_manual_line_stock_is_unknown_not_zero():
    db = _session()
    product, prn = _prn_with_stock(db)

    _apply_lines(db, prn, [PRNLineIn(
        description="Unlisted Bearing", quantity=3, uom="Nos")], _User())
    db.flush()
    ln = prn.lines[0]
    assert ln.material_id is None
    assert ln.is_new_material is True
    assert ln.available_stock is None            # unknown, never 0
    assert ln.stock_override is None


def test_pdf_renders_with_override_and_wraps():
    db = _session()
    product, prn = _prn_with_stock(db)
    _apply_lines(db, prn, [PRNLineIn(
        material_id=product.id, description="Steel Plate " * 10, quantity=5,
        uom="Kg", stock_override=7, remarks="long remark " * 10)], _User())
    db.flush()
    pdf = build_prn_pdf_bytes(prn)
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 1000


def test_prn_number_short_sequence():
    """New format is PRN-0001 onwards; legacy monthly numbers are ignored."""
    db = _session()
    assert _generate_prn_number(db) == "PRN-0001"
    db.add(PRN(prn_number="PRN-0007", prn_date=date(2026, 10, 17)))
    db.add(PRN(prn_number="PRN-202610-9999", prn_date=date(2026, 10, 17)))
    db.flush()
    assert _generate_prn_number(db) == "PRN-0008"


def test_validate_dates_rejects_earlier_required_by():
    from fastapi import HTTPException
    _validate_dates(date(2026, 10, 17), date(2026, 10, 20))  # ok
    _validate_dates(date(2026, 10, 17), None)               # ok
    try:
        _validate_dates(date(2026, 10, 17), date(2026, 10, 10))
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("expected 400 for required_by_date < prn_date")


def test_stock_snapshot_is_per_location_not_summed():
    """Stock is read for ONE location; a location with no inventory row is
    Unknown (None), never assumed zero."""
    from app.models import Plant
    from app.routers.prns import _stock_snapshot
    db = _session()
    product = Product(item_code="ITM-100", model="Widget", uom="Nos")
    plant = Plant(name="Dispatch", code="D1")
    other = Plant(name="Production", code="P1")
    db.add_all([product, plant, other])
    db.flush()
    db.add(Inventory(product_id=product.id, plant_id=None, current_stock=10))
    db.add(Inventory(product_id=product.id, plant_id=plant.id, current_stock=5))
    db.flush()
    assert _stock_snapshot(db, product.id)["available_stock"] == 10.0        # Main Store
    disp = _stock_snapshot(db, product.id, plant_id=plant.id)
    assert disp["available_stock"] == 5.0                                    # Dispatch only
    assert disp["location"] == "Dispatch"
    assert _stock_snapshot(db, product.id, plant_id=other.id)["available_stock"] is None


def test_apply_lines_stores_location():
    from app.models import Plant
    db = _session()
    product = Product(item_code="ITM-200", model="Bolt", uom="Nos")
    plant = Plant(name="Dispatch", code="D1")
    db.add_all([product, plant])
    db.flush()
    db.add(Inventory(product_id=product.id, plant_id=plant.id, current_stock=7))
    prn = PRN(prn_number="PRN-L-0001", prn_date=date(2026, 10, 17))
    prn.status = PRNStatus.draft
    db.add(prn)
    db.flush()
    _apply_lines(db, prn, [PRNLineIn(
        material_id=product.id, plant_id=plant.id, material_code="ITM-200",
        description="Bolt", quantity=2, uom="Nos")], _User())
    db.flush()
    ln = prn.lines[0]
    assert ln.plant_id == plant.id
    assert ln.available_stock == 7.0
    assert build_prn_pdf_bytes(prn)[:5] == b"%PDF-"   # plant label renders without crash


def test_create_prn_uses_manual_requested_by_name():
    """A manually entered Requested By name is stored verbatim; a blank value
    falls back to the authenticated user's name."""
    from app.schemas import PRNCreate
    from app.routers import prns as prns_router
    db = _session()
    orig = prns_router.write_audit
    prns_router.write_audit = lambda *a, **k: None   # audit_logs PK is Postgres-only
    try:
        out = prns_router.create_prn(PRNCreate(requested_by_name="Rahul More", lines=[
            PRNLineIn(description="Widget", quantity=1, uom="Nos")]), db, _User())
        assert out["requested_by_name"] == "Rahul More"
        out2 = prns_router.create_prn(PRNCreate(requested_by_name="   ", lines=[
            PRNLineIn(description="Widget", quantity=1, uom="Nos")]), db, _User())
        assert out2["requested_by_name"] == "Requester"
    finally:
        prns_router.write_audit = orig


def test_delete_draft_prn_removes_lines_not_inventory():
    """A Draft PRN is hard-deletable by its requester: the PRN and its lines go,
    inventory and stock records are untouched, and the delete is audited."""
    from fastapi import HTTPException
    from app.models import PRNLine, UserRole, User  # noqa: F401
    from app.routers import prns as prns_router
    db = _session()
    product, prn = _prn_with_stock(db, current=42.0)
    prn.requested_by_id = _User.id
    _apply_lines(db, prn, [PRNLineIn(
        material_id=product.id, material_code="ITM-001", description="Steel Plate",
        quantity=3, uom="Kg")], _User())
    db.commit()
    prn_id, product_id = prn.id, product.id

    calls = []
    orig = prns_router.write_audit
    prns_router.write_audit = lambda db, user, action, entity, eid, details="": calls.append(action)
    try:
        resp = prns_router.delete_prn(prn_id, db, _User())
    finally:
        prns_router.write_audit = orig
    assert resp.status_code == 204
    assert db.get(PRN, prn_id) is None
    assert db.query(PRNLine).filter_by(prn_id=prn_id).count() == 0
    assert db.query(Inventory).filter_by(product_id=product_id).one().current_stock == 42.0
    assert "DELETE" in calls


def test_delete_blocked_when_linked_to_purchase_order():
    from fastapi import HTTPException
    from app.models import PurchaseOrder
    from app.routers import prns as prns_router
    db = _session()
    product, prn = _prn_with_stock(db)
    prn.requested_by_id = _User.id
    _apply_lines(db, prn, [PRNLineIn(
        material_id=product.id, material_code="ITM-001", description="Steel Plate",
        quantity=1, uom="Kg")], _User())
    db.add(PurchaseOrder(po_number="PO-DEL-1", prn_id=prn.id))
    db.commit()

    orig = prns_router.write_audit
    prns_router.write_audit = lambda *a, **k: None
    try:
        try:
            prns_router.delete_prn(prn.id, db, _User())
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("expected 409 when a PO links the PRN")
    finally:
        prns_router.write_audit = orig
    assert db.get(PRN, prn.id) is not None


def test_delete_allowed_for_any_status_when_unlinked():
    """With the approval workflow removed, status no longer gates deletion: an
    approved PRN that is not linked to any purchase order is deletable."""
    from app.routers import prns as prns_router
    db = _session()
    product, prn = _prn_with_stock(db)
    prn.requested_by_id = _User.id
    prn.status = PRNStatus.approved
    db.commit()

    orig = prns_router.write_audit
    prns_router.write_audit = lambda *a, **k: None
    try:
        assert prns_router.delete_prn(prn.id, db, _User()).status_code == 204
    finally:
        prns_router.write_audit = orig
    assert db.get(PRN, prn.id) is None


def test_delete_forbidden_for_non_requester():
    from fastapi import HTTPException
    from app.models import UserRole
    from app.routers import prns as prns_router
    db = _session()
    product, prn = _prn_with_stock(db)
    prn.requested_by_id = 1  # owned by _User

    class _Other:
        id = 2
        full_name = "Other"
        username = "other"
        role = UserRole.store

    db.commit()
    try:
        prns_router.delete_prn(prn.id, db, _Other())
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("expected 403 for a non-requester, non-admin user")
    assert db.get(PRN, prn.id) is not None


def test_delete_cancelled_prn_allowed_but_blocked_when_linked():
    """A Cancelled PRN is deletable, but not if a purchase order already links
    it (cancellation does not erase purchasing history)."""
    from fastapi import HTTPException
    from app.models import PurchaseOrder
    from app.routers import prns as prns_router
    db = _session()
    product, prn = _prn_with_stock(db)
    prn.requested_by_id = _User.id
    prn.status = PRNStatus.cancelled
    db.commit()

    orig = prns_router.write_audit
    prns_router.write_audit = lambda *a, **k: None
    try:
        # Cancelled with no linked PO -> allowed.
        assert prns_router.delete_prn(prn.id, db, _User()).status_code == 204
        assert db.get(PRN, prn.id) is None

        # Cancelled with a linked PO -> blocked.
        product2, prn2 = _prn_with_stock(db)
        prn2.requested_by_id = _User.id
        prn2.status = PRNStatus.cancelled
        db.add(PurchaseOrder(po_number="PO-DEL-2", prn_id=prn2.id))
        db.commit()
        try:
            prns_router.delete_prn(prn2.id, db, _User())
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("expected 409 for a cancelled PRN linked to a PO")
        assert db.get(PRN, prn2.id) is not None
    finally:
        prns_router.write_audit = orig


def test_update_blocked_when_linked_to_purchase_order():
    """A PRN linked to a purchase order cannot be edited: line edits could
    orphan the PO's prn_line_id references."""
    from fastapi import HTTPException
    from app.models import PurchaseOrder
    from app.routers import prns as prns_router
    from app.schemas import PRNUpdate
    db = _session()
    product, prn = _prn_with_stock(db)
    prn.requested_by_id = _User.id
    db.add(PurchaseOrder(po_number="PO-EDIT-1", prn_id=prn.id))
    db.commit()
    try:
        prns_router.update_prn(prn.id, PRNUpdate(department="Ops"), db, _User())
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("expected 409 editing a PO-linked PRN")
    assert db.get(PRN, prn.id).department != "Ops"


if __name__ == "__main__":
    test_override_stored_and_inventory_untouched()
    test_clearing_override_reverts_to_snapshot()
    test_manual_line_stock_is_unknown_not_zero()
    test_pdf_renders_with_override_and_wraps()
    test_prn_number_short_sequence()
    test_validate_dates_rejects_earlier_required_by()
    test_stock_snapshot_is_per_location_not_summed()
    test_apply_lines_stores_location()
    test_create_prn_uses_manual_requested_by_name()
    test_delete_draft_prn_removes_lines_not_inventory()
    test_delete_allowed_for_any_status_when_unlinked()
    test_delete_blocked_when_linked_to_purchase_order()
    test_delete_forbidden_for_non_requester()
    test_delete_cancelled_prn_allowed_but_blocked_when_linked()
    test_update_blocked_when_linked_to_purchase_order()
    print("PRN override + PDF self-check passed.")
