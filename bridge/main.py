"""Windows bridge entry point for barcode and weighing data."""
from __future__ import annotations

import json
import os
import random
import sys
import time
from datetime import datetime, timezone

from config import BridgeConfig
from device_client import create_device_client, device_config_summary
from erp_client import ErpClient
from logging_setup import configure_logging
from parser import FrameBuffer, ParserError, build_parser
from queue_store import QueueStore


class BridgeApp:
    def __init__(self):
        self.config = BridgeConfig.from_env()
        self.logger = configure_logging(self.config)
        try:
            self.config.validate()
        except ValueError as exc:
            self.logger.event(
                "device.config.invalid",
                component="weighing.service",
                field="",
                reason=str(exc),
                level=40,
            )
            self.logger.stop_uploader()
            raise
        self.logger.event(
            "device.config.loaded",
            component="weighing.service",
            config=device_config_summary(self.config),
            parser_mode=self.config.parser_mode,
            dry_run=self.config.dry_run,
            queue_path=str(self.config.queue_db_path),
            log_dir=str(self.logger.log_dir),
            gcs_upload_enabled=self.config.gcs_upload_enabled,
            gcs_path=f"gs://{self.config.gcs_bucket}/{self.logger.uploader.object_prefix()}",
        )
        self.queue = QueueStore(self.config.queue_db_path)
        self.parser = build_parser(self.config)
        self.erp = ErpClient(self.config, self.logger)
        self.device = None
        self.state = {
            "device": "DISCONNECTED",
            "erp": "NOT_CHECKED",
            "barcode": "",
            "weight": "",
            "error": "",
            "transaction_id": "",
        }
        self.health = "DISCONNECTED"
        self.sequence = 0
        self.bytes_received = 0
        self.connection_id = ""
        self.connection_started: float | None = None
        self.last_byte_at = ""
        self.last_valid_reading_at = ""
        self.last_reading_monotonic: float | None = None
        self.last_frame_monotonic: float | None = None
        self.stale_logged = False
        self.attempt = 0
        self.connect_phase = False
        self._last_display = 0.0
        self._last_status_check = 0.0
        self._last_poll_log = 0.0
        self.frame_counts = {"received": 0, "parsed": 0, "failed": 0}
        self.reading_counts = {"captured": 0, "rejected": 0}
        self.error_counts: dict[str, int] = {}

    def run(self) -> None:
        self.logger.start_uploader()
        self.logger.event(
            "device.worker.started",
            component="weighing.service",
            process_id=os.getpid(),
        )
        try:
            while True:
                buffer = FrameBuffer(self.config.frame_delimiters, self.config.frame_max_bytes)
                connected_duration_ms = 0
                try:
                    self.device = create_device_client(self.config)
                    self.connect_phase = True
                    self.logger.event(
                        "device.connect.started",
                        component="weighing.tcp_client",
                        host=self.config.device_host,
                        port=self.config.device_port or 0,
                        attempt=self.attempt + 1,
                    )
                    self.device.connect()
                    self.connect_phase = False
                    self.connection_id = getattr(self.device, "connection_id", "")
                    self.logger.set_context(connection_id=self.connection_id)
                    self.connection_started = time.monotonic()
                    self.attempt = 0
                    self.stale_logged = False
                    self.last_frame_monotonic = None
                    self.last_reading_monotonic = None
                    self._set_health(getattr(self.device, "status", "CONNECTED_NO_DATA"))
                    self.logger.event(
                        "device.connect.succeeded",
                        component="weighing.tcp_client",
                        connection_id=self.connection_id,
                        peer=getattr(self.device, "peer", ""),
                        duration_ms=getattr(self.device, "last_connect_ms", 0),
                        attempt=1,
                    )
                    self._send_heartbeat()
                    for chunk in self.device.read_chunks():
                        if not chunk:
                            self._check_stale()
                            self._maybe_check_erp_status()
                            self._maybe_emit_poll_summary()
                            self._display(force=False)
                            continue
                        self._handle_chunk(chunk, buffer)
                        self._process_queue()
                        self._maybe_check_erp_status()
                        self._maybe_emit_poll_summary()
                        self._display(force=False)
                    for frame in buffer.flush():
                        self._handle_frame(frame)
                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    self._handle_error(exc)
                finally:
                    if self.connection_started is not None:
                        connected_duration_ms = int((time.monotonic() - self.connection_started) * 1000)
                    self.logger.event(
                        "device.connection.closed",
                        component="weighing.tcp_client",
                        connection_id=self.connection_id,
                        reason=getattr(self.device, "error", "") or "connection ended",
                        duration_ms=connected_duration_ms,
                    )
                    if self.device is not None:
                        try:
                            self.device.close()
                        except Exception:
                            pass
                        self.device = None
                    self.connect_phase = False
                    self._set_health("DISCONNECTED")
                    self._maybe_emit_poll_summary(force=True)
                    delay = self._reconnect_delay()
                    self.logger.event(
                        "device.reconnect.scheduled",
                        component="weighing.tcp_client",
                        delay_seconds=delay,
                        attempt=self.attempt + 1,
                    )
                    self._display(force=True)
                    time.sleep(delay)
                    self.attempt += 1
        except KeyboardInterrupt:
            self.logger.event(
                "device.worker.stopped",
                component="weighing.service",
                reason="keyboard interrupt",
            )
        finally:
            self.logger.event(
                "bridge.stopped",
                component="weighing.service",
                queue_counts=self.queue.counts(),
                last_barcode=self.state["barcode"],
                last_weight=self.state["weight"],
            )
            self.logger.stop_uploader()
            self._display(force=True)
            print()

    def _handle_chunk(self, chunk: bytes, buffer: FrameBuffer) -> None:
        self.bytes_received += len(chunk)
        self.last_byte_at = _utc_now()
        self.last_frame_monotonic = time.monotonic()
        self.logger.event(
            "device.bytes.received",
            component="weighing.tcp_client",
            byte_count=len(chunk),
            cumulative_bytes=self.bytes_received,
        )
        try:
            frames = buffer.feed(chunk)
        except ParserError as exc:
            self.frame_counts["failed"] += 1
            self._record_error("frame", str(exc))
            self.logger.event(
                "device.frame.invalid",
                component="weighing.framing",
                reason=str(exc),
                sequence=self.sequence + 1,
                error_code="FRAME_TOO_LARGE",
            )
            self._set_health("RECEIVING_UNPARSED")
            return
        if not frames:
            self._set_health("RECEIVING_UNPARSED")
            return
        self.frame_counts["received"] += len(frames)
        for frame in frames:
            self._handle_frame(frame)

    def _handle_frame(self, frame) -> None:
        self.sequence += 1
        self.logger.event(
            "device.frame.completed",
            component="weighing.framing",
            frame_length=len(frame.text),
            sequence=self.sequence,
            **self._raw_fields(frame),
        )
        try:
            result = self.parser.parse(frame.text, frame.hex, self.config)
        except ParserError as exc:
            self.frame_counts["failed"] += 1
            self.state["error"] = str(exc)
            self._record_error("parse", str(exc))
            self.logger.event(
                "device.parse.failed",
                component="weighing.parser",
                reason=str(exc),
                sequence=self.sequence,
                error_code=type(exc).__name__,
                **self._raw_fields(frame),
                level=30,
            )
            self._set_health("RECEIVING_UNPARSED")
            api_status = "RAW" if self.config.parser_mode == "raw" else "ERROR"
            self._send_frame_event(frame, api_status, error=str(exc))
            self._display(force=True)
            return
        payload = result.payload
        self.state["barcode"] = str(payload.get("barcode", ""))
        self.state["weight"] = str(payload.get("gross_weight", ""))
        self.state["transaction_id"] = result.transaction_id
        self.state["error"] = ""
        self.last_valid_reading_at = _utc_now()
        self.last_reading_monotonic = time.monotonic()
        self.stale_logged = False
        self.frame_counts["parsed"] += 1
        self.logger.event(
            "device.parse.succeeded",
            component="weighing.parser",
            value=payload.get("gross_weight"),
            unit=result.unit,
            stable=result.is_stable,
            sequence=self.sequence,
            transaction_id=result.transaction_id,
        )
        self._set_health("UNSTABLE" if result.is_stable is False else "STABLE")
        self._send_frame_event(frame, "PARSED", result=result)
        event_id = self.queue.enqueue(payload, result.transaction_id)
        self.logger.event(
            "queue.enqueued",
            component="weighing.queue",
            event_id=event_id,
            transaction_id=result.transaction_id,
            duplicate=event_id is None,
        )
        self._display(force=True)

    def _handle_error(self, exc: Exception) -> None:
        device = self.device
        error_code = getattr(device, "error_code", "") or str(getattr(exc, "errno", "") or "")
        error_message = getattr(device, "error", "") or str(exc)
        self.state["device"] = "DISCONNECTED"
        self.state["error"] = error_message
        self._record_error("device", error_message)
        connecting = self.connect_phase
        self.logger.event(
            "device.connect.failed" if connecting else "device.error",
            component="weighing.tcp_client",
            host=self.config.device_host,
            port=self.config.device_port or 0,
            connection_id=self.connection_id,
            attempt=self.attempt + 1,
            duration_ms=getattr(device, "last_connect_ms", 0),
            error_code=error_code,
            error_message=error_message,
            exception_type=type(exc).__name__,
            level=30,
        )
        self._set_health("DEVICE_ERROR" if not connecting else "DISCONNECTED")
        self._send_heartbeat()
        self._display(force=True)

    def _check_stale(self) -> None:
        anchor = self.last_reading_monotonic or self.last_frame_monotonic
        if anchor is None or self.stale_logged:
            return
        age = time.monotonic() - anchor
        if age < self.config.device_stale_after_seconds:
            return
        self.stale_logged = True
        self._record_error("stale", f"no valid reading for {age:.1f}s")
        self.logger.event(
            "device.reading.stale",
            component="weighing.service",
            age_seconds=age,
            threshold_seconds=self.config.device_stale_after_seconds,
            sequence=self.sequence,
        )
        self._set_health("CONNECTED_STALE")

    def _set_health(self, status: str) -> None:
        normalized = str(status or "DISCONNECTED").upper()
        if normalized == self.health:
            return
        old = self.health
        self.health = normalized
        self.state["device"] = normalized
        self.logger.event(
            "device.health.changed",
            component="weighing.service",
            old_status=old,
            new_status=normalized,
            sequence=self.sequence,
        )

    def _record_error(self, category: str, message: str = "") -> None:
        key = str(category or "unknown").strip().lower()[:40]
        self.error_counts[key] = self.error_counts.get(key, 0) + 1
        self.logger.event(
            "device.poll.error",
            component="weighing.diagnostics",
            category=key,
            error_message=str(message)[:500],
            error_breakdown=dict(self.error_counts),
            sequence=self.sequence,
            level=30,
        )

    def _diagnostics_snapshot(self) -> dict:
        return {
            "generated_at": _utc_now(),
            "poll_interval_seconds": self.config.diagnostics_poll_interval_seconds,
            "device_health": self.health,
            "device_status": self.state["device"],
            "erp_status": self.state["erp"],
            "connection_id": self.connection_id,
            "sequence": self.sequence,
            "bytes_received": self.bytes_received,
            "frame_counts": dict(self.frame_counts),
            "reading_counts": dict(self.reading_counts),
            "error_breakdown": dict(self.error_counts),
            "queue_counts": self.queue.counts(),
            "last_byte_at": self.last_byte_at,
            "last_valid_reading_at": self.last_valid_reading_at,
            "reading_age_seconds": self._reading_age_seconds(),
            "last_error": self.state["error"],
        }

    def _maybe_emit_poll_summary(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_poll_log < max(
            self.config.diagnostics_poll_interval_seconds, 0.2
        ):
            return
        self._last_poll_log = now
        try:
            snapshot = self._diagnostics_snapshot()
            self.logger.event(
                "device.poll.summary",
                component="weighing.diagnostics",
                **snapshot,
            )
            self._send_heartbeat(snapshot)
        except Exception as exc:
            self.logger.event(
                "device.poll.error",
                component="weighing.diagnostics",
                category="diagnostics",
                error_message=str(exc),
                error_code=type(exc).__name__,
                level=30,
            )

    def _reconnect_delay(self) -> float:
        bounded = min(
            self.config.device_reconnect_max_seconds,
            self.config.device_reconnect_min_seconds * (2 ** min(self.attempt, 10)),
        )
        return max(0.0, bounded * random.uniform(0.8, 1.2))

    def _raw_fields(self, frame) -> dict:
        fields = {
            "raw_text_length": len(frame.text),
            "raw_hex_length": len(frame.hex),
        }
        if not self.config.raw_log_enabled or self.config.raw_log_max_bytes <= 0:
            return fields
        limit = self.config.raw_log_max_bytes
        fields["raw_text_preview"] = frame.text[:limit]
        fields["raw_hex_preview"] = frame.hex[: limit * 2]
        return fields

    def _send_heartbeat(self, snapshot: dict | None = None) -> None:
        try:
            diagnostics = snapshot or self._diagnostics_snapshot()
            self.erp.post_heartbeat({
                "status": self.health,
                "health_status": self.health,
                "device_id": self.config.device_id,
                "device_mac": self.config.device_mac,
                "device_host": self.config.device_host,
                "device_port": self.config.device_port or 0,
                "parser_mode": self.config.parser_mode,
                "dry_run": self.config.dry_run,
                "gcs_upload_enabled": self.config.gcs_upload_enabled,
                "error_message": self.state["error"],
                "last_barcode": self.state["barcode"],
                "last_gross_weight": _float_or_none(self.state["weight"]),
                "last_byte_at": self.last_byte_at,
                "last_valid_reading_at": self.last_valid_reading_at,
                "reading_age_seconds": diagnostics.get("reading_age_seconds"),
                "sequence": self.sequence,
                "error_breakdown": diagnostics.get("error_breakdown", {}),
                "frame_counts": diagnostics.get("frame_counts", {}),
                "reading_counts": diagnostics.get("reading_counts", {}),
                "queue_counts": diagnostics.get("queue_counts", {}),
                "poll_interval_seconds": diagnostics.get(
                    "poll_interval_seconds", self.config.diagnostics_poll_interval_seconds
                ),
                "diagnostics_generated_at": diagnostics.get("generated_at", ""),
            })
        except Exception as exc:
            self._record_error("erp_heartbeat", str(exc))
            self.logger.event(
                "erp.heartbeat.error",
                component="weighing.erp",
                error_code=type(exc).__name__,
                error_message=str(exc),
                level=30,
            )

    def _send_frame_event(self, frame, parser_status: str, result=None, error: str = "") -> None:
        mode = self.config.erp_frame_report_mode
        if mode == "none":
            return
        if mode == "parsed" and parser_status != "PARSED":
            return
        if mode == "errors" and parser_status != "ERROR":
            return
        payload = result.payload if result else {}
        event = {
            "raw_text": self._raw_fields(frame).get("raw_text_preview", ""),
            "raw_hex": self._raw_fields(frame).get("raw_hex_preview", ""),
            "device_id": self.config.device_id,
            "device_host": self.config.device_host,
            "device_port": self.config.device_port or 0,
            "machine_id": self.config.machine_id,
            "parser_status": parser_status,
            "health_status": self.health,
            "sequence": self.sequence,
            "unit": result.unit if result else "",
            "is_stable": result.is_stable if result else None,
            "is_zero": result.is_zero if result else None,
            "is_overload": result.is_overload if result else None,
            "last_byte_at": self.last_byte_at,
            "last_valid_reading_at": self.last_valid_reading_at,
            "barcode": payload.get("barcode", ""),
            "gross_weight": payload.get("gross_weight"),
            "transaction_id": result.transaction_id if result else "",
            "error_message": error,
        }
        try:
            self.erp.post_frame(event)
        except Exception as exc:
            self._record_error("erp_frame", str(exc))
            self.logger.event(
                "erp.frame.error",
                component="weighing.erp",
                transaction_id=event["transaction_id"],
                error_code=type(exc).__name__,
                error_message=str(exc),
                level=30,
            )

    def _process_queue(self) -> None:
        if self.config.dry_run:
            return
        for event in self.queue.pending(self.config.queue_batch_size):
            payload = event["payload"]
            transaction_id = str(payload.get("transaction_id", ""))
            result = self.erp.post_transaction(payload)
            response_text = json.dumps(result.body, default=str) if result.body else result.error
            if result.ok:
                self.queue.mark_sent(event["id"], response_text)
                self.state["erp"] = str(result.body.get("status", "OK")) if result.body else "OK"
                self.state["error"] = ""
                self.reading_counts["captured"] += 1
                self.logger.event(
                    "device.reading.captured",
                    component="weighing.service",
                    transaction_id=transaction_id,
                    reading_sequence=self.sequence,
                    value=payload.get("gross_weight"),
                    erp_status=self.state["erp"],
                )
                self.logger.event(
                    "queue.sent",
                    component="weighing.queue",
                    event_id=event["id"],
                    transaction_id=transaction_id,
                    http_status=result.http_status,
                    erp_status=self.state["erp"],
                )
            elif result.retryable:
                status = self.queue.mark_failed(
                    event["id"],
                    result.error,
                    event["attempts"],
                    self.config.max_attempts,
                    self.config.retry_base_delay_seconds,
                    response_text,
                )
                self.state["erp"] = "RETRY"
                self.state["error"] = result.error
                self._record_error("erp", result.error)
                self.logger.event(
                    "queue.retry",
                    component="weighing.queue",
                    event_id=event["id"],
                    transaction_id=transaction_id,
                    attempts=event["attempts"] + 1,
                    queue_status=status,
                    error_code=type(result).__name__,
                    error_message=result.error,
                    level=30,
                )
            else:
                self.queue.mark_failed(
                    event["id"],
                    result.error,
                    event["attempts"],
                    1,
                    self.config.retry_base_delay_seconds,
                    response_text,
                )
                self.state["erp"] = "REJECTED"
                self.state["error"] = result.error
                self.reading_counts["rejected"] += 1
                self._record_error("erp", result.error)
                self.logger.event(
                    "device.reading.rejected",
                    component="weighing.service",
                    transaction_id=transaction_id,
                    reading_sequence=self.sequence,
                    reason=result.error,
                    health_status=self.health,
                )
                self.logger.event(
                    "queue.dead",
                    component="weighing.queue",
                    event_id=event["id"],
                    transaction_id=transaction_id,
                    error_code=type(result).__name__,
                    error_message=result.error,
                    level=30,
                )

    def _maybe_check_erp_status(self) -> None:
        if self.config.dry_run:
            return
        now = time.monotonic()
        if now - self._last_status_check < max(self.config.erp_status_interval_seconds, 1.0):
            return
        self._last_status_check = now
        try:
            self.erp.fetch_status()
            self.state["erp"] = "CONNECTED"
            self.state["error"] = ""
        except Exception as exc:
            self.state["erp"] = "ERROR"
            self.state["error"] = str(exc)
            self._record_error("erp_status", str(exc))
            self.logger.event(
                "erp.status.error",
                component="weighing.erp",
                error_code=type(exc).__name__,
                error_message=str(exc),
                level=30,
            )

    def _reading_age_seconds(self) -> float | None:
        if self.last_reading_monotonic is None:
            return None
        return max(0.0, time.monotonic() - self.last_reading_monotonic)

    def _display(self, force: bool) -> None:
        now = time.monotonic()
        if not force and now - self._last_display < max(self.config.status_refresh_seconds, 0.1):
            return
        self._last_display = now
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        counts = self.queue.counts()
        line = (
            f"{timestamp} device={self.state['device']} health={self.health} erp={self.state['erp']} "
            f"parser={self.config.parser_mode} dry_run={self.config.dry_run} "
            f"barcode={self.state['barcode'] or '-'} weight={self.state['weight'] or '-'} "
            f"txn={self.state['transaction_id'] or '-'} "
            f"queue={counts.get('PENDING', 0)}/{counts.get('SENT', 0)}/{counts.get('DEAD', 0)} "
            f"error={self.state['error'] or '-'}"
        )
        print(line, flush=True)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _float_or_none(value) -> float | None:
    try:
        return float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def main() -> None:
    try:
        BridgeApp().run()
    except ValueError as exc:
        print(f"CONFIG_ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
