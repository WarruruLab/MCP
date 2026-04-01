from __future__ import annotations

from dataclasses import dataclass, field, replace
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from mcp.utils.validate import normalize_role


_TOKEN_RE = re.compile(r"[A-Za-z0-9_가-힣]+")

_PROBLEM_KEYWORDS = (
    "error",
    "exception",
    "fail",
    "failed",
    "timeout",
    "bug",
    "issue",
    "문제",
    "오류",
    "에러",
    "실패",
)
_PROPOSAL_KEYWORDS = (
    "maybe",
    "could",
    "should",
    "suggest",
    "proposal",
    "consider",
    "제안",
    "생각",
    "해보자",
)
_TRIAL_KEYWORDS = (
    "try",
    "trying",
    "attempt",
    "attempted",
    "check",
    "checked",
    "test",
    "tested",
    "change",
    "changed",
    "install",
    "installed",
    "설정",
    "확인",
    "시도",
    "테스트",
    "변경",
    "설치",
)
_RESULT_SUCCESS_KEYWORDS = (
    "fixed",
    "resolve",
    "resolved",
    "solved",
    "success",
    "worked",
    "해결",
    "수정",
    "조치",
)
_RESULT_FAIL_KEYWORDS = (
    "failed",
    "still",
    "error",
    "exception",
    "not working",
    "안됨",
    "실패",
)
_INSIGHT_KEYWORDS = (
    "because",
    "root cause",
    "caused by",
    "therefore",
    "원인",
    "결국",
    "때문",
)

_ALLOWED_BLOCK_TYPES = {"problem", "proposal", "trial", "result", "insight"}
_ALLOWED_STATUSES = {"open", "neutral", "failed", "success"}


@dataclass(frozen=True)
class NarrativeMessage:
    message_id: str
    role: str
    content: str
    timestamp: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "NarrativeMessage":
        return cls(
            message_id=str(value.get("messageId", "")).strip(),
            role=normalize_role(str(value.get("role", "")).strip()),
            content=str(value.get("content", "")).strip(),
            timestamp=str(value.get("timestamp", "")).strip(),
        )

    def as_dict(self) -> Dict[str, str]:
        return {
            "messageId": self.message_id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
        }


