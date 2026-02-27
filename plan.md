# MCP 서버 구현·전환·성능비교 계획서 (Batch → Real-time)

> 전제: **DevTalk / DevLog는 이미 완성**되어 있고, 지금 필요한 것은 **MCP 서버 구현**이다.  
> 전략: **1) 먼저 “분석 버튼 = 한 번에 분석(Batch)” 방식으로 안정화**하고,  
> **2) 이후 “실시간(Streaming/Incremental)”로 확장**하여 **성능/운영/UX를 비교**한 뒤 최종 운영 방식을 결정한다.

---

## 0. 목표

### 기능 목표
- DevTalk의 원본 메시지(`messageId`, `role`, `content`, `timestamp`)를 기반으로
- MCP가 **세션 블록(session_block)** 을 생성한다.
- 블록은 DevLog의 블로그 초안 생성에 필요한 **messageIds(원문 근거)** 중심으로 구성된다.

### 품질 목표
- JSON 출력 안정성(스키마 준수)
- 결정적 결과(동일 입력 → 동일 결과)
- DevLog가 블록을 선택하고 “블록 해결됨(outcome)”을 남길 수 있도록 블록 품질 확보

### 성능 비교 목표
- Batch 방식 vs Real-time 방식에서 다음을 비교:
    - LLM 호출량, 지연시간(p50/p95), CPU/RAM, 처리량, 실패율
    - 블록 품질(전환 오탐/과분할/과병합), 사용자 수정량(수동 경계 수정 빈도)

---

## 1. 현재 합의된 도메인/흐름 요약

### 역할
- **DevTalk**: 대화 생성 + 원본 메시지 저장 + 세션 해결됨 표시
- **DevLog**: 블록 조회/선택 + 블록 해결됨(outcome) 피드백 + `messageIds`로 원문 복원해 **사고과정 중심** 초안 생성
- **MCP**: 메시지 → 블록 배정(append/new) + 블록 요약(tags/code_snippets) 생성

### session_block JSON(기본 형태)
```json
{
  "blockId": "blk_...",
  "messageIds": ["msg_001","msg_002","msg_007"],
  "tags": {
    "CONTEXT": "...",
    "PROBLEM": "...",
    "TRIAL": ["..."],
    "SOLUTION": "...",
    "INSIGHT": "..."
  },
  "code_snippets": [
    {"language":"yaml","content":"spring.data.redis.host: redis","sourceMessageId":"msg_007"}
  ],
  "confidence": 0.84,
  "metadata": {"model":"qwen2.5:3b","timestamp":"2026-02-27T10:00:00","analysis_version":"mcp-2026.02.27-01"}
}
```

---

## 2. 단계 1: Batch(분석 버튼) 방식으로 MCP 구현 및 안정화

> DevLog에서 “분석 버튼” 클릭 시 MCP 호출 → MCP가 **세션 전체 메시지를 시간순으로 순회**하며  
> 메시지마다 **기존 블록에 append할지 / 새 블록 생성할지** 결정 → blocks 반환 → DevLog가 upsert 저장.

### 2.1 Batch 분석의 입력/출력 계약 (권장 REST Shim)
#### DevTalk -> DevLog cursor paging (before MCP call)
- DevLog calls DevTalk internal API to fetch messages by cursor:
  - `GET /api/internal/messages/{sessionId}?cursor={createdAt}&limit=100`
  - response includes `nextCursor` and `hasMore`
- DevLog repeats paging until `hasMore=false`, then builds MCP request payload.
- Cursor is `createdAt` ISO string (e.g. `2026-02-18T17:00:00`).
- Optional batch by IDs:
  - `POST /api/internal/messages/batch` with messageIds list.

#### MCP server responsibilities (Batch)
- Validate request schema and normalize messages (required: `messageId/role/content/timestamp`).
- Deterministic ordering: `timestamp` asc, tie-breaker `messageId` asc.
- Decide APPEND vs NEW_BLOCK per message (rules + LLM fallback).
- Update `messageToBlock` mapping and produce `session_block[]`.
- Summarize only changed blocks into `tags/code_snippets`.
- Return `analysis_version`, `model`, and `stats` (llm calls, blocks, messages).

