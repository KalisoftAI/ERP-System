"""Bridge configuration loaded from bridge/.env and repository .env."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BRIDGE_DIR = Path(__file__).resolve().parent
REPO_DIR = BRIDGE_DIR.parent

load_dotenv(BRIDGE_DIR / ".env")
load_dotenv(REPO_DIR / ".env")


def _env(*names: str) -> tuple[str, str]:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return name, value
    return names[0], ""


def _text(*names: str, default: str = "") -> str:
    _, value = _env(*names)
    return value or default


def _bool(*names: str, default: bool = False) -> bool:
    _, value = _env(*names)
    if not value:
        return default
    return value.lower() in ("1", "true", "yes", "on")


def _int(*names: str, errors: list[str], default: int | None = None) -> int | None:
    name, value = _env(*names)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        errors.append(f"{name} must be an integer")
        return default


def _float(*names: str, errors: list[str], default: float | None = None) -> float | None:
    name, value = _env(*names)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        errors.append(f"{name} must be a number")
        return default


def _csv(*names: str, default: str = "") -> tuple[str, ...]:
    return tuple(item.strip() for item in _text(*names, default=default).split(",") if item.strip())


def _json_object(*names: str, errors: list[str]) -> dict[str, str]:
    name, value = _env(*names)
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        errors.append(f"{name} must be a JSON object")
        return {}
    if not isinstance(parsed, dict):
        errors.append(f"{name} must be a JSON object")
        return {}
    return {str(key): str(item) for key, item in parsed.items()}


def _path(*names: str, default: str, errors: list[str]) -> Path:
    _, value = _env(*names)
    path = Path(value) if value else Path(default)
    if not path.is_absolute():
        path = REPO_DIR / path
    return path


def _delimiters(errors: list[str]) -> tuple[bytes, ...]:
    known = {
        "CRLF": b"\r\n",
        "LF": b"\n",
        "CR": b"\r",
        "NUL": b"\x00",
    }
    names = _csv("DEVICE_FRAME_DELIMITERS") or _csv("DEVICE_SERIAL_DELIMITER")
    values: list[bytes] = []
    for name in names:
        key = name.upper()
        if key in known and known[key] not in values:
            values.append(known[key])
        elif key not in known:
            errors.append(f"DEVICE_FRAME_DELIMITERS contains unsupported delimiter {name}")
    return tuple(sorted(values, key=len, reverse=True))


@dataclass(frozen=True)
class BridgeConfig:
    erp_base_url: str
    erp_login_path: str
    erp_status_path: str
    erp_transactions_path: str
    erp_frame_path: str
    erp_heartbeat_path: str
    erp_telemetry_enabled: bool
    erp_frame_report_mode: str
    erp_token: str
    erp_username: str
    erp_password: str
    erp_timeout_seconds: float
    device_mode: str
    device_id: str
    device_mac: str
    device_host: str
    device_port: int | None
    device_bind_host: str
    device_bind_port: int | None
    device_baudrate: str
    device_bytesize: str
    device_parity: str
    device_stopbits: str
    device_flow_control: str
    device_serial_delimiter: str
    device_timeout_seconds: float
    device_reconnect_min_seconds: float
    device_reconnect_max_seconds: float
    device_stale_after_seconds: float
    device_socket_timeout_seconds: float
    device_read_chunk_size: int
    frame_delimiters: tuple[bytes, ...]
    frame_max_bytes: int
    parser_mode: str
    frame_regex: str
    field_map: dict[str, str]
    stable_field: str
    stable_values: tuple[str, ...]
    require_barcode: bool
    machine_id: str
    queue_db_path: Path
    dry_run: bool
    max_attempts: int
    retry_base_delay_seconds: float
    queue_batch_size: int
    erp_status_interval_seconds: float
    log_dir: Path
    log_file_name: str
    log_max_bytes: int
    log_backup_count: int
    log_level: str
    weighing_environment: str
    raw_log_enabled: bool
    raw_log_max_bytes: int
    gcs_bucket: str
    gcs_log_prefix: str
    gcs_upload_enabled: bool
    gcs_upload_interval_seconds: float
    gcs_credentials_path: str
    simulation_interval_seconds: float
    status_refresh_seconds: float
    diagnostics_poll_interval_seconds: float
    config_errors: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "BridgeConfig":
        errors: list[str] = []
        return cls(
            erp_base_url=_text("ERP_BASE_URL", default="http://localhost:8000").rstrip("/"),
            erp_login_path=_text("ERP_LOGIN_PATH", default="/auth/login"),
            erp_status_path=_text("ERP_STATUS_PATH", default="/production/machine/status"),
            erp_transactions_path=_text(
                "ERP_TRANSACTIONS_PATH", default="/production/machine/transactions"
            ),
            erp_frame_path=_text("ERP_FRAME_PATH", default="/production/machine/frames"),
            erp_heartbeat_path=_text("ERP_HEARTBEAT_PATH", default="/production/machine/heartbeat"),
            erp_telemetry_enabled=_bool("ERP_TELEMETRY_ENABLED", default=True),
            erp_frame_report_mode=_text("ERP_FRAME_REPORT_MODE", default="all").lower(),
            erp_token=_text("ERP_TOKEN"),
            erp_username=_text("ERP_USERNAME"),
            erp_password=_text("ERP_PASSWORD"),
            erp_timeout_seconds=_float("ERP_TIMEOUT_SECONDS", errors=errors, default=10.0) or 10.0,
            device_mode=_text("DEVICE_MODE", default="tcp_client").lower(),
            device_id=_text("DEVICE_ID", default="USR-TCP232-302"),
            device_mac=_text("DEVICE_MAC", default="D4:AD:20:DB:E8:C9").upper(),
            device_host=_text("DEVICE_HOST", default="192.168.0.7"),
            device_port=_int("DEVICE_PORT", errors=errors),
            device_bind_host=_text("DEVICE_BIND_HOST", default="0.0.0.0"),
            device_bind_port=_int("DEVICE_BIND_PORT", errors=errors),
            device_baudrate=_text("DEVICE_BAUDRATE", "DEVICE_SERIAL_BAUD_RATE").upper(),
            device_bytesize=_text("DEVICE_BYTESIZE", "DEVICE_SERIAL_DATA_BITS").upper(),
            device_parity=_text("DEVICE_PARITY", "DEVICE_SERIAL_PARITY").upper(),
            device_stopbits=_text("DEVICE_STOPBITS", "DEVICE_SERIAL_STOP_BITS").upper(),
            device_flow_control=_text("DEVICE_FLOW_CONTROL", "DEVICE_SERIAL_FLOW_CONTROL").upper(),
            device_serial_delimiter=_text("DEVICE_SERIAL_DELIMITER").upper(),
            device_timeout_seconds=_float(
                "DEVICE_TIMEOUT_SECONDS", errors=errors, default=2.0
            ) or 2.0,
            device_reconnect_min_seconds=_float(
                "DEVICE_RECONNECT_MIN_SECONDS",
                "DEVICE_RECONNECT_DELAY_SECONDS",
                errors=errors,
                default=1.0,
            )
            or 1.0,
            device_reconnect_max_seconds=_float(
                "DEVICE_RECONNECT_MAX_SECONDS", errors=errors, default=30.0
            )
            or 30.0,
            device_stale_after_seconds=_float(
                "DEVICE_STALE_AFTER_SECONDS", errors=errors, default=5.0
            )
            or 5.0,
            device_socket_timeout_seconds=_float(
                "DEVICE_SOCKET_TIMEOUT_SECONDS", errors=errors, default=1.0
            )
            or 1.0,
            device_read_chunk_size=_int("DEVICE_READ_CHUNK_SIZE", errors=errors, default=4096) or 4096,
            frame_delimiters=_delimiters(errors),
            frame_max_bytes=_int(
                "DEVICE_MAX_FRAME_BYTES", "FRAME_MAX_BYTES", errors=errors, default=512
            )
            or 512,
            parser_mode=_text("PARSER_MODE", default="raw").lower(),
            frame_regex=_text("FRAME_REGEX"),
            field_map=_json_object("FIELD_MAP", errors=errors),
            stable_field=_text("STABLE_FIELD"),
            stable_values=tuple(value.upper() for value in _csv("STABLE_VALUES")),
            require_barcode=_bool("REQUIRE_BARCODE", default=False),
            machine_id=_text("MACHINE_ID", default="BS44"),
            queue_db_path=_path("QUEUE_DB_PATH", default="bridge/data/queue.sqlite3", errors=errors),
            dry_run=_bool("DRY_RUN", default=True),
            max_attempts=_int("MAX_ATTEMPTS", errors=errors, default=8) or 8,
            retry_base_delay_seconds=_float(
                "RETRY_BASE_DELAY_SECONDS", errors=errors, default=5.0
            )
            or 5.0,
            queue_batch_size=_int("QUEUE_BATCH_SIZE", errors=errors, default=50) or 50,
            erp_status_interval_seconds=_float(
                "ERP_STATUS_INTERVAL_SECONDS", errors=errors, default=60.0
            )
            or 60.0,
            log_dir=_path(
                "LOG_DIR", default="kalisoftai-datahub/Kalika_inventory/Logs", errors=errors
            ),
            log_file_name=_text("LOG_FILE_NAME", default="bridge.jsonl"),
            log_max_bytes=_int("LOG_MAX_BYTES", errors=errors, default=5242880) or 5242880,
            log_backup_count=_int("LOG_BACKUP_COUNT", errors=errors, default=5) or 5,
            log_level=_text("WEIGHING_LOG_LEVEL", "LOG_LEVEL", default="INFO").upper(),
            weighing_environment=_text("WEIGHING_ENVIRONMENT", default="local"),
            raw_log_enabled=_bool("WEIGHING_RAW_LOG_ENABLED", default=False),
            raw_log_max_bytes=_int("WEIGHING_RAW_LOG_MAX_BYTES", errors=errors, default=64) or 64,
            gcs_bucket=_text("GCS_BUCKET", default="kalisoftai-datahub"),
            gcs_log_prefix=_text(
                "GCS_LOG_PREFIX", default="Kalika_inventory/Logs"
            ).strip("/"),
            gcs_upload_enabled=_bool("GCS_UPLOAD_ENABLED", default=False),
            gcs_upload_interval_seconds=_float(
                "GCS_UPLOAD_INTERVAL_SECONDS", errors=errors, default=60.0
            )
            or 60.0,
            gcs_credentials_path=_text("GOOGLE_APPLICATION_CREDENTIALS"),
            simulation_interval_seconds=_float(
                "SIMULATION_INTERVAL_SECONDS", errors=errors, default=2.0
            )
            or 2.0,
            status_refresh_seconds=_float("STATUS_REFRESH_SECONDS", errors=errors, default=2.0)
            or 2.0,
            diagnostics_poll_interval_seconds=_float(
                "DIAGNOSTICS_POLL_INTERVAL_SECONDS",
                "POLL_INTERVAL_SECONDS",
                errors=errors,
                default=2.0,
            )
            or 2.0,
            config_errors=tuple(errors),
        )

    def validate(self) -> None:
        errors = list(self.config_errors)
        if self.device_mode not in ("tcp_client", "tcp_server", "simulation"):
            errors.append("DEVICE_MODE must be tcp_client, tcp_server or simulation")
        if self.parser_mode not in ("raw", "regex", "simulation"):
            errors.append("PARSER_MODE must be raw, regex or simulation")
        if self.erp_frame_report_mode not in ("all", "parsed", "errors", "none"):
            errors.append("ERP_FRAME_REPORT_MODE must be all, parsed, errors or none")
        if self.device_mode == "tcp_client":
            errors.extend(_port_errors("DEVICE_PORT", self.device_port, required=True))
        if self.device_mode == "tcp_server":
            errors.extend(_port_errors("DEVICE_BIND_PORT", self.device_bind_port, required=True))
        if self.parser_mode == "regex" and not self.frame_regex:
            errors.append("FRAME_REGEX is required when PARSER_MODE=regex")
        if self.frame_max_bytes <= 0:
            errors.append("DEVICE_MAX_FRAME_BYTES must be greater than zero")
        if self.raw_log_max_bytes < 0:
            errors.append("WEIGHING_RAW_LOG_MAX_BYTES must be zero or greater")
        if self.device_reconnect_min_seconds <= 0:
            errors.append("DEVICE_RECONNECT_MIN_SECONDS must be greater than zero")
        if self.device_reconnect_max_seconds < self.device_reconnect_min_seconds:
            errors.append("DEVICE_RECONNECT_MAX_SECONDS must be >= DEVICE_RECONNECT_MIN_SECONDS")
        if self.device_stale_after_seconds <= 0:
            errors.append("DEVICE_STALE_AFTER_SECONDS must be greater than zero")
        if self.diagnostics_poll_interval_seconds <= 0:
            errors.append("DIAGNOSTICS_POLL_INTERVAL_SECONDS must be greater than zero")
        errors.extend(_serial_errors(self))
        if not self.erp_token and not self.dry_run:
            if not self.erp_username or not self.erp_password:
                errors.append("ERP_TOKEN or ERP_USERNAME/ERP_PASSWORD is required")
        if errors:
            raise ValueError("; ".join(dict.fromkeys(errors)))


def _port_errors(name: str, value: int | None, *, required: bool) -> list[str]:
    if value is None:
        return [f"{name} is required"] if required else []
    if not 1 <= value <= 65535:
        return [f"{name} must be an integer between 1 and 65535"]
    return []


def _serial_errors(config: BridgeConfig) -> list[str]:
    errors: list[str] = []
    if config.device_baudrate:
        try:
            if int(config.device_baudrate) <= 0:
                raise ValueError
        except ValueError:
            errors.append("DEVICE_BAUDRATE must be a positive integer")
    if config.device_bytesize:
        try:
            if int(config.device_bytesize) not in (5, 6, 7, 8, 9):
                raise ValueError
        except ValueError:
            errors.append("DEVICE_BYTESIZE must be between 5 and 9")
    parity = config.device_parity.replace("NONE", "N").replace("EVEN", "E").replace("ODD", "O")
    if parity and parity not in ("N", "E", "O", "M", "S"):
        errors.append("DEVICE_PARITY must be NONE, EVEN, ODD, N, E, O, M or S")
    if config.device_stopbits and config.device_stopbits not in ("1", "1.5", "2"):
        errors.append("DEVICE_STOPBITS must be 1, 1.5 or 2")
    flow = config.device_flow_control.replace("-", "_")
    if flow and flow not in ("NONE", "RTS_CTS", "XON_XOFF"):
        errors.append("DEVICE_FLOW_CONTROL must be NONE, RTS_CTS or XON_XOFF")
    return errors
