"""Weighing-machine integration layer (PREPARATION ONLY).

Design contract with the future machine integration:

  * The weighing machine continues to operate independently — it handles data
    entry, weighing and printing of the Packing Slip. The ERP never controls
    the machine and never generates or triggers printing.
  * Machine data arrives as *weighing transactions* matching the standard
    internal schema (`schemas.WeighingTransactionIn`). All payloads — real,
    simulated or manual — flow through the same business pipeline
    (`services.weighing_service.ingest_weighing_transaction`).
  * Machine-specific communication is isolated in this module behind the
    `MachineAdapter` interface, so RS232, USB Serial, Ethernet/TCP-IP or a
    vendor API/SDK can each be implemented later WITHOUT touching Production
    business logic.

NO actual COM port, IP address, TCP port, baud rate, protocol or vendor API is
assumed. Real transports raise `NotImplementedError` until the machine
technician provides: machine model, communication protocol, port details and a
sample data format.

A clearly labelled SIMULATION mode exists to demonstrate the ERP receiving
workflow end-to-end; it never claims a real machine is connected.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import MachineConnection

# Supported connection types (placeholders — no live communication yet).
CONNECTION_TYPES = ("NONE", "RS232", "USB_SERIAL", "TCP_IP", "VENDOR_API", "SIMULATION")

# Operator-visible integration status.
STATUS_AWAITING = "AWAITING_CONFIGURATION"
STATUS_CONNECTED = "CONNECTED"
STATUS_DISCONNECTED = "DISCONNECTED"
CONNECTION_STATUSES = (STATUS_AWAITING, STATUS_CONNECTED, STATUS_DISCONNECTED)

# Config keys the technician is expected to fill in later, per transport.
CONFIG_PLACEHOLDERS: dict[str, tuple[str, ...]] = {
    "RS232": (
        "com_port", "baud_rate", "data_bits", "parity", "stop_bits",
        "flow_control", "delimiter",
    ),
    "USB_SERIAL": (
        "com_port", "baud_rate", "data_bits", "parity", "stop_bits",
        "flow_control", "delimiter",
    ),
    "TCP_IP": ("ip_address", "tcp_port"),
    "VENDOR_API": ("api_endpoint", "api_key_ref", "poll_interval_seconds"),
    "SIMULATION": (),
    "NONE": (),
}


def validate_config(connection_type: str, config: dict | None) -> None:
    """Validate technician-supplied transport details.

    Real transports are never marked CONNECTED by this function; they only
    become eligible for a future adapter once all required details are present.
    """
    ctype = (connection_type or "NONE").strip().upper()
    values = config or {}
    missing = [key for key in CONFIG_PLACEHOLDERS.get(ctype, ())
               if values.get(key) in (None, "", False)]
    if missing:
        raise ValueError("Missing " + ctype + " config keys: " + ", ".join(missing))
    if ctype in ("RS232", "USB_SERIAL"):
        try:
            baud = int(values["baud_rate"])
        except (TypeError, ValueError):
            raise ValueError("baud_rate must be a positive integer") from None
        if baud <= 0:
            raise ValueError("baud_rate must be a positive integer")
        if int(values["data_bits"]) not in (7, 8):
            raise ValueError("data_bits must be 7 or 8")
        if str(values["parity"]).upper() not in ("NONE", "EVEN", "ODD"):
            raise ValueError("parity must be NONE, EVEN or ODD")
        if int(values["stop_bits"]) not in (1, 2):
            raise ValueError("stop_bits must be 1 or 2")
        if str(values["flow_control"]).upper() not in ("NONE", "RTS_CTS", "XON_XOFF"):
            raise ValueError("flow_control must be NONE, RTS_CTS or XON_XOFF")
        if str(values["delimiter"]).upper() not in ("CR", "LF", "CRLF"):
            raise ValueError("delimiter must be CR, LF or CRLF")
    elif ctype == "TCP_IP":
        try:
            port = int(values["tcp_port"])
        except (TypeError, ValueError):
            raise ValueError("tcp_port must be an integer between 1 and 65535") from None
        if not 1 <= port <= 65535:
            raise ValueError("tcp_port must be an integer between 1 and 65535")


# ---------------------------------------------------------------------------
# Connection configuration (persistence helpers)
# ---------------------------------------------------------------------------
def get_or_create_connection(db: Session) -> MachineConnection:
    """Return the primary machine connection row, creating the default
    'Awaiting Configuration' placeholder on first use."""
    conn = db.scalars(select(MachineConnection).order_by(MachineConnection.id)).first()
    if conn is None:
        conn = MachineConnection(
            name="Weighing Machine 1",
            connection_type="NONE",
            status=STATUS_AWAITING,
        )
        db.add(conn)
        db.commit()
        db.refresh(conn)
    return conn


def save_connection_config(
    db: Session, *, name: str, connection_type: str, config: dict, notes: str
) -> MachineConnection:
    """Persist connection settings. NEVER opens a real connection.

    Status rules (no fake connectivity):
      * SIMULATION          -> CONNECTED (clearly labelled simulation mode)
      * any real transport  -> AWAITING_CONFIGURATION (waiting for the
                               technician's details + a real adapter)
    """
    ctype = (connection_type or "NONE").strip().upper()
    if ctype not in CONNECTION_TYPES:
        raise ValueError(
            "connection_type must be one of: " + ", ".join(CONNECTION_TYPES)
        )
    validate_config(ctype, config)
    conn = get_or_create_connection(db)
    conn.name = (name or conn.name or "Weighing Machine 1").strip()
    conn.connection_type = ctype
    conn.config_json = json.dumps(config or {})
    conn.notes = notes or ""
    conn.status = STATUS_CONNECTED if ctype == "SIMULATION" else STATUS_AWAITING
    conn.last_error = ""
    db.commit()
    db.refresh(conn)
    return conn


def serialize_connection(conn: MachineConnection) -> dict[str, Any]:
    try:
        config = json.loads(conn.config_json) if conn.config_json else {}
    except (ValueError, TypeError):
        config = {}
    return {
        "id": conn.id,
        "name": conn.name,
        "connection_type": conn.connection_type,
        "status": conn.status,
        "config": config,
        "config_placeholders": list(CONFIG_PLACEHOLDERS.get(conn.connection_type, ())),
        "notes": conn.notes or "",
        "last_seen_at": conn.last_seen_at,
        "last_error": conn.last_error or "",
        "updated_at": conn.updated_at,
        "connection_types": list(CONNECTION_TYPES),
        "statuses": list(CONNECTION_STATUSES),
    }


# ---------------------------------------------------------------------------
# Transport adapter interface (pluggable; real adapters are placeholders)
# ---------------------------------------------------------------------------
class MachineAdapter:
    """Interface for a machine transport. One implementation per
    connection_type. The Production module never talks to adapters directly
    for business rules — adapters only *receive* raw transactions."""

    def __init__(self, connection: MachineConnection):
        self.connection = connection

    def connect(self) -> None:
        raise NotImplementedError(self._pending_message())

    def poll(self) -> None:
        raise NotImplementedError(self._pending_message())

    def disconnect(self) -> None:  # safe no-op for placeholders
        return None

    def _pending_message(self) -> str:
        return (
            f"{self.connection.connection_type} adapter is not implemented yet. "
            "Waiting for the machine technician to provide the machine model, "
            "communication protocol, port details and a sample data format."
        )


class SerialAdapter(MachineAdapter):
    """RS232 / USB Serial placeholder (COM port, baud rate, … from technician)."""


class TcpIpAdapter(MachineAdapter):
    """Ethernet / TCP-IP placeholder (IP address + port from technician)."""


class VendorApiAdapter(MachineAdapter):
    """Vendor API/SDK placeholder (endpoint + credentials from technician)."""


class SimulationAdapter(MachineAdapter):
    """Clearly labelled simulation — demonstrates the receiving workflow
    without claiming a real machine is connected."""

    def connect(self) -> None:
        return None  # simulation is always 'connected'

    def poll(self) -> None:
        return None


_ADAPTERS = {
    "RS232": SerialAdapter,
    "USB_SERIAL": SerialAdapter,
    "TCP_IP": TcpIpAdapter,
    "VENDOR_API": VendorApiAdapter,
    "SIMULATION": SimulationAdapter,
}


def get_adapter(connection: MachineConnection) -> MachineAdapter:
    """Factory: pick the adapter for the configured connection type."""
    cls = _ADAPTERS.get((connection.connection_type or "NONE").upper(), MachineAdapter)
    return cls(connection)


def mark_seen(db: Session, conn: MachineConnection) -> None:
    """Update last_seen_at when a transaction arrives through any channel."""
    conn.last_seen_at = datetime.utcnow()
    db.commit()


# ---------------------------------------------------------------------------
# Simulation helpers
# ---------------------------------------------------------------------------
def build_simulation_payload(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """A packing-slip-shaped sample transaction for SIMULATION mode.

    Values mirror the reference packing slip (Product / Box No / Grade / Size /
    Micron / Date / Gross Weight / Barcode / Remark) and are always labelled
    as simulation data.
    """
    payload: dict[str, Any] = {
        "product": "TEST",
        "size": "400mm",
        "grade": "Higher",
        "micron": "4500",
        "production_date": date.today().isoformat(),
        "box_number": "1",
        "barcode": f"SIM-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}",
        # The reference slip prints 1.000 kg (a machine test print); the demo
        # uses a realistic box gross so Net = Gross - Tare stays positive.
        "gross_weight": 26.5,
        "remark": "SIMULATION — demonstrates the receiving workflow; no real machine connected",
        "machine_id": "SIMULATOR",
    }
    payload.update(overrides or {})
    return payload