#### MCP server non-functional rules
- Determinism: fixed seeds / temperature 0 for structured outputs.
- Input validation: reject missing required fields with 4xx error.
- Output validation: schema check before response (Pydantic/JSON Schema).
- Error handling: retry LLM once, fallback to rule-based decision.
- Logging: per-request trace id, latency, llm calls, error codes.

#### Request (DevLog → MCP)
```json
{
  "sessionId": "sess_123",
  "analysisMode": "INCREMENTAL",
  "messages": [
    {"messageId":"msg_001","role":"user","content":"...","timestamp":"..."},
    {"messageId":"msg_002","role":"assistant","content":"...","timestamp":"..."}
  ],
  "existingBlocks": [
    {"blockId":"blk_a","messageIds":["msg_001","msg_002"],"tags":{"CONTEXT":"..."}}
  ],
  "options": {
    "timeGapMinutes": 10,
    "shiftLowSim": 0.20,
    "shiftHighSim": 0.45,
    "maxLastMessagesForContext": 6
  }
}
```

#### Response (MCP → DevLog)
```json
{
  "sessionId": "sess_123",
  "analysis_version": "mcp-2026.02.27-01",
  "model": "qwen2.5:3b",
  "blocks": [ /* session_block[] */ ],
  "messageToBlock": { "msg_001":"blk_a", "msg_004":"blk_new_1" },
  "stats": { "numMessages": 120, "numBlocks": 9, "llmCalls_shift": 14, "llmCalls_summarize": 3 }
}
```

> **핵심**: `messageIds`는 반드시 포함. DevLog가 원문 복원/내러티브 구성에 사용한다.

---

### 2.2 Batch 분석 알고리즘(내부는 “메시지 1개씩” 결정)
#### 결정적 정렬
1) timestamp 오름차순
2) 동률이면 messageId 오름차순
3) timestamp 없으면 입력순 + messageId

#### 배정(append vs new) 로직
- 1차: 휴리스틱 점수(빠름)
    - 시간 간격, 키워드 유사도(Jaccard), 전환 표현, 태그 흐름 패턴
- 2차: 애매 구간만 **Local LLM(Ollama 3B)** 타이브레이크
    - 입력: 현재 블록 tail N개 + 새 메시지 1개 (+ 현재 블록 tags가 있으면 함께)
    - 출력: `{action: APPEND|NEW_BLOCK, score, reason}` JSON

#### 요약(tags/code_snippets)
- 메시지 배정이 끝난 후:
    - **변경된 블록만** `summarize_block` 수행(기존 유지 블록은 재요약 생략)
- `code_snippets`는 규칙 기반(코드펜스/설정/커맨드) 선추출 + 필요시 LLM 보강

---

### 2.3 구현 우선순위(바로 개발 착수용)
**MVP(필수)**
- [ ] `/v1/session-blocks:build` (REST)
- [ ] `build_session_blocks(existingBlocks, messages, options)` 핵심 함수
- [ ] Ollama Structured Outputs(스키마 강제) + Pydantic 검증 + 실패 시 1회 재시도
- [ ] DevLog에서 “분석 버튼” → MCP 호출 → blocks upsert → UI 표시

**개선(선택)**
- [ ] chunk 처리(예: 300~500 messages 단위) + OPEN 블록 tail만 carry
- [ ] LLM 호출 상한(세션당 shift 타이브레이크 최대 N회)
- [ ] 빠른 모드: “블록 배정만” 먼저 반환 후, 선택 블록만 tags 생성

---

### 2.4 안정화(DoD: 완료 기준)
- [ ] 샘플 세션 10개에서 결과 JSON 스키마 100% 통과
- [ ] 동일 입력 재요청 시 blocks 결과가 동일(결정성)
- [ ] DevLog UI에서 블록이 자연스럽게 보이고, 사용자가 블록을 선택/해결됨(outcome) 표시 가능
- [ ] 8시간 세션(대규모 메시지)에서 **타임아웃 없이 완료**(chunk/timeout/fallback 포함)

---

## 3. 단계 1 성능 측정(기준선 Baseline) — Batch

> Real-time 비교를 위해 Batch의 기준선 데이터를 먼저 확보한다.

### 3.1 측정 시나리오
- S1: 일반 세션(예: 50~150 messages)
- S2: 중간 세션(300~800 messages)
- S3: 장시간 세션(8시간, 1000~3000+ messages 가능)
- S4: 동시 세션 5/10/20개 분석 요청(DevLog에서 여러 사용자가 동시에 분석)

