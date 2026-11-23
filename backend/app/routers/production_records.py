"""Box-wise Production Records + Tare Weight Settings + Machine Integration.

All routes share the `/production` prefix with the existing production router.
This router MUST be included BEFORE `routers/production.py` in main.py so the
static paths below (/records, /settings/…, /machine/…) win over the existing
`/production/{order_id}` int-parameter routes.

Business rules implemented here:
  * Net Weight = Gross Weight - Tare Weight (tare resolved per Size at capture
    time and stored on the record — historical records never change).
  * Inventory receives NET weight only, exactly once per box, traceable via
    inventory_movement_id <-> stock_movements (ref_type='production_record').
  * Duplicate transactions never create duplicate records or duplicate stock.
  * No customer / sales-order fields anywhere in this workflow.
"""
import csv
import io
import json
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import CurrentUser, AllStaff, ManagerOrAdmin
from ..crud import get_or_404, write_audit
from ..database import get_db
from ..models import (
    ProductionRecord, TareWeightSetting, WeighingTransaction,
)
from ..schemas import MachineConfigIn, TareWeightSettingIn, TareWeightSettingUpdate, WeighingTransactionIn
from ..services import machine_integration as mi
from ..services import weighing_service as ws

router = APIRouter(prefix="/production", tags=["production-records"])


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def _serialize_record(r: ProductionRecord) -> dict:
    p = r.product
    txn = r.transaction
    return {
        "id": r.id,
        "box_number": r.box_number,
        "barcode": r.barcode,
        "product_id": r.product_id,
        "product": {"id": p.id, "model": p.model, "item_code": p.item_code,
                    "uom": p.uom} if p else None,
        "product_name": r.product_name or (p.model if p else ""),
        "size": r.size, "grade": r.grade, "micron": r.micron,
        "production_date": r.production_date,
        "gross_weight": r.gross_weight,
        "tare_weight": r.tare_weight,
        "net_weight": r.net_weight,
        "record_status": "READY" if r.net_weight is not None else "TARE_MISSING",
        "remark": r.remark,
        "machine_transaction_id": r.machine_transaction_id,
        "transaction_uid": txn.transaction_uid if txn else None,
        "source": txn.source if txn else None,
        "inventory_sync_status": r.inventory_sync_status,
        "inventory_sync_error": r.inventory_sync_error or "",
        "inventory_movement_id": r.inventory_movement_id,
        "created_by": r.created_by or "",
        "created_at": r.created_at,
    }


def _serialize_txn(t: WeighingTransaction) -> dict:
    return {
        "id": t.id,
        "transaction_uid": t.transaction_uid,
        "machine_id": t.machine_id,
        "source": t.source,
        "barcode": t.barcode,
        "box_number": t.box_number,
        "status": t.status,
        "error_message": t.error_message or "",
        "duplicate_count": t.duplicate_count,
        "production_record_id": t.production_record_id,
        "received_at": t.received_at,
        "processed_at": t.processed_at,
    }


def _serialize_setting(s: TareWeightSetting) -> dict:
    return {
        "id": s.id, "size": s.size, "tare_weight": s.tare_weight, "uom": s.uom,
        "is_active": s.is_active, "notes": s.notes or "",
        "created_by": s.created_by or "", "updated_by": s.updated_by or "",
        "created_at": s.created_at, "updated_at": s.updated_at,
    }


def _apply_filters(stmt, *, search, product_id, size, grade, date_from, date_to,
                   sync_status, record_status):
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(
            ProductionRecord.box_number.ilike(like),
            ProductionRecord.barcode.ilike(like),
            ProductionRecord.product_name.ilike(like),
            ProductionRecord.remark.ilike(like),
        ))
    if product_id:
        stmt = stmt.where(ProductionRecord.product_id == product_id)
    if size:
        stmt = stmt.where(func.lower(func.replace(ProductionRecord.size, " ", ""))
                          == ws.normalize_size(size))
    if grade:
        stmt = stmt.where(ProductionRecord.grade.ilike(f"%{grade}%"))
    if date_from:
        stmt = stmt.where(ProductionRecord.production_date >= date.fromisoformat(date_from))
    if date_to:
        stmt = stmt.where(ProductionRecord.production_date <= date.fromisoformat(date_to))
    if sync_status:
        stmt = stmt.where(ProductionRecord.inventory_sync_status == sync_status.upper())
    if record_status == "TARE_MISSING":
        stmt = stmt.where(ProductionRecord.net_weight.is_(None))
    elif record_status == "READY":
        stmt = stmt.where(ProductionRecord.net_weight.is_not(None))
    return stmt


