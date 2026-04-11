from __future__ import annotations

import unittest

from devlog_mcp_server.models import DevLogEventDeliveryState, DevLogEventPersistenceRecordDTO
from devlog_mcp_server.persistence import InMemoryDevLogEventStore, build_payload_hash


class DevLogEventStoreTests(unittest.TestCase):
    def test_create_and_lookup_record(self) -> None:
        store = InMemoryDevLogEventStore()
        record = DevLogEventPersistenceRecordDTO(
            eventId="evt-sess-1-msg-1-append",
            sessionId="sess_1",
            messageId="msg_1",
            operation="APPEND",
            payloadHash=build_payload_hash({"a": 1}),
        )

        created = store.create(record)
        loaded = store.get("evt-sess-1-msg-1-append")

        self.assertIsNotNone(loaded)
        self.assertEqual(created.eventId, loaded.eventId)
        self.assertEqual(DevLogEventDeliveryState.PENDING, loaded.deliveryState)

    def test_mark_attempt_success_and_failure(self) -> None:
        store = InMemoryDevLogEventStore()
        store.create(
            DevLogEventPersistenceRecordDTO(
                eventId="evt-sess-1-msg-1-append",
                sessionId="sess_1",
                messageId="msg_1",
                operation="APPEND",
                payloadHash=build_payload_hash({"a": 1}),
            )
        )

        attempted = store.mark_attempt("evt-sess-1-msg-1-append", last_status="202")
        self.assertEqual(1, attempted.attemptCount)
        self.assertEqual(DevLogEventDeliveryState.ATTEMPTING, attempted.deliveryState)
        self.assertEqual("202", attempted.lastStatus)

        success = store.mark_success("evt-sess-1-msg-1-append", last_status="200")
        self.assertEqual(DevLogEventDeliveryState.DELIVERED, success.deliveryState)
        self.assertEqual("200", success.lastStatus)
        self.assertIsNone(success.lastError)

        failed = store.mark_failure(
            "evt-sess-1-msg-1-append",
            error="timeout",
            retryable=True,
            last_status="504",
        )
        self.assertEqual(DevLogEventDeliveryState.RETRYABLE_FAILED, failed.deliveryState)
        self.assertEqual("timeout", failed.lastError)
        self.assertEqual("504", failed.lastStatus)


if __name__ == "__main__":
    unittest.main()
