from __future__ import annotations

import asyncio
import importlib
import unittest


def _extract_registered_tool_names(mcp: object) -> set[str]:
    candidates = []

    for attr_name in ("list_tools", "get_tools"):
        attr = getattr(mcp, attr_name, None)
        if callable(attr):
            try:
                candidate = attr()
                if asyncio.iscoroutine(candidate):
                    candidate = asyncio.run(candidate)
                candidates.append(candidate)
            except Exception:
                pass

    for container in (
        getattr(mcp, "tools", None),
        getattr(getattr(mcp, "_tool_manager", None), "tools", None),
    ):
        if container is not None:
            candidates.append(container)

    for candidate in candidates:
        if isinstance(candidate, dict):
            return {str(key) for key in candidate.keys()}
        if isinstance(candidate, (list, tuple, set)):
            names: set[str] = set()
            for item in candidate:
                if isinstance(item, str):
                    names.add(item)
                    continue
                for attr_name in ("name", "tool_name", "id"):
                    name = getattr(item, attr_name, None)
                    if isinstance(name, str) and name.strip():
                        names.add(name.strip())
                        break
            if names:
                return names

    raise AssertionError(f"Unable to determine registered tools from object: {type(mcp)!r}")


class McpServerSmokeTests(unittest.TestCase):
    def test_server_module_imports_and_registers_tools(self) -> None:
        module = importlib.import_module("devlog_mcp_server.server")

        self.assertTrue(hasattr(module, "mcp"))
        tool_names = _extract_registered_tool_names(module.mcp)
        self.assertIn("ingest_message", tool_names)
        self.assertIn("build_session_blocks", tool_names)
