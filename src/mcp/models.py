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


class MessageProcessingStatus(str, Enum):
    RECEIVED = "received"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
    RECONCILE_PENDING = "reconcile_pending"


class ReconciliationRunType(str, Enum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"
    STARTUP = "startup"
    RETRY = "retry"


class ReconciliationRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ReconciliationItemStatus(str, Enum):
    MISSING = "missing"
    RECOVERED = "recovered"
    FAILED = "failed"
    SKIPPED = "skipped"


class MessageProcessingRecordDTO(BaseModel):
    sessionId: str
    messageId: str
    status: MessageProcessingStatus = MessageProcessingStatus.RECEIVED
    attemptCount: int = 0
    blockAction: Optional[BlockAction] = None
    blockId: Optional[str] = None
    blockType: Optional[NarrativeBlockType] = None
    blockStatus: Optional[NarrativeBlockStatus] = None
    routingScore: Optional[float] = None
    lastErrorStage: Optional[str] = None
    lastErrorCode: Optional[str] = None
    lastErrorMessage: Optional[str] = None
    lastDecisionPayload: Dict[str, object] = Field(default_factory=dict)
    lastPayload: Dict[str, object] = Field(default_factory=dict)
    reconciliationRunId: Optional[int] = None
    receivedAt: Optional[str] = None
    processingAt: Optional[str] = None
    processedAt: Optional[str] = None
    failedAt: Optional[str] = None
    reconciledAt: Optional[str] = None
    retryAfter: Optional[str] = None


class MessageProcessingUpdateDTO(BaseModel):
    sessionId: str
    messageId: str
    status: MessageProcessingStatus
    attemptCount: Optional[int] = None
    blockAction: Optional[BlockAction] = None
    blockId: Optional[str] = None
    blockType: Optional[NarrativeBlockType] = None
    blockStatus: Optional[NarrativeBlockStatus] = None
    routingScore: Optional[float] = None
    lastErrorStage: Optional[str] = None
    lastErrorCode: Optional[str] = None
    lastErrorMessage: Optional[str] = None
    lastDecisionPayload: Dict[str, object] = Field(default_factory=dict)
    retryAfter: Optional[str] = None


class MessageReconciliationRunDTO(BaseModel):
    reconciliationRunId: Optional[int] = None
    sessionId: str
    runType: ReconciliationRunType = ReconciliationRunType.SCHEDULED
    status: ReconciliationRunStatus = ReconciliationRunStatus.PENDING
    expectedMessageCount: int = 0
    processedMessageCount: int = 0
    missingMessageCount: int = 0
    recoveredMessageCount: int = 0
    notes: str = ""
    summaryPayload: Dict[str, object] = Field(default_factory=dict)
    startedAt: Optional[str] = None
    finishedAt: Optional[str] = None


class MessageReconciliationItemDTO(BaseModel):
    reconciliationRunId: Optional[int] = None
    sessionId: str
    messageId: str
    status: ReconciliationItemStatus = ReconciliationItemStatus.MISSING
    reason: str = ""
    blockId: Optional[str] = None
    attemptCount: int = 0
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None


class MessageReconciliationSummaryDTO(BaseModel):
    sessionId: str
    reconciliationRunId: Optional[int] = None
    expectedMessageIds: List[str] = Field(default_factory=list)
    processedMessageIds: List[str] = Field(default_factory=list)
    missingMessageIds: List[str] = Field(default_factory=list)
    recoveredMessageIds: List[str] = Field(default_factory=list)
    failedMessageIds: List[str] = Field(default_factory=list)
    status: ReconciliationRunStatus = ReconciliationRunStatus.PENDING
    notes: str = ""


class SessionIngestCursorDTO(BaseModel):
    sessionId: str
    lastReceivedMessageId: Optional[str] = None
    lastProcessingMessageId: Optional[str] = None
    lastProcessedMessageId: Optional[str] = None
    lastReconciledMessageId: Optional[str] = None
    pendingMessageCount: int = 0
    failedMessageCount: int = 0
    updatedAt: Optional[str] = None


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
