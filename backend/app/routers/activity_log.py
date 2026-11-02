"""Read-only activity log: daily summary, detailed history and exports."""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from ..auth import ManagerOrAdmin
from ..database import get_db
from ..models import AuditLog, User
from .reports import _csv_response, _excel_response

router = APIRouter(prefix="/activity-log", tags=["activity-log"])

# Raw audit entities -> business modules shown in the UI.
MODULE_MAP = {
    "customers": "Customers",
    "suppliers": "Suppliers",
    "prns": "PRN",
    "purchase_orders": "Purchases",
    "sales_orders": "Orders",
    "sales_order_lines": "Orders",
    "dispatches": "Dispatch",
    "dispatch_lines": "Dispatch",
    "customer_dispatches": "Dispatch",
    "production_orders": "Production",
    "production_movements": "Production",
    "plans": "Production",
    "employees": "Employee Management",
    "products": "Inventory",
    "inventory": "Inventory",
    "stock_movements": "Inventory",
    "stock_transfers": "Inventory",
    "raw_material_balances": "Inventory",
    "import_batches": "Inventory",
    "boms": "BOM",
    "bill_of_materials": "BOM",
    "packaging_lists": "Packaging",
    "quotation": "Quotations",
    "purchase_requirements": "Requirements",
    "plants": "Plants",
    "users": "Administration",
    "auth": "Administration",
    "salespersons": "Salespersons",
}


def module_of(entity: str) -> str:
    if not entity:
        return "Other"
    return MODULE_MAP.get(entity, entity.replace("_", " ").title())


def _entities_for(module: str) -> list[str]:
    label = (module or "").strip()
    if not label:
        return []
    entities = [entity for entity, name in MODULE_MAP.items()
                if name.lower() == label.lower()]
    return entities or [label]


def _counts(log: AuditLog) -> dict:
    created = int(log.created_count or 0)
    updated = int(log.updated_count or 0)
    return {
        "added": created or (1 if log.action == "CREATE" else 0),
        "updated": updated or (1 if log.action == "UPDATE" else 0),
        "deleted": 1 if log.action == "DELETE" else 0,
        "failed": int(log.failed_count or 0),
    }


def _apply_filters(stmt, date_from: date | None, date_to: date | None, module: str,
                   user_id: int | None, action: str, search: str, kind: str = ""):
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        stmt = stmt.where(AuditLog.created_at < datetime.combine(date_to + timedelta(days=1), time.min))
    if module:
        stmt = stmt.where(AuditLog.entity.in_(_entities_for(module)))
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if kind == "added":
        stmt = stmt.where(or_(AuditLog.action == "CREATE", AuditLog.created_count > 0))
    elif kind == "updated":
        stmt = stmt.where(or_(AuditLog.action == "UPDATE", AuditLog.updated_count > 0))
    elif kind == "deleted":
        stmt = stmt.where(AuditLog.action == "DELETE")
    elif kind == "records":
        stmt = stmt.where(or_(
            AuditLog.action.in_(("CREATE", "UPDATE", "DELETE")),
            AuditLog.created_count > 0, AuditLog.updated_count > 0))
    elif kind == "imports":
        stmt = stmt.where(AuditLog.action == "IMPORT")
    elif kind == "failed":
        stmt = stmt.where(AuditLog.failed_count > 0)
    if search:
        term = f"%{search.strip()}%"
        stmt = stmt.where(or_(
            AuditLog.entity.ilike(term),
            AuditLog.action.ilike(term),
            AuditLog.details.ilike(term),
            User.username.ilike(term),
            User.full_name.ilike(term),
        ))
    return stmt


def _decode_changes(raw: str) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _user_dict(user: User | None) -> dict:
    if user is None:
        return {"id": None, "username": "System", "full_name": "", "role": ""}
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role.value if hasattr(user.role, "value") else user.role,
    }


def _serialize(log: AuditLog, user: User | None) -> dict:
    return {
        "id": log.id,
        "user": _user_dict(user),
        "action": log.action,
        "module": module_of(log.entity),
        "entity": log.entity,
        "record_id": log.entity_id,
        "details": log.details,
        "changes": _decode_changes(log.changes),
        "counts": _counts(log),
        "ip": log.ip,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }


def _display(value) -> str:
    if value is None or value == "":
        return "(empty)"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _changes_text(raw: str) -> str:
    changes = _decode_changes(raw)
    return "; ".join(
        f"{field}: {_display(item.get('old'))} -> {_display(item.get('new'))}"
        for field, item in changes.items() if isinstance(item, dict)
    )


@router.get("/options")
def filter_options(db: Annotated[Session, Depends(get_db)], _: ManagerOrAdmin):
    entities = db.scalars(select(AuditLog.entity).distinct()).all()
    actions = db.scalars(select(AuditLog.action).distinct().order_by(AuditLog.action)).all()
    users = db.scalars(select(User).order_by(User.username)).all()
    return {
        "modules": sorted({module_of(e) for e in entities if e}),
        "actions": [a for a in actions if a],
        "users": [_user_dict(u) for u in users],
    }