@dataclass
class NarrativeBlock:
    block_id: str
    session_id: str
    topic: str = ""
    block_type: str = "proposal"
    status: str = "neutral"
    summary: str = ""
    message_ids: List[str] = field(default_factory=list)
    tags: Dict[str, object] = field(default_factory=dict)
    tail_messages: List[NarrativeMessage] = field(default_factory=list)
    parent_block_id: Optional[str] = None
    related_block_ids: List[str] = field(default_factory=list)
    metadata: Dict[str, object] = field(default_factory=dict)

    def clone(self) -> "NarrativeBlock":
        return replace(
            self,
            message_ids=list(self.message_ids),
            tags=_clone_mapping(self.tags),
            tail_messages=[replace(m) for m in self.tail_messages],
            related_block_ids=list(self.related_block_ids),
            metadata=_clone_mapping(self.metadata),
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "NarrativeBlock":
        tail_messages_raw = value.get("tailMessages", []) or []
        tail_messages = [
            NarrativeMessage.from_mapping(item)
            for item in tail_messages_raw
            if isinstance(item, Mapping)
        ]
        return cls(
            block_id=str(value.get("blockId", "")).strip(),
            session_id=str(value.get("sessionId", "")).strip(),
            topic=str(value.get("topic", "")).strip(),
            block_type=_normalize_choice(str(value.get("blockType", "proposal")).strip(), _ALLOWED_BLOCK_TYPES, "proposal"),
            status=_normalize_choice(str(value.get("status", "neutral")).strip(), _ALLOWED_STATUSES, "neutral"),
            summary=str(value.get("summary", "")).strip(),
            message_ids=_normalize_string_list(value.get("messageIds", [])),
            tags=_clone_mapping(value.get("tags", {})),
            tail_messages=tail_messages,
            parent_block_id=_optional_string(value.get("parentBlockId")),
            related_block_ids=_normalize_string_list(value.get("relatedBlockIds", [])),
            metadata=_clone_mapping(value.get("metadata", {})),
        )

    def as_dict(self) -> Dict[str, object]:
        return {
            "blockId": self.block_id,
            "sessionId": self.session_id,
            "topic": self.topic,
            "blockType": self.block_type,
            "status": self.status,
            "summary": self.summary,
            "messageIds": list(self.message_ids),
            "tags": _clone_mapping(self.tags),
            "tailMessages": [message.as_dict() for message in self.tail_messages],
            "parentBlockId": self.parent_block_id,
            "relatedBlockIds": list(self.related_block_ids),
            "metadata": _clone_mapping(self.metadata),
        }


@dataclass(frozen=True)
class BlockScore:
    block_id: str
    score: float
    reason: str


@dataclass(frozen=True)
class RoutingDecision:
    action: str
    target_block_id: Optional[str]
    score: float
    reason: str
    block_type: str
    status: str
    topic: str
    summary: str
    tags: Dict[str, object]
    candidate_scores: List[BlockScore] = field(default_factory=list)

    def as_dict(self) -> Dict[str, object]:
        return {
            "action": self.action,
            "targetBlockId": self.target_block_id,
            "score": self.score,
            "reason": self.reason,
            "blockType": self.block_type,
            "status": self.status,
            "topic": self.topic,
            "summary": self.summary,
            "tags": _clone_mapping(self.tags),
            "candidateScores": [
                {"blockId": item.block_id, "score": item.score, "reason": item.reason}
                for item in self.candidate_scores
            ],
        }


@dataclass(frozen=True)
class RoutingResult:
    session_id: str
    blocks: List[NarrativeBlock]
    message_to_block: Dict[str, str]
    active_block_id: Optional[str]
    decision: RoutingDecision

    def as_dict(self) -> Dict[str, object]:
        return {
            "sessionId": self.session_id,
            "blocks": [block.as_dict() for block in self.blocks],
            "messageToBlock": dict(self.message_to_block),
            "activeBlockId": self.active_block_id,
            "decision": self.decision.as_dict(),
        }


def apply_routing_decision(
    session_id: str,
    current_message: Mapping[str, Any] | NarrativeMessage,
    candidate_blocks: Sequence[Mapping[str, Any] | NarrativeBlock],
    decision: Mapping[str, Any] | RoutingDecision,
    *,
    tail_limit: int = 6,
    existing_message_to_block: Optional[Mapping[str, str]] = None,
) -> RoutingResult:
    message = coerce_message(current_message)
    candidates = [coerce_block(block) for block in candidate_blocks]
    message_to_block = dict(existing_message_to_block or {})
    resolved = _coerce_routing_decision(decision)

    if message.message_id and message.message_id in message_to_block:
        return RoutingResult(
            session_id=session_id,
            blocks=[block.clone() for block in candidates],
            message_to_block=message_to_block,
            active_block_id=message_to_block[message.message_id],
            decision=resolved,
        )

    if resolved.action == "APPEND" and resolved.target_block_id:
        updated_blocks: List[NarrativeBlock] = []
        appended = False
        for block in candidates:
            if block.block_id != resolved.target_block_id:
                updated_blocks.append(block.clone())
                continue
            updated_blocks.append(
                _append_message_to_block_by_decision(
                    block,
                    message,
                    resolved,
                    tail_limit=tail_limit,
                )
            )
            appended = True

        if appended:
            if message.message_id:
                message_to_block[message.message_id] = resolved.target_block_id
            return RoutingResult(
                session_id=session_id,
                blocks=updated_blocks,
                message_to_block=message_to_block,
                active_block_id=resolved.target_block_id,
                decision=resolved,
            )

    new_block = _create_new_block_from_decision(session_id, candidates, message, resolved, tail_limit=tail_limit)
    updated_blocks = [block.clone() for block in candidates] + [new_block]
    if message.message_id:
        message_to_block[message.message_id] = new_block.block_id
    final_decision = RoutingDecision(
        action="NEW_BLOCK",
        target_block_id=None,
        score=resolved.score,
        reason=resolved.reason,
        block_type=resolved.block_type,
        status=resolved.status,
        topic=resolved.topic,
        summary=resolved.summary,
        tags=_clone_mapping(resolved.tags),
        candidate_scores=resolved.candidate_scores,
    )
    return RoutingResult(
        session_id=session_id,
        blocks=updated_blocks,
        message_to_block=message_to_block,
        active_block_id=new_block.block_id,
        decision=final_decision,
    )


def route_message(
    session_id: str,
    current_message: Mapping[str, Any] | NarrativeMessage,
    candidate_blocks: Sequence[Mapping[str, Any] | NarrativeBlock],
    recent_messages: Sequence[Mapping[str, Any] | NarrativeMessage],
    *,
    append_threshold: float = 0.40,
    tail_limit: int = 6,
    existing_message_to_block: Optional[Mapping[str, str]] = None,
) -> RoutingResult:
    message = coerce_message(current_message)
    candidates = [coerce_block(block) for block in candidate_blocks]
    recent = [coerce_message(message_item) for message_item in recent_messages]
    message_to_block = dict(existing_message_to_block or {})

    if message.message_id and message.message_id in message_to_block:
        blocks = [block.clone() for block in candidates]
        decision = RoutingDecision(
            action="APPEND",
            target_block_id=message_to_block[message.message_id],
            score=1.0,
            reason="already_routed",
            block_type="proposal",
            status="neutral",
            topic="",
            summary="",
            tags={},
        )
        return RoutingResult(
            session_id=session_id,
            blocks=blocks,
            message_to_block=message_to_block,
            active_block_id=message_to_block[message.message_id],
            decision=decision,
        )

    profile = infer_narrative_profile(message)
    scored_candidates = rank_candidate_blocks(message, profile, candidates, recent)
    best_candidate = scored_candidates[0] if scored_candidates else None

    if best_candidate is not None and best_candidate.score >= append_threshold:
        updated_blocks: List[NarrativeBlock] = []
        selected_block_id = best_candidate.block_id
        selected_block = get_block_by_id(candidates, selected_block_id)
        active_block_id = selected_block_id
        decision = RoutingDecision(
            action="APPEND",
            target_block_id=selected_block_id,
            score=best_candidate.score,
            reason=best_candidate.reason,
            block_type=_coalesce_choice(profile["blockType"], selected_block.block_type, "proposal"),
            status=_coalesce_choice(profile["status"], selected_block.status, "neutral"),
            topic=_coalesce_choice(profile["topic"], selected_block.topic, ""),
            summary=_coalesce_choice(profile["summary"], selected_block.summary, ""),
            tags=_merge_tags(selected_block.tags, profile["tags"]),
            candidate_scores=scored_candidates,
        )
        for block in candidates:
            if block.block_id != selected_block_id:
                updated_blocks.append(block.clone())
                continue
            updated_blocks.append(
                _append_message_to_block(
                    block,
                    message,
                    profile,
                    tail_limit=tail_limit,
                )
            )
        message_to_block[message.message_id] = selected_block_id
        return RoutingResult(
            session_id=session_id,
            blocks=updated_blocks,
            message_to_block=message_to_block,
            active_block_id=active_block_id,
            decision=decision,
        )

    new_block = _create_new_block(session_id, candidates, message, profile, tail_limit=tail_limit)
    updated_blocks = [block.clone() for block in candidates] + [new_block]
    message_to_block[message.message_id] = new_block.block_id
    decision = RoutingDecision(
        action="NEW_BLOCK",
        target_block_id=None,
        score=best_candidate.score if best_candidate is not None else 1.0,
        reason=best_candidate.reason if best_candidate is not None else "no_candidate",
        block_type=new_block.block_type,
        status=new_block.status,
        topic=new_block.topic,
        summary=new_block.summary,
        tags=_clone_mapping(new_block.tags),
        candidate_scores=scored_candidates,
    )
    return RoutingResult(
        session_id=session_id,
        blocks=updated_blocks,
        message_to_block=message_to_block,
        active_block_id=new_block.block_id,
        decision=decision,
    )


def coerce_message(value: Mapping[str, Any] | NarrativeMessage) -> NarrativeMessage:
    if isinstance(value, NarrativeMessage):
        return value
    return NarrativeMessage.from_mapping(value)


def coerce_block(value: Mapping[str, Any] | NarrativeBlock) -> NarrativeBlock:
    if isinstance(value, NarrativeBlock):
        return value.clone()
    return NarrativeBlock.from_mapping(value)


def rank_candidate_blocks(
    current_message: NarrativeMessage,
    profile: Mapping[str, object],
    candidate_blocks: Sequence[NarrativeBlock],
    recent_messages: Sequence[NarrativeMessage],
) -> List[BlockScore]:
    recent_context = _joined_message_text(recent_messages)
    scored: List[BlockScore] = []
    for block in candidate_blocks:
        candidate_text = _block_search_text(block)
        current_score = _jaccard_similarity(current_message.content, candidate_text)
        recent_score = _jaccard_similarity(current_message.content, recent_context)
        type_score = _block_type_alignment(str(profile["blockType"]), block.block_type)
        status_score = 0.10 if block.status in {"open", "neutral"} else 0.0
        topic_score = _topic_alignment(str(profile["topic"]), block.topic)
        score = round(
            (0.48 * current_score)
            + (0.20 * recent_score)
            + (0.20 * type_score)
            + (0.07 * status_score)
            + (0.05 * topic_score),
            4,
        )
        reason = _compose_reason(current_score, recent_score, type_score, topic_score, block.block_type)
        scored.append(BlockScore(block_id=block.block_id, score=score, reason=reason))
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored


def infer_narrative_profile(message: NarrativeMessage) -> Dict[str, object]:
    content = message.content
    normalized = _normalize_text(content)
    summary = _to_summary_line(content)
    topic = summary[:120]
    block_type = "proposal"
    status = "neutral"
    tags: Dict[str, object] = {}

    if _contains_keyword(normalized, _PROBLEM_KEYWORDS):
        block_type = "problem"
        status = "open"
        tags["problem"] = summary
        topic = _extract_topic(summary, content)
    elif _contains_keyword(normalized, _RESULT_SUCCESS_KEYWORDS):
        block_type = "result"
        status = "success"
        tags["result"] = "success"
        tags["method"] = summary
        topic = _extract_topic(summary, content)
    elif _contains_keyword(normalized, _RESULT_FAIL_KEYWORDS):
        block_type = "result"
        status = "failed"
        tags["result"] = "failed"
        tags["method"] = summary
        topic = _extract_topic(summary, content)
    elif _contains_keyword(normalized, _TRIAL_KEYWORDS):
        block_type = "trial"
        status = "neutral"
        tags["method"] = summary
        topic = _extract_topic(summary, content)
    elif _contains_keyword(normalized, _INSIGHT_KEYWORDS):
        block_type = "insight"
        status = "neutral"
        tags["root_cause"] = summary
        topic = _extract_topic(summary, content)
    elif _contains_keyword(normalized, _PROPOSAL_KEYWORDS):
        block_type = "proposal"
        status = "neutral"
        tags["candidates"] = [summary] if summary else []
        topic = _extract_topic(summary, content)
    else:
        tags["note"] = summary

    if not summary:
        summary = content.strip()[:160]

    return {
        "blockType": block_type,
        "status": status,
        "topic": topic,
        "summary": summary,
        "tags": tags,
    }


def _create_new_block(
    session_id: str,
    existing_blocks: Sequence[NarrativeBlock],
    message: NarrativeMessage,
    profile: Mapping[str, object],
    *,
    tail_limit: int,
) -> NarrativeBlock:
    block_id = _build_block_id(session_id, existing_blocks)
    tags = _clone_mapping(profile["tags"])
    return NarrativeBlock(
        block_id=block_id,
        session_id=session_id,
        topic=str(profile["topic"]),
        block_type=str(profile["blockType"]),
        status=str(profile["status"]),
        summary=str(profile["summary"]),
        message_ids=[message.message_id] if message.message_id else [],
        tags=tags,
        tail_messages=[message] if message.message_id else [],
        metadata={
            "source": "realtime_router",
            "tailLimit": tail_limit,
        },
    )


def _create_new_block_from_decision(
    session_id: str,
    existing_blocks: Sequence[NarrativeBlock],
    message: NarrativeMessage,
    decision: RoutingDecision,
    *,
    tail_limit: int,
) -> NarrativeBlock:
    block_id = _build_block_id(session_id, existing_blocks)
    return NarrativeBlock(
        block_id=block_id,
        session_id=session_id,
        topic=decision.topic,
        block_type=decision.block_type,
        status=decision.status,
        summary=decision.summary,
        message_ids=[message.message_id] if message.message_id else [],
        tags=_clone_mapping(decision.tags),
        tail_messages=[message] if message.message_id else [],
        metadata={
            "source": "llm_routing_decision",
            "tailLimit": tail_limit,
            "reason": decision.reason,
            "score": decision.score,
        },
    )


def _append_message_to_block(
    block: NarrativeBlock,
    message: NarrativeMessage,
    profile: Mapping[str, object],
    *,
    tail_limit: int,
) -> NarrativeBlock:
    merged_tags = _merge_tags(block.tags, profile["tags"])
    merged_tail = list(block.tail_messages) + [message]
    if tail_limit > 0:
        merged_tail = merged_tail[-tail_limit:]

    summary = block.summary
    if not summary:
        summary = str(profile["summary"])

    topic = block.topic or str(profile["topic"])
    block_type = block.block_type or str(profile["blockType"])
    status = block.status or str(profile["status"])
    if status == "neutral" and str(profile["status"]) in {"success", "failed"}:
        status = str(profile["status"])

    message_ids = list(block.message_ids)
    if message.message_id and message.message_id not in message_ids:
        message_ids.append(message.message_id)

    return NarrativeBlock(
        block_id=block.block_id,
        session_id=block.session_id,
        topic=topic,
        block_type=block_type,
        status=status,
        summary=summary,
        message_ids=message_ids,
        tags=merged_tags,
        tail_messages=merged_tail,
        parent_block_id=block.parent_block_id,
        related_block_ids=list(block.related_block_ids),
        metadata=_clone_mapping(block.metadata),
    )


def _append_message_to_block_by_decision(
    block: NarrativeBlock,
    message: NarrativeMessage,
    decision: RoutingDecision,
    *,
    tail_limit: int,
) -> NarrativeBlock:
    merged_tail = list(block.tail_messages) + [message]
    if tail_limit > 0:
        merged_tail = merged_tail[-tail_limit:]

    message_ids = list(block.message_ids)
    if message.message_id and message.message_id not in message_ids:
        message_ids.append(message.message_id)

    metadata = _clone_mapping(block.metadata)
    metadata["lastRoutingReason"] = decision.reason
    metadata["lastRoutingScore"] = decision.score

    return NarrativeBlock(
        block_id=block.block_id,
        session_id=block.session_id,
        topic=decision.topic or block.topic,
        block_type=decision.block_type or block.block_type,
        status=decision.status or block.status,
        summary=decision.summary or block.summary,
        message_ids=message_ids,
        tags=_merge_tags(block.tags, decision.tags),
        tail_messages=merged_tail,
        parent_block_id=block.parent_block_id,
        related_block_ids=list(block.related_block_ids),
        metadata=metadata,
    )


def get_block_by_id(blocks: Sequence[NarrativeBlock], block_id: str) -> NarrativeBlock:
    for block in blocks:
        if block.block_id == block_id:
            return block
    raise KeyError(block_id)


def _build_block_id(session_id: str, blocks: Sequence[NarrativeBlock]) -> str:
    prefix = f"blk_{session_id}_"
    max_suffix = 0
    for block in blocks:
        if not block.block_id.startswith(prefix):
            continue
        suffix = block.block_id[len(prefix) :]
        if suffix.isdigit():
            max_suffix = max(max_suffix, int(suffix))
    return f"{prefix}{max_suffix + 1}"


def _block_search_text(block: NarrativeBlock) -> str:
    parts: List[str] = [block.topic, block.summary, block.block_type, block.status]
    for value in block.tags.values():
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
        elif isinstance(value, dict):
            parts.extend(str(item) for item in value.values())
        else:
            parts.append(str(value))
    for message in block.tail_messages[-3:]:
        parts.append(message.content)
    return " ".join(part for part in parts if part).strip()


def _joined_message_text(messages: Sequence[NarrativeMessage]) -> str:
    return " ".join(message.content for message in messages if message.content).strip()


def _jaccard_similarity(a: str, b: str) -> float:
    a_tokens = _tokenize(a)
    b_tokens = _tokenize(b)
    if not a_tokens and not b_tokens:
        return 1.0
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / len(a_tokens | b_tokens)


def _tokenize(value: str) -> Set[str]:
    return {match.group(0).lower() for match in _TOKEN_RE.finditer(value or "") if match.group(0).strip()}


def _normalize_text(content: str) -> str:
    return re.sub(r"\s+", " ", content).strip().lower()


def _contains_keyword(content: str, keywords: Sequence[str]) -> bool:
    return any(keyword in content for keyword in keywords)


def _to_summary_line(content: str) -> str:
    text = re.sub(r"```.*?```", " ", content, flags=re.DOTALL)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:160]


