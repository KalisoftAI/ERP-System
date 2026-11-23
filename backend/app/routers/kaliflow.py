"""JWT-gated Kaliflow 3D plant view served from a database-bound GCS path."""
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import AdminUser, CurrentUser
from ..crud import write_audit
from ..database import get_db
from ..models import FeatureToggle, GcsAsset
from ..services.kaliflow_assets import (
    AssetFetchError,
    AssetSpec,
    AssetValidationError,
    allowed_buckets,
    asset_reader,
    asset_registry,
    public_url,
    reconcile_assets,
    validate_asset_update,
)
from .dashboard import summary as dashboard_summary

router = APIRouter(prefix="/kaliflow", tags=["kaliflow"])
log = logging.getLogger(__name__)

TOGGLE_KEY = "kaliflow_dashboard"
DEFAULT_ASSETS = {
    key: (spec.bucket, spec.object_path, spec.kind)
    for key, spec in asset_registry.items()
}


class ToggleOut(BaseModel):
    enabled: bool


class ToggleIn(BaseModel):
    enabled: bool


class AssetOut(BaseModel):
    key: str
    kind: str
    bucket: str
    object_path: str
    url: str


class AssetIn(BaseModel):
    kind: str | None = None
    bucket: str | None = None
    object_path: str | None = None


def _ensure_toggle(db: Session) -> None:
    if db.get(FeatureToggle, TOGGLE_KEY) is None:
        db.add(FeatureToggle(key=TOGGLE_KEY, enabled=True))
        db.commit()


def _toggle_row(db: Session) -> FeatureToggle | None:
    _ensure_toggle(db)
    return db.get(FeatureToggle, TOGGLE_KEY)


def _is_enabled(db: Session) -> bool:
    row = _toggle_row(db)
    return bool(row and row.enabled)


def _seed_assets(db: Session) -> None:
    reconcile_assets(db)


def _asset(db: Session, key: str) -> GcsAsset:
    _seed_assets(db)
    row = db.get(GcsAsset, key)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Asset {key} not found")
    return row


def _asset_out(row: GcsAsset) -> AssetOut:
    return AssetOut(
        key=row.key,
        kind=row.kind,
        bucket=row.bucket,
        object_path=row.object_path,
        url=public_url(row.bucket, row.object_path),
    )


def _read_asset(row: GcsAsset) -> bytes:
    spec = AssetSpec(row.key, row.kind, row.bucket, row.object_path)
    try:
        return asset_reader.read(spec, allowed_buckets())
    except AssetValidationError as exc:
        log.warning("Rejecting invalid Kaliflow asset %s: %s", row.key, exc)
    except AssetFetchError:
        pass
    raise HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Kaliflow asset is unavailable",
    )


def _inject_live_numbers(document: bytes, db: Session, user) -> bytes:
    data = dashboard_summary(db=db, _=user)
    total = float(data.get("total_orders") or 0)
    completed = float(data.get("completed_orders") or 0)
    produced = float(data.get("production_produced_qty") or 0)
    stock = float(data.get("raw_material_stock") or 0)
    resin = max(0, min(100, round(stock / 5000)))
    nos = {
        "output": f"{produced / 1000:.2f}",
        "oee": f"{(completed / total * 100) if total else 0:.1f}%",
        "dispatched": str(int(data.get("orders_dispatched") or 0)),
        "resin": f"{resin}%",
        "resin_pct": str(resin),
    }
    payload = json.dumps(nos).replace("<", "\\u003c")
    script = f"<script>window.KALIFLOW_NOS = {payload};</script>"
    text = document.decode("utf-8")
    text = text.replace("<head>", f"<head>{script}", 1) if "<head>" in text else script + text
    return text.encode("utf-8")


@router.get("/assets")
def list_assets(_: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    _seed_assets(db)
    rows = db.query(GcsAsset).order_by(GcsAsset.key).all()
    return {"items": [_asset_out(row).model_dump() for row in rows]}


@router.patch("/assets/{key}")
def update_asset(
    key: str,
    body: AssetIn,
    user: AdminUser,
    db: Annotated[Session, Depends(get_db)],
):
    row = _asset(db, key)
    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields to update")
    try:
        candidate = validate_asset_update(key, data)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Asset {key} not found") from exc
    except AssetValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    asset_reader.invalidate(row.bucket, row.object_path)
    for field in ("kind", "bucket", "object_path"):
        if field in data:
            setattr(row, field, getattr(candidate, field))
    db.commit()
    asset_reader.invalidate(candidate.bucket, candidate.object_path)
    write_audit(db, user, "KALIFLOW_ASSET", "kaliflow", None, f"Updated GCS asset {key}")
    return _asset_out(row)


@router.get("/asset/{key}")
def asset_file(key: str, _: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    if not _is_enabled(db):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kaliflow view is disabled")
    row = _asset(db, key)
    data = _read_asset(row)
    media_type = AssetSpec(
        key=row.key,
        kind=row.kind,
        bucket=row.bucket,
        object_path=row.object_path,
    ).media_type
    return Response(
        content=data,
        media_type=media_type,
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get("/toggle", response_model=ToggleOut)
def get_toggle(_: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    return ToggleOut(enabled=_is_enabled(db))


@router.patch("/toggle", response_model=ToggleOut)
def set_toggle(
    body: ToggleIn,
    user: AdminUser,
    db: Annotated[Session, Depends(get_db)],
):
    row = _toggle_row(db)
    if row is None:
        db.add(FeatureToggle(key=TOGGLE_KEY, enabled=body.enabled))
    else:
        row.enabled = body.enabled
    db.commit()
    write_audit(
        db,
        user,
        "KALIFLOW_TOGGLE",
        "kaliflow",
        None,
        f"Kaliflow dashboard {'enabled' if body.enabled else 'disabled'}",
    )
    return ToggleOut(enabled=body.enabled)


@router.get("/dashboard")
def dashboard(user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    if not _is_enabled(db):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kaliflow view is disabled")
    asset = _asset(db, TOGGLE_KEY)
    html = _inject_live_numbers(_read_asset(asset), db, user)
    return Response(
        content=html,
        media_type="text/html",
        headers={"X-Content-Type-Options": "nosniff"},
    )
