from __future__ import annotations

import json
import os
import subprocess
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib import error, request


DATASET_PATH = Path(__file__).resolve().parents[1] / "examples" / "realtime_dummy_session_100_messages.json"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_RECENT_LIMIT = 8
DEFAULT_CANDIDATE_LIMIT = 8
DEFAULT_HTTP_TIMEOUT = 120
DEFAULT_DEVLOG_DB_CONTAINER = "devlog-db"
DEFAULT_DEVLOG_DB_NAME = "devlog"
DEFAULT_DEVLOG_DB_USER = "devlog_app"
DEFAULT_DEVLOG_DB_PASSWORD = "change-me"


def _read_env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:  # pragma: no cover - defensive guard for test configuration
        raise AssertionError(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise AssertionError(f"{name} must be >= {minimum}, got {value}")
    return value


def _load_dataset() -> Tuple[str, List[Dict[str, Any]]]:
    if not DATASET_PATH.exists():
        raise FileNotFoundError(f"dataset not found: {DATASET_PATH}")

    with DATASET_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    session_id = str(payload["sessionId"])
    messages = list(payload["messages"])
    if not messages:
        raise AssertionError("dataset messages must not be empty")
    return session_id, messages


def _parse_dataset_timestamp(raw: str) -> datetime:
    normalized = raw.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_mysql_datetime(raw: str) -> str:
    return _parse_dataset_timestamp(raw).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")


def _sql_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def _seed_devlog_session_and_messages(session_id: str, messages: List[Dict[str, Any]]) -> None:
    if not messages:
        raise AssertionError("messages must not be empty")

    container = os.getenv("DEVLOG_DB_CONTAINER", DEFAULT_DEVLOG_DB_CONTAINER)
    database = os.getenv("DEVLOG_DB_NAME", DEFAULT_DEVLOG_DB_NAME)
    username = os.getenv("DEVLOG_DB_USER", DEFAULT_DEVLOG_DB_USER)
    password = os.getenv("DEVLOG_DB_PASSWORD", DEFAULT_DEVLOG_DB_PASSWORD)
    title = os.getenv("LOCAL_LLM_TEST_SESSION_TITLE", "Realtime dummy session 100")
    last_message_at = _to_mysql_datetime(str(messages[-1]["timestamp"]))
    synced_count = len(messages)

    delete_sql = f"""
DELETE FROM draft_block
WHERE draft_id IN (SELECT draft_id FROM draft WHERE session_id = {_sql_string(session_id)});
DELETE FROM draft WHERE session_id = {_sql_string(session_id)};
DELETE FROM session_block_message WHERE session_id = {_sql_string(session_id)};
DELETE FROM session_block WHERE session_id = {_sql_string(session_id)};
DELETE FROM mcp_ingest_event WHERE session_id = {_sql_string(session_id)};
DELETE FROM session_message WHERE session_id = {_sql_string(session_id)};
DELETE FROM logical_session WHERE session_id = {_sql_string(session_id)};
"""

    insert_session_sql = f"""
INSERT INTO logical_session (
    session_id,
    source_session_id,
    title,
    session_status,
    sync_status,
    analysis_status,
    total_message_count,
    synced_message_count,
    structured_message_count,
    unstructured_message_count,
    block_count,
    last_message_at,
    last_synced_at,
    last_analyzed_at,
    sync_error_message,
    analysis_error_message
) VALUES (
    {_sql_string(session_id)},
    {_sql_string(session_id)},
    {_sql_string(title)},
    'READY',
    'DONE',
    'IDLE',
    {synced_count},
    {synced_count},
    0,
    {synced_count},
    0,
    {_sql_string(last_message_at)},
    NOW(),
    NULL,
    NULL,
    NULL
);
"""

    message_values = []
    for message in messages:
        message_values.append(
            "("
            + ", ".join(
                [
                    _sql_string(str(message["messageId"])),
                    _sql_string(session_id),
                    _sql_string(str(message["role"]).upper()),
                    "NULL",
                    _sql_string(str(message["content"])),
                    _sql_string(_to_mysql_datetime(str(message["timestamp"]))),
                    "'PENDING'",
                    "NULL",
                ]
            )
            + ")"
        )

    insert_messages_sql = """
INSERT INTO session_message (
    message_id,
    session_id,
    role,
    author_name,
    content,
    message_created_at,
    structure_status,
    structured_at
) VALUES
"""
    insert_messages_sql += ",\n".join(message_values) + ";\n"

    full_sql = delete_sql + insert_session_sql + insert_messages_sql

    command = [
        "docker",
        "exec",
        "-i",
        container,
        "mysql",
        f"-u{username}",
        f"-p{password}",
        database,
    ]

    try:
        subprocess.run(
            command,
            input=full_sql.encode("utf-8"),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise AssertionError("docker command is required to seed DevLog test data") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace")
        raise AssertionError(f"failed to seed DevLog test data: {stderr}") from exc


def _normalize_action(action: Any) -> str:
    if action is None:
        return ""
    if isinstance(action, str):
        return action.strip().upper()
    return str(action).strip().upper()


def _message_dict(message: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "messageId": str(message["messageId"]),
        "role": str(message["role"]),
        "content": str(message["content"]),
        "timestamp": str(message["timestamp"]),
    }


def _candidate_block_from_response(block: Dict[str, Any], recent_limit: int) -> Dict[str, Any]:
    message_ids = [str(message_id) for message_id in block.get("messageIds", [])]
    return {
        "blockId": str(block["blockId"]),
        "topic": str(block.get("topic", "")),
        "blockType": str(block.get("blockType", "")),
        "status": str(block.get("status", "neutral")),
        "summary": str(block.get("summary", "")),
        "tags": dict(block.get("tags") or {}),
        "parentBlockId": block.get("parentBlockId"),
        "relatedBlockIds": list(block.get("relatedBlockIds") or []),
        "recentMessageIds": message_ids[-recent_limit:],
    }


def _build_request_payload(
    *,
    session_id: str,
    message: Dict[str, Any],
    candidate_blocks: List[Dict[str, Any]],
    recent_messages: List[Dict[str, Any]],
    recent_limit: int,
    candidate_limit: int,
) -> Dict[str, Any]:
    return {
        "sessionId": session_id,
        "currentMessage": _message_dict(message),
        "candidateBlocks": candidate_blocks[-candidate_limit:],
        "recentMessages": recent_messages[-recent_limit:],
        "options": {
            "maxRecentMessages": recent_limit,
            "maxCandidateBlocks": candidate_limit,
        },
    }


def _post_json(url: str, payload: Dict[str, Any], timeout_seconds: int) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise AssertionError(
            f"POST {url} failed with HTTP {exc.code}: {error_body or exc.reason}"
        ) from exc


def _write_report(report_path: Path, report: Dict[str, Any]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


@unittest.skipUnless(os.getenv("RUN_LOCAL_LLM_TEST") == "1", "local LLM integration test disabled")
class LocalLlmRealtimeDummySessionTests(unittest.TestCase):
    maxDiff = None

    def test_realtime_dummy_session_100_messages(self) -> None:
        session_id, messages = _load_dataset()
        _seed_devlog_session_and_messages(session_id, messages)
        smoke_count = min(
            len(messages),
            _read_env_int("LOCAL_LLM_SMOKE_COUNT", len(messages)),
        )
        recent_limit = _read_env_int("LOCAL_LLM_RECENT_LIMIT", DEFAULT_RECENT_LIMIT)
        candidate_limit = _read_env_int("LOCAL_LLM_CANDIDATE_LIMIT", DEFAULT_CANDIDATE_LIMIT)
        timeout_seconds = _read_env_int("LOCAL_LLM_HTTP_TIMEOUT", DEFAULT_HTTP_TIMEOUT)
        base_url = os.getenv("MCP_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
        endpoint = f"{base_url}/v1/session-blocks:ingest-message"
        report_path = Path(
            os.getenv("LOCAL_LLM_REPORT_PATH", str(Path("artifacts") / "realtime_dummy_local_llm_report.json"))
        )

        processed_messages: List[Dict[str, Any]] = []
        response_summaries: List[Dict[str, Any]] = []
        final_blocks_by_id: Dict[str, Dict[str, Any]] = {}
        final_block_order: List[str] = []
        new_block_count = 0
        append_count = 0

        report: Dict[str, Any] = {
            "sessionId": session_id,
            "datasetPath": str(DATASET_PATH),
            "baseUrl": base_url,
            "endpoint": endpoint,
            "smokeCount": smoke_count,
            "recentLimit": recent_limit,
            "candidateLimit": candidate_limit,
            "processedCount": 0,
            "newBlockCount": 0,
            "appendCount": 0,
            "finalBlockCount": 0,
            "responses": response_summaries,
            "finalBlocks": [],
        }

        try:
            for index, message in enumerate(messages[:smoke_count]):
                candidate_blocks = [
                    _candidate_block_from_response(final_blocks_by_id[block_id], recent_limit)
                    for block_id in final_block_order
                ]
                payload = _build_request_payload(
                    session_id=session_id,
                    message=message,
                    candidate_blocks=candidate_blocks,
                    recent_messages=processed_messages,
                    recent_limit=recent_limit,
                    candidate_limit=candidate_limit,
                )
                response_payload = _post_json(endpoint, payload, timeout_seconds)

                response_block = dict(response_payload["block"])
                action = _normalize_action(response_payload.get("action"))
                target_block_id = str(response_payload.get("targetBlockId") or response_block.get("blockId") or "")
                score = float(response_payload.get("score", 0.0))
                reason = str(response_payload.get("reason", ""))
                current_message = _message_dict(message)

                self.assertTrue(target_block_id, "response targetBlockId must not be empty")
                self.assertIn("messageIds", response_block, "response block must include messageIds")
                self.assertIn(
                    current_message["messageId"],
                    [str(message_id) for message_id in response_block.get("messageIds", [])],
                    f"current messageId {current_message['messageId']} must be present in the selected block",
                )
                self.assertGreaterEqual(score, 0.0, f"score must be >= 0.0, got {score}")
                self.assertLessEqual(score, 1.0, f"score must be <= 1.0, got {score}")

                if action == "NEW_BLOCK":
                    new_block_count += 1
                elif action == "APPEND":
                    append_count += 1

                block_id = str(response_block["blockId"])
                if block_id not in final_blocks_by_id:
                    final_block_order.append(block_id)
                final_blocks_by_id[block_id] = response_block

                response_summaries.append(
                    {
                        "index": index,
                        "messageId": current_message["messageId"],
                        "action": action,
                        "targetBlockId": target_block_id,
                        "score": score,
                        "reason": reason,
                        "blockId": block_id,
                        "blockType": str(response_block.get("blockType", "")),
                        "status": str(response_block.get("status", "")),
                        "messageCount": len(response_block.get("messageIds", [])),
                        "candidateBlockCount": len(candidate_blocks),
                        "recentMessageCount": len(processed_messages),
                    }
                )

                processed_messages.append(current_message)
                report.update(
                    {
                        "processedCount": len(response_summaries),
                        "newBlockCount": new_block_count,
                        "appendCount": append_count,
                    }
                )

            final_blocks = [final_blocks_by_id[block_id] for block_id in final_block_order]
            processed_count = len(response_summaries)
            processed_message_ids = {item["messageId"] for item in response_summaries}
            covered_message_ids = {
                str(message_id)
                for block in final_blocks
                for message_id in block.get("messageIds", [])
            }

            report.update(
                {
                    "processedCount": processed_count,
                    "newBlockCount": new_block_count,
                    "appendCount": append_count,
                    "finalBlockCount": len(final_blocks),
                    "finalBlocks": final_blocks,
                }
            )

            self.assertGreaterEqual(processed_count, 1, "expected at least one processed message")
            self.assertGreaterEqual(len(final_blocks), 1, "expected at least one final block")
            self.assertTrue(
                processed_message_ids.issubset(covered_message_ids),
                "all processed messages must be covered by the final block set",
            )

            if processed_count > 1:
                if smoke_count == 1:
                    self.assertGreaterEqual(new_block_count + append_count, 1)
                else:
                    self.assertGreaterEqual(new_block_count, 1, "expected at least one NEW_BLOCK action")
                    self.assertGreaterEqual(append_count, 1, "expected at least one APPEND action")
        finally:
            _write_report(report_path, report)


if __name__ == "__main__":
    unittest.main()
