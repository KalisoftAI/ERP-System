"""Persistent SQLite queue for ERP transactions."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PENDING = "PENDING"
SENT = "SENT"
DEAD = "DEAD"


class QueueStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS queue_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transaction_uid TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_retry_at TEXT,
                    last_error TEXT NOT NULL DEFAULT '',
                    last_response TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS queue_events_status_idx "
                "ON queue_events(status, next_retry_at)"
            )

    def enqueue(self, payload: dict[str, Any], transaction_uid: str) -> int | None:
        now = _now()
        with self._connect() as db:
            cursor = db.execute(
                """
                INSERT OR IGNORE INTO queue_events
                    (transaction_uid, payload_json, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(transaction_uid),
                    json.dumps(payload, default=str),
                    PENDING,
                    now,
                    now,
                ),
            )
            return int(cursor.lastrowid) if cursor.rowcount else None

    def pending(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT id, payload_json, attempts
                FROM queue_events
                WHERE status = ?
                  AND (next_retry_at IS NULL OR next_retry_at <= ?)
                ORDER BY id
                LIMIT ?
                """,
                (PENDING, _now(), limit),
            ).fetchall()
        return [
            {
                "id": int(row[0]),
                "payload": json.loads(row[1]),
                "attempts": int(row[2]),
            }
            for row in rows
        ]

    def mark_sent(self, event_id: int, response: str = "") -> None:
        with self._connect() as db:
            db.execute(
                """
                UPDATE queue_events
                SET status = ?, last_response = ?, updated_at = ?
                WHERE id = ?
                """,
                (SENT, response[:2000], _now(), event_id),
            )

    def mark_failed(
        self,
        event_id: int,
        error: str,
        attempts: int,
        max_attempts: int,
        base_delay_seconds: float,
        response: str = "",
    ) -> str:
        next_attempts = int(attempts) + 1
        status = DEAD if next_attempts >= max_attempts else PENDING
        delay = min(max(base_delay_seconds, 0.0) * (2 ** max(next_attempts - 1, 0)), 300.0)
        next_retry_at = None if status == DEAD else (
            datetime.now(timezone.utc) + timedelta(seconds=delay)
        ).isoformat()
        with self._connect() as db:
            db.execute(
                """
                UPDATE queue_events
                SET status = ?, attempts = ?, next_retry_at = ?, last_error = ?,
                    last_response = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    next_attempts,
                    next_retry_at,
                    error[:2000],
                    response[:2000],
                    _now(),
                    event_id,
                ),
            )
        return status

    def dead_letters(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT id, payload_json, attempts, last_error
                FROM queue_events
                WHERE status = ?
                ORDER BY id
                LIMIT ?
                """,
                (DEAD, limit),
            ).fetchall()
        return [
            {
                "id": int(row[0]),
                "payload": json.loads(row[1]),
                "attempts": int(row[2]),
                "error": row[3],
            }
            for row in rows
        ]

    def counts(self) -> dict[str, int]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT status, COUNT(*) FROM queue_events GROUP BY status"
            ).fetchall()
        return {str(row[0]): int(row[1]) for row in rows}

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
