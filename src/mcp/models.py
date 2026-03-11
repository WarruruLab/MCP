from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class MessageDTO(BaseModel):
    messageId: str
    role: str
    content: str
    timestamp: str


class ExistingBlockLastMessageDTO(BaseModel):
    messageId: str
    role: str
    content: str
    timestamp: str


class ExistingBlockDTO(BaseModel):
    blockId: str
    messageIds: List[str]
    tags: Optional[Dict[str, object]] = None
    lastMessage: Optional[ExistingBlockLastMessageDTO] = None


class BuildOptionsDTO(BaseModel):
    timeGapMinutes: int = 10
    shiftLowSim: float = 0.20
    shiftHighSim: float = 0.45
    maxLastMessagesForContext: int = 6


class BuildRequestDTO(BaseModel):
    sessionId: str
    analysisMode: str
    messages: List[MessageDTO]
    existingBlocks: List[ExistingBlockDTO] = Field(default_factory=list)
    options: BuildOptionsDTO = Field(default_factory=BuildOptionsDTO)


class CodeSnippetDTO(BaseModel):
    language: str
    content: str
    sourceMessageId: str


class SessionBlockDTO(BaseModel):
    blockId: str
    messageIds: List[str]
    tags: Dict[str, object]
    code_snippets: List[CodeSnippetDTO]
    confidence: float
    metadata: Dict[str, object]


class BuildStatsDTO(BaseModel):
    numMessages: int
    numBlocks: int
    llmCalls_shift: int
    llmCalls_summarize: int


class BuildResponseDTO(BaseModel):
    sessionId: str
    analysis_version: str
    model: str
    blocks: List[SessionBlockDTO]
    messageToBlock: Dict[str, str]
    stats: BuildStatsDTO
