from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from devlog_mcp_server.utils.validate import parse_iso8601


@dataclass
class DecisionResult:
    action: str
    score: float
    reason: str


def jaccard_similarity(a: str, b: str) -> float:
    a_tokens = {t for t in a.lower().split() if t}
    b_tokens = {t for t in b.lower().split() if t}
    if not a_tokens and not b_tokens:
        return 1.0
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / len(a_tokens | b_tokens)


def time_gap_minutes(prev_ts: str, cur_ts: str) -> float:
    prev_dt = parse_iso8601(prev_ts)
    cur_dt = parse_iso8601(cur_ts)
    return abs((cur_dt - prev_dt).total_seconds()) / 60.0


def decide_action(
    last_message_content: Optional[str],
    last_message_ts: Optional[str],
    cur_message_content: str,
    cur_message_ts: str,
    time_gap_minutes_threshold: int,
    shift_low: float,
    shift_high: float,
) -> DecisionResult:
    if last_message_content is None or last_message_ts is None:
        return DecisionResult(action="NEW_BLOCK", score=1.0, reason="first_message")

    gap = time_gap_minutes(last_message_ts, cur_message_ts)
    if gap > time_gap_minutes_threshold:
        return DecisionResult(action="NEW_BLOCK", score=1.0, reason="time_gap")

    sim = jaccard_similarity(last_message_content, cur_message_content)
    if sim <= shift_low:
        return DecisionResult(action="NEW_BLOCK", score=1.0 - sim, reason="low_similarity")
    if sim >= shift_high:
        return DecisionResult(action="APPEND", score=sim, reason="high_similarity")

    # ambiguous: return signal for LLM
    return DecisionResult(action="LLM", score=sim, reason="mid_similarity")