# ===========================================================================
# Tare Weight Settings  (/production/settings/tare-weights)
# ===========================================================================
@router.get("/settings/tare-weights", response_model=dict)
def list_tare_settings(db: Annotated[Session, Depends(get_db)], _: CurrentUser):
    rows = db.scalars(select(TareWeightSetting).order_by(TareWeightSetting.size)).all()
    return {"items": [_serialize_setting(s) for s in rows], "total": len(rows)}


@router.post("/settings/tare-weights", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_tare_setting(body: TareWeightSettingIn, db: Annotated[Session, Depends(get_db)],
                        user: ManagerOrAdmin):
    if ws.tare_setting_exists(db, body.size):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"A tare weight for size '{body.size}' already exists")
    s = TareWeightSetting(
        size=" ".join(body.size.split()).strip(),
        tare_weight=body.tare_weight, uom=body.uom or "kg",
        notes=body.notes or "", created_by=user.full_name or user.username,
        updated_by=user.full_name or user.username,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    write_audit(db, user, "CREATE", "tare_weight_settings", s.id,
                f"Tare weight {s.tare_weight:g} {s.uom} for size {s.size}")
    return _serialize_setting(s)


@router.patch("/settings/tare-weights/{setting_id}", response_model=dict)
def update_tare_setting(setting_id: int, body: TareWeightSettingUpdate,
                        db: Annotated[Session, Depends(get_db)], user: ManagerOrAdmin):
    """Edit a setting. Historical production records keep the tare value that
    was applied at capture time — only future records use the new value."""
    s = get_or_404(db, TareWeightSetting, setting_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("size") and ws.tare_setting_exists(db, data["size"], exclude_id=s.id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"A tare weight for size '{data['size']}' already exists")
    for key, value in data.items():
        if value is not None and hasattr(s, key):
            setattr(s, key, " ".join(value.split()).strip() if key == "size" else value)
    s.updated_by = user.full_name or user.username
    db.commit()
    db.refresh(s)
    write_audit(db, user, "UPDATE", "tare_weight_settings", s.id,
                f"Updated tare weight for size {s.size}", changes=data)
    return _serialize_setting(s)


@router.delete("/settings/tare-weights/{setting_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tare_setting(setting_id: int, db: Annotated[Session, Depends(get_db)],
                        user: ManagerOrAdmin):
    """Delete a setting. Existing production records are unaffected (they store
    the tare value applied at capture time)."""
    s = get_or_404(db, TareWeightSetting, setting_id)
    db.delete(s)
    db.commit()
    write_audit(db, user, "DELETE", "tare_weight_settings", setting_id,
                f"Deleted tare weight setting for size {s.size}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ===========================================================================
# Machine Integration  (/production/machine/…)  — preparation only
# ===========================================================================
@router.get("/machine/status", response_model=dict)
def machine_status(db: Annotated[Session, Depends(get_db)], _: CurrentUser):
    """Integration status: connection info, counters and last activity.

    Status is Awaiting Configuration / Connected / Disconnected. No live
    machine communication is performed by this endpoint.
    """
    conn = mi.get_or_create_connection(db)
    counts = dict(
        db.execute(
            select(WeighingTransaction.status, func.count())
            .group_by(WeighingTransaction.status)
        ).all()
    )
    today_start = datetime.combine(date.today(), datetime.min.time())
    received_today = db.scalar(
        select(func.count()).select_from(WeighingTransaction)
        .where(WeighingTransaction.received_at >= today_start)
    ) or 0
    last_txn = db.scalars(
        select(WeighingTransaction).order_by(WeighingTransaction.received_at.desc()).limit(1)
    ).first()
    last_record = db.scalars(
        select(ProductionRecord).order_by(ProductionRecord.created_at.desc()).limit(1)
    ).first()
    return {
        "connection": mi.serialize_connection(conn),
        "counters": {
            "received_today": received_today,
            "processed": counts.get(ws.TXN_PROCESSED, 0),
            "failed": counts.get(ws.TXN_FAILED, 0),
            "duplicate": counts.get(ws.TXN_DUPLICATE, 0),
            "total": sum(counts.values()),
        },
        "last_transaction": _serialize_txn(last_txn) if last_txn else None,
        "last_record": _serialize_record(last_record) if last_record else None,
        "integration_note": (
            "Preparation only — no live machine communication. Real transport "
            "(RS232 / USB Serial / TCP-IP / vendor API) is enabled after the "
            "machine technician provides the machine model, protocol, port "
            "details and sample data format. SIMULATION mode demonstrates the "
            "receiving workflow without a real machine."
        ),
    }


@router.put("/machine/config", response_model=dict)
def save_machine_config(body: MachineConfigIn, db: Annotated[Session, Depends(get_db)],
                        user: ManagerOrAdmin):
    """Save connection configuration placeholders. Never opens a connection."""
    try:
        conn = mi.save_connection_config(
            db, name=body.name, connection_type=body.connection_type,
            config=body.config, notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    write_audit(db, user, "UPDATE", "machine_connections", conn.id,
                f"Saved machine connection config ({conn.connection_type})")
    return mi.serialize_connection(conn)


@router.post("/machine/scan", response_model=dict)
@router.post("/machine/transactions", response_model=dict)
def receive_machine_transaction(body: WeighingTransactionIn,
                                db: Annotated[Session, Depends(get_db)],
                                user: CurrentUser):
    """**Machine data receiving API** — the integration endpoint.

    Accepts one weighing transaction (standard internal schema) and processes
    it through validation -> dedupe -> tare -> net -> record -> inventory.
    Always answers with the transaction status instead of raising for
    business-rule failures, so a machine gateway can log the outcome:
    201 PROCESSED / 200 DUPLICATE / 200 FAILED.
    """
    conn = mi.get_or_create_connection(db)
    result = ws.ingest_weighing_transaction(db, body, source=ws.SOURCE_MACHINE,
                                            user_name=user.full_name or user.username)
    mi.mark_seen(db, conn)
    out = {
        "status": result["status"],
        "duplicate": result["duplicate"],
        "error": result["error"],
        "transaction": _serialize_txn(result["transaction"]),
        "record": _serialize_record(result["record"]) if result["record"] else None,
    }
    if result["ok"]:
        return JSONResponse(status_code=status.HTTP_201_CREATED,
                            content=json.loads(json.dumps(out, default=str)))
    return out


@router.get("/machine/transactions", response_model=dict)
def list_machine_transactions(
    db: Annotated[Session, Depends(get_db)], _: CurrentUser,
    status_: str = Query(default="", alias="status"),
    source: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    """Integration inbox: every received transaction with its status and any
    error — the integration error log."""
    stmt = select(WeighingTransaction)
    if status_:
        stmt = stmt.where(WeighingTransaction.status == status_.upper())
    if source:
        stmt = stmt.where(WeighingTransaction.source == source.upper())
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.order_by(WeighingTransaction.received_at.desc(), WeighingTransaction.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {"items": [_serialize_txn(t) for t in rows],
            "total": total, "page": page, "page_size": page_size}


@router.post("/machine/simulate", response_model=dict)
def simulate_machine_transaction(
    db: Annotated[Session, Depends(get_db)], user: AllStaff,
    body: WeighingTransactionIn | None = None,
):
    """SIMULATION mode — run one sample packing-slip transaction through the
    real receiving pipeline. Clearly labelled; never implies a real machine
    is connected. Optional body overrides the sample values."""
    overrides = body.model_dump(exclude_unset=True) if body else {}
    payload_data = mi.build_simulation_payload(overrides)
    if body and body.box_number:
        payload_data["box_number"] = body.box_number
    else:
        # Auto box number: next sequence for today (simulation convenience).
        today_count = db.scalar(
            select(func.count()).select_from(ProductionRecord)
            .where(ProductionRecord.production_date == date.today())
        ) or 0
        payload_data["box_number"] = str(today_count + 1)
    payload = WeighingTransactionIn(**payload_data)
    result = ws.ingest_weighing_transaction(db, payload, source=ws.SOURCE_SIMULATION,
                                            user_name=user.full_name or user.username)
    conn = mi.get_or_create_connection(db)
    mi.mark_seen(db, conn)
    if result["ok"]:
        write_audit(db, user, "CREATE", "production_records", result["record"].id,
                    "Simulated weighing transaction (SIMULATION mode)")
    return {
        "simulation": True,
        "status": result["status"],
        "duplicate": result["duplicate"],
        "error": result["error"],
        "transaction": _serialize_txn(result["transaction"]),
        "record": _serialize_record(result["record"]) if result["record"] else None,
    }


# ===========================================================================
# Production Records  (/production/records…)
# NOTE: all static /records/... paths are defined BEFORE /records/{record_id}.
# ===========================================================================
@router.get("/records/summary", response_model=dict)
def records_summary(
    db: Annotated[Session, Depends(get_db)], _: CurrentUser,
    search: str = "", product_id: int | None = None, size: str = "", grade: str = "",
    date_from: str = "", date_to: str = "", sync_status: str = "", record_status: str = "",
):
    """Totals for the current filter set (box-wise report header)."""
    stmt = _apply_filters(
        select(ProductionRecord),
        search=search, product_id=product_id, size=size, grade=grade,
        date_from=date_from, date_to=date_to, sync_status=sync_status,
        record_status=record_status,
    )
    rows = db.scalars(stmt).all()
    return {
        "total_boxes": len(rows),
        "total_gross_weight": round(sum(float(r.gross_weight or 0) for r in rows), 3),
        "total_tare_weight": round(sum(float(r.tare_weight or 0) for r in rows), 3),
        "total_net_weight": round(sum(float(r.net_weight or 0) for r in rows), 3),
        "tare_missing": sum(1 for r in rows if r.net_weight is None),
        "synced": sum(1 for r in rows if r.inventory_sync_status == ws.SYNC_SYNCED),
        "sync_pending": sum(1 for r in rows if r.inventory_sync_status == ws.SYNC_PENDING),
        "sync_failed": sum(1 for r in rows if r.inventory_sync_status == ws.SYNC_FAILED),
    }


@router.get("/records/size-summary", response_model=dict)
def records_size_summary(
    db: Annotated[Session, Depends(get_db)], _: CurrentUser,
    product_id: int | None = None, date_from: str = "", date_to: str = "",
):
    """Size-wise production summary: Size, Total Boxes, Total Gross / Tare /
    Net Weight."""
    q = select(
        ProductionRecord.size.label("size"),
        func.count().label("boxes"),
        func.coalesce(func.sum(ProductionRecord.gross_weight), 0).label("gross"),
        func.coalesce(func.sum(ProductionRecord.tare_weight), 0).label("tare"),
        func.coalesce(func.sum(ProductionRecord.net_weight), 0).label("net"),
    )
    if product_id:
        q = q.where(ProductionRecord.product_id == product_id)
    if date_from:
        q = q.where(ProductionRecord.production_date >= date.fromisoformat(date_from))
    if date_to:
        q = q.where(ProductionRecord.production_date <= date.fromisoformat(date_to))
    q = (q.group_by(func.lower(ProductionRecord.size), ProductionRecord.size)
         .order_by(ProductionRecord.size))
    items = [
        {
            "size": r.size or "(no size)",
            "total_boxes": int(r.boxes),
            "total_gross_weight": round(float(r.gross or 0), 3),
            "total_tare_weight": round(float(r.tare or 0), 3),
            "total_net_weight": round(float(r.net or 0), 3),
        }
        for r in db.execute(q).all()
    ]
    return {
        "items": items,
        "totals": {
            "total_boxes": sum(i["total_boxes"] for i in items),
            "total_gross_weight": round(sum(i["total_gross_weight"] for i in items), 3),
            "total_tare_weight": round(sum(i["total_tare_weight"] for i in items), 3),
            "total_net_weight": round(sum(i["total_net_weight"] for i in items), 3),
        },
    }


@router.get("/records/daily-summary", response_model=dict)
def records_daily_summary(
    db: Annotated[Session, Depends(get_db)], _: CurrentUser,
    product_id: int | None = None, size: str = "", date_from: str = "", date_to: str = "",
):
    """Date-wise production summary: per production date — boxes, gross, tare,
    net weight (box-wise records; the weighing workflow)."""
    q = select(
        ProductionRecord.production_date.label("day"),
        func.count().label("boxes"),
        func.coalesce(func.sum(ProductionRecord.gross_weight), 0).label("gross"),
        func.coalesce(func.sum(ProductionRecord.tare_weight), 0).label("tare"),
        func.coalesce(func.sum(ProductionRecord.net_weight), 0).label("net"),
    )
    if product_id:
        q = q.where(ProductionRecord.product_id == product_id)
    if size:
        q = q.where(func.lower(func.replace(ProductionRecord.size, " ", ""))
                    == ws.normalize_size(size))
    if date_from:
        q = q.where(ProductionRecord.production_date >= date.fromisoformat(date_from))
    if date_to:
        q = q.where(ProductionRecord.production_date <= date.fromisoformat(date_to))
    q = q.group_by(ProductionRecord.production_date).order_by(ProductionRecord.production_date.desc())
    items = [
        {
            "production_date": r.day,
            "total_boxes": int(r.boxes),
            "total_gross_weight": round(float(r.gross or 0), 3),
            "total_tare_weight": round(float(r.tare or 0), 3),
            "total_net_weight": round(float(r.net or 0), 3),
        }
        for r in db.execute(q).all()
    ]
    return {
        "items": items,
        "totals": {
            "total_boxes": sum(i["total_boxes"] for i in items),
            "total_gross_weight": round(sum(i["total_gross_weight"] for i in items), 3),
            "total_tare_weight": round(sum(i["total_tare_weight"] for i in items), 3),
            "total_net_weight": round(sum(i["total_net_weight"] for i in items), 3),
            "days": len(items),
        },
    }


@router.get("/records/sizes", response_model=dict)
def record_sizes(db: Annotated[Session, Depends(get_db)], _: CurrentUser):
    """Distinct sizes seen in records + configured tare sizes (filter dropdown)."""
    from_records = db.scalars(
        select(ProductionRecord.size).distinct().where(ProductionRecord.size != "")
    ).all()
    from_settings = db.scalars(
        select(TareWeightSetting.size).where(TareWeightSetting.is_active == True)  # noqa: E712
    ).all()
    seen: dict[str, str] = {}
    for s in [*from_settings, *from_records]:
        key = ws.normalize_size(s)
        if key and key not in seen:
            seen[key] = " ".join(s.split()).strip()
    return {"items": sorted(seen.values(), key=str.lower)}


@router.get("/records/report/csv")
def records_csv(
    db: Annotated[Session, Depends(get_db)], _: CurrentUser,
    search: str = "", product_id: int | None = None, size: str = "", grade: str = "",
    date_from: str = "", date_to: str = "", sync_status: str = "", record_status: str = "",
):
    """Box-wise production report as CSV."""
    stmt = _apply_filters(
        select(ProductionRecord),
        search=search, product_id=product_id, size=size, grade=grade,
        date_from=date_from, date_to=date_to, sync_status=sync_status,
        record_status=record_status,
    )
    rows = db.scalars(
        stmt.order_by(ProductionRecord.production_date.desc(), ProductionRecord.id.desc())
    ).all()
    headers = ["Production Date", "Box No", "Barcode", "Product", "Item Code",
               "Size", "Grade", "Micron", "Gross Weight", "Tare Weight",
               "Net Weight", "Record Status", "Inventory Sync", "Remark", "Created At"]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for r in rows:
        writer.writerow([
            r.production_date, r.box_number, r.barcode or "",
            r.product_name or (r.product.model if r.product else ""),
            r.product.item_code if r.product else "",
            r.size, r.grade, r.micron,
            r.gross_weight,
            r.tare_weight if r.tare_weight is not None else "",
            r.net_weight if r.net_weight is not None else "",
            "READY" if r.net_weight is not None else "TARE_MISSING",
            r.inventory_sync_status, r.remark or "",
            r.created_at,
        ])
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode("utf-8-sig")),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=production_records.csv"},
    )


@router.get("/records", response_model=dict)
def list_records(
    db: Annotated[Session, Depends(get_db)], _: CurrentUser,
    search: str = "", product_id: int | None = None, size: str = "", grade: str = "",
    date_from: str = "", date_to: str = "", sync_status: str = "", record_status: str = "",
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500),
):
    """Box-wise production records (the packing-slip ledger)."""
    stmt = _apply_filters(
        select(ProductionRecord),
        search=search, product_id=product_id, size=size, grade=grade,
        date_from=date_from, date_to=date_to, sync_status=sync_status,
        record_status=record_status,
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.order_by(ProductionRecord.production_date.desc(), ProductionRecord.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {"items": [_serialize_record(r) for r in rows],
            "total": total, "page": page, "page_size": page_size}


@router.post("/records", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_record(body: WeighingTransactionIn, db: Annotated[Session, Depends(get_db)],
                  user: AllStaff):
    """Manual box entry — runs the same validated pipeline as machine data
    (source=MANUAL). 409 on duplicate, 400 on validation failure."""
    result = ws.ingest_weighing_transaction(db, body, source=ws.SOURCE_MANUAL,
                                            user_name=user.full_name or user.username)
    if not result["ok"]:
        code = (status.HTTP_409_CONFLICT if (result["duplicate"] or result.get("conflict"))
                else status.HTTP_400_BAD_REQUEST)
        raise HTTPException(status_code=code, detail=result["error"])
    record = result["record"]
    write_audit(db, user, "CREATE", "production_records", record.id,
                f"Production record box {record.box_number} ({record.product_name}, "
                f"net {record.net_weight if record.net_weight is not None else '—'} kg)")
    return _serialize_record(record)


@router.get("/records/{record_id}", response_model=dict)
def get_record(record_id: int, db: Annotated[Session, Depends(get_db)], _: CurrentUser):
    return _serialize_record(get_or_404(db, ProductionRecord, record_id))


@router.post("/records/{record_id}/retry-sync", response_model=dict)
def retry_record_sync(record_id: int, db: Annotated[Session, Depends(get_db)], user: AllStaff):
    """Retry tare resolution / inventory posting for a PENDING or FAILED record.

    Exactly-once: an already-synced record is returned unchanged; a record with
    an applied tare never re-reads the settings (historical protection).
    """
    record = get_or_404(db, ProductionRecord, record_id)
    record = ws.reprocess_record(db, record)
    write_audit(db, user, "UPDATE", "production_records", record.id,
                f"Retry sync — status {record.inventory_sync_status}")
    return _serialize_record(record)


@router.delete("/records/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_record(record_id: int, db: Annotated[Session, Depends(get_db)],
                  user: ManagerOrAdmin):
    """Delete a production record and reverse its stock effect (if posted).
    The originating weighing transaction is kept for audit."""
    record = get_or_404(db, ProductionRecord, record_id)
    ws.delete_record_and_reverse_stock(db, record)
    db.commit()
    write_audit(db, user, "DELETE", "production_records", record_id,
                f"Deleted production record box {record.box_number} (stock reversed)")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