def _extract_topic(summary: str, content: str) -> str:
    candidate = summary or _to_summary_line(content)
    if not candidate:
        return ""
    return candidate[:100]


def _block_type_alignment(current_type: str, candidate_type: str) -> float:
    if current_type == candidate_type:
        return 1.0
    compatible_pairs = {
        ("trial", "result"),
        ("result", "trial"),
        ("problem", "proposal"),
        ("proposal", "problem"),
        ("proposal", "trial"),
        ("trial", "proposal"),
        ("result", "insight"),
        ("insight", "result"),
    }
    if (current_type, candidate_type) in compatible_pairs:
        return 0.55
    return 0.0


def _topic_alignment(current_topic: str, candidate_topic: str) -> float:
    if not current_topic or not candidate_topic:
        return 0.0
    return _jaccard_similarity(current_topic, candidate_topic)


def _compose_reason(
    current_score: float,
    recent_score: float,
    type_score: float,
    topic_score: float,
    candidate_type: str,
) -> str:
    if current_score >= recent_score and current_score >= type_score:
        base = "content_overlap"
    elif type_score >= current_score and type_score >= recent_score:
        base = "type_alignment"
    else:
        base = "recent_context_alignment"
    return f"{base}:{candidate_type}:{topic_score:.2f}"


def _merge_tags(existing: Mapping[str, object], inferred: Mapping[str, object]) -> Dict[str, object]:
    merged = _clone_mapping(existing)
    for key, value in inferred.items():
        if key == "TRIAL" or key == "candidates":
            if isinstance(value, list):
                existing_list = merged.setdefault(key, [])
                if isinstance(existing_list, list):
                    seen = {str(item).strip() for item in existing_list}
                    for item in value:
                        normalized = str(item).strip()
                        if normalized and normalized not in seen:
                            existing_list.append(normalized)
                            seen.add(normalized)
                else:
                    merged[key] = [str(item).strip() for item in value if str(item).strip()]
            continue
        if value not in (None, "", []):
            merged[key] = value
    return merged


