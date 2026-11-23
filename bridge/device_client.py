"""USR gateway TCP clients and local simulation source."""
from __future__ import annotations

import json
import socket
import time
from uuid import uuid4

from config import BridgeConfig


class DeviceError(Exception):
    pass


class TcpClient:
    def __init__(self, config: BridgeConfig):
        self.config = config
        self.status = "DISCONNECTED"
        self.error = ""
        self.error_code = ""
        self.connection_id = ""
        self.peer = f"{config.device_host}:{config.device_port or 0}"
        self.connected_at: float | None = None
        self.last_connect_ms = 0
        self.connected_duration_ms = 0
        self._socket: socket.socket | None = None

    def connect(self) -> None:
        self.close()
        started = time.monotonic()
        self.connection_id = uuid4().hex[:12]
        self.status = "CONNECTING"
        self.error = ""
        self.error_code = ""
        try:
            self._socket = socket.create_connection(
                (self.config.device_host, int(self.config.device_port or 0)),
                timeout=self.config.device_socket_timeout_seconds,
            )
            self._socket.settimeout(self.config.device_socket_timeout_seconds)
        except OSError as exc:
            self.last_connect_ms = int((time.monotonic() - started) * 1000)
            self.status = "DISCONNECTED"
            self.error = str(exc)
            self.error_code = str(getattr(exc, "errno", "") or type(exc).__name__)
            raise
        self.last_connect_ms = int((time.monotonic() - started) * 1000)
        self.connected_at = time.monotonic()
        self.status = "CONNECTED_NO_DATA"

    def read_chunks(self):
        if self._socket is None:
            raise DeviceError("device is not connected")
        while True:
            try:
                chunk = self._socket.recv(self.config.device_read_chunk_size)
            except socket.timeout:
                yield b""
                continue
            except OSError as exc:
                self.status = "DEVICE_ERROR"
                self.error = str(exc)
                self.error_code = str(getattr(exc, "errno", "") or type(exc).__name__)
                raise DeviceError(str(exc)) from exc
            if not chunk:
                self.status = "DISCONNECTED"
                self.error = "connection closed by device"
                self.error_code = "EOF"
                raise DeviceError(self.error)
            yield chunk

    def close(self) -> None:
        if self.connected_at is not None:
            self.connected_duration_ms = int((time.monotonic() - self.connected_at) * 1000)
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None
        self.connected_at = None
        self.status = "DISCONNECTED"


class TcpServer:
    def __init__(self, config: BridgeConfig):
        self.config = config
        self.status = "LISTENING"
        self.error = ""
        self.error_code = ""
        self.connection_id = ""
        self.peer = f"{config.device_bind_host}:{config.device_bind_port or 0}"
        self.connected_at: float | None = None
        self.last_connect_ms = 0
        self.connected_duration_ms = 0
        self._server: socket.socket | None = None
        self._connection: socket.socket | None = None

    def connect(self) -> None:
        self.close()
        started = time.monotonic()
        self.connection_id = uuid4().hex[:12]
        self.status = "CONNECTING"
        self.error = ""
        self.error_code = ""
        try:
            self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server.bind((self.config.device_bind_host, int(self.config.device_bind_port or 0)))
            self._server.listen(1)
        except OSError as exc:
            self.last_connect_ms = int((time.monotonic() - started) * 1000)
            self.status = "DEVICE_ERROR"
            self.error = str(exc)
            self.error_code = str(getattr(exc, "errno", "") or type(exc).__name__)
            raise
        self.last_connect_ms = int((time.monotonic() - started) * 1000)
        self.status = "LISTENING"

    def read_chunks(self):
        if self._server is None:
            raise DeviceError("device server is not started")
        while True:
            if self._connection is None:
                self._connection, address = self._server.accept()
                self._connection.settimeout(self.config.device_socket_timeout_seconds)
                self.peer = f"{address[0]}:{address[1]}"
                self.connection_id = uuid4().hex[:12]
                self.connected_at = time.monotonic()
                self.status = "CONNECTED_NO_DATA"
                yield b""
            try:
                chunk = self._connection.recv(self.config.device_read_chunk_size)
            except socket.timeout:
                yield b""
                continue
            except OSError as exc:
                self.status = "DEVICE_ERROR"
                self.error = str(exc)
                self.error_code = str(getattr(exc, "errno", "") or type(exc).__name__)
                self._connection.close()
                self._connection = None
                raise DeviceError(str(exc)) from exc
            if not chunk:
                self.status = "DISCONNECTED"
                self.error = "connection closed by device"
                self.error_code = "EOF"
                self._connection.close()
                self._connection = None
                raise DeviceError(self.error)
            yield chunk

    def close(self) -> None:
        if self.connected_at is not None:
            self.connected_duration_ms = int((time.monotonic() - self.connected_at) * 1000)
        if self._connection is not None:
            try:
                self._connection.close()
            except OSError:
                pass
            self._connection = None
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
            self._server = None
        self.connected_at = None
        self.status = "DISCONNECTED"


