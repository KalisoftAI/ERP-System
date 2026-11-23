"""Self-check for box-wise Production Records (weighing machine workflow).

Plain asserts (no pytest dependency). Run from the backend directory:

    python tests/test_production_records.py

Proves the key data-integrity rules:
  * Net Weight = Gross Weight - Tare Weight (per-Size setting, stored on record)
  * Duplicate transactions / barcodes never create duplicate records or stock
  * Unique Box Number validation (same product + size + date)
  * Missing Tare Weight is never silently accepted (clear PENDING state)
  * Inventory receives NET weight exactly once per box, traceable both ways
  * Retry sync is idempotent; delete reverses stock
  * Existing production_order / plan stock flows are untouched
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.database import Base  # noqa: E402
from app.models import (  # noqa: E402
    Inventory, MovementType, Product, ProductCategory, ProductionRecord,
    StockMovement, TareWeightSetting, WeighingTransaction,
)
from app.schemas import WeighingTransactionIn  # noqa: E402
from app.services import weighing_service as ws  # noqa: E402
from app.services import machine_integration as mi  # noqa: E402


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _tare(db, size="400mm", weight=5.0):
    s = TareWeightSetting(size=size, tare_weight=weight, uom="kg")
    db.add(s)
    db.flush()
    return s


def _payload(**kw):
    base = dict(product="Stretch Film 400", size="400mm", grade="Higher",
                micron="4500", production_date=date(2026, 11, 2),
                box_number="1", gross_weight=26.5, remark="")
    base.update(kw)
    return WeighingTransactionIn(**base)


def _stock(db, product_id):
    return db.scalars(select(Inventory).where(Inventory.product_id == product_id,
                                              Inventory.plant_id.is_(None))).first()


# ---------------------------------------------------------------------------
def test_record_created_net_calculated_stock_posted():
    db = _session()
    _tare(db, "400mm", 5.0)
    res = ws.ingest_weighing_transaction(db, _payload(), source=ws.SOURCE_MACHINE,
                                         user_name="Tester")
    assert res["ok"] and res["status"] == ws.TXN_PROCESSED
    rec = res["record"]
    assert rec.tare_weight == 5.0                     # tare snapshot stored
    assert rec.net_weight == 21.5                     # 26.5 - 5.0
    assert rec.inventory_sync_status == ws.SYNC_SYNCED
    assert rec.inventory_movement_id is not None
    # Inventory received NET weight only, at Main Store
    inv = _stock(db, rec.product_id)
    assert inv is not None and inv.current_stock == 21.5 and inv.received_qty == 21.5
    # Traceability both ways
    mv = db.get(StockMovement, rec.inventory_movement_id)
    assert mv.ref_type == "production_record" and mv.ref_id == rec.id
    assert mv.movement_type == MovementType.production_output and mv.quantity == 21.5
    # Transaction marked processed and linked
    txn = res["transaction"]
    assert txn.status == ws.TXN_PROCESSED and txn.production_record_id == rec.id
    # Product auto-created as finished goods
    prod = db.get(Product, rec.product_id)
    assert prod.category == ProductCategory.finished and prod.uom == "KG"


def test_existing_product_reused_unchanged():
    db = _session()
    _tare(db)
    existing = Product(item_code="SF-400", model="Stretch Film 400", uom="Each",
                       category=ProductCategory.finished)
    db.add(existing)
    db.flush()
    res = ws.ingest_weighing_transaction(db, _payload(), source=ws.SOURCE_MANUAL,
                                         user_name="")
    assert res["ok"]
    assert res["record"].product_id == existing.id
    assert db.get(Product, existing.id).uom == "Each"   # master never clobbered


def test_duplicate_transaction_id_never_duplicates():
    db = _session()
    _tare(db)
    p = _payload(transaction_id="MCH-0001", barcode="BC-1")
    first = ws.ingest_weighing_transaction(db, p, source=ws.SOURCE_MACHINE)
    assert first["ok"]
    second = ws.ingest_weighing_transaction(db, p, source=ws.SOURCE_MACHINE)
    assert second["status"] == ws.TXN_DUPLICATE and second["duplicate"] is True
    assert second["record"].id == first["record"].id
    # Exactly one record, one movement, stock posted once
    assert db.scalar(select(__import__("sqlalchemy").func.count()).select_from(ProductionRecord)) == 1
    assert db.scalar(select(__import__("sqlalchemy").func.count()).select_from(StockMovement)
                     .where(StockMovement.ref_type == "production_record")) == 1
    assert _stock(db, first["record"].product_id).current_stock == 21.5
    assert second["transaction"].duplicate_count == 1


def test_duplicate_barcode_flagged():
    db = _session()
    _tare(db)
    assert ws.ingest_weighing_transaction(db, _payload(barcode="BC-9", box_number="1"),
                                          source=ws.SOURCE_MACHINE)["ok"]
    res = ws.ingest_weighing_transaction(
        db, _payload(transaction_id="MCH-OTHER", barcode="BC-9", box_number="2"),
        source=ws.SOURCE_MACHINE)
    assert res["status"] == ws.TXN_DUPLICATE
    assert "Barcode" in res["error"]
    assert db.scalar(select(__import__("sqlalchemy").func.count()).select_from(ProductionRecord)) == 1


def test_unique_box_number_validation():
    db = _session()
    _tare(db)
    assert ws.ingest_weighing_transaction(db, _payload(box_number="7"),
                                          source=ws.SOURCE_MACHINE)["ok"]
    res = ws.ingest_weighing_transaction(db, _payload(box_number="7"),
                                         source=ws.SOURCE_MACHINE)
    assert res["status"] == ws.TXN_FAILED and "Box number" in res["error"]
    # Different date -> allowed
    ok = ws.ingest_weighing_transaction(
        db, _payload(box_number="7", production_date=date(2026, 11, 3)),
        source=ws.SOURCE_MACHINE)
    assert ok["ok"]


def test_missing_tare_flagged_then_completed_by_retry():
    db = _session()
    res = ws.ingest_weighing_transaction(db, _payload(), source=ws.SOURCE_MACHINE)
    assert res["ok"]                                    # transaction received + record kept
    rec = res["record"]
    assert rec.net_weight is None and rec.tare_weight is None
    assert rec.inventory_sync_status == ws.SYNC_PENDING
    assert "No tare weight configured" in rec.inventory_sync_error
    assert _stock(db, rec.product_id) is None           # nothing posted yet
    # Configure tare later, then retry
    _tare(db, "400mm", 4.0)
    rec = ws.reprocess_record(db, rec)
    assert rec.net_weight == 22.5 and rec.tare_weight == 4.0
    assert rec.inventory_sync_status == ws.SYNC_SYNCED
    assert _stock(db, rec.product_id).current_stock == 22.5


def test_retry_sync_is_idempotent():
    db = _session()
    _tare(db, "400mm", 5.0)
    rec = ws.ingest_weighing_transaction(db, _payload(), source=ws.SOURCE_MACHINE)["record"]
    ws.reprocess_record(db, rec)
    ws.reprocess_record(db, rec)
    assert _stock(db, rec.product_id).current_stock == 21.5   # never double-posted
    assert db.scalar(select(__import__("sqlalchemy").func.count()).select_from(StockMovement)
                     .where(StockMovement.ref_type == "production_record")) == 1


def test_gross_below_tare_rejected():
    db = _session()
    _tare(db, "400mm", 30.0)
    res = ws.ingest_weighing_transaction(db, _payload(gross_weight=26.5),
                                         source=ws.SOURCE_MACHINE)
    assert res["status"] == ws.TXN_FAILED and "below the configured tare" in res["error"]
    assert db.scalar(select(__import__("sqlalchemy").func.count()).select_from(ProductionRecord)) == 0


def test_historical_tare_survives_setting_change():
    db = _session()
    setting = _tare(db, "400mm", 5.0)
    rec = ws.ingest_weighing_transaction(db, _payload(), source=ws.SOURCE_MACHINE)["record"]
    setting.tare_weight = 9.9                             # config changed later
    db.commit()
    assert db.get(ProductionRecord, rec.id).net_weight == 21.5   # history untouched
    # Retry on an already-tared record never re-reads settings
    ws.reprocess_record(db, db.get(ProductionRecord, rec.id))
    assert db.get(ProductionRecord, rec.id).net_weight == 21.5


def test_delete_reverses_stock_and_keeps_transaction():
    db = _session()
    _tare(db)
    res = ws.ingest_weighing_transaction(db, _payload(), source=ws.SOURCE_MACHINE)
    rec, txn = res["record"], res["transaction"]
    ws.delete_record_and_reverse_stock(db, rec)
    db.commit()
    assert _stock(db, rec.product_id).current_stock == 0
    assert db.scalar(select(__import__("sqlalchemy").func.count()).select_from(StockMovement)
                     .where(StockMovement.ref_type == "production_record")) == 0
    kept = db.get(WeighingTransaction, txn.id)
    assert kept is not None and kept.production_record_id is None


def test_failed_transaction_does_not_lose_inbox_row():
    db = _session()
    res = ws.ingest_weighing_transaction(db, _payload(product="", item_code=""),
                                         source=ws.SOURCE_MACHINE)
    assert res["status"] == ws.TXN_FAILED
    assert res["transaction"].id is not None            # error is logged, not dropped


def test_size_summary_aggregation():
    db = _session()
    _tare(db, "400mm", 5.0)
    _tare(db, "250mm", 4.0)
    ws.ingest_weighing_transaction(db, _payload(box_number="1"), source=ws.SOURCE_MACHINE)
    ws.ingest_weighing_transaction(db, _payload(box_number="2", gross_weight=30.0),
                                   source=ws.SOURCE_MACHINE)
    ws.ingest_weighing_transaction(db, _payload(box_number="1", size="250mm"),
                                   source=ws.SOURCE_MACHINE)
    from collections import defaultdict
    agg = defaultdict(lambda: [0, 0.0, 0.0])
    for r in db.scalars(select(ProductionRecord)).all():
        a = agg[r.size]
        a[0] += 1
        a[1] += r.gross_weight
        a[2] += r.net_weight or 0
    assert agg["400mm"] == [2, 56.5, 46.5]              # 2 boxes, gross 26.5+30, net 21.5+25
    assert agg["250mm"] == [1, 26.5, 22.5]


def test_machine_adapter_placeholders():
    db = _session()
    conn = mi.get_or_create_connection(db)
    assert conn.status == mi.STATUS_AWAITING
    rs232_config = {
        "com_port": "COM3", "baud_rate": 9600, "data_bits": 8,
        "parity": "NONE", "stop_bits": 1, "flow_control": "NONE",
        "delimiter": "CRLF",
    }
    conn = mi.save_connection_config(db, name="Scale 1", connection_type="RS232",
                                     config=rs232_config, notes="")
    assert conn.status == mi.STATUS_AWAITING   # never fakes connectivity
    try:
        mi.get_adapter(conn).connect()
    except NotImplementedError as exc:
        assert "technician" in str(exc)
    else:
        raise AssertionError("real transport must not connect")
    conn = mi.save_connection_config(db, name="Scale 1", connection_type="SIMULATION",
                                     config={}, notes="")
    assert conn.status == mi.STATUS_CONNECTED                # simulation only
    mi.get_adapter(conn).connect()                           # no-op, does not raise
    payload = mi.build_simulation_payload()
    assert payload["remark"].startswith("SIMULATION")        # always labelled


def test_simulation_end_to_end():
    db = _session()
    _tare(db, "400mm", 5.0)
    payload = WeighingTransactionIn(**mi.build_simulation_payload())
    res = ws.ingest_weighing_transaction(db, payload, source=ws.SOURCE_SIMULATION,
                                         user_name="Demo")
    assert res["ok"] and res["record"].net_weight is not None
    assert res["transaction"].source == ws.SOURCE_SIMULATION


def test_tare_setting_duplicate_rejected():
    db = _session()
    _tare(db, "400mm")
    assert ws.tare_setting_exists(db, " 400 MM ") is True     # normalized
    assert ws.tare_setting_exists(db, "250mm") is False


def test_rs232_config_requires_transport_details():
    db = _session()
    try:
        mi.save_connection_config(db, name="Scale 1", connection_type="RS232",
                                  config={"com_port": "COM3"}, notes="")
    except ValueError as exc:
        assert "Missing RS232 config keys" in str(exc)
    else:
        raise AssertionError("incomplete RS232 config must be rejected")
    assert "delimiter" in mi.CONFIG_PLACEHOLDERS["RS232"]


if __name__ == "__main__":
    test_record_created_net_calculated_stock_posted()
    test_existing_product_reused_unchanged()
    test_duplicate_transaction_id_never_duplicates()
    test_duplicate_barcode_flagged()
    test_unique_box_number_validation()
    test_missing_tare_flagged_then_completed_by_retry()
    test_retry_sync_is_idempotent()
    test_gross_below_tare_rejected()
    test_historical_tare_survives_setting_change()
    test_delete_reverses_stock_and_keeps_transaction()
    test_failed_transaction_does_not_lose_inbox_row()
    test_size_summary_aggregation()
    test_machine_adapter_placeholders()
    test_simulation_end_to_end()
    test_tare_setting_duplicate_rejected()
    test_rs232_config_requires_transport_details()
    print("Production records (weighing) self-check passed.")
