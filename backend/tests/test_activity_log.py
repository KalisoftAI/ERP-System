"""Self-check for activity log change capture and read-only summary.

Plain asserts (no pytest dependency). Run from the backend directory:

    python tests/test_activity_log.py
"""
import os
import sys
from datetime import date, datetime
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.crud import apply_updates, write_audit  # noqa: E402
from app.database import Base  # noqa: E402
from app.models import AuditLog, Product, User, UserRole  # noqa: E402
from app.routers.activity_log import daily_summary, list_activity, module_of  # noqa: E402
from app.schemas import ProductUpdate  # noqa: E402


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_update_captures_old_and_new():
    db = _session()
    token = uuid4().hex[:8]
    user = User(username=f"mgr-{token}", email=f"{token}@example.com",
                password_hash="x", role=UserRole.manager)
    product = Product(item_code=f"ITM-{token}", model="Old Name")
    db.add_all([user, product])
    db.commit()

    changes = apply_updates(product, ProductUpdate(name="New Name"))
    db.commit()
    write_audit(db, user, "UPDATE", "products", product.id,
                "Updated product", changes=changes)

    log = db.query(AuditLog).one()
    assert log.changes
    assert '"old": "Old Name"' not in log.changes  # product name was empty before
    assert '"old": ""' in log.changes
    assert '"new": "New Name"' in log.changes

    page = list_activity(db=db, _=user, module="products", page=1, page_size=50)
    assert page["total"] == 1
    assert page["items"][0]["changes"]["name"]["new"] == "New Name"

    summary = daily_summary(db=db, _=user, module="products")
    assert summary["items"][0]["total"] == 1
    assert summary["items"][0]["updates"] == 1


def test_import_counts_and_drilldown_filters():
    db = _session()
    token = uuid4().hex[:8]
    user = User(username=f"mgr-{token}", email=f"{token}@example.com",
                password_hash="x", role=UserRole.manager)
    db.add(user)
    db.commit()

    write_audit(db, user, "IMPORT", "purchase_orders", None,
                "PO import: 10 created, 3 updated, 2 failed",
                created=10, updated=3, failed=2)
    write_audit(db, user, "CREATE", "customers", 1, "Created customer")
    write_audit(db, user, "DELETE", "customers", 2, "Deleted customer")

    assert module_of("purchase_orders") == "Purchases"
    assert module_of("employees") == "Employee Management"

    summary = daily_summary(db=db, _=user)
    by_module = {row["module"]: row for row in summary["items"]}
    assert by_module["Purchases"]["added"] == 10
    assert by_module["Purchases"]["updated"] == 3
    assert by_module["Purchases"]["failed"] == 2
    assert by_module["Purchases"]["total"] == 13
    assert by_module["Customers"]["added"] == 1
    assert by_module["Customers"]["deleted"] == 1

    added = list_activity(db=db, _=user, module="Purchases", kind="added",
                          page=1, page_size=50)
    assert added["total"] == 1
    assert added["items"][0]["counts"]["added"] == 10

    updated = list_activity(db=db, _=user, kind="updated", page=1, page_size=50)
    assert updated["total"] == 1

    failed = list_activity(db=db, _=user, kind="failed", page=1, page_size=50)
    assert failed["total"] == 1

    imports = list_activity(db=db, _=user, kind="imports", page=1, page_size=50)
    assert imports["total"] == 1

    deleted = list_activity(db=db, _=user, kind="deleted", page=1, page_size=50)
    assert deleted["total"] == 1
    assert deleted["items"][0]["counts"]["deleted"] == 1

    records = list_activity(db=db, _=user, kind="records", page=1, page_size=50)
    assert records["total"] == 3


def test_summary_groups_by_day_module_user_without_double_count():
    db = _session()
    token = uuid4().hex[:8]
    u1 = User(username=f"mgr-{token}", email=f"{token}@example.com",
              password_hash="x", role=UserRole.manager)
    u2 = User(username=f"ops-{token}", email=f"ops-{token}@example.com",
              password_hash="x", role=UserRole.manager)
    db.add_all([u1, u2])
    db.commit()

    day1 = datetime(2025, 1, 2, 9, 0, 0)
    day2 = datetime(2025, 1, 3, 9, 0, 0)
    db.add_all([
        AuditLog(user_id=u1.id, action="CREATE", entity="boms",
                 created_count=1, created_at=day1),
        AuditLog(user_id=u1.id, action="UPDATE", entity="bill_of_materials",
                 updated_count=1, created_at=day1),
        AuditLog(user_id=u2.id, action="CREATE", entity="products",
                 created_at=day1),
        AuditLog(user_id=u1.id, action="DELETE", entity="products",
                 created_at=day2),
    ])
    db.commit()

    summary = daily_summary(db=db, _=u1)
    by_key = {(i["day"], i["module"], i["user"]["id"]): i
              for i in summary["items"]}
    assert len(summary["items"]) == 3

    bom = by_key[("2025-01-02", "BOM", u1.id)]
    assert bom["added"] == 1
    assert bom["updated"] == 1
    assert bom["deleted"] == 0
    assert bom["total"] == 2

    inventory_u2 = by_key[("2025-01-02", "Inventory", u2.id)]
    assert inventory_u2["added"] == 1
    assert inventory_u2["total"] == 1

    inventory_u1 = by_key[("2025-01-03", "Inventory", u1.id)]
    assert inventory_u1["deleted"] == 1
    assert inventory_u1["total"] == 1

    bom_logs = list_activity(db=db, _=u1, module="BOM", page=1, page_size=50)
    counts_by_action = {i["action"]: i["counts"] for i in bom_logs["items"]}
    assert counts_by_action["UPDATE"]["updated"] == 1
    assert counts_by_action["CREATE"]["added"] == 1

    bom_only = daily_summary(db=db, _=u1, module="BOM")
    assert len(bom_only["items"]) == 1
    assert bom_only["items"][0]["total"] == 2

    day2_only = daily_summary(db=db, _=u1, date_from=date(2025, 1, 3),
                              date_to=date(2025, 1, 3))
    assert len(day2_only["items"]) == 1
    assert day2_only["items"][0]["deleted"] == 1

    user2_only = daily_summary(db=db, _=u1, user_id=u2.id)
    assert len(user2_only["items"]) == 1
    assert user2_only["items"][0]["added"] == 1

    deletes_only = daily_summary(db=db, _=u1, action="DELETE")
    assert len(deletes_only["items"]) == 1
    assert deletes_only["items"][0]["total"] == 1


def test_audit_rows_are_immutable():
    db = _session()
    log = AuditLog(action="CREATE", entity="products", details="x")
    db.add(log)
    db.commit()

    log.details = "changed"
    try:
        db.commit()
    except ValueError as exc:
        assert "immutable" in str(exc)
        db.rollback()
    else:
        raise AssertionError("audit log update was not blocked")


if __name__ == "__main__":
    test_update_captures_old_and_new()
    test_import_counts_and_drilldown_filters()
    test_summary_groups_by_day_module_user_without_double_count()
    test_audit_rows_are_immutable()
    print("activity log checks passed")
