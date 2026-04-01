from __future__ import annotations

from fastapi import FastAPI, HTTPException

from mcp.core.builder import build_session_blocks
from mcp.core.routing import apply_routing_decision
from mcp.llm.client import LlmClient
from mcp.models import (
    BuildRequestDTO,
    BuildResponseDTO,
    IngestMessageRequestDTO,
    IngestMessageResponseDTO,
    NarrativeBlockDTO,
)
from mcp.utils.validate import normalize_role, parse_iso8601, require_non_empty, validate_roles

app = FastAPI(title="MCP", version="0.1.0")
llm_client = LlmClient()
ALLOWED_ANALYSIS_MODES = {"FULL", "INCREMENTAL"}


@app.post("/v1/session-blocks:build", response_model=BuildResponseDTO)
def build_session_blocks_endpoint(request: BuildRequestDTO) -> BuildResponseDTO:
    try:
        require_non_empty(request.sessionId, "sessionId")
        mode = request.analysisMode.strip().upper()
        if mode not in ALLOWED_ANALYSIS_MODES:
            raise ValueError(f"invalid analysisMode: {request.analysisMode}")
        if not request.messages:
            raise ValueError("messages is required")

        roles = [normalize_role(m.role) for m in request.messages]
        validate_roles(roles)
        for m in request.messages:
            require_non_empty(m.messageId, "messageId")
            require_non_empty(m.content, "content")
            parse_iso8601(m.timestamp)

        for block in request.existingBlocks:
            require_non_empty(block.blockId, "existingBlocks.blockId")
            if block.lastMessage is None:
                continue
            require_non_empty(block.lastMessage.messageId, "existingBlocks.lastMessage.messageId")
            require_non_empty(block.lastMessage.content, "existingBlocks.lastMessage.content")
            validate_roles([normalize_role(block.lastMessage.role)])
            parse_iso8601(block.lastMessage.timestamp)

        return build_session_blocks(request, llm_client)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/v1/session-blocks:ingest-message", response_model=IngestMessageResponseDTO)
def ingest_message_endpoint(request: IngestMessageRequestDTO) -> IngestMessageResponseDTO:
    try:
        require_non_empty(request.sessionId, "sessionId")
        require_non_empty(request.currentMessage.messageId, "currentMessage.messageId")
        require_non_empty(request.currentMessage.content, "currentMessage.content")
        validate_roles([normalize_role(request.currentMessage.role)])
        parse_iso8601(request.currentMessage.timestamp)

        for message in request.recentMessages:
            require_non_empty(message.messageId, "recentMessages.messageId")
            require_non_empty(message.content, "recentMessages.content")
            validate_roles([normalize_role(message.role)])
            parse_iso8601(message.timestamp)

        candidate_block_payloads = []
        for block in request.candidateBlocks:
            require_non_empty(block.blockId, "candidateBlocks.blockId")
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

        decision = llm_client.classify_narrative_block(
            current_message=_model_dump(request.currentMessage),
            candidate_blocks=candidate_block_payloads,
            recent_messages=[_model_dump(message) for message in request.recentMessages],
            session_id=request.sessionId,
        )

        routing_result = apply_routing_decision(
            session_id=request.sessionId,
            current_message=_model_dump(request.currentMessage),
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

        selected_block = _find_block(routing_result.blocks, routing_result.active_block_id)
        if selected_block is None:
            raise ValueError("failed to resolve active block")

        return IngestMessageResponseDTO(
            sessionId=request.sessionId,
            action=routing_result.decision.action,
            targetBlockId=routing_result.decision.target_block_id or selected_block["blockId"],
            block=NarrativeBlockDTO(**selected_block),
            score=routing_result.decision.score,
            reason=routing_result.decision.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _model_dump(model: object) -> dict:
    if hasattr(model, "model_dump"):
        return getattr(model, "model_dump")()
    if hasattr(model, "dict"):
        return getattr(model, "dict")()
    raise TypeError("unsupported model object")


def _find_block(blocks: list, block_id: str | None) -> dict | None:
    if not block_id:
        return None
    for block in blocks:
        block_dict = block.as_dict() if hasattr(block, "as_dict") else dict(block)
        if block_dict.get("blockId") == block_id:
            return block_dict
    return None
