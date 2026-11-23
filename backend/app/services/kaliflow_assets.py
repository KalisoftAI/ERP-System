"""Validated GCS asset registry and reader for the Kaliflow view."""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from sqlalchemy.orm import Session

from ..config import settings
from ..models import GcsAsset

log = logging.getLogger(__name__)

_ALLOWED_KINDS = ("html", "video", "logo")
_MEDIA_TYPES = {
    "html": "text/html",
    "video": "video/mp4",
    "logo": "image/png",
}
_MAX_BYTES = {
    "html": 16 * 1024 * 1024,
    "video": 512 * 1024 * 1024,
    "logo": 4 * 1024 * 1024,
}
_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]$")
_MAX_OBJECT_PATH_LENGTH = 500
_CHUNK_SIZE = 1024 * 1024
_CACHE_MAX_BYTES = 32 * 1024 * 1024
_STALE_GRACE_SECONDS = 30


class AssetValidationError(ValueError):
    pass


class AssetFetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class AssetSpec:
    key: str
    kind: str
    bucket: str
    object_path: str
    legacy_bucket: str | None = None
    legacy_object_path: str | None = None

    @property
    def media_type(self) -> str:
        return _MEDIA_TYPES.get(self.kind, "application/octet-stream")

    @property
    def max_bytes(self) -> int:
        return _MAX_BYTES.get(self.kind, 8 * 1024 * 1024)

    @property
    def cache_key(self) -> str:
        return f"{self.bucket}/{self.object_path}"

    @property
    def url(self) -> str:
        return public_url(self.bucket, self.object_path)


@dataclass
class _CacheEntry:
    data: bytes
    expires_at: float


def public_url(bucket: str, object_path: str) -> str:
    return f"https://storage.googleapis.com/{quote(bucket, safe='')}/{quote(object_path)}"


def validate_bucket(bucket: Any) -> str:
    if not isinstance(bucket, str) or not _BUCKET_RE.fullmatch(bucket) or ".." in bucket:
        raise AssetValidationError("Invalid GCS bucket name")
    return bucket


def validate_object_path(object_path: Any) -> str:
    if not isinstance(object_path, str) or not object_path:
        raise AssetValidationError("GCS object path is required")
    if len(object_path) > _MAX_OBJECT_PATH_LENGTH:
        raise AssetValidationError("GCS object path is too long")
    if object_path.startswith("/") or object_path.endswith("/"):
        raise AssetValidationError("GCS object path must be relative")
    if "\\" in object_path or "//" in object_path:
        raise AssetValidationError("GCS object path has invalid separators")
    if any(ord(char) < 32 or ord(char) == 127 for char in object_path):
        raise AssetValidationError("GCS object path has control characters")
    if any(char in object_path for char in ("%", "?", "#")):
        raise AssetValidationError("GCS object path must be unencoded")
    if any(part in (".", "..") for part in object_path.split("/")):
        raise AssetValidationError("GCS object path has traversal segments")
    return object_path


def validate_kind(kind: Any) -> str:
    if kind not in _ALLOWED_KINDS:
        raise AssetValidationError("Invalid Kaliflow asset kind")
    return kind


def validate_spec(spec: AssetSpec, allowed_buckets: set[str] | None = None) -> AssetSpec:
    validate_kind(spec.kind)
    validate_bucket(spec.bucket)
    validate_object_path(spec.object_path)
    if allowed_buckets is not None and spec.bucket not in allowed_buckets:
        raise AssetValidationError("GCS bucket is not allowed for Kaliflow assets")
    if spec.legacy_bucket is not None:
        validate_bucket(spec.legacy_bucket)
    if spec.legacy_object_path is not None:
        validate_object_path(spec.legacy_object_path)
    return spec


def build_registry(cfg=settings) -> dict[str, AssetSpec]:
    bucket = cfg.KALIFLOW_GCS_BUCKET
    specs = {
        "kaliflow_dashboard": AssetSpec(
            key="kaliflow_dashboard",
            kind="html",
            bucket=bucket,
            object_path=cfg.KALIFLOW_GCS_OBJECT,
            legacy_bucket="sales-crm",
            legacy_object_path="assets/UI/kaliflow_kalika_enterprises_3d_manufacturing_dashboard.html",
        ),
        "kalika_logo": AssetSpec(
            key="kalika_logo",
            kind="logo",
            bucket=bucket,
            object_path=cfg.KALIFLOW_LOGO_OBJECT,
        ),
        "kalisoftai_logo": AssetSpec(
            key="kalisoftai_logo",
            kind="logo",
            bucket=bucket,
            object_path=cfg.KALIFLOW_SOFT_LOGO_OBJECT,
        ),
        "kalika_demo_video": AssetSpec(
            key="kalika_demo_video",
            kind="video",
            bucket=bucket,
            object_path=cfg.KALIFLOW_VIDEO_OBJECT,
            legacy_bucket="sales-crm",
            legacy_object_path="Manufacturing-Data/kalika-videos/app-demo-videos/15-30-12.mp4",
        ),
    }
    allowed_buckets = {spec.bucket for spec in specs.values()} | {"sales-crm"}
    for spec in specs.values():
        validate_spec(spec, allowed_buckets)
    return specs