class Simulator:
    def __init__(self, config: BridgeConfig):
        self.config = config
        self.status = "CONNECTED_NO_DATA"
        self.error = ""
        self.error_code = ""
        self.connection_id = uuid4().hex[:12]
        self.peer = "simulation"
        self.connected_at: float | None = None
        self.last_connect_ms = 0
        self.connected_duration_ms = 0

    def connect(self) -> None:
        self.status = "CONNECTED_NO_DATA"
        self.error = ""
        self.error_code = ""
        self.connected_at = time.monotonic()

    def read_chunks(self):
        while True:
            token = uuid4().hex[:12]
            frame = {
                "product": "TEST",
                "size": "400mm",
                "box_number": token,
                "barcode": f"SIM-{token}",
                "gross_weight": 26.5,
                "transaction_id": f"SIM-{token}",
                "machine_id": "SIMULATOR",
            }
            yield json.dumps(frame).encode("utf-8")
            time.sleep(max(self.config.simulation_interval_seconds, 0.1))

    def close(self) -> None:
        if self.connected_at is not None:
            self.connected_duration_ms = int((time.monotonic() - self.connected_at) * 1000)
        self.connected_at = None
        self.status = "DISCONNECTED"


def device_config_summary(config: BridgeConfig) -> dict:
    summary = {
        "mode": config.device_mode,
        "device_id": config.device_id,
        "device_mac": config.device_mac,
        "host": config.device_host,
        "port": config.device_port or 0,
        "serial": {
            "baudrate": config.device_baudrate or "UNSET",
            "bytesize": config.device_bytesize or "UNSET",
            "parity": config.device_parity or "UNSET",
            "stopbits": config.device_stopbits or "UNSET",
            "flow_control": config.device_flow_control or "UNSET",
            "delimiter": config.device_serial_delimiter or "UNSET",
            "timeout_seconds": config.device_timeout_seconds,
        },
        "reconnect": {
            "min_seconds": config.device_reconnect_min_seconds,
            "max_seconds": config.device_reconnect_max_seconds,
        },
        "stale_after_seconds": config.device_stale_after_seconds,
        "max_frame_bytes": config.frame_max_bytes,
        "frame_delimiters": [_delimiter_name(item) for item in config.frame_delimiters],
    }
    if config.device_mode == "tcp_server":
        summary["bind_host"] = config.device_bind_host
        summary["bind_port"] = config.device_bind_port or 0
    return summary


def create_device_client(config: BridgeConfig):
    if config.device_mode == "tcp_client":
        return TcpClient(config)
    if config.device_mode == "tcp_server":
        return TcpServer(config)
    if config.device_mode == "simulation":
        return Simulator(config)
    raise ValueError("DEVICE_MODE must be tcp_client, tcp_server or simulation")


def _delimiter_name(value: bytes) -> str:
    return {
        b"\r\n": "CRLF",
        b"\n": "LF",
        b"\r": "CR",
        b"\x00": "NUL",
    }.get(value, value.hex())
