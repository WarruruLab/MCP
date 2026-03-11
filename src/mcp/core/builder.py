from __future__ import annotations

from datetime import UTC, datetime
from typing import Dict, List, Optional, Tuple

from mcp.core.decision import decide_action
from mcp.core.summarize import extract_code_snippets, summarize_block
from mcp.llm.client import LlmClient
from mcp.models import (
    BuildOptionsDTO,
    BuildRequestDTO,
    BuildResponseDTO,
    BuildStatsDTO,
    SessionBlockDTO,
)
from mcp.utils.validate import normalize_role, parse_iso8601

ANALYSIS_VERSION = "mcp-2026.02.27-01"


def default_tags() -> Dict[str, object]:
    return {
        "CONTEXT": "",
        "PROBLEM": "",
        "TRIAL": [],
        "SOLUTION": "",
        "INSIGHT": "",
    }


def merge_tags(existing: Optional[Dict[str, object]], inferred: Dict[str, object]) -> Dict[str, object]:
    merged = default_tags()
    for source in (existing or {}, inferred):
        for key, value in source.items():
            if key == "TRIAL":
                if isinstance(value, list):
                    items = [str(item).strip() for item in value if str(item).strip()]
                    seen = set(merged["TRIAL"])
                    for item in items:
                        if item not in seen:
                            merged["TRIAL"].append(item)
                            seen.add(item)
                continue
            if value not in (None, ""):
                merged[key] = value
    return merged


def build_session_blocks(request: BuildRequestDTO, llm_client: LlmClient) -> BuildResponseDTO:
    options: BuildOptionsDTO = request.options

    messages = []
    message_lookup: Dict[str, Dict[str, str]] = {}
    for m in request.messages:
        role = normalize_role(m.role)
        normalized = {
            "messageId": m.messageId,
            "role": role,
            "content": m.content.strip() if m.content else "",
            "timestamp": m.timestamp,
        }
        messages.append(normalized)
        message_lookup[m.messageId] = normalized

    messages.sort(key=lambda x: (parse_iso8601(x["timestamp"]), x["messageId"]))

    blocks: Dict[str, SessionBlockDTO] = {}
    message_to_block: Dict[str, str] = {}
    changed_blocks: set[str] = set()

    if request.analysisMode.upper() == "FULL":
        existing_blocks = []
    else:
        existing_blocks = request.existingBlocks

    last_block_id = None
    for b in existing_blocks:
        blocks[b.blockId] = SessionBlockDTO(
            blockId=b.blockId,
            messageIds=list(b.messageIds),
            tags=merge_tags(None, b.tags or {}),
            code_snippets=[],
            confidence=0.0,
            metadata={},
        )
        for mid in b.messageIds:
            message_to_block[mid] = b.blockId
        if b.lastMessage is not None:
            message_lookup[b.lastMessage.messageId] = {
                "messageId": b.lastMessage.messageId,
                "role": normalize_role(b.lastMessage.role),
                "content": b.lastMessage.content.strip(),
                "timestamp": b.lastMessage.timestamp,
            }
        last_block_id = b.blockId

    seq = len(blocks) + 1
    llm_calls_shift = 0
    llm_calls_summarize = 0

    last_message_content = None
    last_message_ts = None
    if last_block_id and blocks[last_block_id].messageIds:
        last_message_id = blocks[last_block_id].messageIds[-1]
        last_message = message_lookup.get(last_message_id)
        if last_message is not None:
            last_message_content = last_message["content"]
            last_message_ts = last_message["timestamp"]

    for m in messages:
        if m["messageId"] in message_to_block:
            continue

        decision = decide_action(
            last_message_content=last_message_content,
            last_message_ts=last_message_ts,
            cur_message_content=m["content"],
            cur_message_ts=m["timestamp"],
            time_gap_minutes_threshold=options.timeGapMinutes,
            shift_low=options.shiftLowSim,
            shift_high=options.shiftHighSim,
        )

        action = decision.action
        reason = decision.reason
        score = decision.score

        if action == "LLM":
            llm_calls_shift += 1
            context = f"last={last_message_content}\ncur={m['content']}"
            llm_decision = llm_client.decide_append_or_new(context)
            action = llm_decision.action
            score = llm_decision.score
            reason = llm_decision.reason

        if action == "APPEND" and last_block_id is not None:
            blocks[last_block_id].messageIds.append(m["messageId"])
            message_to_block[m["messageId"]] = last_block_id
            changed_blocks.add(last_block_id)
        else:
            block_id = f"blk_{request.sessionId}_{seq}"
            while block_id in blocks:
                seq += 1
                block_id = f"blk_{request.sessionId}_{seq}"
            seq += 1
            blocks[block_id] = SessionBlockDTO(
                blockId=block_id,
                messageIds=[m["messageId"]],
                tags=default_tags(),
                code_snippets=[],
                confidence=0.0,
                metadata={},
            )
            message_to_block[m["messageId"]] = block_id
            changed_blocks.add(block_id)
            last_block_id = block_id

        last_message_content = m["content"]
        last_message_ts = m["timestamp"]

    for block_id in changed_blocks:
        block = blocks[block_id]
        block_messages: List[Tuple[str, str]] = []
        for mid in block.messageIds:
            content = message_lookup.get(mid, {}).get("content", "")
            block_messages.append((mid, content))
        block.tags = merge_tags(block.tags, summarize_block(block_messages))
        block.code_snippets = extract_code_snippets(block_messages)
        block.confidence = 0.5
        block.metadata = {
            "model": llm_client.model,
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "analysis_version": ANALYSIS_VERSION,
        }
        llm_calls_summarize += 1

    response = BuildResponseDTO(
        sessionId=request.sessionId,
        analysis_version=ANALYSIS_VERSION,
        model=llm_client.model,
        blocks=list(blocks.values()),
        messageToBlock=message_to_block,
        stats=BuildStatsDTO(
            numMessages=len(messages),
            numBlocks=len(blocks),
            llmCalls_shift=llm_calls_shift,
            llmCalls_summarize=llm_calls_summarize,
        ),
    )
    return response
