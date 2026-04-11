from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, Mapping, Sequence

from mcp.core.routing import NarrativeBlock, NarrativeMessage, coerce_block, coerce_message


_FINALIZE_KEYWORDS = (
    "done",
    "finalize",
    "finalise",
    "close",
    "closed",
    "wrap up",
    "wrap this up",
    "end here",
    "resolved",
    "fixed",
    "solved",
    "success",
    "complete",
    "completed",
    "finish",
    "finished",
    "정리",
    "마무리",
    "종료",
    "끝",
    "해결",
    "완료",
)

_FAILURE_KEYWORDS = (
    "failed",
    "failure",
    "cannot",
    "can't",
    "won't",
    "not working",
    "still broken",
    "no longer",
    "포기",
    "안되",
    "실패",
)

_HANDOFF_KEYWORDS = (
    "next topic",
    "different issue",
    "separate issue",
    "new issue",
    "move on",
    "another topic",
    "다른 문제",
    "다음 문제",
    "이건 별개",
)

_KEEP_OPEN_PAIRS = {
    ("problem", "proposal"),
    ("proposal", "trial"),
    ("trial", "result"),
    ("result", "insight"),
}


@dataclass(frozen=True)
class FinalizeDecision:
    should_finalize: bool
    reason: str
    confidence: float

    def as_dict(self) -> Dict[str, object]:
        return {
            "shouldFinalize": self.should_finalize,
            "reason": self.reason,
            "confidence": self.confidence,
        }


def decide_finalize_block(
    active_block: Mapping[str, Any] | NarrativeBlock,
    selected_block: Mapping[str, Any] | NarrativeBlock,
    current_message: Mapping[str, Any] | NarrativeMessage,
    recent_messages: Sequence[Mapping[str, Any] | NarrativeMessage],
) -> FinalizeDecision:
    active = coerce_block(active_block)
    selected = coerce_block(selected_block)
    message = coerce_message(current_message)
    recent = [coerce_message(item) for item in recent_messages]

    signals = []
    confidence = 0.35

    explicit_score, explicit_reason = _explicit_finalize_signal(message, recent)
    confidence += explicit_score
    if explicit_reason:
        signals.append(explicit_reason)
    explicit_finalize = explicit_reason.startswith("explicit_")

    transition_score, transition_reason = _transition_signal(active, selected)
    confidence += transition_score
    if transition_reason:
        signals.append(transition_reason)

    topic_score, topic_reason = _topic_signal(active, selected, message, recent)
    confidence += topic_score
    if topic_reason:
        signals.append(topic_reason)

    status_score, status_reason = _status_signal(active, selected)
    confidence += status_score
    if status_reason:
        signals.append(status_reason)

    confidence = _clamp(confidence)
    should_finalize = explicit_finalize or confidence >= 0.55
    if explicit_finalize:
        confidence = max(confidence, 0.72)
    reason = _compose_reason(signals, should_finalize)

    return FinalizeDecision(
        should_finalize=should_finalize,
        reason=reason,
        confidence=confidence,
    )


def _explicit_finalize_signal(
    message: NarrativeMessage,
    recent_messages: Sequence[NarrativeMessage],
) -> tuple[float, str]:
    text = " ".join([message.content, *[item.content for item in recent_messages if item.content]]).lower()
    if _contains_any(text, _FINALIZE_KEYWORDS):
        if _contains_any(text, _FAILURE_KEYWORDS):
            return 0.72, "explicit_failure_close"
        return 0.68, "explicit_close"
    if _contains_any(text, _HANDOFF_KEYWORDS):
        return 0.18, "topic_handoff"
    return 0.0, ""


def _transition_signal(active: NarrativeBlock, selected: NarrativeBlock) -> tuple[float, str]:
    pair = (active.block_type, selected.block_type)
    if pair in _KEEP_OPEN_PAIRS:
        return -0.26, f"keep_open_transition:{active.block_type}->{selected.block_type}"
    if active.block_type == selected.block_type:
        return -0.08, f"same_block_type:{active.block_type}"
    return 0.0, ""


def _topic_signal(
    active: NarrativeBlock,
    selected: NarrativeBlock,
    message: NarrativeMessage,
    recent_messages: Sequence[NarrativeMessage],
) -> tuple[float, str]:
    active_topic = _normalize_text(active.topic or active.summary)
    selected_topic = _normalize_text(selected.topic or selected.summary)
    message_text = _normalize_text(message.content)
    recent_text = _normalize_text(" ".join(item.content for item in recent_messages if item.content))

    overlap = max(
        _jaccard_similarity(active_topic, selected_topic),
        _jaccard_similarity(active_topic, message_text),
        _jaccard_similarity(selected_topic, message_text),
        _jaccard_similarity(active_topic, recent_text),
        _jaccard_similarity(selected_topic, recent_text),
    )

    if overlap >= 0.6:
        return -0.22, "high_topic_overlap"
    if overlap >= 0.35:
        return -0.12, "medium_topic_overlap"
    if overlap <= 0.08:
        return 0.10, "topic_shift"
    return 0.0, ""


def _status_signal(active: NarrativeBlock, selected: NarrativeBlock) -> tuple[float, str]:
    if selected.status in {"success", "failed"} and active.status not in {"success", "failed"}:
        return -0.05, f"terminal_status:{selected.status}"
    return 0.0, ""


def _compose_reason(signals: Sequence[str], should_finalize: bool) -> str:
    if not signals:
        return "finalize" if should_finalize else "keep_open"
    prefix = "finalize" if should_finalize else "keep_open"
    return f"{prefix}:{'|'.join(signals[:3])}"


def _contains_any(text: str, keywords: Sequence[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def _jaccard_similarity(a: str, b: str) -> float:
    a_tokens = set(_tokenize(a))
    b_tokens = set(_tokenize(b))
    if not a_tokens and not b_tokens:
        return 1.0
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / len(a_tokens | b_tokens)


def _tokenize(value: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_가-힣]+", value or "")


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, round(value, 4)))