def _clone_mapping(value: Any) -> Dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    cloned: Dict[str, object] = {}
    for key, item in value.items():
        if isinstance(item, list):
            cloned[str(key)] = [sub_item for sub_item in item]
        elif isinstance(item, Mapping):
            cloned[str(key)] = dict(item)
        else:
            cloned[str(key)] = item
    return cloned


def _normalize_choice(value: str, allowed: Set[str], default: str) -> str:
    return value if value in allowed else default


def _optional_string(value: Any) -> Optional[str]:
    text = str(value).strip() if value is not None else ""
    return text or None


def _normalize_string_list(value: Any) -> List[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _coalesce_choice(*values: str) -> str:
    for value in values:
        if value:
            return value
    return ""


def _coerce_routing_decision(value: Mapping[str, Any] | RoutingDecision) -> RoutingDecision:
    if isinstance(value, RoutingDecision):
        return value

    candidate_scores_raw = value.get("candidateScores", []) if isinstance(value, Mapping) else []
    candidate_scores: List[BlockScore] = []
    if isinstance(candidate_scores_raw, Sequence) and not isinstance(candidate_scores_raw, (str, bytes)):
        for item in candidate_scores_raw:
            if not isinstance(item, Mapping):
                continue
            candidate_scores.append(
                BlockScore(
                    block_id=str(item.get("blockId", "")).strip(),
                    score=float(item.get("score", 0.0)),
                    reason=str(item.get("reason", "")).strip(),
                )
            )

    return RoutingDecision(
        action=_normalize_choice(str(value.get("action", "")).strip().upper(), {"APPEND", "NEW_BLOCK"}, "NEW_BLOCK"),
        target_block_id=_optional_string(value.get("targetBlockId")),
        score=float(value.get("score", 0.0)),
        reason=str(value.get("reason", "")).strip() or "llm_decision",
        block_type=_normalize_choice(str(value.get("blockType", "")).strip().lower(), _ALLOWED_BLOCK_TYPES, "proposal"),
        status=_normalize_choice(str(value.get("status", "")).strip().lower(), _ALLOWED_STATUSES, "neutral"),
        topic=str(value.get("topic", "")).strip(),
        summary=str(value.get("summary", "")).strip(),
        tags=_clone_mapping(value.get("tags", {})),
        candidate_scores=candidate_scores,
    )
