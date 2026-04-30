from __future__ import annotations

import unittest

from devlog_mcp_server.core.routing import apply_routing_decision
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
            currentMessage=_make_message("msg_10", "Should we increase the timeout?"),
            candidateBlocks=[
                _make_candidate_block(
                    "blk_1",
                    NarrativeBlockType.TRIAL,
                    NarrativeBlockStatus.NEUTRAL,
                    "Tried increasing timeout.",
                )
            ],
            recentMessages=[_make_message("msg_9", "We are checking the timeout setting.")],
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

    def test_classifier_can_append_to_existing_candidate_block_with_separate_route_and_metadata(self) -> None:
        client = LlmClient(model="fake-model", base_url="http://127.0.0.1:11434", timeout_seconds=0.01)
        original_generate = client._generate

        responses = iter(
            [
                '{"action":"APPEND","targetBlockId":"blk_1","score":0.93,"reason":"same_attempt_continues"}',
                (
                    '{"blockType":"trial","status":"neutral","topic":"Redis timeout issue",'
                    '"summary":"Tried increasing timeout.","tags":{"method":"increase timeout"}}'
                ),
            ]
        )

        def fake_generate(_: str) -> str:
            return next(responses)

        try:
            client._generate = fake_generate  # type: ignore[method-assign]
            result = client.classify_narrative_block(
                current_message={
                    "messageId": "msg_10",
                    "role": "user",
                    "content": "Should we increase the timeout and retry?",
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
        self.assertEqual("Redis timeout issue", result.topic)
        self.assertEqual("Tried increasing timeout.", result.summary)
        self.assertEqual({"method": "increase timeout"}, result.tags)
        self.assertEqual("same_attempt_continues", result.reason)
        self.assertGreaterEqual(result.score, 0.0)
        self.assertLessEqual(result.score, 1.0)

    def test_classifier_can_create_new_block_with_separate_route_and_metadata(self) -> None:
        client = LlmClient(model="fake-model", base_url="http://127.0.0.1:11434", timeout_seconds=0.01)
        original_generate = client._generate

        responses = iter(
            [
                '{"action":"NEW_BLOCK","targetBlockId":null,"score":0.89,"reason":"new_narrative_step"}',
                (
                    '{"blockType":"result","status":"success","topic":"Timeout fix result",'
                    '"summary":"The timeout increase resolved the issue.","tags":{"result":"resolved"}}'
                ),
            ]
        )

        def fake_generate(_: str) -> str:
            return next(responses)

        try:
            client._generate = fake_generate  # type: ignore[method-assign]
            result = client.classify_narrative_block(
                current_message={
                    "messageId": "msg_11",
                    "role": "user",
                    "content": "The timeout increase resolved the issue.",
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
        self.assertEqual(
            "The timeout increase resolved the issue.",
            result.summary,
        )

    def test_invalid_route_output_falls_back_to_new_block_with_heuristics(self) -> None:
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
                    "content": "Let's check the timeout again.",
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
        self.assertEqual("trial", result.block_type)
        self.assertEqual("neutral", result.status)
        self.assertEqual("fallback_conservative_new_block", result.reason)

    def test_metadata_failure_reuses_candidate_metadata_for_append(self) -> None:
        client = LlmClient(model="fake-model", base_url="http://127.0.0.1:11434", timeout_seconds=0.01)
        original_generate = client._generate

        responses = iter(
            [
                '{"action":"APPEND","targetBlockId":"blk_2","score":0.87,"reason":"same_attempt_continues"}',
                "not-json",
            ]
        )

        def fake_generate(_: str) -> str:
            return next(responses)

        try:
            client._generate = fake_generate  # type: ignore[method-assign]
            result = client.classify_narrative_block(
                current_message={
                    "messageId": "msg_13",
                    "role": "user",
                    "content": "Let's retry the same timeout change once more.",
                    "timestamp": "2026-04-01T10:03:00Z",
                },
                candidate_blocks=[
                    {
                        "blockId": "blk_2",
                        "topic": "Redis timeout issue",
                        "blockType": "trial",
                        "status": "neutral",
                        "summary": "Adjusted timeout handling.",
                        "tags": {"method": "adjust timeout"},
                    }
                ],
                recent_messages=[],
                session_id="sess_1",
            )
        finally:
            client._generate = original_generate  # type: ignore[method-assign]

        self.assertEqual("APPEND", result.action)
        self.assertEqual("blk_2", result.target_block_id)
        self.assertEqual("trial", result.block_type)
        self.assertEqual("neutral", result.status)
        self.assertEqual("Redis timeout issue", result.topic)
        self.assertEqual("Adjusted timeout handling.", result.summary)
        self.assertEqual({"method": "adjust timeout"}, result.tags)

    def test_metadata_failure_uses_heuristics_for_new_block(self) -> None:
        client = LlmClient(model="fake-model", base_url="http://127.0.0.1:11434", timeout_seconds=0.01)
        original_generate = client._generate

        responses = iter(
            [
                '{"action":"NEW_BLOCK","targetBlockId":null,"score":0.82,"reason":"new_narrative_step"}',
                "not-json",
            ]
        )

        def fake_generate(_: str) -> str:
            return next(responses)

        try:
            client._generate = fake_generate  # type: ignore[method-assign]
            result = client.classify_narrative_block(
                current_message={
                    "messageId": "msg_14",
                    "role": "user",
                    "content": "Let's check the timeout again.",
                    "timestamp": "2026-04-01T10:04:00Z",
                },
                candidate_blocks=[],
                recent_messages=[],
                session_id="sess_1",
            )
        finally:
            client._generate = original_generate  # type: ignore[method-assign]

        self.assertEqual("NEW_BLOCK", result.action)
        self.assertEqual("trial", result.block_type)
        self.assertEqual("neutral", result.status)
        self.assertEqual("Let's check the timeout again.", result.summary)

    def test_new_block_id_is_deterministic_from_session_and_message_id(self) -> None:
        current_message = {
            "messageId": "msg_10",
            "role": "user",
            "content": "Create a new block for this attempt.",
            "timestamp": "2026-04-01T10:00:00Z",
        }
        decision = {
            "action": "NEW_BLOCK",
            "blockType": "trial",
            "status": "neutral",
            "topic": "Timeout retry",
            "summary": "Retry timeout handling.",
            "score": 0.9,
            "reason": "new_attempt",
        }

        first = apply_routing_decision("sess_1", current_message, [], decision)
        second = apply_routing_decision("sess_1", current_message, [], decision)

        self.assertEqual("blk_sess_1_msg_10", first.active_block_id)
        self.assertEqual(first.active_block_id, second.active_block_id)
        self.assertEqual(["msg_10"], first.blocks[0].message_ids)

    def test_new_block_id_normalizes_unsafe_and_long_values(self) -> None:
        long_message_id = "message/" + ("abc:" * 30)
        result = apply_routing_decision(
            "세션/with spaces/and/symbols",
            {
                "messageId": long_message_id,
                "role": "user",
                "content": "Create a new block for unsafe ids.",
                "timestamp": "2026-04-01T10:00:00Z",
            },
            [],
            {
                "action": "NEW_BLOCK",
                "blockType": "trial",
                "status": "neutral",
                "topic": "Unsafe ids",
                "summary": "Normalize ids.",
                "score": 0.9,
                "reason": "new_attempt",
            },
        )

        self.assertRegex(result.active_block_id or "", r"^blk_[A-Za-z0-9_-]+_[A-Za-z0-9_-]+$")
        self.assertLessEqual(len(result.active_block_id or ""), 105)

    def test_new_block_id_collision_uses_deterministic_suffix(self) -> None:
        current_message = {
            "messageId": "msg_10",
            "role": "user",
            "content": "Create a new block despite a stale collision.",
            "timestamp": "2026-04-01T10:00:00Z",
        }
        existing_blocks = [
            {
                "blockId": "blk_sess_1_msg_10",
                "sessionId": "sess_1",
                "topic": "Existing stale block",
                "blockType": "trial",
                "status": "neutral",
                "summary": "Existing block.",
                "messageIds": ["msg_9"],
            }
        ]
        decision = {
            "action": "NEW_BLOCK",
            "blockType": "trial",
            "status": "neutral",
            "topic": "Collision handling",
            "summary": "Resolve deterministic collision.",
            "score": 0.9,
            "reason": "new_attempt",
        }

        first = apply_routing_decision("sess_1", current_message, existing_blocks, decision)
        second = apply_routing_decision("sess_1", current_message, existing_blocks, decision)

        self.assertNotEqual("blk_sess_1_msg_10", first.active_block_id)
        self.assertRegex(first.active_block_id or "", r"^blk_sess_1_msg_10_[0-9a-f]{12}$")
        self.assertEqual(first.active_block_id, second.active_block_id)

    def test_rerouted_same_message_uses_existing_candidate_block_id(self) -> None:
        current_message = {
            "messageId": "msg_10",
            "role": "user",
            "content": "This message was already routed.",
            "timestamp": "2026-04-01T10:00:00Z",
        }

        result = apply_routing_decision(
            "sess_1",
            current_message,
            [
                {
                    "blockId": "blk_sess_1_msg_10",
                    "sessionId": "sess_1",
                    "topic": "Existing block",
                    "blockType": "trial",
                    "status": "neutral",
                    "summary": "Already routed.",
                    "messageIds": ["msg_10"],
                }
            ],
            {
                "action": "NEW_BLOCK",
                "blockType": "trial",
                "status": "neutral",
                "topic": "Should not duplicate",
                "summary": "Already routed.",
                "score": 0.9,
                "reason": "new_attempt",
            },
        )

        self.assertEqual("blk_sess_1_msg_10", result.active_block_id)
        self.assertEqual(1, len(result.blocks))


if __name__ == "__main__":
    unittest.main()
