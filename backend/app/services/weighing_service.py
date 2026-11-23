"""Box-wise production records from weighing transactions (packing-slip data).

This is the Production-side business logic for the weighing machine workflow.
It is deliberately decoupled from any machine communication (that lives in
`services/machine_integration.py`): a transaction can arrive from the machine
API, the clearly-labelled simulation mode, or a manual entry form — all three
funnel through the same `ingest_weighing_transaction` pipeline:

    validate -> dedupe (transaction uid / barcode) -> tare lookup
    -> Net = Gross - Tare -> save ProductionRecord -> post Inventory (net only)

Safety rules:
  * A duplicate transaction NEVER creates a second record or a second stock
    movement (uid unique index + barcode unique index + ref_type/ref_id guard).
  * The applied tare weight is stored on the record, so later Tare Weight
    Setting changes never alter historical Net Weights.
  * A missing tare configuration never silently passes: the record is saved
    with net_weight NULL, inventory_sync_status PENDING and a clear error;
    `reprocess_record` completes it after the setting is configured.
  * Stock posting uses the shared inventory engine (`apply_movement`) with
    ref_type='production_record', fully separate from the existing
    ProductionOrder / ProductionMovement (ref_type='production_order') flow.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import (
    MovementType, Product, ProductCategory, ProductSourceType,
    ProductionRecord, StockMovement, TareWeightSetting, WeighingTransaction,
)
from .stock_service import apply_movement, reverse_and_remove_ref

# WeighingTransaction.status
TXN_RECEIVED = "RECEIVED"
TXN_PROCESSED = "PROCESSED"
TXN_DUPLICATE = "DUPLICATE"
TXN_FAILED = "FAILED"

# ProductionRecord.inventory_sync_status
SYNC_PENDING = "PENDING"
SYNC_SYNCED = "SYNCED"
SYNC_FAILED = "FAILED"

# StockMovement ref_type used by this module (never collides with the
# ProductionOrder flow which uses ref_type='production_order').
REF_TYPE = "production_record"

# WeighingTransaction.source
SOURCE_MACHINE = "MACHINE_API"
SOURCE_SIMULATION = "SIMULATION"
SOURCE_MANUAL = "MANUAL"


class DuplicateTransactionError(Exception):
    """Same machine transaction / same barcode delivered more than once."""


class BoxConflictError(ValueError):
    """Same product + size + date + box number already recorded — a genuine
    data conflict that needs review (box counters reset per production run)."""


# ---------------------------------------------------------------------------
# Tare weight settings
# ---------------------------------------------------------------------------
def normalize_size(size: str | None) -> str:
    """Fully space/case-insensitive comparison key (' 400 MM ' -> '400mm'),
    matching the raw-material `squash_key` convention."""
    return "".join((size or "").split()).lower()


def find_tare_setting(db: Session, size: str) -> TareWeightSetting | None:
    """Active Tare Weight Setting for a size (normalized, case-insensitive)."""
    target = normalize_size(size)
    if not target:
        return None
    rows = db.scalars(
        select(TareWeightSetting).where(TareWeightSetting.is_active == True)  # noqa: E712
    ).all()
    for r in rows:
        if normalize_size(r.size) == target:
            return r
    return None


def tare_setting_exists(db: Session, size: str, exclude_id: int | None = None) -> bool:
    """Normalized (case/whitespace-insensitive) duplicate check for a size."""
    target = normalize_size(size)
    stmt = select(TareWeightSetting)
    if exclude_id is not None:
        stmt = stmt.where(TareWeightSetting.id != exclude_id)
    rows = db.scalars(stmt).all()
    return any(normalize_size(r.size) == target for r in rows)


# ---------------------------------------------------------------------------
# Product resolution (weighing context — finished goods, stock kept in KG)
# ---------------------------------------------------------------------------
def resolve_weighing_product(
    db: Session, product_id: int | None, product_name: str, item_code: str = ""
) -> Product | None:
    """Match the machine-entered product to the master, creating it lazily.

    Existing products are always reused unchanged. New products created here
    are finished goods whose stock is tracked by weight (uom KG).
    """
    if product_id:
        return db.get(Product, product_id)
    ic = (item_code or "").strip()
    name = " ".join((product_name or "").split()).strip()
    if ic:
        existing = db.scalars(select(Product).where(Product.item_code == ic).limit(1)).first()
        if existing:
            return existing
    if name:
        existing = db.scalars(select(Product).where(Product.model == name).limit(1)).first()
        if existing:
            return existing
        existing = db.scalars(
            select(Product).where(func.lower(Product.model) == name.lower()).limit(1)
        ).first()
        if existing:
            return existing
    if not ic and not name:
        return None
    prod = Product(
        item_code=ic,
        model=name or ic,
        name=name or ic,
        category=ProductCategory.finished,
        source_type=ProductSourceType.manufactured,
        uom="KG",
        is_active=True,
    )
    db.add(prod)
    db.flush()
    return prod


# ---------------------------------------------------------------------------
# Inventory posting (net weight, exactly once, traceable)
# ---------------------------------------------------------------------------
def post_record_to_inventory(db: Session, record: ProductionRecord) -> StockMovement | None:
    """Post the record's NET weight to finished-goods stock (Main Store).

    Exactly-once: an existing stock_movements row with
    (ref_type='production_record', ref_id=record.id) is adopted instead of
    posting again; the database additionally enforces this with a partial
    unique index on PostgreSQL. Returns the movement row (or None when the
    record has no net weight yet).
    """
    if record.net_weight is None:
        return None
    existing = db.scalars(
        select(StockMovement).where(
            StockMovement.ref_type == REF_TYPE, StockMovement.ref_id == record.id
        )
    ).first()
    if existing:
        record.inventory_sync_status = SYNC_SYNCED
        record.inventory_movement_id = existing.id
        record.inventory_sync_error = ""
        return existing
    try:
        movement = apply_movement(
            db, record.product_id, MovementType.production_output, record.net_weight,
            record.production_date, ref_type=REF_TYPE, ref_id=record.id,
            remarks=(f"Box {record.box_number} net {record.net_weight:g} kg "
                     f"(production record #{record.id})"),
        )
    except Exception as exc:  # leave the record intact, flag for retry
        record.inventory_sync_status = SYNC_FAILED
        record.inventory_sync_error = str(exc)[:2000]
        raise
    record.inventory_sync_status = SYNC_SYNCED
    record.inventory_movement_id = movement.id
    record.inventory_sync_error = ""
    return movement


# ---------------------------------------------------------------------------
# Main ingestion pipeline
# ---------------------------------------------------------------------------
def _process_transaction(db: Session, txn: WeighingTransaction, payload, user_name: str):
    """Create the ProductionRecord for a validated transaction and post stock.

    Runs inside a savepoint (caller wraps with db.begin_nested) so a failure
    never loses the inbox transaction row.
    """
    product = resolve_weighing_product(db, payload.product_id, payload.product, payload.item_code)
    if product is None:
        raise ValueError("Product is required — provide product_id or a product/model name")

    # Unique box safeguard: same product + size + date + box number is a
    # genuine data conflict (box counters reset per run) and needs review.
    # Size compare uses lower(replace(size,' ','')) == normalize_size (stored
    # sizes are whitespace-collapsed at capture time).
    dup = db.scalars(
        select(ProductionRecord).where(
            ProductionRecord.product_id == product.id,
            ProductionRecord.production_date == payload.production_date,
            ProductionRecord.box_number == payload.box_number,
            func.lower(func.replace(ProductionRecord.size, " ", ""))
                == normalize_size(payload.size),
        )
    ).first()
    if dup:
        raise BoxConflictError(
            f"Box number '{payload.box_number}' is already recorded for "
            f"'{product.model}' size '{payload.size}' on {payload.production_date} "
            f"(production record #{dup.id})"
        )

    # Barcode safeguard (the DB unique index on barcode is the final guard).
    if payload.barcode:
        existing_bc = db.scalars(
            select(ProductionRecord).where(ProductionRecord.barcode == payload.barcode)
        ).first()
        if existing_bc:
            raise DuplicateTransactionError(
                f"Barcode '{payload.barcode}' is already recorded "
                f"(production record #{existing_bc.id})"
            )

    # Tare lookup: missing configuration is NOT silently accepted — the record
    # is saved with a clear PENDING state and error text for the UI.
    tare_setting = find_tare_setting(db, payload.size)
    tare = float(tare_setting.tare_weight) if tare_setting else None
    net = None
    sync_error = ""
    if tare is None:
        sync_error = (
            f"No tare weight configured for size '{payload.size}'. "
            "Configure it under Tare Weight Settings, then use Retry Sync."
        )
    else:
        net = round(float(payload.gross_weight) - tare, 3)
        if net < 0:
            raise ValueError(
                f"Gross weight {payload.gross_weight:g} kg is below the configured tare "
                f"weight {tare:g} kg for size '{payload.size}'"
            )

    record = ProductionRecord(
        box_number=payload.box_number,
        barcode=payload.barcode or None,
        product_id=product.id,
        product_name=product.model or payload.product,
        size=" ".join(payload.size.split()).strip(),
        grade=payload.grade or "",
        micron=payload.micron or "",
        production_date=payload.production_date,
        gross_weight=float(payload.gross_weight),
        tare_weight=tare,
        tare_weight_setting_id=tare_setting.id if tare_setting else None,
        net_weight=net,
        remark=payload.remark or "",
        machine_transaction_id=txn.id,
        inventory_sync_status=SYNC_PENDING,
        inventory_sync_error=sync_error,
        created_by=user_name,
    )
    db.add(record)
    db.flush()

    if net is not None:
        post_record_to_inventory(db, record)
    return record


def ingest_weighing_transaction(db: Session, payload, *, source: str, user_name: str = "") -> dict[str, Any]:
    """Receive one weighing transaction and drive it to a final state.

    Returns a result dict: {ok, status, duplicate, error, transaction, record}.
    Never raises for business-rule failures — the transaction inbox row is
    always committed with a status (PROCESSED / DUPLICATE / FAILED) so machine
    activity is fully auditable.
    """
    uid = ((payload.transaction_id or "").strip()
           or (payload.barcode or "").strip()
           or f"{source}-{uuid4().hex[:12]}")

    # Anchor 1: explicit transaction id (or barcode used as the uid). A repeat
    # delivery only increments the counter — no new record, no stock effect.
    existing_txn = db.scalars(
        select(WeighingTransaction).where(WeighingTransaction.transaction_uid == uid)
    ).first()
    if existing_txn:
        existing_txn.duplicate_count = (existing_txn.duplicate_count or 0) + 1
        db.commit()
        return {
            "ok": False, "status": TXN_DUPLICATE, "duplicate": True, "conflict": False,
            "error": f"Duplicate transaction '{uid}' (already {existing_txn.status.lower()})",
            "transaction": existing_txn,
            "record": (db.get(ProductionRecord, existing_txn.production_record_id)
                       if existing_txn.production_record_id else None),
        }

    txn = WeighingTransaction(
        transaction_uid=uid,
        machine_id=payload.machine_id or "",
        source=source,
        barcode=payload.barcode or None,
        box_number=payload.box_number,
        raw_payload=json.dumps(payload.model_dump(), default=str),
        status=TXN_RECEIVED,
    )
    db.add(txn)
    try:
        db.flush()
    except IntegrityError:
        # Same uid inserted concurrently — treat as a duplicate delivery.
        db.rollback()
        winner = db.scalars(
            select(WeighingTransaction).where(WeighingTransaction.transaction_uid == uid)
        ).first()
        return {
            "ok": False, "status": TXN_DUPLICATE, "duplicate": True, "conflict": False,
            "error": f"Duplicate transaction '{uid}'",
            "transaction": winner, "record": None,
        }

    try:
        with db.begin_nested():
            record = _process_transaction(db, txn, payload, user_name)
    except DuplicateTransactionError as exc:
        txn.status = TXN_DUPLICATE
        txn.error_message = str(exc)[:2000]
        txn.processed_at = datetime.utcnow()
        db.commit()
        return {"ok": False, "status": TXN_DUPLICATE, "duplicate": True, "conflict": False,
                "error": str(exc), "transaction": txn, "record": None}
    except BoxConflictError as exc:
        txn.status = TXN_FAILED
        txn.error_message = str(exc)[:2000]
        txn.processed_at = datetime.utcnow()
        db.commit()
        return {"ok": False, "status": TXN_FAILED, "duplicate": False, "conflict": True,
                "error": str(exc), "transaction": txn, "record": None}
    except IntegrityError as exc:
        # Race on the barcode unique index — the barcode already exists.
        msg = str(exc).lower()
        if "barcode" in msg:
            txn.status = TXN_DUPLICATE
            txn.error_message = f"Barcode '{payload.barcode}' is already recorded"
            txn.processed_at = datetime.utcnow()
            db.commit()
            return {"ok": False, "status": TXN_DUPLICATE, "duplicate": True, "conflict": False,
                    "error": txn.error_message, "transaction": txn, "record": None}
        txn.status = TXN_FAILED
        txn.error_message = str(exc)[:2000]
        txn.processed_at = datetime.utcnow()
        db.commit()
        return {"ok": False, "status": TXN_FAILED, "duplicate": False, "conflict": False,
                "error": str(exc), "transaction": txn, "record": None}
    except Exception as exc:
        txn.status = TXN_FAILED
        txn.error_message = str(exc)[:2000]
        txn.processed_at = datetime.utcnow()
        db.commit()
        return {"ok": False, "status": TXN_FAILED, "duplicate": False, "conflict": False,
                "error": str(exc), "transaction": txn, "record": None}

    txn.status = TXN_PROCESSED
    txn.processed_at = datetime.utcnow()
    txn.production_record_id = record.id
    db.commit()
    return {"ok": True, "status": TXN_PROCESSED, "duplicate": False, "conflict": False,
            "error": "", "transaction": txn, "record": record}


def reprocess_record(db: Session, record: ProductionRecord) -> ProductionRecord:
    """Complete a PENDING/FAILED record: fill missing tare (once) + post stock.

    Historical protection: a record that already carries an applied
    tare_weight NEVER re-reads the settings — retry only affects records whose
    tare was missing at capture time. Stock posting is exactly-once (adopted
    if the movement already exists).
    """
    if record.tare_weight is None:
        setting = find_tare_setting(db, record.size)
        if setting is None:
            record.inventory_sync_status = SYNC_PENDING
            record.inventory_sync_error = (
                f"No tare weight configured for size '{record.size}'. "
                "Configure it under Tare Weight Settings, then use Retry Sync."
            )
            db.commit()
            return record
        record.tare_weight = float(setting.tare_weight)
        record.tare_weight_setting_id = setting.id
        record.net_weight = round(float(record.gross_weight or 0) - record.tare_weight, 3)
        if record.net_weight < 0:
            record.net_weight = None
            record.tare_weight = None
            record.tare_weight_setting_id = None
            record.inventory_sync_status = SYNC_FAILED
            record.inventory_sync_error = (
                f"Gross weight {record.gross_weight:g} kg is below the configured tare "
                f"weight for size '{record.size}'"
            )
            db.commit()
            return record
    try:
        post_record_to_inventory(db, record)
    except Exception:
        db.commit()
        return record
    db.commit()
    return record


def delete_record_and_reverse_stock(db: Session, record: ProductionRecord) -> None:
    """Delete a production record and reverse its stock effect (if posted)."""
    reverse_and_remove_ref(db, REF_TYPE, record.id)
    if record.machine_transaction_id:
        txn = db.get(WeighingTransaction, record.machine_transaction_id)
        if txn is not None:
            txn.production_record_id = None
            txn.error_message = (
                f"Production record #{record.id} deleted; transaction kept for audit."
            )
    db.delete(record)
