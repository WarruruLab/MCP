from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from devlog_mcp_server.llm.client import LlmClient
from devlog_mcp_server.output.devlog_client import DevLogClient
from devlog_mcp_server.services.realtime_ingest_service import RealtimeIngestService
from devlog_mcp_server.tools import register_build_session_blocks_tool, register_ingest_message_tool

SERVER_NAME = "DevLog MCP Server"

llm_client = LlmClient()
devlog_client = DevLogClient()
realtime_ingest_service = RealtimeIngestService(llm_client, devlog_client=devlog_client)

mcp = FastMCP(SERVER_NAME)
register_ingest_message_tool(mcp, realtime_ingest_service)
register_build_session_blocks_tool(mcp, llm_client)


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
