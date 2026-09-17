"""Flexible CSV/Excel table reader for user-facing bulk imports.

Headers are normalized (lowercase, non-alphanumeric stripped) and matched
through per-import alias maps, so column order, capitalization, spaces,
underscores and minor naming differences never matter. Unknown columns are
ignored; missing optional columns are simply absent from the mapped rows.

Cell normalization reuses the existing migration parser helpers
(`norm_text` / `norm_num`) so behaviour matches the Excel migration path.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from io import BytesIO
from typing import Any, Iterable

import pandas as pd

from .excel_parser_v2 import norm_num, norm_text

_HEADER_RE = re.compile(r"[^a-z0-9]+")


def normalize_header(h: Any) -> str:
    """'Item Code' / 'item_code' / 'ITEM-CODE' -> 'itemcode'; '% COMP' -> 'comp'."""
    return _HEADER_RE.sub("", str(h or "").strip().lower())


def read_table(filename: str, content: bytes) -> tuple[list[str], list[list[Any]]]:
    """Read a CSV or Excel upload into (headers, rows). Raises ValueError on
    unsupported/unreadable files."""
    name = (filename or "").lower()
    try:
        if name.endswith(".csv"):
            df = pd.read_csv(BytesIO(content), dtype=object, keep_default_na=False)
        elif name.endswith((".xlsx", ".xls")):
            df = pd.read_excel(BytesIO(content), dtype=object, keep_default_na=False)
        else:
            # Sniff: try Excel first (zip magic), then CSV.
            if content[:2] == b"PK":
                df = pd.read_excel(BytesIO(content), dtype=object, keep_default_na=False)
            else:
                df = pd.read_csv(BytesIO(content), dtype=object, keep_default_na=False)
    except Exception as exc:  # noqa: BLE001 - surface a clean message to the user
        raise ValueError(f"Could not read file '{filename}': {exc}") from exc
    headers = [str(h) for h in df.columns]
    rows = df.values.tolist()
    return headers, rows


def build_column_map(headers: Iterable[str], aliases: dict[str, list[str]]) -> dict[int, str]:
    """Map column index -> canonical field using normalized alias lookup.

    `aliases` maps canonical field -> list of acceptable header names (already
    in any human-readable form; they are normalized here).
    """
    norm_aliases: dict[str, str] = {}
    for canonical, names in aliases.items():
        for n in names:
            norm_aliases.setdefault(normalize_header(n), canonical)
    colmap: dict[int, str] = {}
    for idx, h in enumerate(headers):
        canon = norm_aliases.get(normalize_header(h))
        if canon and canon not in colmap.values():
            colmap[idx] = canon
    return colmap


def row_to_dict(colmap: dict[int, str], row: list[Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for idx, canon in colmap.items():
        if idx < len(row):
            out[canon] = row[idx]
    return out


def cell_text(v: Any) -> str:
    return norm_text(v)


def cell_num(v: Any) -> float | None:
    return norm_num(v)


def is_blank_row(mapped: dict[str, Any]) -> bool:
    return all(norm_text(v) == "" for v in mapped.values())


def parse_date_value(v: Any) -> date | None:
    """Parse common date representations (ISO, DD-MM-YYYY, DD/MM/YYYY,
    Excel serials, real datetimes). Returns None when unparseable."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)):  # Excel serial day number
        if 20000 <= float(v) <= 80000:
            return date(1899, 12, 30) + timedelta(days=int(v))
        return None
    s = str(v).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d.%m.%Y",
                "%m/%d/%Y", "%d-%b-%Y", "%d %b %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        f = float(s)
        if 20000 <= f <= 80000:
            return date(1899, 12, 30) + timedelta(days=int(f))
    except ValueError:
        pass
    return None
