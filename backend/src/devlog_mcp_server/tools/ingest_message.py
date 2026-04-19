from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from devlog_mcp_server.models import IngestMessageRequestDTO, IngestMessageResponseDTO
from devlog_mcp_server.services.realtime_ingest_service import RealtimeIngestService


def register_ingest_message_tool(mcp: FastMCP, service: RealtimeIngestService) -> None:
    @mcp.tool(
        name="ingest_message",
        description="Classify a session message and sync the result to DevLog.",
        structured_output=True,
    )
    def ingest_message(request: IngestMessageRequestDTO) -> IngestMessageResponseDTO:
        return service.ingest_message(request)

