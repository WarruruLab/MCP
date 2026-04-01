from __future__ import annotations

from enum import Enum
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


class BlockAction(str, Enum):
    APPEND = "APPEND"
    NEW_BLOCK = "NEW_BLOCK"


class NarrativeBlockType(str, Enum):
    PROBLEM = "problem"
    PROPOSAL = "proposal"
    TRIAL = "trial"
    RESULT = "result"
    INSIGHT = "insight"


class NarrativeBlockStatus(str, Enum):
    OPEN = "open"
    NEUTRAL = "neutral"
    FAILED = "failed"
    SUCCESS = "success"


class NarrativeBlockBaseDTO(BaseModel):
    topic: str = ""
    blockType: NarrativeBlockType
    status: NarrativeBlockStatus = NarrativeBlockStatus.NEUTRAL
    summary: str = ""
    tags: Dict[str, object] = Field(default_factory=dict)
    parentBlockId: Optional[str] = None
    relatedBlockIds: List[str] = Field(default_factory=list)


class NarrativeBlockDTO(NarrativeBlockBaseDTO):
    blockId: str
    messageIds: List[str] = Field(default_factory=list)


class CandidateBlockContextDTO(NarrativeBlockBaseDTO):
    blockId: str
    recentMessageIds: List[str] = Field(default_factory=list)


class IngestMessageOptionsDTO(BaseModel):
    maxRecentMessages: int = 8
    maxCandidateBlocks: int = 8


class BlockRoutingDecisionDTO(BaseModel):
    action: BlockAction
    targetBlockId: Optional[str] = None
    blockType: NarrativeBlockType
    status: NarrativeBlockStatus = NarrativeBlockStatus.NEUTRAL
    topic: str = ""
    summary: str = ""
    tags: Dict[str, object] = Field(default_factory=dict)
    score: float = 0.0
    reason: str = ""


class IngestMessageRequestDTO(BaseModel):
    sessionId: str
    currentMessage: MessageDTO
    candidateBlocks: List[CandidateBlockContextDTO] = Field(default_factory=list)
    recentMessages: List[MessageDTO] = Field(default_factory=list)
    options: IngestMessageOptionsDTO = Field(default_factory=IngestMessageOptionsDTO)


class IngestMessageResponseDTO(BaseModel):
    sessionId: str
    action: BlockAction
    targetBlockId: Optional[str] = None
    block: NarrativeBlockDTO
    score: float = 0.0
    reason: str = ""


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
