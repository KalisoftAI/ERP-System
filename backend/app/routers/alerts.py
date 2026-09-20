from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import AllStaff, CurrentUser
from ..database import get_db
from ..models import Alert, AlertType, AlertPriority
from ..schemas import AlertOut, AlertUpdate

router = APIRouter(prefix="/alerts", tags=["Alerts"])


@router.get("", response_model=list[AlertOut])
def list_alerts(
    _: CurrentUser,
    type: str | None = None,
    priority: str | None = None,
    status: str | None = None,
    is_read: bool | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(Alert).order_by(Alert.created_at.desc())
    if type:
        q = q.filter(Alert.type == type)
    if priority:
        q = q.filter(Alert.priority == priority)
    if status:
        q = q.filter(Alert.status == status)
    if is_read is not None:
        q = q.filter(Alert.is_read == is_read)
    return q.all()


@router.get("/count")
def alert_count(_: CurrentUser, db: Session = Depends(get_db)):
    """Return unread alert count for the notification bell."""
    unread = db.query(func.count(Alert.id)).filter(
        Alert.is_read == False, Alert.status == "OPEN"
    ).scalar() or 0
    total = db.query(func.count(Alert.id)).filter(Alert.status == "OPEN").scalar() or 0
    critical = db.query(func.count(Alert.id)).filter(
        Alert.is_read == False, Alert.priority == AlertPriority.critical, Alert.status == "OPEN"
    ).scalar() or 0
    return {"unread": unread, "total_open": total, "critical_unread": critical}


@router.patch("/{alert_id}", response_model=AlertOut)
def update_alert(alert_id: int, body: AlertUpdate, _: AllStaff, db: Session = Depends(get_db)):
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(alert, k, v)
    if body.status and body.status == "RESOLVED" and not alert.resolved_at:
        alert.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(alert)
    return alert


@router.post("/mark-all-read")
def mark_all_read(_: AllStaff, db: Session = Depends(get_db)):
    """Mark all OPEN alerts as read."""
    now = datetime.now(timezone.utc)
    db.query(Alert).filter(Alert.is_read == False, Alert.status == "OPEN").update(
        {"is_read": True}
    )
    db.commit()
    return {"message": "All alerts marked as read"}


@router.post("", status_code=201)
def create_alert(
    _: AllStaff,
    type: str,
    message: str,
    priority: str = "MEDIUM",
    entity_type: str = "",
    entity_id: int | None = None,
    target_role: str = "",
    db: Session = Depends(get_db),
):
    """Create an alert (internal API for engine services)."""
    if type not in [e.value for e in AlertType]:
        raise HTTPException(400, f"Invalid alert type: {type}")
    if priority not in [e.value for e in AlertPriority]:
        raise HTTPException(400, f"Invalid priority: {priority}")
    alert = Alert(
        type=type,
        priority=priority,
        message=message,
        entity_type=entity_type,
        entity_id=entity_id,
        target_role=target_role,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return {"id": alert.id, "message": "Alert created"}


@router.post("/resolve-by-type")
def resolve_by_type(entity_type: str, entity_id: int, _: AllStaff, db: Session = Depends(get_db)):
    """Resolve all open alerts for a specific entity."""
    now = datetime.now(timezone.utc)
    db.query(Alert).filter(
        Alert.entity_type == entity_type,
        Alert.entity_id == entity_id,
        Alert.status == "OPEN",
    ).update({"status": "RESOLVED", "is_read": True, "resolved_at": now})
    db.commit()
    return {"message": f"Resolved alerts for {entity_type}#{entity_id}"}
