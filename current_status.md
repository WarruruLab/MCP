# MCP 현재 상태 정리

기준일: 2026-04-01

## 1. 한 줄 상태

현재 저장소에는 batch 기반 구현이 남아 있지만, 제품 방향은 **실시간 서사 단위 block 분류 서버**로 전환되었다.

## 2. MCP가 만드는 block의 의미

이 서버에서 block은 "한 이슈 전체 요약"이 아니다.

block 하나는 개발 흐름 안의 한 단계다.

예시:

- 문제 발견
- 해결책 제안
- 특정 방법 시도
- 시도 실패
- 다른 방법 시도
- 최종 성공

따라서 하나의 세션은 여러 block으로 쪼개져야 하며, 사용자는 이 block들을 선택적으로 조합해 DevLog 글을 만든다.

## 3. 기존 5-tag 방식의 한계

현재 코드의 `CONTEXT / PROBLEM / TRIAL / SOLUTION / INSIGHT` 구조는 block 하나에 여러 의미를 동시에 넣는 방식이다.

이 방식의 문제:

- "문제", "제안", "시도", "실패", "성공"을 분리하기 어렵다
- 사용자가 실패 과정을 제외하거나 특정 시도만 남기기 어렵다
- narrative editing보다 summary aggregation에 가깝다

즉 현재 구현은 baseline으로는 쓸 수 있지만, 최종 제품 모델로는 맞지 않는다.

## 4. 목표 block 모델

앞으로 block은 아래 필드를 중심으로 가져간다.

- `topic`
- `blockType`
- `status`
- `summary`
- `messageIds`
- `tags`

여기서 중요한 점은 `tags`를 전부 채우지 않는다는 것이다.

block 타입에 따라 일부만 사용한다.

예:

- problem block: `problem`
- proposal block: `candidates`
- trial block: `method`
- result block: `result`, `reason`
- insight block: `root_cause`, `lesson`

## 5. local LLM의 역할

local LLM은 생성기가 아니라 분류기다.

- 새 메시지가 이미 존재하는 block 후보들 중 어디에 속하는지 판단
- 적합한 기존 block이 있으면 append 대상으로 선택
- 적합한 block이 없으면 새 block을 만들도록 판단
- block의 `blockType`, `status`, `summary`, `tags` 후보를 반환

## 6. 서버의 역할

- 세션 단위 직렬 처리
- `sessionId + messageId` 멱등 처리
- out-of-order 메시지 정책 처리
- LLM 응답 JSON 검증
- block 상태 저장
- append / new block 반영
- 필요한 경우 재요약 예약

## 7. 현재 구현되어 있는 것

- FastAPI 진입점
- `ingest-message` endpoint
- narrative block DTO
- candidate block 기반 local LLM 분류
- block append / new block 반영 로직
- realtime 계약 테스트
- 기본 테스트

## 8. 예외 처리 방향

정상 경로 외의 실패는 버리지 않고 복구 가능한 상태로 남기는 방향으로 간다.

핵심 정책:

- 메시지 저장과 block 반영을 논리적으로 분리
- 반영 실패 메시지는 `failed` 또는 `reconcile_pending` 상태로 유지
- 나중에 batch reconciliation으로 세션 전체 메시지와 `block_messages`를 비교
- block에 포함되지 않은 `messageId`만 다시 routing

즉 운영 기준 복구 방식은 "전체 재분석"보다 **누락 메시지만 다시 block에 넣는 방식**이다.

## 9. 지금 필요한 다음 단계

1. 메시지 처리 상태 모델 추가
2. DB persistence와 멱등 처리 연결
3. retry 정책 추가
4. reconciliation batch 구현
5. 기존 5-tag summarize 의존 제거
