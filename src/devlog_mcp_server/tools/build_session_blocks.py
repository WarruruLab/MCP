from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from devlog_mcp_server.core.builder import build_session_blocks as run_build_session_blocks
from devlog_mcp_server.llm.client import LlmClient
from devlog_mcp_server.models import BuildRequestDTO, BuildResponseDTO


def register_build_session_blocks_tool(mcp: FastMCP, llm_client: LlmClient) -> None:
    @mcp.tool(
        name="build_session_blocks",
        description="Build narrative blocks for a session from a batch of messages.",
        structured_output=True,
    )
    def build_session_blocks(request: BuildRequestDTO) -> BuildResponseDTO:
        return run_build_session_blocks(request, llm_client)
