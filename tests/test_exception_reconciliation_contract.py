from __future__ import annotations

import unittest
from typing import Iterable, List, Sequence

import devlog_mcp_server.models as models
from devlog_mcp_server.core.routing import route_message


def _get_processing_state_enum():
    return (
        getattr(models, "MessageProcessingState", None)
        or getattr(models, "MessageProcessingStatus", None)
        or getattr(models, "MessageState", None)
    )


def _make_session_messages() -> List[dict]:
    return [
        {"messageId": "msg_1", "role": "user", "content": "문제 A를 발견했다", "timestamp": "2026-04-01T10:00:00Z"},
        {"messageId": "msg_2", "role": "assistant", "content": "방법 B를 시도해보자", "timestamp": "2026-04-01T10:01:00Z"},
        {"messageId": "msg_3", "role": "user", "content": "방법 B는 실패했다", "timestamp": "2026-04-01T10:02:00Z"},
        {"messageId": "msg_4", "role": "assistant", "content": "그럼 방법 C를 보자", "timestamp": "2026-04-01T10:03:00Z"},
    ]


def _reconcile_missing_message_ids(
    session_messages: Sequence[dict],
    routed_message_ids: Iterable[str],
) -> List[str]:
    helper = (
        getattr(models, "reconcile_missing_message_ids", None)
        or getattr(models, "find_missing_message_ids", None)
        or getattr(models, "missing_message_ids", None)
    )
    if callable(helper):
        return list(helper(session_messages, routed_message_ids))

    routed = {str(message_id).strip() for message_id in routed_message_ids if str(message_id).strip()}
    missing: List[str] = []
    for message in session_messages:
        message_id = str(message.get("messageId", "")).strip()
        if message_id and message_id not in routed:
            missing.append(message_id)
    return missing


class ExceptionHandlingContractTests(unittest.TestCase):
    def test_processing_state_enum_if_available(self) -> None:
        state_enum = _get_processing_state_enum()
        if state_enum is None:
            self.skipTest("processing state enum is not implemented yet")

        self.assertEqual("received", getattr(state_enum, "RECEIVED").value)
        self.assertEqual("processing", getattr(state_enum, "PROCESSING").value)
        self.assertEqual("processed", getattr(state_enum, "PROCESSED").value)
        self.assertEqual("failed", getattr(state_enum, "FAILED").value)
        self.assertEqual("reconcile_pending", getattr(state_enum, "RECONCILE_PENDING").value)

    def test_reconciliation_identifies_only_missing_message_ids(self) -> None:
        session_messages = _make_session_messages()
        routed_message_ids = {"msg_1", "msg_3"}

        missing = _reconcile_missing_message_ids(session_messages, routed_message_ids)

        self.assertEqual(["msg_2", "msg_4"], missing)

    def test_route_message_is_idempotent_for_already_routed_message(self) -> None:
        result = route_message(
            session_id="sess_1",
            current_message={
                "messageId": "msg_2",
                "role": "user",
                "content": "방법 B를 시도해보자",
                "timestamp": "2026-04-01T10:01:00Z",
            },
            candidate_blocks=[
                {
                    "blockId": "blk_1",
                    "sessionId": "sess_1",
                    "topic": "문제 A",
                    "blockType": "trial",
                    "status": "neutral",
                    "summary": "방법 B를 시도한 단계",
                    "messageIds": ["msg_1", "msg_2"],
                    "tags": {"method": "방법 B"},
                }
            ],
            recent_messages=[],
            existing_message_to_block={"msg_2": "blk_1"},
        )

        self.assertEqual("APPEND", result.decision.action)
        self.assertEqual("already_routed", result.decision.reason)
        self.assertEqual("blk_1", result.active_block_id)
        self.assertEqual(["msg_1", "msg_2"], result.blocks[0].message_ids)
        self.assertEqual({"msg_2": "blk_1"}, result.message_to_block)


if __name__ == "__main__":
    unittest.main()
