from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib import error, request


@dataclass
class LlmDecision:
    action: str
    score: float
    reason: str


@dataclass
class NarrativeBlockClassification:
    action: str
    target_block_id: Optional[str]
    block_type: str
    status: str
    topic: str
    summary: str
    tags: Dict[str, object]
    score: float
    reason: str


class LlmClient:
    def __init__(
        self,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        self.model = model or os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
        timeout_value = timeout_seconds or os.getenv("OLLAMA_TIMEOUT_SECONDS", "10")
        self.timeout_seconds = float(timeout_value)

    def decide_append_or_new(self, context: str) -> LlmDecision:
        try:
            response_text = self._generate_with_schema(
                self._build_prompt(context),
                {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["APPEND", "NEW_BLOCK"]},
                        "score": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "required": ["action", "score", "reason"],
                },
            )
            return self._parse_decision(response_text)
        except (ValueError, error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            return self._fallback_decision(context)

    def classify_narrative_block(
        self,
        current_message: Mapping[str, Any],
        candidate_blocks: Sequence[Mapping[str, Any]],
        recent_messages: Sequence[Mapping[str, Any]] = (),
        session_id: Optional[str] = None,
    ) -> NarrativeBlockClassification:
        try:
            prompt = self._build_narrative_prompt(current_message, candidate_blocks, recent_messages, session_id)
            response_text = self._generate_with_schema(
                prompt,
                {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["APPEND", "NEW_BLOCK"]},
                        "targetBlockId": {"type": ["string", "null"]},
                        "blockType": {"type": "string", "enum": ["problem", "proposal", "trial", "result", "insight"]},
                        "status": {"type": "string", "enum": ["open", "neutral", "failed", "success"]},
                        "topic": {"type": "string"},
                        "summary": {"type": "string"},
                        "tags": {"type": "object"},
                        "score": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "required": ["action", "blockType", "status", "topic", "summary", "tags", "score", "reason"],
                },
            )
            return self._parse_narrative_classification(response_text, current_message, candidate_blocks)
        except (ValueError, error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            return self._fallback_narrative_classification(current_message, candidate_blocks)

    def _generate_with_schema(self, prompt: str, format_schema: Dict[str, Any]) -> str:
        try:
            return self._generate(prompt, format_schema=format_schema)
        except TypeError:
            # Test doubles may still implement the legacy single-arg signature.
            return self._generate(prompt)

    def _build_prompt(self, context: str) -> str:
        return (
            "You decide whether a new message should be appended to the current session block.\n"
            "Return JSON only with keys action, score, reason.\n"
            'action must be either "APPEND" or "NEW_BLOCK".\n'
            "score must be a float between 0 and 1.\n"
            "reason must be a short snake_case string.\n\n"
            f"{context}"
        )

    def _build_narrative_prompt(
        self,
        current_message: Mapping[str, Any],
        candidate_blocks: Sequence[Mapping[str, Any]],
        recent_messages: Sequence[Mapping[str, Any]],
        session_id: Optional[str],
    ) -> str:
        payload = {
            "sessionId": session_id,
            "currentMessage": self._compact_mapping(current_message),
            "candidateBlocks": [self._compact_candidate_block(block) for block in candidate_blocks],
            "recentMessages": [self._compact_mapping(message) for message in recent_messages],
        }
        return (
            "Role:\n"
            "You are a narrative block classifier for a development work log.\n"
            "Your job is to decide whether the current message should be appended to one existing block or start a new block.\n\n"
            "Task:\n"
            "Read the current message, recent messages, and candidate blocks.\n"
            "Structure the session into core narrative blocks that would become meaningful sections in a technical blog post or dev retrospective.\n"
            "Do not create one block per message. A block should represent one coherent story unit: one problem, one investigation thread, one design decision, one implementation chunk, one deployment issue, one testing insight, or one lesson learned.\n"
            "Choose APPEND when the current message helps develop the same story unit as one candidate block.\n"
            "Choose NEW_BLOCK when the message starts a different story unit that would deserve its own paragraph or section in a blog post.\n\n"
            "Positive rules:\n"
            "1. Prefer coherent story-level grouping. A long session can contain several blocks, but each block should cover one blog-worthy unit rather than one utterance.\n"
            "2. Use APPEND when the message belongs to the same problem-solving arc, same investigation thread, same design discussion, same implementation effort, same deployment/debugging episode, same testing analysis, or same retrospective insight.\n"
            "3. Messages that are clarification, follow-up, command output, error log inspection, intermediate hypothesis, small correction, or next debugging step for the same arc should usually be APPEND.\n"
            "4. Use NEW_BLOCK when the message starts a different story unit, even if the overall project is the same.\n"
            "5. A good block should be something you could later title in a blog post, such as 'Why login returned 500 locally', 'Fixing CORS for the deployed frontend', 'Restructuring MCP prompt logic', or 'Tuning block granularity with 100-message tests'.\n"
            "6. Treat changes like these as likely NEW_BLOCK signals: moving from one concrete issue to another unrelated one, or switching between clearly separate themes such as login 500 bug, CORS issue, nginx routing, README/docs, prompt tuning, threshold tuning, reconciliation design, model selection, deployment, or testing strategy.\n"
            "7. Explicit transition cues such as '이제', '다른', '문서', '배포', 'nginx', 'CORS', 'README', 'prompt', 'threshold', 'reconciliation', 'model', 'llm', '테스트' can indicate a new block, but only when the concrete story unit has actually changed.\n"
            "8. If the new message still advances the same immediate narrative, prefer APPEND.\n"
            "9. If the message is ambiguous, prefer the most coherent ongoing story unit instead of reflexively creating a new block.\n"
            "10. topic should be a short concrete phrase representing the story-worthy work item, not a vague project-wide label.\n"
            "11. summary should read like the one-sentence summary of that block for a future write-up.\n"
            "12. You must classify the block phase accurately using blockType.\n"
            "13. blockType means:\n"
            "    - problem: recognizing or describing a bug, failure, symptom, or obstacle.\n"
            "    - proposal: suggesting an approach, option, hypothesis, or plan before trying it.\n"
            "    - trial: actively trying, changing, testing, checking, logging, or experimenting.\n"
            "    - result: reporting what happened after a trial, including success, failure, or observed effect.\n"
            "    - insight: extracting root cause, lesson learned, design conclusion, or general principle.\n"
            "14. Distinguish carefully between these phases. For example, 'maybe nginx is stripping the prefix' is proposal, 'I changed proxy_pass and rebuilt' is trial, 'the 404 disappeared' is result, and 'the root cause was prefix stripping by the outer nginx' is insight.\n"
            "15. status should also be accurate:\n"
            "    - open: active unresolved problem.\n"
            "    - neutral: ongoing exploration, proposal, or trial without final outcome yet.\n"
            "    - failed: a result showing the attempt did not work or the issue remains.\n"
            "    - success: a result showing the issue was resolved or the expected behavior appeared.\n"
            "16. tags must be compact and only include fields that matter for the chosen block.\n"
            "17. Tag guidance:\n"
            "    - problem: use tags like problem, symptom, component, error_code if clear.\n"
            "    - proposal: use tags like hypothesis, candidates, target, component.\n"
            "    - trial: use tags like method, command, file, endpoint, component.\n"
            "    - result: use tags like method, result, effect, status_change.\n"
            "    - insight: use tags like root_cause, lesson, rule, architecture.\n"
            "18. Do not output vague tags. Prefer one or two precise tags over many generic ones.\n\n"
            "Negative rules:\n"
            "1. Do not append just because the session already has an open block.\n"
            "2. Do not append just because the message shares generic words like server, error, docker, devlog, devtalk, mcp, or login.\n"
            "3. Do not collapse multiple distinct work items into one block.\n"
            "4. Do not create a new block for every minor step, every shell command, or every short follow-up within the same task.\n"
            "5. Do not choose APPEND unless you can point to one clearly matching candidate block.\n"
            "6. If no candidate is a reasonable match, action must be NEW_BLOCK.\n\n"
            "Output rules:\n"
            "Return JSON only with keys action, targetBlockId, blockType, status, topic, summary, tags, score, reason.\n"
            'action must be either "APPEND" or "NEW_BLOCK".\n'
            "If action is APPEND, targetBlockId must be one of the candidate block IDs.\n"
            "If action is NEW_BLOCK, targetBlockId must be null.\n"
            "blockType must be one of problem, proposal, trial, result, insight.\n"
            "status must be one of open, neutral, failed, success.\n"
            "score must be between 0 and 1 and reflect confidence.\n"
            "reason must be a short snake_case explanation.\n\n"
            "Few-shot guidance:\n"
            "Example 1: existing block is 'login 500 after local devlog startup', current message is 'CORS origin needs update for warurulab.site'. This should be NEW_BLOCK because it is a different operational issue.\n"
            "Example 2: existing block is 'MCP 100-message test keeps appending to one block', current message is 'raise append threshold and update prompt'. This can be APPEND if the candidate block is already about the same prompt/threshold tuning work.\n"
            "Example 3: existing block is 'README deployment guide update', current message is 'add nginx reverse proxy note'. This can be APPEND if the candidate block is the README/doc update block.\n\n"
            "Example 4: existing block is 'prompt tuning for over-grouping', current message is 'the messages are now over-splitting, one block per message'. This should be APPEND because it is a follow-up observation in the same prompt-tuning thread.\n"
            "Example 5: existing block is 'local devlog login 500 bug', current message is 'checked backend log and saw null pointer in auth service'. This should be APPEND because it is the same bug investigation.\n\n"
            "Example 6: existing block is 'devlog login 500 bug investigation', current message is 'now let's update AGENT.md and deployment docs'. This should be NEW_BLOCK because documentation work is a separate blog section from the login bug.\n"
            "Example 7: existing block is 'tuning MCP prompt granularity', current message is 'we should structure blocks around blog-post-worthy core sections'. This should be APPEND because it refines the same design direction for block granularity.\n\n"
            "Example 8: message is '로컬에서 Devlog 서버를 띄웠는데 로그인 직후 500에러가 나요'. blockType should be problem, status should be open, and tags should center on the symptom and component.\n"
            "Example 9: message is 'nginx가 prefix를 strip하는 것 같아요'. blockType should be proposal, because it is still a hypothesis.\n"
            "Example 10: message is 'proxy_pass 뒤 슬래시를 제거하고 다시 빌드했어요'. blockType should be trial, because it is an active change.\n"
            "Example 11: message is '404는 없어졌지만 CSS는 아직 깨져요'. blockType should be result with failed or neutral status depending on whether the attempted fix clearly failed or only partially helped.\n"
            "Example 12: message is '원인은 outer nginx가 /devtalk prefix를 strip한 것이었어요'. blockType should be insight, because it states the root cause.\n\n"
            "---\n"
            "[input]\n"
            f"{json.dumps(payload, ensure_ascii=False)}\n"
            "---"
        )

    def _generate(self, prompt: str, format_schema: Optional[Dict[str, Any]] = None) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": format_schema
            or {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["APPEND", "NEW_BLOCK"]},
                    "score": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["action", "score", "reason"],
            },
            "options": {
                "temperature": 0,
            },
        }
        req = request.Request(
            url=f"{self.base_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=self.timeout_seconds) as response:
            body = response.read().decode("utf-8")
        decoded = json.loads(body)
        return str(decoded.get("response", "")).strip()

    def _parse_decision(self, response_text: str) -> LlmDecision:
        data = json.loads(response_text)
        action = str(data.get("action", "")).strip().upper()
        if action not in {"APPEND", "NEW_BLOCK"}:
            raise ValueError("invalid action")

        score = float(data.get("score", 0.0))
        if score < 0.0 or score > 1.0:
            raise ValueError("invalid score")

        reason = str(data.get("reason", "")).strip() or "llm_decision"
        return LlmDecision(action=action, score=score, reason=reason)

    def _fallback_decision(self, context: str) -> LlmDecision:
        # Deterministic fallback used when Ollama is unavailable or returns invalid JSON.
        if len(context) % 2 == 0:
            return LlmDecision(action="APPEND", score=0.55, reason="fallback_even_length")
        return LlmDecision(action="NEW_BLOCK", score=0.55, reason="fallback_odd_length")

    def _parse_narrative_classification(
        self,
        response_text: str,
        current_message: Mapping[str, Any],
        candidate_blocks: Sequence[Mapping[str, Any]],
    ) -> NarrativeBlockClassification:
        data = self._coerce_json_object(response_text)
        action = str(data.get("action", "")).strip().upper()
        if action not in {"APPEND", "NEW_BLOCK"}:
            raise ValueError("invalid action")

        target_block_id = data.get("targetBlockId")
        if target_block_id is not None:
            target_block_id = str(target_block_id).strip() or None

        block_type = str(data.get("blockType", "")).strip().lower()
        if block_type not in {"problem", "proposal", "trial", "result", "insight"}:
            raise ValueError("invalid blockType")

        status = str(data.get("status", "")).strip().lower()
        if status not in {"open", "neutral", "failed", "success"}:
            raise ValueError("invalid status")

        topic = str(data.get("topic", "")).strip()
        summary = str(data.get("summary", "")).strip()
        tags = data.get("tags", {})
        if tags is None:
            tags = {}
        if not isinstance(tags, dict):
            raise ValueError("invalid tags")

        score = float(data.get("score", 0.0))
        if score < 0.0 or score > 1.0:
            raise ValueError("invalid score")

        reason = str(data.get("reason", "")).strip() or "narrative_decision"
        if action == "APPEND" and not target_block_id:
            target_block_id = self._choose_candidate_block_id(candidate_blocks)
            if target_block_id is None:
                raise ValueError("missing targetBlockId")

        if action == "NEW_BLOCK":
            target_block_id = None

        return NarrativeBlockClassification(
            action=action,
            target_block_id=target_block_id,
            block_type=block_type,
            status=status,
            topic=topic or self._infer_topic(current_message),
            summary=summary or self._short_text(current_message.get("content", "")),
            tags=tags,
            score=score,
            reason=reason,
        )

    def _fallback_narrative_classification(
        self,
        current_message: Mapping[str, Any],
        candidate_blocks: Sequence[Mapping[str, Any]],
    ) -> NarrativeBlockClassification:
        inferred_block_type = self._infer_block_type(current_message)
        inferred_status = "open" if inferred_block_type == "problem" else "neutral"
        return NarrativeBlockClassification(
            action="NEW_BLOCK",
            target_block_id=None,
            block_type=inferred_block_type,
            status=inferred_status,
            topic=self._infer_topic(current_message),
            summary=self._short_text(current_message.get("content", "")),
            tags=self._infer_tags(current_message, inferred_block_type),
            score=0.5,
            reason="fallback_conservative_new_block",
        )

    def _coerce_json_object(self, response_text: str) -> Dict[str, Any]:
        text = self._strip_code_fences(str(response_text).strip())
        parsed = self._try_json_loads(text)
        if isinstance(parsed, dict):
            nested = parsed.get("response")
            if isinstance(nested, str):
                nested_text = self._strip_code_fences(nested.strip())
                nested_parsed = self._try_json_loads(nested_text)
                if isinstance(nested_parsed, dict):
                    return nested_parsed
            return parsed
        if isinstance(parsed, str):
            nested_text = self._strip_code_fences(parsed.strip())
            nested_parsed = self._try_json_loads(nested_text)
            if isinstance(nested_parsed, dict):
                return nested_parsed
        raise ValueError("invalid json response")

    def _try_json_loads(self, text: str) -> Any:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                return json.loads(text[start : end + 1])
            raise

    def _strip_code_fences(self, text: str) -> str:
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3 and lines[-1].strip() == "```":
                return "\n".join(lines[1:-1]).strip()
        return text

    def _choose_candidate_block(self, candidate_blocks: Sequence[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
        for block in candidate_blocks:
            status = self._stringify(block.get("status")).lower()
            if status in {"open", "neutral"}:
                return block
        return candidate_blocks[0] if candidate_blocks else None

    def _choose_candidate_block_id(self, candidate_blocks: Sequence[Mapping[str, Any]]) -> Optional[str]:
        candidate = self._choose_candidate_block(candidate_blocks)
        if candidate is None:
            return None
        return self._stringify(candidate.get("blockId")) or None

    def _compact_candidate_block(self, block: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "blockId": self._stringify(block.get("blockId")),
            "topic": self._stringify(block.get("topic")),
            "blockType": self._stringify(block.get("blockType")),
            "status": self._stringify(block.get("status")),
            "summary": self._stringify(block.get("summary")),
            "messageIds": self._coerce_list_of_strings(block.get("messageIds")),
            "tags": self._coerce_dict(block.get("tags")),
        }

    def _compact_mapping(self, mapping: Mapping[str, Any]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in mapping.items():
            if value is None:
                continue
            if isinstance(value, (str, int, float, bool)):
                result[str(key)] = value
            elif isinstance(value, dict):
                result[str(key)] = self._coerce_dict(value)
            elif isinstance(value, (list, tuple)):
                result[str(key)] = self._coerce_list(value)
            else:
                result[str(key)] = self._stringify(value)
        return result

    def _coerce_dict(self, value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        return {str(key): self._coerce_value(item) for key, item in value.items() if item is not None}

    def _coerce_list(self, value: Any) -> List[Any]:
        if not isinstance(value, (list, tuple)):
            return []
        return [self._coerce_value(item) for item in value if item is not None]

    def _coerce_list_of_strings(self, value: Any) -> List[str]:
        if not isinstance(value, (list, tuple)):
            return []
        result: List[str] = []
        for item in value:
            text = self._stringify(item)
            if text:
                result.append(text)
        return result

    def _coerce_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            return self._coerce_dict(value)
        if isinstance(value, (list, tuple)):
            return self._coerce_list(value)
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return self._stringify(value)

    def _stringify(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        return str(value).strip()

    def _infer_topic(self, current_message: Mapping[str, Any]) -> str:
        content = self._stringify(current_message.get("content"))
        return self._short_text(content)

    def _short_text(self, value: Any) -> str:
        text = self._stringify(value)
        if not text:
            return ""
        text = " ".join(text.split())
        return text[:160]

    def _infer_block_type(self, current_message: Mapping[str, Any]) -> str:
        content = self._stringify(current_message.get("content")).lower()
        if any(keyword in content for keyword in ("solution", "fix", "resolved", "해결", "수정", "조치")):
            return "result"
        if any(keyword in content for keyword in ("try", "attempt", "test", "시도", "테스트", "확인", "변경")):
            return "trial"
        if any(keyword in content for keyword in ("because", "root cause", "원인", "insight", "결국")):
            return "insight"
        if any(keyword in content for keyword in ("maybe", "suggest", "proposal", "제안", "추천")):
            return "proposal"
        return "problem"

    def _infer_tags(self, current_message: Mapping[str, Any], block_type: str) -> Dict[str, object]:
        content = self._short_text(current_message.get("content"))
        if block_type == "result":
            return {"method": content, "result": "unknown"}
        if block_type == "trial":
            return {"method": content}
        if block_type == "proposal":
            return {"candidates": [content] if content else []}
        if block_type == "insight":
            return {"root_cause": content, "lesson": ""}
        return {"problem": content}
