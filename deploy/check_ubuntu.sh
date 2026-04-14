#!/usr/bin/env bash
set -euo pipefail

MCP_BASE_URL="${MCP_BASE_URL:-${1:-http://mcp:8000}}"
OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://ollama:11434}"
DEVLOG_BASE_URL="${DEVLOG_BASE_URL:-http://devlog-backend:8081}"
PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"

echo "[1/5] python unit tests"
PYTHONPATH=src "${PYTHON_BIN}" -m unittest discover -s tests -v

echo
echo "[2/5] FULL request"
curl -sS -X POST "${MCP_BASE_URL}/v1/session-blocks:build" \
  -H "Content-Type: application/json" \
  --data @examples/full_build_request.json

echo
echo
echo "[3/5] INCREMENTAL request"
curl -sS -X POST "${MCP_BASE_URL}/v1/session-blocks:build" \
  -H "Content-Type: application/json" \
  --data @examples/incremental_build_request.json

echo
echo
echo "[4/5] Ollama ambiguous request"
curl -sS -X POST "${MCP_BASE_URL}/v1/session-blocks:build" \
  -H "Content-Type: application/json" \
  --data @examples/ollama_ambiguous_request.json

echo
echo
echo "[5/5] service address summary"
echo "MCP base URL: ${MCP_BASE_URL}"
echo "Ollama base URL: ${OLLAMA_BASE_URL}"
echo "DevLog base URL: ${DEVLOG_BASE_URL}"

echo
echo "Ollama availability check"
if curl -fsS "${OLLAMA_BASE_URL}/api/tags" >/dev/null 2>&1; then
  echo "Ollama is reachable at ${OLLAMA_BASE_URL}"
else
  echo "Ollama is not reachable. MCP fallback mode will be used."
fi
