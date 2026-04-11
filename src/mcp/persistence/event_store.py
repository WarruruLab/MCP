from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Dict, Mapping, Optional, Protocol

from mcp.models import DevLogEventDeliveryState, DevLogEventPersistenceRecordDTO


class DevLogEventStore(Protocol):
    def get(self, event_id: str) -> Optional[DevLogEventPersistenceRecordDTO]:
        ...

    def get_or_create(self, record: DevLogEventPersistenceRecordDTO) -> DevLogEventPersistenceRecordDTO:
        ...

    def create(self, record: DevLogEventPersistenceRecordDTO) -> DevLogEventPersistenceRecordDTO:
        ...

    def mark_attempt(
        self,
        event_id: str,
        *,
        last_status: Optional[str] = None,
        last_error: Optional[str] = None,
    ) -> DevLogEventPersistenceRecordDTO:
        ...

    def mark_success(
        self,
        event_id: str,
        *,
        last_status: Optional[str] = None,
    ) -> DevLogEventPersistenceRecordDTO:
        ...

    def mark_failure(
        self,
        event_id: str,
        *,
        error: str,
        retryable: bool = True,
        last_status: Optional[str] = None,
    ) -> DevLogEventPersistenceRecordDTO:
        ...


@dataclass
class InMemoryEventStore:
    _records: Dict[str, DevLogEventPersistenceRecordDTO] = field(default_factory=dict)

    def get(self, event_id: str) -> Optional[DevLogEventPersistenceRecordDTO]:
        return self._records.get(_normalize_event_id(event_id))

    def create(self, record: DevLogEventPersistenceRecordDTO) -> DevLogEventPersistenceRecordDTO:
        event_id = _normalize_event_id(record.eventId)
        existing = self._records.get(event_id)
        if existing is not None:
            return existing
        self._records[event_id] = _clone_record(record)
        return self._records[event_id]

    def get_or_create(self, record: DevLogEventPersistenceRecordDTO) -> DevLogEventPersistenceRecordDTO:
        return self.create(record)

    def save(self, record: DevLogEventPersistenceRecordDTO) -> DevLogEventPersistenceRecordDTO:
        event_id, cloned = _normalize_any_record(record)
        self._records[event_id] = cloned
        return self._records[event_id]

    def mark_attempt(
        self,
        event_id: str,
        *,
        last_status: Optional[str] = None,
        last_error: Optional[str] = None,
    ) -> DevLogEventPersistenceRecordDTO:
        record = self._require(event_id)
        updated = record.copy(
            update={
                "attemptCount": record.attemptCount + 1,
                "lastStatus": last_status or "attempting",
                "lastError": last_error,
                "deliveryState": DevLogEventDeliveryState.ATTEMPTING,
                "retriable": True,
            }
        )
        self._records[_normalize_event_id(event_id)] = updated
        return updated

    def mark_success(
        self,
        event_id: str,
        *,
        last_status: Optional[str] = None,
    ) -> DevLogEventPersistenceRecordDTO:
        record = self._require(event_id)
        updated = record.copy(
            update={
                "lastStatus": last_status or "delivered",
                "lastError": None,
                "deliveryState": DevLogEventDeliveryState.DELIVERED,
                "retriable": False,
            }
        )
        self._records[_normalize_event_id(event_id)] = updated
        return updated

    def mark_failure(
        self,
        event_id: str,
        *,
        last_status: Optional[str] = None,
        last_error: Optional[str] = None,
        retriable: Optional[bool] = None,
        error: Optional[str] = None,
        retryable: bool = True,
    ) -> DevLogEventPersistenceRecordDTO:
        record = self._require(event_id)
        resolved_error = error if error is not None else (last_error or "")
        resolved_retryable = retryable if retriable is None else retriable
        updated = record.copy(
            update={
                "lastStatus": last_status or "failed",
                "lastError": resolved_error,
                "deliveryState": DevLogEventDeliveryState.RETRYABLE_FAILED if resolved_retryable else DevLogEventDeliveryState.FAILED,
                "retriable": resolved_retryable,
            }
        )
        self._records[_normalize_event_id(event_id)] = updated
        return updated

    def _require(self, event_id: str) -> DevLogEventPersistenceRecordDTO:
        key = _normalize_event_id(event_id)
        record = self._records.get(key)
        if record is None:
            raise KeyError(key)
        return record


def build_payload_hash(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(_normalize_payload(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def _clone_record(record: DevLogEventPersistenceRecordDTO) -> DevLogEventPersistenceRecordDTO:
    if hasattr(record, "model_copy"):
        return record.model_copy(deep=True)
    return record.copy(deep=True)


def _normalize_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, Mapping):
            normalized[str(key)] = _normalize_payload(value)
        elif isinstance(value, list):
            normalized[str(key)] = [_normalize_payload(item) if isinstance(item, Mapping) else item for item in value]
        else:
            normalized[str(key)] = value
    return normalized


def _normalize_event_id(event_id: str) -> str:
    text = str(event_id).strip()
    if not text:
        raise ValueError("event_id is required")
    return text


def _normalize_any_record(record: Any) -> tuple[str, DevLogEventPersistenceRecordDTO]:
    if hasattr(record, "eventId"):
        event_id = _normalize_event_id(getattr(record, "eventId"))
        payload = {
            "eventId": event_id,
            "sessionId": getattr(record, "sessionId"),
            "messageId": getattr(record, "messageId"),
            "operation": getattr(record, "operation"),
            "payloadHash": getattr(record, "payloadHash", ""),
            "attemptCount": getattr(record, "attemptCount", 0),
            "lastStatus": getattr(record, "lastStatus", None),
            "lastError": getattr(record, "lastError", None),
            "deliveryState": getattr(record, "deliveryState", DevLogEventDeliveryState.PENDING),
            "retriable": getattr(record, "retriable", True),
        }
        return event_id, DevLogEventPersistenceRecordDTO(**payload)

    event_id = _normalize_event_id(getattr(record, "event_id"))
    payload = {
        "eventId": event_id,
        "sessionId": getattr(record, "session_id"),
        "messageId": getattr(record, "message_id"),
        "operation": getattr(record, "operation"),
        "payloadHash": getattr(record, "payload_hash", ""),
        "attemptCount": getattr(record, "attempt_count", 0),
        "lastStatus": getattr(record, "last_status", None),
        "lastError": getattr(record, "last_error", None),
        "deliveryState": getattr(record, "delivery_state", DevLogEventDeliveryState.PENDING),
        "retriable": getattr(record, "retriable", True),
    }
    return event_id, DevLogEventPersistenceRecordDTO(**payload)


InMemoryDevLogEventStore = InMemoryEventStore
