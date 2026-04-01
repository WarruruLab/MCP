# MCP 실시간 전환 개발 계획

기준일: 2026-04-01

## 0. 목표

이 프로젝트를 "batch summary server"에서 "real-time narrative block classifier"로 전환한다.

핵심 요구:

- 새 메시지 1개를 실시간으로 분류할 수 있어야 한다.
- block은 조립 가능한 서사 단위여야 한다.
- block은 문제, 제안, 시도, 실패, 성공 같은 단계를 분리해야 한다.
- 사용자는 block을 선택해 원하는 흐름만 DevLog 글에 반영할 수 있어야 한다.

## 1. block 모델 원칙

block 하나는 한 단계만 표현한다.

가능한 block type 예시:

- `problem`
- `proposal`
- `trial`
- `result`
- `insight`

status 예시:

- `neutral`
- `open`
- `failed`
- `success`

## 2. 권장 block 스키마

```json
{
  "blockId": "blk_123",
  "topic": "Redis timeout issue",
  "blockType": "result",
  "status": "failed",
  "summary": "Retry with increased timeout failed again.",
  "messageIds": ["msg_21", "msg_22"],
  "tags": {
    "method": "increase timeout",
    "result": "failed",
    "reason": "upstream dependency still blocked"
  }
}
```

## 3. 실시간 처리 흐름

1. DevTalk에서 새 메시지 발생
2. MCP가 최근 메시지와 active block 목록을 조회
3. local LLM에 분류 요청
4. LLM이 아래 중 하나를 반환
   - 기존 block 후보 중 하나 선택 후 append
   - 새 block 생성
5. MCP가 block 상태 저장
6. DevLog가 최신 block 흐름 조회

## 4. LLM 입력 컨텍스트

- `sessionId`
- `currentMessage`
- `recentMessages`
- `activeBlocks`

`activeBlocks`는 "append 가능한 block 후보 집합"이다. LLM은 이 후보들 중 가장 어울리는 block을 선택하거나, 적합한 후보가 없다고 판단하면 새 block 생성을 반환해야 한다.

`activeBlocks`에는 각 block의 아래 정보가 포함되어야 한다.

- `blockId`
- `topic`
- `blockType`
- `status`
- `summary`
- `recentMessageIds`
- `tags`

## 5. LLM 출력 계약

```json
{
  "action": "APPEND",
  "targetBlockId": "blk_123",
  "blockType": "trial",
  "status": "neutral",
  "topic": "Redis timeout issue",
  "summary": "Tried increasing timeout and reran the request.",
  "tags": {
    "method": "increase timeout"
  },
  "score": 0.88,
  "reason": "same_attempt_continues"
}
```

필수 조건:

- JSON only
- `action`: `APPEND | NEW_BLOCK`
- `blockType`는 허용된 enum만 사용
- `status`는 허용된 enum만 사용
- `summary`는 block 한 줄 설명이어야 함
- `tags`는 block 타입에 맞는 일부 필드만 채움

## 6. 구현 단계

### Phase 1. 모델 정리

1. 기존 5-tag 기본 모델 제거 방향 확정
2. narrative block DTO 설계
3. active block 조회/저장 구조 설계

### Phase 2. 분류 경로 구현

1. `ingest-message` DTO 작성
2. local LLM prompt 작성
3. structured output parser 작성
4. invalid output fallback 작성

### Phase 3. block 상태 반영

1. 기존 block append
2. 새 block 생성
3. tag merge 정책 작성
4. summary 갱신 정책 작성

### Phase 4. 운영 안전성

1. 세션 직렬 처리
2. 멱등 처리
3. replay 처리
4. logging / metrics / trace id

## 7. 더 이상 기본으로 두지 않는 가정

- block 하나에 문제부터 해결까지 모두 담는 방식
- 모든 block에 동일한 tag 세트를 채우는 방식
- batch가 중심이고 real-time이 보조라는 가정
- 규칙 기반 판정이 주가 되는 구조

## 8. 개발 산출물

개발 완료 시 최소 산출물:

- `POST /v1/session-blocks:ingest-message`
- narrative block DTO
- local LLM classifier prompt
- active block state update 로직
- block 선택용 DevLog 계약 문서