asset_registry = build_registry()


def allowed_buckets(registry: dict[str, AssetSpec] | None = None) -> set[str]:
    specs = registry if registry is not None else asset_registry
    return {spec.bucket for spec in specs.values()} | {"sales-crm"}


def validate_asset_update(
    key: str,
    fields: dict[str, Any],
    registry: dict[str, AssetSpec] | None = None,
) -> AssetSpec:
    specs = registry if registry is not None else asset_registry
    current = specs.get(key)
    if current is None:
        raise KeyError(key)
    candidate = AssetSpec(
        key=key,
        kind=fields.get("kind", current.kind),
        bucket=fields.get("bucket", current.bucket),
        object_path=fields.get("object_path", current.object_path),
    )
    return validate_spec(candidate, allowed_buckets(specs))


def reconcile_assets(
    db: Session,
    registry: dict[str, AssetSpec] | None = None,
) -> bool:
    specs = registry if registry is not None else asset_registry
    changed = False
    for key, spec in specs.items():
        row = db.get(GcsAsset, key)
        if row is None:
            db.add(GcsAsset(key=key, kind=spec.kind, bucket=spec.bucket, object_path=spec.object_path))
            changed = True
            continue
        legacy_match = (
            spec.legacy_object_path is not None
            and row.object_path == spec.legacy_object_path
            and (spec.legacy_bucket is None or row.bucket == spec.legacy_bucket)
        )
        if legacy_match:
            row.bucket = spec.bucket
            row.object_path = spec.object_path
            row.kind = spec.kind
            changed = True
            continue
        try:
            validate_spec(AssetSpec(row.key, row.kind, row.bucket, row.object_path))
        except AssetValidationError as exc:
            log.warning("Keeping existing Kaliflow asset %s unchanged: %s", key, exc)
    if changed:
        db.commit()
    return changed


class GcsAssetReader:
    def __init__(self, cache_seconds: int | None = None):
        self.cache_seconds = settings.KALIFLOW_CACHE_SECONDS if cache_seconds is None else cache_seconds
        self._cache: dict[str, _CacheEntry] = {}

    def prime(self, bucket: str, object_path: str, data: bytes, ttl: float | None = None) -> None:
        key = f"{bucket}/{object_path}"
        lifetime = self.cache_seconds if ttl is None else ttl
        self._cache[key] = _CacheEntry(bytes(data), time.monotonic() + lifetime)

    def invalidate(self, bucket: str, object_path: str) -> None:
        self._cache.pop(f"{bucket}/{object_path}", None)

    def clear(self) -> None:
        self._cache.clear()

    def read(self, spec: AssetSpec, permitted_buckets: set[str] | None = None) -> bytes:
        validate_spec(spec, permitted_buckets)
        key = spec.cache_key
        now = time.monotonic()
        entry = self._cache.get(key)
        if entry is not None and now < entry.expires_at:
            return entry.data
        try:
            data = self._download(spec)
            if len(data) > spec.max_bytes:
                raise AssetFetchError(
                    f"Kaliflow asset exceeds {spec.max_bytes} byte limit"
                )
        except Exception as exc:
            log.warning("Kaliflow GCS fetch failed for %s: %s", key, exc)
            if entry is not None:
                entry.expires_at = now + _STALE_GRACE_SECONDS
                return entry.data
            raise AssetFetchError("Kaliflow asset is unavailable") from exc
        if len(data) <= _CACHE_MAX_BYTES:
            self._cache[key] = _CacheEntry(data, now + max(0, self.cache_seconds))
        return data

    def _download(self, spec: AssetSpec) -> bytes:
        from google.cloud import storage

        client = storage.Client()
        blob = client.bucket(spec.bucket).blob(spec.object_path)
        data = bytearray()
        with blob.open("rb") as stream:
            while True:
                chunk = stream.read(_CHUNK_SIZE)
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > spec.max_bytes:
                    raise AssetFetchError(
                        f"Kaliflow asset exceeds {spec.max_bytes} byte limit"
                    )
        return bytes(data)


asset_reader = GcsAssetReader()
