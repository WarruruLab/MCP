#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8000}"

echo "[1/4] python unit tests"
PYTHONPATH=src python -m unittest discover -s tests -v

echo
echo "[2/4] FULL request"
curl -sS -X POST "${BASE_URL}/v1/session-blocks:build" \
  -H "Content-Type: application/json" \
  --data @examples/full_build_request.json

echo
echo
echo "[3/4] INCREMENTAL request"
curl -sS -X POST "${BASE_URL}/v1/session-blocks:build" \
  -H "Content-Type: application/json" \
  --data @examples/incremental_build_request.json

echo
echo
echo "[4/4] Ollama availability check"
if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "Ollama is reachable at http://127.0.0.1:11434"
else
  echo "Ollama is not reachable. MCP fallback mode will be used."
fi
