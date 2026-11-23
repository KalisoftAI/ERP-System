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
from uuid import uuid4

from config import BridgeConfig


class JsonFormatter(logging.Formatter):
    def __init__(self, config: BridgeConfig):
        super().__init__()
        self.config = config

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "component": getattr(record, "component", "bridge"),
            "event": getattr(record, "event", "log"),
            "device_id": getattr(record, "device_id", self.config.device_id),
            "host": getattr(record, "host", self.config.device_host),
            "port": getattr(record, "port", self.config.device_port or 0),
            "connection_id": getattr(record, "connection_id", ""),
            "sequence": getattr(record, "sequence", None),
            "correlation_id": getattr(record, "correlation_id", ""),
            "message": record.getMessage(),
        }
        data = getattr(record, "data", None)
        if isinstance(data, dict):
            payload.update(data)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class GCSLogUploader:
    def __init__(self, config: BridgeConfig, log_dir: Path, bridge_logger: "BridgeLogger"):
        self.config = config
        self.log_dir = log_dir
        self.bridge_logger = bridge_logger
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._client = None
        self._uploaded: dict[str, tuple[str, int, int]] = {}

    def start(self) -> None:
        if not self.config.gcs_upload_enabled:
            self.bridge_logger.event(
                "gcs.uploader.disabled",
                component="weighing.logging",
                reason="GCS_UPLOAD_ENABLED=false",
            )
            return
        try:
            from google.cloud import storage
        except ImportError:
            self.bridge_logger.event(
                "gcs.uploader.disabled",
                component="weighing.logging",
                reason="google-cloud-storage is not installed",
            )
            return
        if self.config.gcs_credentials_path:
            credentials = Path(self.config.gcs_credentials_path)
            if not credentials.is_absolute():
                credentials = Path.cwd() / credentials
            if not credentials.is_file():
                self.bridge_logger.event(
                    "gcs.uploader.error",
                    component="weighing.logging",
                    error_code="CREDENTIALS_NOT_FOUND",
                    error_message=str(credentials),
                )
                return
            os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(credentials))
        try:
            self._client = storage.Client()
        except Exception as exc:
            self.bridge_logger.event(
                "gcs.uploader.error",
                component="weighing.logging",
                error_code=type(exc).__name__,
                error_message=str(exc),
            )
            return
        self._thread = threading.Thread(
            target=self._run,
            name="gcs-log-uploader",
            daemon=True,
        )
        self._thread.start()
        self.bridge_logger.event(
            "gcs.uploader.started",
            component="weighing.logging",
            bucket=self.config.gcs_bucket,
            prefix=self.config.gcs_log_prefix,
            interval_seconds=self.config.gcs_upload_interval_seconds,
            object_pattern=self.object_prefix() + "/YYYY/MM/DD/<filename>.jsonl",
        )

    def object_prefix(self) -> str:
        parts = [
            self.config.gcs_log_prefix,
            "weighing",
            self.config.weighing_environment,
            self.config.device_id,
        ]
        return "/".join(_safe_segment(part) for part in parts if part)

    def _run(self) -> None:
        while not self._stop.wait(max(self.config.gcs_upload_interval_seconds, 1.0)):
            self.upload_once()

    def upload_once(self) -> None:
        if self._client is None:
            return
        pattern = f"{Path(self.config.log_file_name).name}*"
        for path in sorted(self.log_dir.glob(pattern)):
            if not path.is_file():
                continue
            stat = path.stat()
            signature = (path.name, stat.st_size, stat.st_mtime_ns)
            if self._uploaded.get(path.name) == signature:
                continue
            object_name = self._object_name(path, stat.st_ctime)
            try:
                blob = self._client.bucket(self.config.gcs_bucket).blob(object_name)
                blob.upload_from_filename(str(path), content_type="application/x-ndjson")
                self._uploaded[path.name] = signature
                self.bridge_logger.event(
                    "gcs.upload.success",
                    component="weighing.logging",
                    bucket=self.config.gcs_bucket,
                    object=object_name,
                    bytes=stat.st_size,
                )
            except Exception as exc:
                self.bridge_logger.event(
                    "gcs.upload.error",
                    component="weighing.logging",
                    bucket=self.config.gcs_bucket,
                    object=object_name,
                    error_code=type(exc).__name__,
                    error_message=str(exc),
                )

    def _object_name(self, path: Path, created_at: float) -> str:
        created = datetime.fromtimestamp(created_at, timezone.utc)
        stem = re.sub(r"\.\d+$", "", path.name)
        if stem.endswith(".jsonl"):
            stem = stem[:-6]
        file_name = f"{_safe_segment(stem)}.jsonl"
        date_path = f"{created.year:04d}/{created.month:02d}/{created.day:02d}"
        return f"{self.object_prefix()}/{date_path}/{file_name}"

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self.upload_once()


class BridgeLogger:
    def __init__(self, config: BridgeConfig):
        self.config = config
        self.log_dir = self._resolve_log_dir(config)
        formatter = JsonFormatter(config)
        self.logger = logging.getLogger("kalika.bridge")
        self.logger.setLevel(getattr(logging, config.log_level, logging.INFO))
        self.logger.propagate = False
        self._sequence = 0
        self._lock = threading.Lock()
        self._correlation_id = uuid4().hex[:12]
        self._connection_id = ""
        if not getattr(self.logger, "_kalika_bridge_configured", False):
            console = logging.StreamHandler()
            console.setFormatter(formatter)
            self.logger.addHandler(console)
            file_handler = RotatingFileHandler(
                self.log_dir / config.log_file_name,
                maxBytes=config.log_max_bytes,
                backupCount=config.log_backup_count,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
            self.logger._kalika_bridge_configured = True
        self.uploader = GCSLogUploader(config, self.log_dir, self)

    def set_context(self, *, connection_id: str = "", correlation_id: str = "") -> None:
        if connection_id:
            self._connection_id = connection_id
        if correlation_id:
            self._correlation_id = correlation_id

    def event(self, name: str, message: str = "", level: int = logging.INFO, **fields) -> None:
        try:
            with self._lock:
                self._sequence += 1
                sequence = self._sequence
            data = dict(fields)
            data.setdefault("component", "bridge")
            data.setdefault("device_id", self.config.device_id)
            data.setdefault("host", self.config.device_host)
            data.setdefault("port", self.config.device_port or 0)
            data.setdefault("connection_id", self._connection_id)
            data.setdefault("correlation_id", self._correlation_id)
            data.setdefault("sequence", sequence)
            self.logger.log(
                level,
                message or name,
                extra={"event": name, "data": data},
            )
        except Exception:
            pass

    def start_uploader(self) -> None:
        self.uploader.start()

    def stop_uploader(self) -> None:
        try:
            self.uploader.stop()
        except Exception:
            pass

    def _resolve_log_dir(self, config: BridgeConfig) -> Path:
        try:
            config.log_dir.mkdir(parents=True, exist_ok=True)
            return config.log_dir
        except OSError:
            fallback = (
                Path(tempfile.gettempdir())
                / "kalisoftai-datahub"
                / "Kalika_inventory"
                / "Logs"
            )
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback


def configure_logging(config: BridgeConfig) -> BridgeLogger:
    return BridgeLogger(config)


def _safe_segment(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in str(value))
