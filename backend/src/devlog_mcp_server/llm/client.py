from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib import error, request


@dataclass
class LlmDecision:
    action: str
    score: float
    reason: str


@dataclass
class NarrativeRouteDecision:
    action: str
    target_block_id: Optional[str]
    score: float
    reason: str


@dataclass
class NarrativeMetadataDecision:
    block_type: str
    status: str
    topic: str
    summary: str
    tags: Dict[str, object]


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


DEFAULT_APPEND_PROMPT_TEMPLATE = (
    "You decide whether a new message should be appended to the current session block.\n"
    "Return JSON only with keys action, score, reason.\n"
    'action must be either "APPEND" or "NEW_BLOCK".\n'
    "score must be a float between 0 and 1.\n"
    "reason must be a short snake_case string.\n\n"
    "{{CONTEXT}}"
)


DEFAULT_ROUTE_PROMPT_TEMPLATE = (
    "You are a block router.\n\n"
    "Task:\n"
    "Decide APPEND or NEW_BLOCK for currentMessage.\n\n"
    "Rule:\n"
    "One block = one ongoing issue.\n"
    "Do not create one block per message.\n"
    "If currentMessage continues the same issue, choose APPEND.\n"
    "If currentMessage starts a different issue, choose NEW_BLOCK.\n"
    "If uncertain, choose APPEND.\n\n"
    "Return JSON only:\n"
    "action, targetBlockId, score, reason\n\n"
    "Rules:\n"
    "- action = APPEND or NEW_BLOCK\n"
    "- if APPEND, targetBlockId must be one candidate block id\n"
    "- if NEW_BLOCK, targetBlockId must be null\n"
    "- score = 0 to 1\n"
    "- reason = short snake_case\n\n"
    "[input]\n"
    "{{PAYLOAD_JSON}}"
)


DEFAULT_METADATA_PROMPT_TEMPLATE = (
    "You build narrative block metadata.\n\n"
    "Task:\n"
    "Use currentMessage and routeDecision to fill block metadata.\n\n"
    "Return JSON only:\n"
    "blockType, status, topic, summary, tags\n\n"
    "Rules:\n"
    "- blockType = problem | proposal | trial | result | insight\n"
    "- status = open | neutral | failed | success\n"
    "- topic = short and concrete\n"
    "- summary = one sentence\n"
    "- tags = compact object\n"
    "- if routeDecision.action is APPEND, keep metadata aligned with the selected block unless the message clearly updates status or result\n\n"
    "[input]\n"
    "{{PAYLOAD_JSON}}"
)