### 3.2 측정 지표
**Latency**
- 전체 분석 E2E: `build` 응답 시간 (p50/p95/p99)
- LLM 호출별 시간: shift 타이브레이크 평균/최대, summarize 평균/최대

**Cost/Load**
- LLM 호출 수: `llmCalls_shift`, `llmCalls_summarize`
- 토큰/입력 길이(가능하면 로그에 기록)
- CPU/RAM, Ollama GPU/CPU 사용량(환경에 따라)

**Quality(품질)**
- 블록 수(과분할/과병합 감지)
- 사용자 수동 수정량(DevLog에서 블록 경계 수정/태그 수정 발생 수)
- “해결됨 블록”이 마지막에 자연스럽게 위치하는지(경험적 점검)

### 3.3 결과 산출물
- `baseline_batch_report.md` (측정 수치 + 로그 + 관찰)
- 기준선 이후, Real-time과 동일한 데이터셋으로 재측정

---

## 4. 단계 2: Real-time(Streaming/Incremental)로 확장 적용 + 성능 비교

> 목표: DevTalk 사용 중에도 블록이 “거의 실시간”으로 생성/갱신되도록 하고,  
> Batch 대비 성능/운영비용/UX 차이를 정량 비교한다.

### 4.1 Real-time 설계 원칙(권장)
- MCP는 **가능하면 Stateless 유지**
- 세션의 OPEN 블록 상태는 **DevLog(또는 별도 consumer/DB/Redis)** 가 관리
- “실시간은 임시(provisional) 결과”로 두고, 필요 시 Batch 분석으로 최종 재정리 가능

---

### 4.2 Real-time 아키텍처 옵션(추천 순)
#### 옵션 B-1: 이벤트/웹훅 기반(추천)
1) DevTalk 메시지 저장
2) `message_created` 이벤트 발행(또는 webhook)
3) DevLog consumer가 수신 → MCP에 `ingest_message` 호출
4) DevLog가 OPEN 블록 업데이트(upsert)

#### 옵션 B-2: 준-실시간 폴링(가벼운 도입)
- DevLog가 활성 세션의 신규 메시지를 N초마다 모아 `ingest_batch` 호출
- 이벤트 라인이 부담될 때 대안

---

### 4.3 Real-time API 계약(추가)
#### `POST /v1/session-blocks:ingest-message`
```json
{
  "sessionId": "sess_123",
  "message": {"messageId":"msg_101","role":"user","content":"...","timestamp":"..."},
  "openBlockContext": {
    "blockId": "blk_open",
    "tailMessages": [
      {"messageId":"msg_095","role":"assistant","content":"..."},
      {"messageId":"msg_100","role":"user","content":"..."}
    ],
    "tailTags": {"CONTEXT":"...","PROBLEM":"..."},
    "lastProcessedMessageId": "msg_100"
  },
  "options": { "timeGapMinutes": 10, "maxLastMessagesForContext": 6 }
}
```

#### Response
```json
{
  "action": "APPEND" ,
  "blockId": "blk_open",
  "updated": {
    "messageIdsAppend": ["msg_101"],
    "shouldResummarize": false
  },
  "debug": {"score":0.78,"reason":"same_topic"}
}
```

> **성능 최적화 포인트**: 실시간에서는 매 메시지마다 tags를 재요약하지 않고  
> `shouldResummarize`가 true일 때만 요약하거나, 일정 주기/블록 종료 시점에만 수행한다.

---

### 4.4 Real-time 운영 필수 조건(난이도의 핵심)
- **멱등성**: `sessionId + messageId` 유니크 처리(중복 ingest 방지)
- **세션 단위 직렬 처리**: 한 세션의 메시지는 동시에 처리하지 않도록(큐/락)
- **out-of-order 처리**: timestamp 기준 재정렬 또는 “늦게 온 메시지” 처리 규칙 정의
- **장애 복구**: consumer 재시작 시 마지막 처리 messageId부터 재처리 가능해야 함

---

## 5. 성능 비교 테스트 플랜 (Batch vs Real-time)

### 5.1 비교 원칙
- 동일한 세션 데이터셋으로 비교
- 동일한 모델/옵션(가능한 범위)으로 비교
- Real-time은 “누적 처리 총량(LLM calls 총합)”과 “UX 반응성”을 함께 평가

