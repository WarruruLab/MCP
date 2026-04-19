from __future__ import annotations

import re
from typing import Dict, List, Tuple

from devlog_mcp_server.models import CodeSnippetDTO

DEFAULT_TAGS: Dict[str, object] = {
    "CONTEXT": "",
    "PROBLEM": "",
    "TRIAL": [],
    "SOLUTION": "",
    "INSIGHT": "",
}

PROBLEM_KEYWORDS = (
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
TRIAL_KEYWORDS = (
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
SOLUTION_KEYWORDS = (
    "fix",
    "fixed",
    "resolve",
    "resolved",
    "solution",
    "solved",
    "workaround",
    "해결",
    "수정",
    "조치",
)
INSIGHT_KEYWORDS = (
    "because",
    "root cause",
    "caused by",
    "therefore",
    "원인",
    "결국",
    "때문",
)


def extract_code_snippets(messages: List[Tuple[str, str]]) -> List[CodeSnippetDTO]:
    snippets: List[CodeSnippetDTO] = []
    for message_id, content in messages:
        snippets.extend(_extract_fenced_snippets(message_id, content))
        snippets.extend(_extract_command_snippets(message_id, content))
    return snippets


def summarize_block(messages: List[Tuple[str, str]]) -> Dict[str, object]:
    if not messages:
        return dict(DEFAULT_TAGS)

    tags: Dict[str, object] = {
        "CONTEXT": _extract_context(messages),
        "PROBLEM": "",
        "TRIAL": [],
        "SOLUTION": "",
        "INSIGHT": "",
    }

    trials: List[str] = []
    for _, content in messages:
        normalized = _normalize_text(content)
        summary_line = _to_summary_line(content)
        if not summary_line:
            continue

        if not tags["PROBLEM"] and _contains_keyword(normalized, PROBLEM_KEYWORDS):
            tags["PROBLEM"] = summary_line
        if _contains_keyword(normalized, TRIAL_KEYWORDS):
            trials.append(summary_line)
        if not tags["SOLUTION"] and _contains_keyword(normalized, SOLUTION_KEYWORDS):
            tags["SOLUTION"] = summary_line
        if not tags["INSIGHT"] and _contains_keyword(normalized, INSIGHT_KEYWORDS):
            tags["INSIGHT"] = summary_line

    tags["TRIAL"] = _dedupe(trials[:3])
    return tags


def _extract_fenced_snippets(message_id: str, content: str) -> List[CodeSnippetDTO]:
    snippets: List[CodeSnippetDTO] = []
    if "```" not in content:
        return snippets

    parts = content.split("```")
    for i in range(1, len(parts), 2):
        block = parts[i].strip("\n")
        if not block:
            continue
        lines = block.splitlines()
        if lines and len(lines[0].strip().split()) == 1:
            language = lines[0].strip()
            code = "\n".join(lines[1:]).strip()
        else:
            language = "text"
            code = block.strip()
        if code:
            snippets.append(CodeSnippetDTO(language=language, content=code, sourceMessageId=message_id))
    return snippets


def _extract_command_snippets(message_id: str, content: str) -> List[CodeSnippetDTO]:
    snippets: List[CodeSnippetDTO] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("$ "):
            snippets.append(CodeSnippetDTO(language="bash", content=line[2:].strip(), sourceMessageId=message_id))
            continue
        if re.match(r"^(pip|python|pytest|uvicorn|npm|pnpm|yarn|docker|git)\b", line):
            snippets.append(CodeSnippetDTO(language="bash", content=line, sourceMessageId=message_id))
    return snippets


def _extract_context(messages: List[Tuple[str, str]]) -> str:
    for _, content in messages:
        line = _to_summary_line(content)
        if line:
            return line
    return ""


def _to_summary_line(content: str) -> str:
    text = re.sub(r"```.*?```", " ", content, flags=re.DOTALL)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    return text[:160]


def _normalize_text(content: str) -> str:
    return re.sub(r"\s+", " ", content).strip().lower()


def _contains_keyword(content: str, keywords: Tuple[str, ...]) -> bool:
    return any(keyword in content for keyword in keywords)


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for item in items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result