@router.get("/summary")
def daily_summary(
    db: Annotated[Session, Depends(get_db)],
    _: ManagerOrAdmin,
    date_from: date | None = None,
    date_to: date | None = None,
    module: str = "",
    user_id: int | None = None,
    action: str = "",
    search: str = "",
):
    day = func.date(AuditLog.created_at).label("day")
    stmt = (
        select(
            day,
            AuditLog.entity,
            AuditLog.user_id,
            User.username,
            User.full_name,
            User.role,
            func.coalesce(func.sum(case(
                (AuditLog.created_count > 0, AuditLog.created_count),
                (AuditLog.action == "CREATE", 1), else_=0)), 0).label("creates"),
            func.coalesce(func.sum(case(
                (AuditLog.updated_count > 0, AuditLog.updated_count),
                (AuditLog.action == "UPDATE", 1), else_=0)), 0).label("updates"),
            func.coalesce(func.sum(case((AuditLog.action == "DELETE", 1), else_=0)), 0).label("deletes"),
            func.coalesce(func.sum(AuditLog.failed_count), 0).label("failed"),
            func.coalesce(func.sum(case((AuditLog.action == "IMPORT", 1), else_=0)), 0).label("imports"),
        )
        .select_from(AuditLog)
        .outerjoin(User, AuditLog.user_id == User.id)
    )
    stmt = _apply_filters(stmt, date_from, date_to, module, user_id, action, search)
    stmt = (
        stmt.group_by(day, AuditLog.entity, AuditLog.user_id, User.username, User.full_name, User.role)
        .order_by(day.desc())
    )
    rows = db.execute(stmt).all()

    grouped: dict[tuple, dict] = {}
    for r in rows:
        user = _user_dict(None if r.user_id is None else User(
            id=r.user_id, username=r.username, full_name=r.full_name or "", role=r.role))
        key = (str(r.day), module_of(r.entity), r.user_id)
        item = grouped.setdefault(key, {
            "day": str(r.day),
            "module": module_of(r.entity),
            "user": user,
            "added": 0, "updated": 0, "deleted": 0, "failed": 0, "imports": 0,
        })
        item["added"] += int(r.creates or 0)
        item["updated"] += int(r.updates or 0)
        item["deleted"] += int(r.deletes or 0)
        item["failed"] += int(r.failed or 0)
        item["imports"] += int(r.imports or 0)

    items = []
    for item in grouped.values():
        item["total"] = item["added"] + item["updated"] + item["deleted"]
        if item["total"] or item["failed"] or item["imports"]:
            item["creates"] = item["added"]  # backward-compatible keys
            item["updates"] = item["updated"]
            item["deletes"] = item["deleted"]
            items.append(item)
    items.sort(key=lambda i: (i["day"], i["total"]), reverse=True)
    return {"items": items}


@router.get("")
def list_activity(
    db: Annotated[Session, Depends(get_db)],
    _: ManagerOrAdmin,
    date_from: date | None = None,
    date_to: date | None = None,
    module: str = "",
    user_id: int | None = None,
    action: str = "",
    kind: str = "",
    search: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    stmt = select(AuditLog, User).outerjoin(User, AuditLog.user_id == User.id)
    stmt = _apply_filters(stmt, date_from, date_to, module, user_id, action, search, kind)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(
        stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {
        "items": [_serialize(log, user) for log, user in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/export")
def export_activity(
    db: Annotated[Session, Depends(get_db)],
    _: ManagerOrAdmin,
    date_from: date | None = None,
    date_to: date | None = None,
    module: str = "",
    user_id: int | None = None,
    action: str = "",
    kind: str = "",
    search: str = "",
    format: str = "csv",
):
    stmt = select(AuditLog, User).outerjoin(User, AuditLog.user_id == User.id)
    stmt = _apply_filters(stmt, date_from, date_to, module, user_id, action, search, kind)
    rows = db.execute(stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())).all()
    headers = ["Date", "User", "Role", "Module", "Record ID", "Action",
               "Added", "Updated", "Deleted", "Failed", "Details", "Changes"]
    data = []
    for log, user in rows:
        counts = _counts(log)
        data.append([
            log.created_at.strftime("%Y-%m-%d %H:%M:%S") if log.created_at else "",
            (user.full_name or user.username) if user else "System",
            (user.role.value if hasattr(user.role, "value") else user.role) if user else "",
            module_of(log.entity),
            log.entity_id or "",
            log.action,
            counts["added"], counts["updated"], counts["deleted"], counts["failed"],
            log.details,
            _changes_text(log.changes),
        ])
    fname = f"activity_log_{date.today().isoformat()}"
    if format.lower() in ("excel", "xlsx"):
        return _excel_response(f"{fname}.xlsx", "Activity Log", headers, data)
    return _csv_response(headers, data, f"{fname}.csv")
