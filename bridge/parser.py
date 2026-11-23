"""Isolated raw-frame capture and configurable message parsing."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from config import BridgeConfig


class ParserError(ValueError):
    pass


class IncompleteReadingError(ParserError):
    pass


@dataclass(frozen=True)
class RawFrame:
    text: str
    hex: str


@dataclass(frozen=True)
class ParseResult:
    payload: dict[str, Any]
    transaction_id: str
    raw_text: str
    raw_hex: str
    unit: str = ""
    is_stable: bool | None = None
    is_zero: bool | None = None
    is_overload: bool | None = None


_ALLOWED_FIELDS = {
    "product_id",
    "product",
    "item_code",
    "size",
    "grade",
    "micron",
    "production_date",
    "box_number",
    "barcode",
    "gross_weight",
    "remark",
    "transaction_id",
    "machine_id",
}


def normalize_weight(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ParserError("gross_weight must be numeric")
    if isinstance(value, Decimal):
        weight = value
    else:
        text = str(value).strip().replace(",", ".")
        text = re.sub(r"(?i)\bkg\b", "", text).strip()
        match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
        if not match:
            raise ParserError("gross_weight is not numeric")
        try:
            weight = Decimal(match.group())
        except InvalidOperation as exc:
            raise ParserError("gross_weight is not numeric") from exc
    if not weight.is_finite() or weight <= 0:
        raise ParserError("gross_weight must be a positive finite number")
    return weight


def build_payload(
    fields: dict[str, Any],
    config: BridgeConfig,
    raw: RawFrame,
    metadata: dict[str, Any] | None = None,
) -> ParseResult:
    meta = metadata or {}
    mapped = {key: value for key, value in fields.items() if key in _ALLOWED_FIELDS}
    required = ["size", "box_number", "gross_weight"]
    if config.require_barcode:
        required.append("barcode")
    missing = [key for key in required if mapped.get(key) in (None, "")]
    if missing:
        raise IncompleteReadingError("Missing required fields: " + ", ".join(missing))
    weight = normalize_weight(mapped["gross_weight"])
    mapped["gross_weight"] = format(weight, "f")
    mapped["size"] = str(mapped["size"]).strip()
    mapped["box_number"] = str(mapped["box_number"]).strip()
    if mapped.get("barcode") is not None:
        mapped["barcode"] = str(mapped["barcode"]).strip()
    transaction_id = str(
        mapped.get("transaction_id")
        or hashlib.sha256((raw.text or raw.hex).encode("utf-8")).hexdigest()[:32]
    ).strip()
    mapped["transaction_id"] = transaction_id
    mapped["machine_id"] = str(mapped.get("machine_id") or config.machine_id).strip()
    unit = str(meta.get("unit") or fields.get("unit") or fields.get("uom") or "").strip()
    return ParseResult(
        payload=mapped,
        transaction_id=transaction_id,
        raw_text=raw.text,
        raw_hex=raw.hex,
        unit=unit,
        is_stable=_as_bool(meta.get("is_stable", fields.get("is_stable"))),
        is_zero=_as_bool(meta.get("is_zero", fields.get("is_zero"))),
        is_overload=_as_bool(meta.get("is_overload", fields.get("is_overload"))),
    )


class FrameBuffer:
    def __init__(self, delimiters: tuple[bytes, ...], max_bytes: int):
        self.delimiters = delimiters
        self.max_bytes = max(max_bytes, 1)
        self.buffer = bytearray()

    def feed(self, chunk: bytes) -> list[RawFrame]:
        self.buffer.extend(chunk)
        if not self.delimiters:
            if len(self.buffer) > self.max_bytes:
                self.buffer.clear()
                raise ParserError(f"frame exceeded DEVICE_MAX_FRAME_BYTES ({self.max_bytes})")
            if not self.buffer:
                return []
            raw = bytes(self.buffer)
            self.buffer.clear()
            return [_raw_frame(raw)]
        frames: list[RawFrame] = []
        while True:
            found = self._next_delimiter()
            if found is None:
                if len(self.buffer) > self.max_bytes:
                    self.buffer.clear()
                    raise ParserError(f"frame exceeded DEVICE_MAX_FRAME_BYTES ({self.max_bytes})")
                break
            index, delimiter_length = found
            raw = bytes(self.buffer[:index])
            del self.buffer[: index + delimiter_length]
            if raw:
                frames.append(_raw_frame(raw))
        return frames

    def flush(self) -> list[RawFrame]:
        if not self.buffer:
            return []
        raw = bytes(self.buffer)
        self.buffer.clear()
        return [_raw_frame(raw)]

    def _next_delimiter(self) -> tuple[int, int] | None:
        best: tuple[int, int] | None = None
        for delimiter in self.delimiters:
            index = self.buffer.find(delimiter)
            if index >= 0 and (best is None or index < best[0]):
                best = (index, len(delimiter))
        return best


class RawCaptureParser:
    def parse(self, raw_text: str, raw_hex: str, config: BridgeConfig) -> ParseResult:
        raise ParserError("PARSER_MODE=raw: frame captured only, no mapping attempted")


class RegexParser:
    def __init__(self, pattern: str):
        self._regex = re.compile(pattern)

    def parse(self, raw_text: str, raw_hex: str, config: BridgeConfig) -> ParseResult:
        match = self._regex.search(raw_text)
        if match is None:
            raise ParserError("FRAME_REGEX did not match the raw frame")
        groups = {key: value for key, value in match.groupdict().items() if value is not None}
        if config.stable_field and config.stable_values:
            stable = str(groups.get(config.stable_field, "")).upper()
            if stable not in config.stable_values:
                raise ParserError(
                    f"unstable or unsupported reading ({config.stable_field}={stable or 'missing'})"
                )
        fields: dict[str, Any] = {}
        for group_name, value in groups.items():
            field_name = config.field_map.get(group_name, group_name)
            if field_name in _ALLOWED_FIELDS:
                fields[field_name] = value
        return build_payload(fields, config, RawFrame(raw_text, raw_hex), groups)


class SimulationParser:
    def parse(self, raw_text: str, raw_hex: str, config: BridgeConfig) -> ParseResult:
        try:
            value = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ParserError("SIMULATION frames must be JSON objects") from exc
        if not isinstance(value, dict):
            raise ParserError("SIMULATION frames must be JSON objects")
        return build_payload(value, config, RawFrame(raw_text, raw_hex), value)


def build_parser(config: BridgeConfig):
    if config.parser_mode == "raw":
        return RawCaptureParser()
    if config.parser_mode == "regex":
        return RegexParser(config.frame_regex)
    if config.parser_mode == "simulation":
        return SimulationParser()
    raise ValueError("PARSER_MODE must be raw, regex or simulation")


def _raw_frame(raw: bytes) -> RawFrame:
    return RawFrame(raw.decode("utf-8", errors="replace"), raw.hex())


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().upper()
    if text in ("1", "TRUE", "YES", "Y", "ST", "STABLE"):
        return True
    if text in ("0", "FALSE", "NO", "N", "US", "UNSTABLE"):
        return False
    return None
