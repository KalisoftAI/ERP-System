"""Structured JSON logging with rotating files and optional GCS upload."""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import settings

_LOG_FIELDS = (
    "event",
    "component",
    "request_id",
    "http_method",
    "http_path",
    "http_status",
    "duration_ms",
    "user_id",
    "user_role",
    "medium",
    "intent",
    "user_class",
    "error_code",
    "error_message",
)
_uploader: "GCSLogUploader | None" = None


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "component": getattr(record, "component", "api"),
            "event": getattr(record, "event", "log"),
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        for key in _LOG_FIELDS:
            if key in ("component", "event"):
                continue
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class GCSLogUploader:
    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._client = None
        self._uploaded: dict[str, tuple[str, int, int]] = {}
        self.logger = logging.getLogger("kalika.logging")

    def start(self) -> None:
        if not settings.GCS_LOG_UPLOAD_ENABLED:
            self.logger.info(
                "gcs.uploader.disabled",
                extra={"component": "logging", "event": "gcs.uploader.disabled",
                       "reason": "GCS_LOG_UPLOAD_ENABLED=false"},
            )
            return
        try:
            from google.cloud import storage
        except ImportError:
            self.logger.warning(
                "gcs.uploader.disabled: google-cloud-storage missing",
                extra={"component": "logging", "event": "gcs.uploader.disabled"},
            )
            return
        credentials = settings.GOOGLE_APPLICATION_CREDENTIALS
        if credentials:
            path = Path(credentials)
            if not path.is_absolute():
                path = Path.cwd() / path
            if not path.is_file():
                self.logger.error(
                    "gcs.uploader.error: credentials not found",
                    extra={"component": "logging", "event": "gcs.uploader.error",
                           "error_code": "CREDENTIALS_NOT_FOUND", "error_message": str(path)},
                )
                return
            os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(path))
        try:
            self._client = storage.Client()
        except Exception as exc:
            self.logger.error(
                "gcs.uploader.error: client init failed",
                extra={"component": "logging", "event": "gcs.uploader.error",
                       "error_code": type(exc).__name__, "error_message": str(exc)},
            )
            return
        self._thread = threading.Thread(target=self._run, name="kalika-gcs-log-uploader", daemon=True)
        self._thread.start()
        self.logger.info(
            "gcs.uploader.started",
            extra={"component": "logging", "event": "gcs.uploader.started",
                   "bucket": settings.GCS_BUCKET, "object_prefix": self.object_prefix(),
                   "interval_seconds": settings.GCS_LOG_UPLOAD_INTERVAL_SECONDS},
        )

    def object_prefix(self) -> str:
        parts = [settings.GCS_LOG_PREFIX, "api", settings.APP_ENV]
        return "/".join(_safe_segment(part) for part in parts if part)

    def _run(self) -> None:
        while not self._stop.wait(max(settings.GCS_LOG_UPLOAD_INTERVAL_SECONDS, 1)):
            self.upload_once()

    def upload_once(self) -> None:
        if self._client is None:
            return
        bucket = self._client.bucket(settings.GCS_BUCKET)
        for path in sorted(self.log_dir.glob(f"{Path(settings.LOG_FILE_NAME).name}*")):
            if not path.is_file():
                continue
            stat = path.stat()
            signature = (path.name, stat.st_size, stat.st_mtime_ns)
            if self._uploaded.get(path.name) == signature:
                continue
            object_name = self._object_name(path, stat.st_ctime)
            try:
                blob = bucket.blob(object_name)
                blob.upload_from_filename(str(path), content_type="application/x-ndjson")
                self._uploaded[path.name] = signature
                self.logger.info(
                    "gcs.upload.success",
                    extra={"component": "logging", "event": "gcs.upload.success",
                           "bucket": settings.GCS_BUCKET, "object": object_name,
                           "bytes": stat.st_size},
                )
            except Exception as exc:
                self.logger.error(
                    "gcs.upload.error",
                    extra={"component": "logging", "event": "gcs.upload.error",
                           "bucket": settings.GCS_BUCKET, "object": object_name,
                           "error_code": type(exc).__name__, "error_message": str(exc)},
                )

    def _object_name(self, path: Path, created_at: float) -> str:
        created = datetime.fromtimestamp(created_at, timezone.utc)
        stem = re.sub(r"\.\d+$", "", path.name)
        if stem.endswith(".jsonl"):
            stem = stem[:-6]
        date_path = f"{created.year:04d}/{created.month:02d}/{created.day:02d}"
        return f"{self.object_prefix()}/{date_path}/{_safe_segment(stem)}.jsonl"

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self.upload_once()


def configure_logging() -> GCSLogUploader:
    global _uploader
    if _uploader is not None:
        return _uploader
    root = logging.getLogger()
    level = getattr(logging, str(settings.LOG_LEVEL).upper(), logging.INFO)
    root.setLevel(level)
    formatter = JsonFormatter()
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)
    file_handler = RotatingFileHandler(
        _resolve_log_dir() / settings.LOG_FILE_NAME,
        maxBytes=settings.LOG_MAX_BYTES,
        backupCount=settings.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        named = logging.getLogger(name)
        named.handlers.clear()
        named.propagate = True
        named.setLevel(level)
    _uploader = GCSLogUploader(_resolve_log_dir())
    return _uploader


def _resolve_log_dir() -> Path:
    path = Path(settings.LOG_DIR)
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path
    except OSError:
        fallback = Path(tempfile.gettempdir()) / "kalika-erp" / "logs"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _safe_segment(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in str(value))
