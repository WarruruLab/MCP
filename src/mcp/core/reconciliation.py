from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

from mcp.core.routing import NarrativeBlock, NarrativeMessage, RoutingResult, coerce_block, coerce_message, route_message
from mcp.utils.validate import parse_iso8601


class MessageProcessingState(str, Enum):
    RECEIVED = "received"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
    RECONCILE_PENDING = "reconcile_pending"


@dataclass(frozen=True)
class MessageProcessingRecord:
    session_id: str
    message_id: str
    state: MessageProcessingState = MessageProcessingState.RECEIVED
    attempts: int = 0
    block_id: Optional[str] = None
    last_error: Optional[str] = None
    updated_at: Optional[str] = None
    retriable: bool = True

    def as_dict(self) -> Dict[str, object]:
        return {
            "sessionId": self.session_id,
            "messageId": self.message_id,
            "state": self.state.value,
            "attempts": self.attempts,
            "blockId": self.block_id,
            "lastError": self.last_error,
            "updatedAt": self.updated_at,
            "retriable": self.retriable,
        }


@dataclass(frozen=True)
class SessionMessageReconciliation:
    session_id: str
    session_messages: List[NarrativeMessage]
    block_message_ids: List[str]
    mapped_message_ids: List[str]
    covered_message_ids: List[str]
    missing_message_ids: List[str]
    missing_messages: List[NarrativeMessage]
    duplicate_session_message_ids: List[str]
    duplicate_block_message_ids: List[str]
    dangling_message_ids: List[str]
    orphan_block_message_ids: List[str]
    foreign_block_ids: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, object]:
        return {
            "sessionId": self.session_id,
            "sessionMessages": [message.as_dict() for message in self.session_messages],
            "blockMessageIds": list(self.block_message_ids),
            "mappedMessageIds": list(self.mapped_message_ids),
            "coveredMessageIds": list(self.covered_message_ids),
            "missingMessageIds": list(self.missing_message_ids),
            "missingMessages": [message.as_dict() for message in self.missing_messages],
            "duplicateSessionMessageIds": list(self.duplicate_session_message_ids),
            "duplicateBlockMessageIds": list(self.duplicate_block_message_ids),
            "danglingMessageIds": list(self.dangling_message_ids),
            "orphanBlockMessageIds": list(self.orphan_block_message_ids),
            "foreignBlockIds": list(self.foreign_block_ids),
        }


@dataclass(frozen=True)
class ReconciliationRoutingResult:
    reconciliation: SessionMessageReconciliation
    routing_result: Optional[RoutingResult]
    rerouted_message_ids: List[str]

    def as_dict(self) -> Dict[str, object]:
        return {
            "reconciliation": self.reconciliation.as_dict(),
            "routingResult": self.routing_result.as_dict() if self.routing_result is not None else None,
            "reroutedMessageIds": list(self.rerouted_message_ids),
        }


def transition_message_processing(
    record: MessageProcessingRecord,
    next_state: MessageProcessingState,
    *,
    block_id: Optional[str] = None,
    error: Optional[str] = None,
    increment_attempts: bool = False,
    retriable: Optional[bool] = None,
    updated_at: Optional[str] = None,
) -> MessageProcessingRecord:
    return replace(
        record,
        state=next_state,
        attempts=record.attempts + (1 if increment_attempts else 0),
        block_id=record.block_id if block_id is None else block_id,
        last_error=record.last_error if error is None else error,
        retriable=record.retriable if retriable is None else retriable,
        updated_at=record.updated_at if updated_at is None else updated_at,
    )


def mark_received(record: MessageProcessingRecord, *, updated_at: Optional[str] = None) -> MessageProcessingRecord:
    updated = transition_message_processing(record, MessageProcessingState.RECEIVED, updated_at=updated_at)
    return replace(updated, last_error=None)


def mark_processing(record: MessageProcessingRecord, *, updated_at: Optional[str] = None) -> MessageProcessingRecord:
    updated = transition_message_processing(
        record,
        MessageProcessingState.PROCESSING,
        increment_attempts=True,
        updated_at=updated_at,
    )
    return replace(updated, last_error=None)


def mark_processed(
    record: MessageProcessingRecord,
    *,
    block_id: Optional[str] = None,
    updated_at: Optional[str] = None,
) -> MessageProcessingRecord:
    updated = transition_message_processing(
        record,
        MessageProcessingState.PROCESSED,
        block_id=block_id,
        error=None,
        retriable=False,
        updated_at=updated_at,
    )
    return replace(updated, last_error=None, retriable=False)


def mark_failed(
    record: MessageProcessingRecord,
    *,
    error: str,
    retryable: bool = True,
    updated_at: Optional[str] = None,
) -> MessageProcessingRecord:
    return transition_message_processing(
        record,
        MessageProcessingState.FAILED,
        error=error,
        increment_attempts=True,
        retriable=retryable,
        updated_at=updated_at,
    )


def mark_reconcile_pending(
    record: MessageProcessingRecord,
    *,
    error: Optional[str] = None,
    updated_at: Optional[str] = None,
) -> MessageProcessingRecord:
    updated = transition_message_processing(
        record,
        MessageProcessingState.RECONCILE_PENDING,
        error=error,
        retriable=True,
        updated_at=updated_at,
    )
    return replace(updated, retriable=True)


def should_reconcile(record: MessageProcessingRecord, *, max_attempts: int = 3) -> bool:
    if record.state in {MessageProcessingState.FAILED, MessageProcessingState.RECONCILE_PENDING}:
        return True
    if record.state == MessageProcessingState.PROCESSING and record.attempts >= max_attempts:
        return True
    return False


