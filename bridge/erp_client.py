"""ERP transaction API client with token or password authentication."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from config import BridgeConfig


class ErpError(Exception):
    retryable = True


class ErpAuthError(ErpError):
    retryable = True


class ErpValidationError(ErpError):
    retryable = False


class ErpServerError(ErpError):
    retryable = True


@dataclass(frozen=True)
class ErpResult:
    ok: bool
    retryable: bool
    http_status: int
    body: dict[str, Any] | None
    error: str


class ErpClient:
    def __init__(self, config: BridgeConfig, bridge_logger):
        self.config = config
        self.logger = bridge_logger
        self._session = requests.Session()
        self._token = config.erp_token

    def ensure_token(self) -> None:
        if self._token:
            return
        if not self.config.erp_username or not self.config.erp_password:
            raise ErpAuthError("ERP_TOKEN or ERP_USERNAME/ERP_PASSWORD is required")
        try:
            response = self._session.post(
                self.config.erp_base_url + self.config.erp_login_path,
                json={
                    "username": self.config.erp_username,
                    "password": self.config.erp_password,
                },
                timeout=self.config.erp_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise ErpAuthError(f"ERP login failed: {exc}") from exc
        body = _json_body(response)
        if response.status_code != 200 or not body or not body.get("access_token"):
            raise ErpAuthError(f"ERP login rejected with status {response.status_code}")
        self._token = str(body["access_token"])
        self.logger.event("erp.login.success", message="ERP login succeeded")

    def post_transaction(self, payload: dict[str, Any]) -> ErpResult:
        transaction_id = str(payload.get("transaction_id", ""))
        self.logger.event(
            "erp.request",
            transaction_id=transaction_id,
            path=self.config.erp_transactions_path,
            barcode=payload.get("barcode", ""),
            gross_weight=payload.get("gross_weight"),
        )
        try:
            response = self._request(
                "POST",
                self.config.erp_transactions_path,
                json=payload,
            )
        except ErpError as exc:
            self.logger.event(
                "erp.response",
                transaction_id=transaction_id,
                http_status=0,
                retryable=exc.retryable,
                error=str(exc),
                level=30,
            )
            return ErpResult(False, exc.retryable, 0, None, str(exc))
        body = _json_body(response)
        status_name = str(body.get("status", "")) if body else ""
        error = str(body.get("error", "")) if body else ""
        ok = response.status_code in (200, 201) and status_name in ("PROCESSED", "DUPLICATE")
        retryable = self._retryable_status(response.status_code)
        if response.status_code == 422:
            retryable = False
        if response.status_code in (200, 201) and status_name == "FAILED":
            retryable = False
        self.logger.event(
            "erp.response",
            transaction_id=transaction_id,
            http_status=response.status_code,
            status=status_name,
            duplicate=bool(body.get("duplicate")) if body else False,
            retryable=retryable,
            error=error,
            level=20 if ok else 30,
        )
        return ErpResult(ok, retryable, response.status_code, body, error)

    def post_frame(self, frame_event: dict[str, Any]) -> bool:
        if not self.config.erp_telemetry_enabled:
            return False
        try:
            response = self._request("POST", self.config.erp_frame_path, json=frame_event)
        except ErpError as exc:
            self.logger.event(
                "erp.frame.error",
                transaction_id=frame_event.get("transaction_id", ""),
                error=str(exc),
                level=30,
            )
            return False
        self.logger.event(
            "erp.frame.ack",
            transaction_id=frame_event.get("transaction_id", ""),
            parser_status=frame_event.get("parser_status", ""),
            http_status=response.status_code,
        )
        return response.status_code in (200, 201)

    def post_heartbeat(self, heartbeat: dict[str, Any]) -> bool:
        if not self.config.erp_telemetry_enabled:
            return False
        try:
            response = self._request("POST", self.config.erp_heartbeat_path, json=heartbeat)
        except ErpError as exc:
            self.logger.event("erp.heartbeat.error", error=str(exc), level=30)
            return False
        self.logger.event(
            "erp.heartbeat.ack",
            device_status=heartbeat.get("status", ""),
            http_status=response.status_code,
        )
        return response.status_code in (200, 201)

    def fetch_status(self) -> dict[str, Any]:
        response = self._request("GET", self.config.erp_status_path)
        if response.status_code != 200:
            raise ErpError(f"ERP status returned {response.status_code}")
        body = _json_body(response) or {}
        connection = body.get("connection", {}) if isinstance(body, dict) else {}
        counters = body.get("counters", {}) if isinstance(body, dict) else {}
        self.logger.event(
            "erp.status",
            connection_status=connection.get("status", "") if isinstance(connection, dict) else "",
            counters=counters,
        )
        return body

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        retry_auth: bool = True,
    ) -> requests.Response:
        self.ensure_token()
        url = self.config.erp_base_url + path
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._token}",
        }
        if json is not None:
            headers["Content-Type"] = "application/json"
        try:
            response = self._session.request(
                method,
                url,
                json=json,
                headers=headers,
                timeout=self.config.erp_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise ErpError(f"ERP request failed: {exc}") from exc
        if response.status_code in (401, 403) and retry_auth and not self.config.erp_token:
            self._token = ""
            self.ensure_token()
            return self._request(method, path, json=json, retry_auth=False)
        if response.status_code >= 500:
            raise ErpServerError(f"ERP server error {response.status_code}")
        if response.status_code == 422:
            raise ErpValidationError("ERP rejected the payload")
        return response

    @staticmethod
    def _retryable_status(status_code: int) -> bool:
        return status_code in (401, 403, 408, 429) or status_code >= 500


def _json_body(response: requests.Response) -> dict[str, Any] | None:
    try:
        value = response.json()
    except ValueError:
        return None
    return value if isinstance(value, dict) else None
