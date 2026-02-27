# MCP 개발 세부 계획 (Batch 전용)

## 0. 범위
1. 대상은 Batch API `/v1/session-blocks:build`만 포함한다.
2. Real-time/ingest 관련 내용은 포함하지 않는다.

## 1. 입력/출력 스펙 고정
1. Request 필수 필드
   - `sessionId`, `analysisMode`, `messages[]`, `existingBlocks[]`, `options`
2. Message 필수 필드
   - `messageId`, `role`, `content`, `timestamp`
3. 정렬 규칙
   - `timestamp` asc, tie-breaker `messageId` asc
4. Response 필수 필드
   - `sessionId`, `analysis_version`, `model`, `blocks[]`, `messageToBlock`, `stats`

## 2. 스키마/검증 정책
1. 입력 검증
   - 필수 필드 누락 시 4xx
   - `role` 허용값 검증
   - `timestamp` 파싱 실패 시 4xx
2. 출력 검증
   - JSON Schema 또는 Pydantic으로 응답 검증
3. 결정론 보장
   - LLM temperature 0, 고정 seed
   - 동일 입력에 동일 출력

## 3. 핵심 처리 단계
1. 메시지 정규화
   - 공백/널 정리, 타입 강제
2. 메시지 정렬
   - 규칙에 따라 정렬, 동일 timestamp 처리
3. APPEND vs NEW_BLOCK 결정
   - 1차 규칙 기반 스코어링
   - 2차 LLM 판정(Structured JSON)
   - LLM 실패 시 규칙 기반으로 fallback
4. 블록 업데이트
   - append 시 `messageIds` 추가
   - new block 시 `blockId` 생성
5. summarize_block 실행
   - 변경된 블록만 요약
   - tags/code_snippets 생성

## 4. APPEND/NEW_BLOCK 규칙(초안)
1. 시간 간격 기준
   - `timeGapMinutes` 초과면 NEW_BLOCK 우선
2. 유사도 기준
   - `shiftLowSim` 이하: NEW_BLOCK
   - `shiftHighSim` 이상: APPEND
3. 경계 구간
   - 사이 구간은 LLM 판단

## 5. 블록 ID 규칙
1. 신규 블록 ID는 `blk_{sessionId}_{seq}` 형식
2. seq는 이번 build 내에서만 증가

## 6. summarize_block 규칙
1. 변경된 블록만 실행
2. tags
   - `CONTEXT`, `PROBLEM`, `TRIAL[]`, `SOLUTION`, `INSIGHT`
3. code_snippets
   - 코드/설정/명령어 추출
4. confidence 계산
   - LLM score 또는 규칙 기반 점수

## 7. LLM 연동 상세
1. Structured Output
   - `{action, score, reason}` 스키마 고정
2. 재시도
   - 1회 재시도 후 실패 시 fallback
3. 장애 대응
   - LLM 불가 시 전량 규칙 기반 처리

## 8. 통계/로그
1. `stats`
   - `numMessages`, `numBlocks`, `llmCalls_shift`, `llmCalls_summarize`
2. 로그
   - request id, 처리시간, 에러코드, LLM 호출 수

## 9. 테스트/검증
1. 샘플 10개 입력에서 스키마 100% 통과
2. 동일 입력 3회 반복 결과 동일성 확인
3. 1000+ 메시지 입력에서 timeout 없이 완료