### 5.2 시나리오
- 동일 세션을 두 방식으로 처리:
    1) Batch: 한 번에 `build`
    2) Real-time: message 단위로 `ingest-message` 반복 + 마지막에 선택적으로 `build`(정합성 재정리) 수행

### 5.3 지표
**성능**
- 누적 처리 시간(총합)
- 메시지당 평균 처리 시간
- p95 지연(실시간 UX에 중요)
- LLM 호출 총량(shift, summarize)
- CPU/RAM/GPU 사용량

**품질**
- 최종 블록 수
- 블록 경계 안정성(실시간 결과와 배치 결과의 차이)
- 사용자 수정량(블록 병합/분할/태그 수정)
- “해결됨 블록” 위치/전개 자연스러움

### 5.4 최종 결정 기준(예시)
- Real-time이 Batch 대비:
    - UX 개선(블록 즉시 표시)이 의미 있고,
    - 운영 복잡도 증가 대비 성능/품질이 충분히 낫거나(또는 동일)  
      → Real-time을 기본으로
- 그렇지 않으면:
    - Batch 기본 + Real-time은 선택 기능(혹은 준-실시간 폴링)

---

## 6. 구현 로드맵(바로 개발 가능한 TODO)

### Sprint 1: Batch MCP 구현 + DevLog 연결
- [ ] FastMCP 서버 + REST shim(`/v1/session-blocks:build`)
- [ ] build_session_blocks(메시지 순회 + append/new 결정)
- [ ] summarize_block(tags/code_snippets) + structured outputs 안정화
- [ ] DevLog 분석 버튼 연결 + 결과 upsert + UI 확인
- [ ] baseline 성능 측정(S1~S3 최소)

### Sprint 2: Batch 안정화/최적화
- [ ] chunk 처리 + timeout/fallback
- [ ] 변경 블록만 재요약(INCREMENTAL)
- [ ] 관측(메트릭/로그) 정리
- [ ] baseline 재측정(동시성 S4 포함)

### Sprint 3: Real-time 도입(최소 기능)
- [ ] `/v1/session-blocks:ingest-message` 구현
- [ ] DevLog(또는 consumer) 측 OPEN 블록 상태 관리(락/멱등)
- [ ] 실시간 모드에서 “요약 갱신 정책” 결정(주기/종료 시점/선택 시)
- [ ] feature flag로 특정 사용자/세션만 실시간 적용

### Sprint 4: 성능 비교/결정/정리
- [ ] 동일 데이터셋으로 Batch vs Real-time 비교 리포트
- [ ] 운영 난이도(장애/재처리/정합성) 평가
- [ ] 최종 운영 모드 결정 + 문서화

---

## 7. 리스크와 대응(사전에 박아두기)

- **8시간 세션 대형 입력**
    - 대응: chunk 처리 + 요약 입력 축약 + LLM 호출 상한
- **실시간에서 블록 경계 흔들림**
    - 대응: provisional 블록 + 마지막에 Batch로 재정리 가능하게 설계
- **LLM JSON 깨짐**
    - 대응: structured outputs + Pydantic 검증 + 1회 재시도 + fallback
- **순서 꼬임/중복**
    - 대응: 멱등키 + per-session 직렬 처리 + 재처리 정책

---

## 8. 최종 산출물(문서/코드)
- MCP 서버
    - Batch: `/v1/session-blocks:build`
    - Real-time: `/v1/session-blocks:ingest-message` (및 필요 시 ingest-batch)
- 성능 리포트
    - `baseline_batch_report.md`
    - `comparison_realtime_vs_batch_report.md`
- 운영 문서
    - env/config, 모델 버전, analysis_version 정책, 장애 대응(runbook)

---

### 부록: 실무 권장 설정(초기값)
- shift 휴리스틱
    - `timeGapMinutes=10`
    - `shiftLowSim=0.20`, `shiftHighSim=0.45`
    - 애매구간만 LLM 타이브레이크 호출
- tail context
    - `maxLastMessagesForContext=6`
- 동시성
    - Ollama 호출 `MAX_CONCURRENCY=2~4`
- 요약 정책
    - Batch: 변경 블록만 요약
    - Real-time: 블록 종료/사용자 선택 시 요약(매 메시지 요약 금지)

