from __future__ import annotations

import unittest

from devlog_mcp_server.core import decide_finalize_block


class FinalizeHeuristicTests(unittest.TestCase):
    def test_explicit_close_language_pushes_finalize(self) -> None:
        decision = decide_finalize_block(
            active_block={
                "blockId": "blk_1",
                "sessionId": "sess_1",
                "topic": "Redis timeout issue",
                "blockType": "trial",
                "status": "neutral",
                "summary": "Trying timeout changes.",
                "messageIds": ["msg_1"],
            },
            selected_block={
                "blockId": "blk_2",
                "sessionId": "sess_1",
                "topic": "Redis timeout issue",
                "blockType": "result",
                "status": "success",
                "summary": "Timeout increase resolved the issue.",
                "messageIds": ["msg_2"],
            },
            current_message={
                "messageId": "msg_3",
                "role": "user",
                "content": "It is resolved, let's close this block now.",
                "timestamp": "2026-04-11T10:00:00Z",
            },
            recent_messages=[],
        )

        self.assertTrue(decision.should_finalize)
        self.assertGreaterEqual(decision.confidence, 0.55)
        self.assertIn("explicit_close", decision.reason)

    def test_trial_to_result_prefers_keep_open(self) -> None:
        decision = decide_finalize_block(
            active_block={
                "blockId": "blk_1",
                "sessionId": "sess_1",
                "topic": "Redis timeout issue",
                "blockType": "trial",
                "status": "neutral",
                "summary": "Trying timeout changes.",
                "messageIds": ["msg_1"],
            },
            selected_block={
                "blockId": "blk_2",
                "sessionId": "sess_1",
                "topic": "Redis timeout issue",
                "blockType": "result",
                "status": "success",
                "summary": "Timeout increase resolved the issue.",
                "messageIds": ["msg_2"],
            },
            current_message={
                "messageId": "msg_3",
                "role": "user",
                "content": "The timeout increase worked.",
                "timestamp": "2026-04-11T10:01:00Z",
            },
            recent_messages=[],
        )

        self.assertFalse(decision.should_finalize)
        self.assertLess(decision.confidence, 0.55)
        self.assertIn("keep_open_transition:trial->result", decision.reason)

    def test_high_topic_overlap_keeps_block_open(self) -> None:
        decision = decide_finalize_block(
            active_block={
                "blockId": "blk_1",
                "sessionId": "sess_1",
                "topic": "Redis timeout issue",
                "blockType": "proposal",
                "status": "neutral",
                "summary": "Maybe increase timeout and retry.",
                "messageIds": ["msg_1"],
            },
            selected_block={
                "blockId": "blk_2",
                "sessionId": "sess_1",
                "topic": "Redis timeout issue",
                "blockType": "trial",
                "status": "neutral",
                "summary": "Try increasing timeout.",
                "messageIds": ["msg_2"],
            },
            current_message={
                "messageId": "msg_3",
                "role": "user",
                "content": "Let's keep working on the same Redis timeout issue.",
                "timestamp": "2026-04-11T10:02:00Z",
            },
            recent_messages=[
                {
                    "messageId": "msg_2",
                    "role": "assistant",
                    "content": "Try increasing timeout.",
                    "timestamp": "2026-04-11T10:01:30Z",
                }
            ],
        )

        self.assertFalse(decision.should_finalize)
        self.assertLess(decision.confidence, 0.55)
        self.assertIn("high_topic_overlap", decision.reason)


if __name__ == "__main__":
    unittest.main()
