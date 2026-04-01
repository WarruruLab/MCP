# 개발 시작용 Plan

기준일: 2026-04-01

이 문서는 바로 개발을 시작하기 위한 실행 계획이다. 기준 모델은 **실시간 서사 단위 block 분류**다.

## 1. 개발 목표

한 메시지가 들어오면 MCP가 아래를 할 수 있어야 한다.

- 어떤 주제의 흐름인지 판단
- 이미 생성된 block 후보 중 어디에 붙일지 판단
- 어울리는 block이 없으면 새 block을 만들지 판단
- 그 block이 문제, 제안, 시도, 결과, 인사이트 중 무엇인지 정리
- 사용자가 나중에 block을 골라 DevLog 글 흐름을 구성할 수 있게 상태를 저장

## 2. 첫 구현 범위

첫 번째 목표는 아래까지다.

1. `POST /v1/session-blocks:ingest-message` 추가
2. 새 narrative block DTO 추가
3. local LLM structured classification 추가
4. 메모리 기반 block state update 구현
5. 기본 테스트 추가

## 3. 작업 분해

### Track A. API / DTO

- 입력 DTO 정의
- 출력 DTO 정의
- block model 정의
- validation 정리

### Track B. LLM 분류기

- prompt 설계
- JSON schema 정의
- 응답 파싱
- fallback 정책

### Track C. 상태 반영 로직

- candidate block 조회
- active block 조회
- target block 선택 결과 반영
- append 처리
- new block 처리
- tag merge / summary update

### Track D. 테스트

- append 시나리오
- new block 시나리오
- failed/success block 시나리오
- invalid LLM output 시나리오

## 4. sub-agent 도입 방식

이 작업은 병렬 분리가 가능하다. sub-agent를 쓴다면 아래 단위로 나눈다.

### Sub-agent 1. DTO / 모델 담당

책임:

- `src/mcp/models.py`
- 요청/응답 스키마 정리
- block type / status enum 설계

완료 조건:

- `ingest-message`용 DTO가 코드에 반영됨

### Sub-agent 2. LLM 클라이언트 담당

책임:

- `src/mcp/llm/client.py`
- 분류 prompt
- structured output parser
- invalid output fallback

완료 조건:

- narrative block classification 결과를 안정적으로 반환

### Sub-agent 3. core 분류/반영 로직 담당

책임:

- `src/mcp/core/` 아래 새 분류 로직
- append / new block state update
- tag merge 정책

완료 조건:

- message 1개 입력 시 block state가 갱신됨

### Sub-agent 4. 테스트 담당

책임:

- `tests/`
- realtime ingest 기준 테스트 작성

완료 조건:

- 최소 핵심 시나리오 자동 검증 가능

## 5. 병렬 작업 순서

1. Sub-agent 1이 DTO와 상태 모델을 먼저 고정
2. Sub-agent 2와 3은 그 계약을 기준으로 병렬 진행
3. Sub-agent 4는 DTO 초안이 정해지는 즉시 테스트 작성 시작
4. 마지막에 메인 에이전트가 endpoint 연결과 통합 검증 수행

## 6. 구현 우선순위

P0

- narrative block 스키마
- ingest endpoint
- LLM classification output
- append / new block 반영

P1

- block 간 연관 관계
- proposal -> trial -> result 연결 필드
- better summary update

P2

- persistence 저장소
- replay / recovery
- metrics / trace

P3

- 메시지 처리 상태 모델
- retry 정책
- reconciliation batch
- 누락 `messageId` 복구

## 7. block 설계 메모

권장 최소 필드:

```json
{
  "blockId": "blk_123",
  "topic": "Redis timeout issue",
  "blockType": "trial",
  "status": "neutral",
  "summary": "Tried increasing timeout and retried the request.",
  "messageIds": ["msg_10", "msg_11"],
  "tags": {
    "method": "increase timeout"
  }
}
```

추가 후보 필드:

- `parentBlockId`
- `relatedBlockIds`
- `createdAt`
- `updatedAt`

## 8. 시작 명령

개발 착수 순서:

1. DTO 설계
2. endpoint 추가
3. LLM output schema 구현
4. state update 구현
5. 테스트 작성

이 문서를 기준으로 바로 sub-agent를 투입해 병렬 개발을 시작할 수 있다.

## 9. 예외 처리 메모

운영 단계에서는 정상 경로만으로 충분하지 않다.

예외 방향:

1. 메시지는 먼저 저장
2. MCP 반영 실패 시 메시지를 버리지 않음
3. 해당 메시지는 `failed` 또는 `reconcile_pending` 상태로 남김
4. reconciliation에서 세션 전체 메시지와 block에 포함된 메시지를 비교
5. 누락된 `messageId`만 다시 routing

즉 복구 기준은 "세션 전체 재분석"이 아니라 "block에 아직 포함되지 않은 메시지만 재처리"다.