def reconcile_session_messages(
    session_id: str,
    session_messages: Sequence[Mapping[str, Any] | NarrativeMessage],
    blocks: Sequence[Mapping[str, Any] | NarrativeBlock],
    *,
    existing_message_to_block: Optional[Mapping[str, str]] = None,
) -> SessionMessageReconciliation:
    ordered_session_messages = _sort_messages([coerce_message(message) for message in session_messages])
    session_message_map: Dict[str, NarrativeMessage] = {}
    duplicate_session_message_ids: List[str] = []
    for message in ordered_session_messages:
        if message.message_id in session_message_map:
            duplicate_session_message_ids.append(message.message_id)
            continue
        session_message_map[message.message_id] = message

    block_message_ids: List[str] = []
    duplicate_block_message_ids: List[str] = []
    orphan_block_message_ids: List[str] = []
    foreign_block_ids: List[str] = []
    seen_block_message_ids: Set[str] = set()
    seen_blocks: Set[str] = set()

    for block in blocks:
        current_block = coerce_block(block)
        if current_block.session_id and current_block.session_id != session_id:
            foreign_block_ids.append(current_block.block_id)
            continue

        if current_block.block_id in seen_blocks:
            continue
        seen_blocks.add(current_block.block_id)

        for message_id in current_block.message_ids:
            if message_id in seen_block_message_ids:
                duplicate_block_message_ids.append(message_id)
                continue
            seen_block_message_ids.add(message_id)
            block_message_ids.append(message_id)
            if message_id not in session_message_map:
                orphan_block_message_ids.append(message_id)

    mapped_message_ids: List[str] = []
    mapped_message_id_set: Set[str] = set()
    for message_id, mapped_block_id in (existing_message_to_block or {}).items():
        if not message_id or message_id not in session_message_map:
            continue
        if mapped_block_id:
            mapped_message_id_set.add(message_id)

    mapped_message_ids = [message.message_id for message in ordered_session_messages if message.message_id in mapped_message_id_set]

    covered_message_ids_set = set(block_message_ids) | mapped_message_id_set
    covered_message_ids = [message.message_id for message in ordered_session_messages if message.message_id in covered_message_ids_set]

    missing_message_id_set = {message.message_id for message in ordered_session_messages if message.message_id not in covered_message_ids_set}
    missing_message_ids = [message.message_id for message in ordered_session_messages if message.message_id in missing_message_id_set]
    missing_messages = [message for message in ordered_session_messages if message.message_id in missing_message_id_set]
    dangling_message_ids = sorted(mapped_message_id_set - set(block_message_ids))

    return SessionMessageReconciliation(
        session_id=session_id,
        session_messages=ordered_session_messages,
        block_message_ids=block_message_ids,
        mapped_message_ids=mapped_message_ids,
        covered_message_ids=covered_message_ids,
        missing_message_ids=missing_message_ids,
        missing_messages=missing_messages,
        duplicate_session_message_ids=duplicate_session_message_ids,
        duplicate_block_message_ids=duplicate_block_message_ids,
        dangling_message_ids=dangling_message_ids,
        orphan_block_message_ids=orphan_block_message_ids,
        foreign_block_ids=foreign_block_ids,
    )


def reroute_missing_messages(
    session_id: str,
    session_messages: Sequence[Mapping[str, Any] | NarrativeMessage],
    candidate_blocks: Sequence[Mapping[str, Any] | NarrativeBlock],
    *,
    existing_message_to_block: Optional[Mapping[str, str]] = None,
    append_threshold: float = 0.40,
    tail_limit: int = 6,
) -> ReconciliationRoutingResult:
    reconciliation = reconcile_session_messages(
        session_id,
        session_messages,
        candidate_blocks,
        existing_message_to_block=existing_message_to_block,
    )
    if not reconciliation.missing_messages:
        return ReconciliationRoutingResult(
            reconciliation=reconciliation,
            routing_result=None,
            rerouted_message_ids=[],
        )

    working_blocks = [coerce_block(block) for block in candidate_blocks]
    working_message_to_block = dict(existing_message_to_block or {})
    sorted_messages = reconciliation.session_messages
    message_index = {message.message_id: index for index, message in enumerate(sorted_messages)}
    last_routing_result: Optional[RoutingResult] = None

    for missing_message in reconciliation.missing_messages:
        index = message_index.get(missing_message.message_id, 0)
        recent_messages = sorted_messages[:index]
        last_routing_result = route_message(
            session_id=session_id,
            current_message=missing_message,
            candidate_blocks=working_blocks,
            recent_messages=recent_messages,
            append_threshold=append_threshold,
            tail_limit=tail_limit,
            existing_message_to_block=working_message_to_block,
        )
        working_blocks = last_routing_result.blocks
        working_message_to_block = last_routing_result.message_to_block

    return ReconciliationRoutingResult(
        reconciliation=reconciliation,
        routing_result=last_routing_result,
        rerouted_message_ids=list(reconciliation.missing_message_ids),
    )


def _sort_messages(messages: Sequence[NarrativeMessage]) -> List[NarrativeMessage]:
    def sort_key(message: NarrativeMessage) -> tuple:
        try:
            return (parse_iso8601(message.timestamp), message.message_id)
        except Exception:
            return (message.timestamp, message.message_id)

    return sorted(messages, key=sort_key)