class LlmClient:
    def __init__(
        self,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        legacy_model = model or os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
        legacy_timeout = timeout_seconds or os.getenv("OLLAMA_TIMEOUT_SECONDS", "30")

        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.route_model = os.getenv("OLLAMA_ROUTE_MODEL", legacy_model)
        self.metadata_model = os.getenv("OLLAMA_METADATA_MODEL", legacy_model)
        self.route_timeout_seconds = float(os.getenv("OLLAMA_ROUTE_TIMEOUT_SECONDS", str(legacy_timeout)))
        self.metadata_timeout_seconds = float(os.getenv("OLLAMA_METADATA_TIMEOUT_SECONDS", str(legacy_timeout)))
        self.model = f"route:{self.route_model}|metadata:{self.metadata_model}"

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
                model=self.route_model,
                timeout_seconds=self.route_timeout_seconds,
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
            route_decision = self.classify_narrative_route(
                current_message=current_message,
                candidate_blocks=candidate_blocks,
                recent_messages=recent_messages,
                session_id=session_id,
            )
        except (ValueError, error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            return self._fallback_narrative_classification(current_message, candidate_blocks)

        try:
            metadata_decision = self.classify_narrative_metadata(
                current_message=current_message,
                candidate_blocks=candidate_blocks,
                recent_messages=recent_messages,
                session_id=session_id,
                route_decision=route_decision,
            )
        except (ValueError, error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            metadata_decision = self._fallback_metadata_decision(
                current_message=current_message,
                candidate_blocks=candidate_blocks,
                route_decision=route_decision,
            )

        return NarrativeBlockClassification(
            action=route_decision.action,
            target_block_id=route_decision.target_block_id,
            block_type=metadata_decision.block_type,
            status=metadata_decision.status,
            topic=metadata_decision.topic,
            summary=metadata_decision.summary,
            tags=metadata_decision.tags,
            score=route_decision.score,
            reason=route_decision.reason,
        )

    def classify_narrative_route(
        self,
        current_message: Mapping[str, Any],
        candidate_blocks: Sequence[Mapping[str, Any]],
        recent_messages: Sequence[Mapping[str, Any]] = (),
        session_id: Optional[str] = None,
    ) -> NarrativeRouteDecision:
        prompt = self._build_route_prompt(current_message, candidate_blocks, recent_messages, session_id)
        response_text = self._generate_with_schema(
            prompt,
            {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["APPEND", "NEW_BLOCK"]},
                    "targetBlockId": {"type": ["string", "null"]},
                    "score": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["action", "score", "reason"],
            },
            model=self.route_model,
            timeout_seconds=self.route_timeout_seconds,
        )
        return self._parse_route_decision(response_text, candidate_blocks)

    def classify_narrative_metadata(
        self,
        *,
        current_message: Mapping[str, Any],
        candidate_blocks: Sequence[Mapping[str, Any]],
        recent_messages: Sequence[Mapping[str, Any]] = (),
        session_id: Optional[str] = None,
        route_decision: NarrativeRouteDecision,
    ) -> NarrativeMetadataDecision:
        prompt = self._build_metadata_prompt(
            current_message=current_message,
            candidate_blocks=candidate_blocks,
            recent_messages=recent_messages,
            session_id=session_id,
            route_decision=route_decision,
        )
        response_text = self._generate_with_schema(
            prompt,
            {
                "type": "object",
                "properties": {
                    "blockType": {"type": "string", "enum": ["problem", "proposal", "trial", "result", "insight"]},
                    "status": {"type": "string", "enum": ["open", "neutral", "failed", "success"]},
                    "topic": {"type": "string"},
                    "summary": {"type": "string"},
                    "tags": {"type": "object"},
                },
                "required": ["blockType", "status", "topic", "summary", "tags"],
            },
            model=self.metadata_model,
            timeout_seconds=self.metadata_timeout_seconds,
        )
        return self._parse_metadata_decision(response_text)

    def fallback_narrative_metadata(
        self,
        *,
        current_message: Mapping[str, Any],
        candidate_blocks: Sequence[Mapping[str, Any]],
        route_decision: NarrativeRouteDecision,
    ) -> NarrativeMetadataDecision:
        return self._fallback_metadata_decision(
            current_message=current_message,
            candidate_blocks=candidate_blocks,
            route_decision=route_decision,
        )

    def _generate_with_schema(
        self,
        prompt: str,
        format_schema: Dict[str, Any],
        *,
        model: str,
        timeout_seconds: float,
    ) -> str:
        try:
            return self._generate(
                prompt,
                format_schema=format_schema,
                model=model,
                timeout_seconds=timeout_seconds,
            )
        except TypeError:
            return self._generate(prompt)

    def _build_prompt(self, context: str) -> str:
        template = self._resolve_prompt_template(
            file_env_name="MCP_APPEND_PROMPT_FILE",
            text_env_name="MCP_APPEND_PROMPT_TEMPLATE",
            default_template=DEFAULT_APPEND_PROMPT_TEMPLATE,
        )
        return template.replace("{{CONTEXT}}", context)

    def _build_route_prompt(
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
        template = self._resolve_prompt_template(
            file_env_name="MCP_ROUTE_PROMPT_FILE",
            text_env_name="MCP_ROUTE_PROMPT_TEMPLATE",
            default_template=DEFAULT_ROUTE_PROMPT_TEMPLATE,
            legacy_file_env_name="MCP_NARRATIVE_PROMPT_FILE",
            legacy_text_env_name="MCP_NARRATIVE_PROMPT_TEMPLATE",
        )
        return template.replace("{{PAYLOAD_JSON}}", json.dumps(payload, ensure_ascii=False))

    def _build_metadata_prompt(
        self,
        *,
        current_message: Mapping[str, Any],
        candidate_blocks: Sequence[Mapping[str, Any]],
        recent_messages: Sequence[Mapping[str, Any]],
        session_id: Optional[str],
        route_decision: NarrativeRouteDecision,
    ) -> str:
        selected_candidate = None
        if route_decision.target_block_id:
            selected_candidate = self._find_candidate_block(candidate_blocks, route_decision.target_block_id)
        payload = {
            "sessionId": session_id,
            "routeDecision": {
                "action": route_decision.action,
                "targetBlockId": route_decision.target_block_id,
                "score": route_decision.score,
                "reason": route_decision.reason,
            },
            "currentMessage": self._compact_mapping(current_message),
            "selectedCandidateBlock": self._compact_candidate_block(selected_candidate) if selected_candidate else None,
            "recentMessages": [self._compact_mapping(message) for message in recent_messages],
        }
        template = self._resolve_prompt_template(
            file_env_name="MCP_METADATA_PROMPT_FILE",
            text_env_name="MCP_METADATA_PROMPT_TEMPLATE",
            default_template=DEFAULT_METADATA_PROMPT_TEMPLATE,
        )
        return template.replace("{{PAYLOAD_JSON}}", json.dumps(payload, ensure_ascii=False))

    def _resolve_prompt_template(
        self,
        *,
        file_env_name: str,
        text_env_name: str,
        default_template: str,
        legacy_file_env_name: Optional[str] = None,
        legacy_text_env_name: Optional[str] = None,
    ) -> str:
        file_path = os.getenv(file_env_name, "").strip()
        if not file_path and legacy_file_env_name:
            file_path = os.getenv(legacy_file_env_name, "").strip()
        if file_path:
            try:
                loaded = self._read_prompt_file(file_path)
                if loaded:
                    return loaded
            except OSError:
                pass

        inline_template = os.getenv(text_env_name, "")
        if not inline_template.strip() and legacy_text_env_name:
            inline_template = os.getenv(legacy_text_env_name, "")
        if inline_template.strip():
            return inline_template

        return default_template

    def _read_prompt_file(self, file_path: str) -> str:
        path = Path(file_path)
        return path.read_text(encoding="utf-8").strip()

    def _generate(
        self,
        prompt: str,
        format_schema: Optional[Dict[str, Any]] = None,
        *,
        model: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> str:
        payload = {
            "model": model or self.route_model,
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
        with request.urlopen(req, timeout=timeout_seconds or self.route_timeout_seconds) as response:
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
        if len(context) % 2 == 0:
            return LlmDecision(action="APPEND", score=0.55, reason="fallback_even_length")
        return LlmDecision(action="NEW_BLOCK", score=0.55, reason="fallback_odd_length")

    def _parse_route_decision(
        self,
        response_text: str,
        candidate_blocks: Sequence[Mapping[str, Any]],
    ) -> NarrativeRouteDecision:
        data = self._coerce_json_object(response_text)
        action = str(data.get("action", "")).strip().upper()
        if action not in {"APPEND", "NEW_BLOCK"}:
            raise ValueError("invalid action")

        target_block_id = data.get("targetBlockId")
        if target_block_id is not None:
            target_block_id = str(target_block_id).strip() or None

        score = float(data.get("score", 0.0))
        if score < 0.0 or score > 1.0:
            raise ValueError("invalid score")

        reason = str(data.get("reason", "")).strip() or "route_decision"
        if action == "APPEND" and not target_block_id:
            target_block_id = self._choose_candidate_block_id(candidate_blocks)
            if target_block_id is None:
                raise ValueError("missing targetBlockId")

        if action == "NEW_BLOCK":
            target_block_id = None

        return NarrativeRouteDecision(
            action=action,
            target_block_id=target_block_id,
            score=score,
            reason=reason,
        )

    def _parse_metadata_decision(self, response_text: str) -> NarrativeMetadataDecision:
        data = self._coerce_json_object(response_text)
        return NarrativeMetadataDecision(
            block_type=self._normalize_block_type(self._stringify(data.get("blockType"))),
            status=self._normalize_status(self._stringify(data.get("status"))),
            topic=self._stringify(data.get("topic")),
            summary=self._stringify(data.get("summary")),
            tags=self._coerce_dict(data.get("tags")),
        )

    def _fallback_metadata_decision(
        self,
        *,
        current_message: Mapping[str, Any],
        candidate_blocks: Sequence[Mapping[str, Any]],
        route_decision: NarrativeRouteDecision,
    ) -> NarrativeMetadataDecision:
        candidate = None
        if route_decision.action == "APPEND" and route_decision.target_block_id:
            candidate = self._find_candidate_block(candidate_blocks, route_decision.target_block_id)
        if candidate is not None:
            block_type = self._normalize_block_type(self._stringify(candidate.get("blockType")))
            return NarrativeMetadataDecision(
                block_type=block_type,
                status=self._normalize_status(self._stringify(candidate.get("status"))),
                topic=self._stringify(candidate.get("topic")) or self._infer_topic(current_message),
                summary=self._stringify(candidate.get("summary")) or self._short_text(current_message.get("content", "")),
                tags=self._coerce_dict(candidate.get("tags")) or self._infer_tags(current_message, block_type),
            )

        block_type = self._infer_block_type(current_message)
        return NarrativeMetadataDecision(
            block_type=block_type,
            status=self._infer_status(current_message, block_type),
            topic=self._infer_topic(current_message),
            summary=self._short_text(current_message.get("content", "")),
            tags=self._infer_tags(current_message, block_type),
        )

    def _fallback_narrative_classification(
        self,
        current_message: Mapping[str, Any],
        candidate_blocks: Sequence[Mapping[str, Any]],
    ) -> NarrativeBlockClassification:
        metadata = self._fallback_metadata_decision(
            current_message=current_message,
            candidate_blocks=candidate_blocks,
            route_decision=NarrativeRouteDecision(
                action="NEW_BLOCK",
                target_block_id=None,
                score=0.5,
                reason="fallback_conservative_new_block",
            ),
        )
        return NarrativeBlockClassification(
            action="NEW_BLOCK",
            target_block_id=None,
            block_type=metadata.block_type,
            status=metadata.status,
            topic=metadata.topic,
            summary=metadata.summary,
            tags=metadata.tags,
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

    def _find_candidate_block(
        self,
        candidate_blocks: Sequence[Mapping[str, Any]],
        block_id: str,
    ) -> Optional[Mapping[str, Any]]:
        for candidate in candidate_blocks:
            if self._stringify(candidate.get("blockId")) == block_id:
                return candidate
        return None

    def _compact_candidate_block(self, block: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
        if block is None:
            return None
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
        if any(keyword in content for keyword in ("solution", "fix", "resolved", "solved", "worked", "success")):
            return "result"
        if any(keyword in content for keyword in ("try", "attempt", "test", "check", "change", "update", "debug")):
            return "trial"
        if any(keyword in content for keyword in ("because", "root cause", "insight", "lesson", "therefore")):
            return "insight"
        if any(keyword in content for keyword in ("maybe", "suggest", "proposal", "plan", "should", "could")):
            return "proposal"
        return "problem"

    def _infer_status(self, current_message: Mapping[str, Any], block_type: str) -> str:
        content = self._stringify(current_message.get("content")).lower()
        if block_type == "result":
            if any(keyword in content for keyword in ("fail", "failed", "error", "broken", "did not", "didn't", "not work")):
                return "failed"
            return "success"
        if block_type == "problem":
            return "open"
        return "neutral"

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

    def _normalize_block_type(self, value: str) -> str:
        return value if value in {"problem", "proposal", "trial", "result", "insight"} else "proposal"

    def _normalize_status(self, value: str) -> str:
        return value if value in {"open", "neutral", "failed", "success"} else "neutral"
