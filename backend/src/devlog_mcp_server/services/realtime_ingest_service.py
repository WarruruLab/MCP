from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from devlog_mcp_server.core import decide_finalize_block
from devlog_mcp_server.core.routing import apply_routing_decision
from devlog_mcp_server.llm.client import LlmClient
from devlog_mcp_server.models import (
    DevLogBlockContentDTO,
    DevLogBlockEventRequestDTO,
    DevLogBlockEventResponseDTO,
    DevLogBlockTargetDTO,
    DevLogEventDeliveryState,
    DevLogEventDispatchDTO,
    DevLogEventPersistenceRecordDTO,
    DevLogSyncResultDTO,
    IngestMessageRequestDTO,
    IngestMessageResponseDTO,
    NarrativeBlockDTO,
)
from devlog_mcp_server.output.devlog_client import DevLogClient, DevLogRequestError
from devlog_mcp_server.persistence import DevLogEventStore, InMemoryEventStore


class RealtimeIngestService:
    def __init__(
        self,
        llm_client: LlmClient,
        devlog_client: Optional[DevLogClient] = None,
        *,
        event_store: Optional[DevLogEventStore] = None,
        analysis_version: str = "realtime-v1",
    ) -> None:
        self.llm_client = llm_client
        self.devlog_client = devlog_client
        self.event_store = event_store or InMemoryEventStore()
        self.analysis_version = analysis_version

    def ingest_message(self, request: IngestMessageRequestDTO) -> IngestMessageResponseDTO:
        return self.handle_message(request)

    def handle_message(self, request: IngestMessageRequestDTO) -> IngestMessageResponseDTO:
        candidate_block_payloads = self._build_candidate_block_payloads(request)
        current_message = self._model_dump(request.currentMessage)
        recent_messages = [self._model_dump(message) for message in request.recentMessages]

        decision = self.llm_client.classify_narrative_block(
            current_message=current_message,
            candidate_blocks=candidate_block_payloads,
            recent_messages=recent_messages,
            session_id=request.sessionId,
        )

        routing_result = apply_routing_decision(
            session_id=request.sessionId,
            current_message=current_message,
            candidate_blocks=candidate_block_payloads,
            decision={
                "action": decision.action,
                "targetBlockId": decision.target_block_id,
                "blockType": decision.block_type,
                "status": decision.status,
                "topic": decision.topic,
                "summary": decision.summary,
                "tags": decision.tags,
                "score": decision.score,
                "reason": decision.reason,
            },
            tail_limit=request.options.maxRecentMessages,
        )

        selected_block = self._find_block(routing_result.blocks, routing_result.active_block_id)
        if selected_block is None:
            raise ValueError("failed to resolve active block")

        devlog_result = self._sync_devlog(
            session_id=request.sessionId,
            message_id=request.currentMessage.messageId,
            selected_block=selected_block,
            current_message=current_message,
            recent_messages=recent_messages,
        )

        return IngestMessageResponseDTO(
            sessionId=request.sessionId,
            action=routing_result.decision.action,
            targetBlockId=routing_result.decision.target_block_id or selected_block["blockId"],
            block=NarrativeBlockDTO(**selected_block),
            score=routing_result.decision.score,
            reason=routing_result.decision.reason,
            devlog=devlog_result,
        )

    def _sync_devlog(
        self,
        *,
        session_id: str,
        message_id: str,
        selected_block: Dict[str, Any],
        current_message: Dict[str, Any],
        recent_messages: List[Dict[str, Any]],
    ) -> Optional[DevLogSyncResultDTO]:
        if self.devlog_client is None:
            return None

        active_block_payload = self.devlog_client.get_active_block(session_id)
        active_block = active_block_payload if active_block_payload else None

        dispatched_events: List[DevLogEventDispatchDTO] = []
        selected_block_id = str(selected_block.get("blockId", "")).strip()
        active_mcp_block_id = ""
        if active_block is not None:
            active_mcp_block_id = str(active_block.get("mcpBlockId", "")).strip()

        if active_block is None:
            dispatched_events.append(
                self._send_event(
                    session_id=session_id,
                    message_id=message_id,
                    operation="CREATE_BLOCK",
                    block_payload=selected_block,
                    target_block_id=selected_block_id,
                    status="ACTIVE",
                )
            )
        elif active_mcp_block_id == selected_block_id:
            dispatched_events.append(
                self._send_event(
                    session_id=session_id,
                    message_id=message_id,
                    operation="APPEND",
                    block_payload=selected_block,
                    target_block_id=selected_block_id,
                    status="ACTIVE",
                )
            )
        else:
            finalize_decision = decide_finalize_block(
                active_block=active_block,
                selected_block=selected_block,
                current_message=current_message,
                recent_messages=recent_messages,
            )
            if finalize_decision.should_finalize:
                dispatched_events.append(
                    self._send_event(
                        session_id=session_id,
                        message_id=message_id,
                        operation="FINALIZE_BLOCK",
                        block_payload=active_block,
                        target_block_id=active_mcp_block_id,
                        status="CLOSED",
                    )
                )
            dispatched_events.append(
                self._send_event(
                    session_id=session_id,
                    message_id=message_id,
                    operation="CREATE_BLOCK",
                    block_payload=selected_block,
                    target_block_id=selected_block_id,
                    status="ACTIVE",
                )
            )

        return DevLogSyncResultDTO(
            activeBlock=active_block_payload and self._coerce_active_block(active_block_payload) or None,
            dispatchedEvents=dispatched_events,
        )

    def _send_event(
        self,
        *,
        session_id: str,
        message_id: str,
        operation: str,
        block_payload: Dict[str, Any],
        target_block_id: str,
        status: str,
    ) -> DevLogEventDispatchDTO:
        event = DevLogBlockEventRequestDTO(
            sessionId=session_id,
            eventId=self._build_event_id(session_id, message_id, operation),
            messageId=message_id,
            analysisVersion=self.analysis_version,
            model=self.llm_client.model,
            operation=operation,
            targetBlock=DevLogBlockTargetDTO(
                mcpBlockId=target_block_id,
                blockType=self._coerce_block_type(block_payload),
                title=self._derive_title(block_payload),
                summary=str(block_payload.get("summary", "")).strip(),
                status=status,
            ),
            content=DevLogBlockContentDTO(
                tags=self._extract_tag_names(block_payload.get("tags", {})),
                codeSnippets=[],
            ),
        )
        payload = self._model_dump(event)
        record = self._build_dispatch_record(
            event_id=event.eventId,
            session_id=session_id,
            message_id=message_id,
            operation=operation,
            payload=payload,
        )

        if record.deliveryState == DevLogEventDeliveryState.DELIVERED:
            return DevLogEventDispatchDTO(
                operation=operation,
                eventId=event.eventId,
                status=record.lastStatus or "OK",
                targetBlockId=target_block_id,
            )

        self.event_store.mark_attempt(event.eventId, last_status="attempting")

        try:
            response_payload = self.devlog_client.send_block_event(payload)
            response = (
                DevLogBlockEventResponseDTO(**response_payload)
                if response_payload
                else DevLogBlockEventResponseDTO(
                    sessionId=session_id,
                    eventId=event.eventId,
                    status="OK",
                    targetBlockId=target_block_id,
                )
            )
            self.event_store.mark_success(event.eventId, last_status=response.status or "OK")
            return DevLogEventDispatchDTO(
                operation=operation,
                eventId=event.eventId,
                status=response.status,
                targetBlockId=response.targetBlockId or target_block_id,
                blockId=response.blockId,
            )
        except DevLogRequestError as exc:
            self.event_store.mark_failure(
                event.eventId,
                error=f"status={exc.status_code}: {exc.message}",
                retryable=exc.retriable,
                last_status=str(exc.status_code),
            )
            raise

    def _build_candidate_block_payloads(self, request: IngestMessageRequestDTO) -> List[Dict[str, Any]]:
        candidate_block_payloads: List[Dict[str, Any]] = []
        for block in request.candidateBlocks:
            candidate_block_payloads.append(
                {
                    "blockId": block.blockId,
                    "sessionId": request.sessionId,
                    "topic": block.topic,
                    "blockType": block.blockType.value,
                    "status": block.status.value,
                    "summary": block.summary,
                    "messageIds": list(block.recentMessageIds),
                    "tags": dict(block.tags),
                    "parentBlockId": block.parentBlockId,
                    "relatedBlockIds": list(block.relatedBlockIds),
                }
            )
        return candidate_block_payloads

    def _build_dispatch_record(
        self,
        *,
        event_id: str,
        session_id: str,
        message_id: str,
        operation: str,
        payload: Dict[str, Any],
    ) -> DevLogEventPersistenceRecordDTO:
        payload_hash = self._hash_payload(payload)
        previous = self.event_store.get(event_id)
        if previous is not None:
            previous.payloadHash = payload_hash
            previous.sessionId = session_id
            previous.messageId = message_id
            previous.operation = operation
            if hasattr(self.event_store, "save"):
                self.event_store.save(previous)
            return previous

        record = DevLogEventPersistenceRecordDTO(
            eventId=event_id,
            sessionId=session_id,
            messageId=message_id,
            operation=operation,
            payloadHash=payload_hash,
        )
        return self.event_store.create(record)

    def _coerce_active_block(self, payload: Dict[str, Any]):
        from devlog_mcp_server.models import DevLogActiveBlockDTO

        return DevLogActiveBlockDTO(**payload)

    def _model_dump(self, model: object) -> Dict[str, Any]:
        if hasattr(model, "model_dump"):
            return getattr(model, "model_dump")()
        if hasattr(model, "dict"):
            return getattr(model, "dict")()
        raise TypeError("unsupported model object")

    def _find_block(self, blocks: List[Any], block_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not block_id:
            return None
        for block in blocks:
            block_dict = block.as_dict() if hasattr(block, "as_dict") else dict(block)
            if block_dict.get("blockId") == block_id:
                return block_dict
        return None

    def _build_event_id(self, session_id: str, message_id: str, operation: str) -> str:
        return f"evt-{session_id}-{message_id}-{operation.lower()}"

    def _hash_payload(self, payload: Dict[str, Any]) -> str:
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _coerce_block_type(self, payload: Dict[str, Any]) -> str:
        return str(payload.get("blockType", "")).strip() or "proposal"

    def _derive_title(self, payload: Dict[str, Any]) -> str:
        topic = str(payload.get("topic", "")).strip()
        if topic:
            return topic[:80]
        summary = str(payload.get("summary", "")).strip()
        if summary:
            return summary[:80]
        block_type = self._coerce_block_type(payload)
        return f"{block_type} block"

    def _extract_tag_names(self, tags: Any) -> List[str]:
        if not isinstance(tags, dict):
            return []
        return [str(key).strip() for key, value in tags.items() if str(key).strip() and value not in (None, "", [], {})]
