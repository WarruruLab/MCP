import unittest

from mcp.core.builder import build_session_blocks
from mcp.core.summarize import extract_code_snippets, summarize_block
from mcp.llm.client import LlmClient
from mcp.models import BuildRequestDTO

try:
    from fastapi.testclient import TestClient
    from mcp.main import app
except ModuleNotFoundError:
    TestClient = None
    app = None


class SummarizeTests(unittest.TestCase):
    def test_summarize_block_extracts_problem_trial_solution_and_insight(self) -> None:
        tags = summarize_block(
            [
                ("msg_1", "개발 서버에서 Redis 연결 오류가 발생했다."),
                ("msg_2", "Redis 호스트 설정을 바꿔보고 다시 테스트했다."),
                ("msg_3", "Docker Compose 네트워크 이름이 잘못된 것이 원인이어서 문제가 해결됐다."),
            ]
        )

        self.assertIn("Redis 연결 오류", tags["PROBLEM"])
        self.assertEqual(1, len(tags["TRIAL"]))
        self.assertIn("설정을 바꿔보고", tags["TRIAL"][0])
        self.assertIn("해결됐다", tags["SOLUTION"])
        self.assertIn("원인", tags["INSIGHT"])

    def test_extract_code_snippets_collects_fenced_code_and_shell_commands(self) -> None:
        snippets = extract_code_snippets(
            [
                ("msg_1", "```yaml\nspring.data.redis.host: redis\n```"),
                ("msg_2", "$ uvicorn mcp.main:app --app-dir src --reload"),
            ]
        )

        self.assertEqual(2, len(snippets))
        self.assertEqual("yaml", snippets[0].language)
        self.assertIn("spring.data.redis.host", snippets[0].content)
        self.assertEqual("bash", snippets[1].language)
        self.assertIn("uvicorn mcp.main:app", snippets[1].content)


class BuilderTests(unittest.TestCase):
    def test_incremental_request_can_append_to_existing_block_with_last_message(self) -> None:
        request = BuildRequestDTO(
            sessionId="sess_1",
            analysisMode="INCREMENTAL",
            messages=[
                {
                    "messageId": "msg_3",
                    "role": "user",
                    "content": "같은 Redis 오류가 계속 발생한다",
                    "timestamp": "2026-03-11T10:02:00Z",
                }
            ],
            existingBlocks=[
                {
                    "blockId": "blk_existing",
                    "messageIds": ["msg_1", "msg_2"],
                    "tags": {"PROBLEM": "Redis 연결 오류가 발생했다"},
                    "lastMessage": {
                        "messageId": "msg_2",
                        "role": "assistant",
                        "content": "같은 Redis 오류가 발생한다",
                        "timestamp": "2026-03-11T10:01:00Z",
                    },
                }
            ],
        )

        response = build_session_blocks(request, LlmClient())

        self.assertEqual(1, len(response.blocks))
        self.assertEqual("blk_existing", response.messageToBlock["msg_3"])
        self.assertEqual(["msg_1", "msg_2", "msg_3"], response.blocks[0].messageIds)


@unittest.skipIf(TestClient is None or app is None, "fastapi is not installed in the local environment")
class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_build_endpoint_rejects_invalid_analysis_mode(self) -> None:
        response = self.client.post(
            "/v1/session-blocks:build",
            json={
                "sessionId": "sess_1",
                "analysisMode": "INVALID",
                "messages": [
                    {
                        "messageId": "msg_1",
                        "role": "user",
                        "content": "테스트 메시지",
                        "timestamp": "2026-03-11T10:00:00Z",
                    }
                ],
            },
        )

        self.assertEqual(400, response.status_code)
        self.assertIn("invalid analysisMode", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
