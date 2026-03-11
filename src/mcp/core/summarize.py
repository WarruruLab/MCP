from __future__ import annotations

from typing import Dict, List, Tuple

from mcp.models import CodeSnippetDTO


def extract_code_snippets(messages: List[Tuple[str, str]]) -> List[CodeSnippetDTO]:
    snippets: List[CodeSnippetDTO] = []
    for message_id, content in messages:
        if "```" not in content:
            continue
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


def summarize_block(messages: List[Tuple[str, str]]) -> Dict[str, object]:
    # Simple heuristic summary for MVP
    text = " ".join([m[1] for m in messages]).lower()
    tags: Dict[str, object] = {
        "CONTEXT": "",
        "PROBLEM": "",
        "TRIAL": [],
        "SOLUTION": "",
        "INSIGHT": "",
    }
    if "error" in text or "exception" in text:
        tags["PROBLEM"] = "runtime error reported"
    if "fix" in text or "resolve" in text:
        tags["SOLUTION"] = "possible fix discussed"
    if "try" in text or "attempt" in text:
        tags["TRIAL"] = ["attempted solution"]
    return tags
