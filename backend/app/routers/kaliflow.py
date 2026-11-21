"""JWT-gated Kaliflow 3D plant view served from a database-bound GCS path."""
import logging
import time
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import AdminUser, CurrentUser
from ..config import settings
from ..crud import write_audit
from ..database import get_db
from ..models import FeatureToggle, GcsAsset

router = APIRouter(prefix="/kaliflow", tags=["kaliflow"])
log = logging.getLogger(__name__)

TOGGLE_KEY = "kaliflow_dashboard"
DEFAULT_ASSETS = {
    TOGGLE_KEY: (settings.KALIFLOW_GCS_BUCKET, settings.KALIFLOW_GCS_OBJECT, "html"),
    "kalika_logo": ("sales-crm", "assets/Kalika-Logo.png", "logo"),
    "kalisoftai_logo": ("sales-crm", "assets/KalisoftAI Logo - 1.png", "logo"),
    "kalika_demo_video": (
        "sales-crm",
        "Manufacturing-Data/kalika-videos/app-demo-videos/15-30-12.mp4",
        "video",
    ),
}
_cached_html: bytes | None = None
_cache_expiry = 0.0
_cache_path = ""


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
    changed = False
    for key, (bucket, object_path, kind) in DEFAULT_ASSETS.items():
        if db.get(GcsAsset, key) is None:
            db.add(GcsAsset(key=key, kind=kind, bucket=bucket, object_path=object_path))
            changed = True
    if changed:
        db.commit()


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
        url=f"https://storage.googleapis.com/{row.bucket}/{quote(row.object_path)}",
    )


def _load_bytes(bucket: str, object_path: str) -> bytes:
    global _cached_html, _cache_expiry, _cache_path
    now = time.monotonic()
    path = f"{bucket}/{object_path}"
    if _cached_html is not None and now < _cache_expiry and _cache_path == path:
        return _cached_html
    try:
        from google.cloud import storage

        client = storage.Client()
        blob = client.bucket(bucket).blob(object_path)
        html = blob.download_as_bytes()
        _cached_html = html
        _cache_expiry = now + max(0, settings.KALIFLOW_CACHE_SECONDS)
        _cache_path = path
        return html
    except Exception as exc:
        log.warning("Kaliflow GCS fetch failed for %s: %s", path, exc)
        if _cached_html is not None and _cache_path == path:
            _cache_expiry = now + 30
            return _cached_html
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Kaliflow dashboard is unavailable",
        ) from exc


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
    for field in ("kind", "bucket", "object_path"):
        if field in data:
            setattr(row, field, data[field])
    db.commit()
    write_audit(db, user, "KALIFLOW_ASSET", "kaliflow", None, f"Updated GCS asset {key}")
    return _asset_out(row)


@router.get("/asset/{key}")
def asset_file(key: str, _: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    if not _is_enabled(db):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kaliflow view is disabled")
    row = _asset(db, key)
    data = _load_bytes(row.bucket, row.object_path)
    media_type = {
        "html": "text/html",
        "video": "video/mp4",
        "logo": "image/png",
    }.get(row.kind, "application/octet-stream")
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
def dashboard(_: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    if not _is_enabled(db):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kaliflow view is disabled")
    asset = _asset(db, TOGGLE_KEY)
    html = _load_bytes(asset.bucket, asset.object_path)
    return Response(
        content=html,
        media_type="text/html",
        headers={"X-Content-Type-Options": "nosniff"},
    )
