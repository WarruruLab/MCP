from __future__ import annotations

import unittest
from typing import Any, Dict

from devlog_mcp_server.llm.client import LlmClient
from devlog_mcp_server.models import (
    BlockAction,
    CandidateBlockContextDTO,
    IngestMessageRequestDTO,
    IngestMessageResponseDTO,
    MessageDTO,
    NarrativeBlockDTO,
    NarrativeBlockStatus,
    NarrativeBlockType,
)


def _make_message(message_id: str, content: str) -> MessageDTO:
    return MessageDTO(
        messageId=message_id,
        role="user",
        content=content,
        timestamp="2026-04-01T10:00:00Z",
    )


def _make_candidate_block(
    block_id: str,
    block_type: NarrativeBlockType,
    status: NarrativeBlockStatus = NarrativeBlockStatus.NEUTRAL,
    summary: str = "",
) -> CandidateBlockContextDTO:
    return CandidateBlockContextDTO(
        blockId=block_id,
        topic="Redis timeout issue",
        blockType=block_type,
        status=status,
        summary=summary,
        tags={"method": "increase timeout"},
        recentMessageIds=["msg_1", "msg_2"],
    )


class RealtimeNarrativeContractTests(unittest.TestCase):
    def test_ingest_request_dto_accepts_candidate_blocks(self) -> None:
        request = IngestMessageRequestDTO(
            sessionId="sess_1",
            currentMessage=_make_message("msg_10", "timeout 값을 늘려볼까요?"),
            candidateBlocks=[
                _make_candidate_block(
                    "blk_1",
                    NarrativeBlockType.TRIAL,
                    NarrativeBlockStatus.NEUTRAL,
                    "Tried increasing timeout.",
                )
            ],
            recentMessages=[_make_message("msg_9", "timeout 설정을 확인해보자")],
        )

        self.assertEqual("sess_1", request.sessionId)
        self.assertEqual("msg_10", request.currentMessage.messageId)
        self.assertEqual("blk_1", request.candidateBlocks[0].blockId)
        self.assertEqual(NarrativeBlockType.TRIAL, request.candidateBlocks[0].blockType)
        self.assertEqual(1, len(request.recentMessages))

    def test_ingest_response_dto_embeds_selected_block(self) -> None:
        response = IngestMessageResponseDTO(
            sessionId="sess_1",
            action=BlockAction.APPEND,
            targetBlockId="blk_1",
            block=NarrativeBlockDTO(
                blockId="blk_1",
                topic="Redis timeout issue",
                blockType=NarrativeBlockType.TRIAL,
                status=NarrativeBlockStatus.NEUTRAL,
                summary="Tried increasing timeout and retried.",
                tags={"method": "increase timeout"},
                messageIds=["msg_1", "msg_10"],
            ),
            score=0.91,
            reason="same_attempt_continues",
        )

        self.assertEqual("sess_1", response.sessionId)
        self.assertEqual(BlockAction.APPEND, response.action)
        self.assertEqual("blk_1", response.targetBlockId)
        self.assertEqual("blk_1", response.block.blockId)
        self.assertEqual(["msg_1", "msg_10"], response.block.messageIds)

    def test_classifier_can_append_to_existing_candidate_block(self) -> None:
        client = LlmClient(model="fake-model", base_url="http://127.0.0.1:11434", timeout_seconds=0.01)
        original_generate = client._generate

        def fake_generate(_: str) -> str:
            return (
                '{"action":"APPEND","targetBlockId":"blk_1","blockType":"trial","status":"neutral",'
                '"topic":"Redis timeout issue","summary":"Tried increasing timeout and retried.",'
                '"tags":{"method":"increase timeout"},"score":0.93,"reason":"same_attempt_continues"}'
            )

        try:
            client._generate = fake_generate  # type: ignore[method-assign]
            result = client.classify_narrative_block(
                current_message={
                    "messageId": "msg_10",
                    "role": "user",
                    "content": "timeout 값을 늘려볼까요?",
                    "timestamp": "2026-04-01T10:00:00Z",
                },
                candidate_blocks=[
                    {
                        "blockId": "blk_1",
                        "topic": "Redis timeout issue",
                        "blockType": "trial",
                        "status": "neutral",
                        "summary": "Tried increasing timeout.",
                        "tags": {"method": "increase timeout"},
                    }
                ],
                recent_messages=[],
                session_id="sess_1",
            )
        finally:
            client._generate = original_generate  # type: ignore[method-assign]

        self.assertEqual("APPEND", result.action)
        self.assertEqual("blk_1", result.target_block_id)
        self.assertEqual("trial", result.block_type)
        self.assertEqual("neutral", result.status)
        self.assertEqual("same_attempt_continues", result.reason)
        self.assertGreaterEqual(result.score, 0.0)
        self.assertLessEqual(result.score, 1.0)

    def test_classifier_can_create_new_block_when_no_candidate_fits(self) -> None:
        client = LlmClient(model="fake-model", base_url="http://127.0.0.1:11434", timeout_seconds=0.01)
        original_generate = client._generate

        def fake_generate(_: str) -> str:
            return (
                '{"action":"NEW_BLOCK","targetBlockId":null,"blockType":"result","status":"success",'
                '"topic":"Redis timeout issue","summary":"Timeout increase resolved the issue.",'
                '"tags":{"method":"increase timeout","result":"success"},"score":0.89,"reason":"new_narrative_step"}'
            )

        try:
            client._generate = fake_generate  # type: ignore[method-assign]
            result = client.classify_narrative_block(
                current_message={
                    "messageId": "msg_11",
                    "role": "user",
                    "content": "timeout 값을 올리니 해결됐어요",
                    "timestamp": "2026-04-01T10:01:00Z",
                },
                candidate_blocks=[],
                recent_messages=[],
                session_id="sess_1",
            )
        finally:
            client._generate = original_generate  # type: ignore[method-assign]

        self.assertEqual("NEW_BLOCK", result.action)
        self.assertIsNone(result.target_block_id)
        self.assertEqual("result", result.block_type)
        self.assertEqual("success", result.status)
        self.assertEqual("new_narrative_step", result.reason)

    def test_invalid_classifier_output_falls_back_to_new_block(self) -> None:
        client = LlmClient(model="fake-model", base_url="http://127.0.0.1:11434", timeout_seconds=0.01)
        original_generate = client._generate

        def fake_generate(_: str) -> str:
            return "not-json"

        try:
            client._generate = fake_generate  # type: ignore[method-assign]
            result = client.classify_narrative_block(
                current_message={
                    "messageId": "msg_12",
                    "role": "user",
                    "content": "timeout 설정을 다시 확인해볼게요",
                    "timestamp": "2026-04-01T10:02:00Z",
                },
                candidate_blocks=[
                    {
                        "blockId": "blk_2",
                        "topic": "Redis timeout issue",
                        "blockType": "trial",
                        "status": "neutral",
                        "summary": "Tried increasing timeout.",
                        "tags": {"method": "increase timeout"},
                    }
                ],
                recent_messages=[],
                session_id="sess_1",
            )
        finally:
            client._generate = original_generate  # type: ignore[method-assign]

        self.assertEqual("NEW_BLOCK", result.action)
        self.assertIsNone(result.target_block_id)
        self.assertEqual("fallback_conservative_new_block", result.reason)
        self.assertEqual("trial", result.block_type)
        self.assertEqual("neutral", result.status)


if __name__ == "__main__":
    unittest.main()
