from __future__ import annotations

from fastapi import FastAPI, HTTPException

from mcp.core.builder import build_session_blocks
from mcp.llm.client import LlmClient
from mcp.models import BuildRequestDTO, BuildResponseDTO
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
