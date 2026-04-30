from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional
from urllib import error, request


class DevLogRequestError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        retriable: bool | None = None,
        response_payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.retriable = retriable if retriable is not None else (status_code == 0 or status_code >= 500)
        self.response_payload = dict(response_payload or {})


class DevLogClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        internal_api_key: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("DEVLOG_BASE_URL", "http://localhost:8081")).rstrip("/")
        self.internal_api_key = internal_api_key if internal_api_key is not None else os.getenv("DEVLOG_INTERNAL_API_KEY", "")
        timeout_value = timeout_seconds if timeout_seconds is not None else os.getenv("DEVLOG_TIMEOUT_SECONDS", "10")
        self.timeout_seconds = float(timeout_value)

    def get_active_block(self, session_id: str) -> Dict[str, Any] | None:
        response = self._request_json(
            method="GET",
            path=f"/internal/mcp/sessions/{session_id}/active-block",
        )
        if response is None:
            return None
        return response

    def send_block_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = self._request_json(
            method="POST",
            path="/internal/mcp/session-block-events",
            payload=payload,
        )
        return response or {}

    def replace_session_blocks(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = self._request_json(
            method="POST",
            path="/internal/mcp/session-blocks",
            payload=payload,
        )
        return response or {}

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        headers = {"Content-Type": "application/json"}
        if self.internal_api_key:
            headers["X-Internal-Api-Key"] = self.internal_api_key

        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        req = request.Request(
            url=f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )

        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8").strip()
                if not body:
                    return {}
                return json.loads(body)
        except error.HTTPError as exc:
            if exc.code == 404 and method == "GET" and path.endswith("/active-block"):
                return None
            error_body = exc.read().decode("utf-8", errors="replace").strip()
            message = error_body or exc.reason or "DevLog request failed"
            response_payload = _parse_json_object(error_body)
            raise DevLogRequestError(
                exc.code,
                message,
                retriable=exc.code >= 500,
                response_payload=response_payload,
            ) from exc
        except error.URLError as exc:
            raise DevLogRequestError(0, str(exc.reason), retriable=True) from exc


def _parse_json_object(value: str) -> Dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
