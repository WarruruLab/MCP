from __future__ import annotations

import unittest

from devlog_mcp_server.models import (
    BlockAction,
    CandidateBlockContextDTO,
    DevLogEventDeliveryState,
    IngestMessageRequestDTO,
    MessageDTO,
    NarrativeBlockStatus,
    NarrativeBlockType,
)
from devlog_mcp_server.persistence import InMemoryEventStore
from devlog_mcp_server.services.realtime_ingest_service import RealtimeIngestService
from devlog_mcp_server.output.devlog_client import DevLogRequestError


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
    def __init__(self, active_block: dict | None, send_error: DevLogRequestError | None = None) -> None:
        self.active_block = active_block
        self.send_error = send_error
        self.sent_events: list[dict] = []

    def get_active_block(self, session_id: str) -> dict | None:
        if self.active_block is None:
            return None
        return dict(self.active_block, sessionId=session_id)

    def send_block_event(self, payload: dict) -> dict:
        if self.send_error is not None:
            raise self.send_error
        self.sent_events.append(payload)
        return {
            "sessionId": payload["sessionId"],
            "eventId": payload["eventId"],
            "status": "OK",
            "targetBlockId": payload["targetBlock"]["mcpBlockId"],
        }


def _make_request(candidate_blocks: list[CandidateBlockContextDTO]) -> IngestMessageRequestDTO:
    return _make_request_with_content(candidate_blocks, "Let's adjust the timeout and retry.")


def _make_request_with_content(
    candidate_blocks: list[CandidateBlockContextDTO],
    content: str,
) -> IngestMessageRequestDTO:
    return IngestMessageRequestDTO(
        sessionId="sess_1",
        currentMessage=MessageDTO(
            messageId="msg_10",
            role="user",
            content=content,
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

    def test_keep_open_when_active_block_differs_without_finalize_signal(self) -> None:
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
        self.assertEqual(1, len(response.devlog.dispatchedEvents))
        self.assertEqual("CREATE_BLOCK", response.devlog.dispatchedEvents[0].operation)

    def test_finalize_then_create_when_message_explicitly_closes_block(self) -> None:
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

        request = _make_request_with_content(
            [],
            "We are done here. The fix is complete and we should close this block.",
        )

        response = service.ingest_message(request)

        self.assertEqual(BlockAction.NEW_BLOCK, response.action)
        self.assertIsNotNone(response.devlog)
        self.assertEqual(2, len(response.devlog.dispatchedEvents))
        self.assertEqual("FINALIZE_BLOCK", response.devlog.dispatchedEvents[0].operation)
        self.assertEqual("CREATE_BLOCK", response.devlog.dispatchedEvents[1].operation)

    def test_devlog_4xx_marks_event_as_non_retriable(self) -> None:
        event_store = InMemoryEventStore()
        service = RealtimeIngestService(
            llm_client=FakeLlmClient(action="NEW_BLOCK", target_block_id=None),
            devlog_client=FakeDevLogClient(
                active_block=None,
                send_error=DevLogRequestError(400, "invalid payload"),
            ),
            event_store=event_store,
        )

        with self.assertRaises(DevLogRequestError):
            service.ingest_message(_make_request([]))

        record = event_store.get("evt-sess_1-msg_10-create_block")
        self.assertIsNotNone(record)
        self.assertEqual("400", record.lastStatus)
        self.assertFalse(record.retriable)
        self.assertIn("status=400", record.lastError)
        self.assertEqual(1, record.attemptCount)
        self.assertEqual(DevLogEventDeliveryState.FAILED, record.deliveryState)

    def test_devlog_5xx_marks_event_as_retriable(self) -> None:
        event_store = InMemoryEventStore()
        service = RealtimeIngestService(
            llm_client=FakeLlmClient(action="NEW_BLOCK", target_block_id=None),
            devlog_client=FakeDevLogClient(
                active_block=None,
                send_error=DevLogRequestError(503, "service unavailable"),
            ),
            event_store=event_store,
        )

        with self.assertRaises(DevLogRequestError):
            service.ingest_message(_make_request([]))

        record = event_store.get("evt-sess_1-msg_10-create_block")
        self.assertIsNotNone(record)
        self.assertEqual("503", record.lastStatus)
        self.assertTrue(record.retriable)
        self.assertIn("status=503", record.lastError)
        self.assertEqual(1, record.attemptCount)
        self.assertEqual(DevLogEventDeliveryState.RETRYABLE_FAILED, record.deliveryState)


if __name__ == "__main__":
    unittest.main()
