from __future__ import annotations

import unittest

from mcp.models import (
    BlockAction,
    CandidateBlockContextDTO,
    IngestMessageRequestDTO,
    MessageDTO,
    NarrativeBlockStatus,
    NarrativeBlockType,
)
from mcp.services.realtime_ingest_service import RealtimeIngestService


class FakeLlmClient:
    def __init__(self, action: str, target_block_id: str | None, block_type: str = "trial") -> None:
        self.model = "fake-model"
        self.action = action
        self.target_block_id = target_block_id
        self.block_type = block_type

    def classify_narrative_block(self, **_: object):
        class Decision:
            pass

        decision = Decision()
        decision.action = self.action
        decision.target_block_id = self.target_block_id
        decision.block_type = self.block_type
        decision.status = "neutral"
        decision.topic = "Redis timeout issue"
        decision.summary = "Adjusted timeout handling."
        decision.tags = {"method": "adjust timeout"}
        decision.score = 0.91
        decision.reason = "same_attempt_continues"
        return decision


class FakeDevLogClient:
    def __init__(self, active_block: dict | None) -> None:
        self.active_block = active_block
        self.sent_events: list[dict] = []

    def get_active_block(self, session_id: str) -> dict | None:
        if self.active_block is None:
            return None
        return dict(self.active_block, sessionId=session_id)

    def send_block_event(self, payload: dict) -> dict:
        self.sent_events.append(payload)
        return {
            "sessionId": payload["sessionId"],
            "eventId": payload["eventId"],
            "status": "OK",
            "targetBlockId": payload["targetBlock"]["mcpBlockId"],
        }


def _make_request(candidate_blocks: list[CandidateBlockContextDTO]) -> IngestMessageRequestDTO:
    return IngestMessageRequestDTO(
        sessionId="sess_1",
        currentMessage=MessageDTO(
            messageId="msg_10",
            role="user",
            content="Let's adjust the timeout and retry.",
            timestamp="2026-04-01T10:00:00Z",
        ),
        candidateBlocks=candidate_blocks,
        recentMessages=[],
    )


class DevLogRealtimeIntegrationTests(unittest.TestCase):
    def test_create_block_when_no_active_block_exists(self) -> None:
        service = RealtimeIngestService(
            llm_client=FakeLlmClient(action="NEW_BLOCK", target_block_id=None),
            devlog_client=FakeDevLogClient(active_block=None),
        )

        response = service.ingest_message(_make_request([]))

        self.assertEqual(BlockAction.NEW_BLOCK, response.action)
        self.assertIsNotNone(response.devlog)
        self.assertEqual(1, len(response.devlog.dispatchedEvents))
        self.assertEqual("CREATE_BLOCK", response.devlog.dispatchedEvents[0].operation)

    def test_append_when_active_block_matches_selected_block(self) -> None:
        service = RealtimeIngestService(
            llm_client=FakeLlmClient(action="APPEND", target_block_id="blk_existing"),
            devlog_client=FakeDevLogClient(
                active_block={
                    "blockId": 101,
                    "mcpBlockId": "blk_existing",
                    "blockType": "trial",
                    "title": "Redis timeout issue",
                    "summary": "Adjusted timeout handling.",
                    "status": "ACTIVE",
                }
            ),
        )

        response = service.ingest_message(
            _make_request(
                [
                    CandidateBlockContextDTO(
                        blockId="blk_existing",
                        topic="Redis timeout issue",
                        blockType=NarrativeBlockType.TRIAL,
                        status=NarrativeBlockStatus.NEUTRAL,
                        summary="Adjusted timeout handling.",
                        tags={"method": "adjust timeout"},
                        recentMessageIds=["msg_1"],
                    )
                ]
            )
        )

        self.assertEqual(BlockAction.APPEND, response.action)
        self.assertIsNotNone(response.devlog)
        self.assertEqual(1, len(response.devlog.dispatchedEvents))
        self.assertEqual("APPEND", response.devlog.dispatchedEvents[0].operation)

    def test_finalize_then_create_when_active_block_differs(self) -> None:
        devlog_client = FakeDevLogClient(
            active_block={
                "blockId": 101,
                "mcpBlockId": "blk_old",
                "blockType": "trial",
                "title": "Old block",
                "summary": "Old summary",
                "status": "ACTIVE",
            }
        )
        service = RealtimeIngestService(
            llm_client=FakeLlmClient(action="NEW_BLOCK", target_block_id=None),
            devlog_client=devlog_client,
        )

        response = service.ingest_message(_make_request([]))

        self.assertEqual(BlockAction.NEW_BLOCK, response.action)
        self.assertIsNotNone(response.devlog)
        self.assertEqual(2, len(response.devlog.dispatchedEvents))
        self.assertEqual("FINALIZE_BLOCK", response.devlog.dispatchedEvents[0].operation)
        self.assertEqual("CREATE_BLOCK", response.devlog.dispatchedEvents[1].operation)


if __name__ == "__main__":
    unittest.main()
