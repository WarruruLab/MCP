# MCP 개발 세부 계획 (Batch 전용, 실행 가능한 수준)

## 0. 범위
1. 대상은 Batch API `/v1/session-blocks:build`만 포함한다.
2. Real-time/ingest 관련 기능은 포함하지 않는다.

## 1. 입력/출력 스펙 고정
1. Request 필수 필드 (고정)
   - `sessionId` (string)
   - `analysisMode` (string: `INCREMENTAL` | `FULL`)
   - `messages[]` (array)
   - `existingBlocks[]` (array)
   - `options` (object)
2. Message 필수 필드 (고정)
   - `messageId` (string)
   - `role` (string: `user` | `assistant` | `system`)
   - `content` (string)
   - `timestamp` (string, ISO-8601)
3. existingBlocks 최소 필드
   - `blockId` (string)
   - `messageIds[]` (string[])
   - `tags` (object, optional)
4. options 기본값
   - `timeGapMinutes`: 10
   - `shiftLowSim`: 0.20
   - `shiftHighSim`: 0.45
   - `maxLastMessagesForContext`: 6
5. 정렬 규칙 (고정)
   - `timestamp` asc, tie-breaker `messageId` asc
6. Response 필수 필드 (고정)
   - `sessionId` (string)
   - `analysis_version` (string)
   - `model` (string)
   - `blocks[]` (session_block[])
   - `messageToBlock` (map)
   - `stats` (object)

## 2. 스키마/검증 정책
1. 입력 검증
   - 필수 필드 누락 시 4xx
   - `role` 허용값 검증
   - `timestamp` 파싱 실패 시 4xx
   - `messages[]` 비어있으면 400
2. 출력 검증
   - JSON Schema 또는 Pydantic으로 응답 검증
   - 검증 실패 시 500
3. 결정론 보장
   - LLM temperature 0, fixed seed
   - 동일 입력 -> 동일 출력

## 3. 구현 파일 구조 (MCP 서버)
1. `src/api/handlers.py`
   - `/v1/session-blocks:build` 라우팅
2. `src/models/dto.py`
   - Request/Response/Block 스키마 정의
3. `src/core/builder.py`
   - `build_session_blocks()` 구현
4. `src/core/decision.py`
   - APPEND/NEW_BLOCK 규칙 + LLM 호출
5. `src/core/summarize.py`
   - summarize_block 로직
6. `src/llm/client.py`
   - LLM client + structured output
7. `src/utils/validate.py`
   - 입력/출력 검증 유틸

## 4. 핵심 처리 단계 (build_session_blocks)
1. 입력 검증
2. 메시지 정규화
   - 공백 trim, null 제거, 타입 강제
3. 메시지 정렬
4. 기존 블록 로딩
   - `existingBlocks`에서 blockId -> block 객체 매핑
5. 메시지 순회
   - 각 메시지마다 APPEND/NEW_BLOCK 판정
   - messageToBlock 갱신
6. 변경된 블록만 summarize
7. 응답 조립
   - blocks, messageToBlock, stats 포함

## 5. APPEND/NEW_BLOCK 결정 규칙 (구체)
1. 시간 간격
   - 마지막 메시지와의 gap > `timeGapMinutes` => NEW_BLOCK
2. 유사도
   - 유사도 <= `shiftLowSim` => NEW_BLOCK
   - 유사도 >= `shiftHighSim` => APPEND
3. 경계 구간
   - LLM structured output로 결정
4. LLM 결과 스키마
   - `{action: APPEND|NEW_BLOCK, score: 0.0~1.0, reason: string}`

## 6. 블록 ID 생성 규칙
1. 신규 블록 ID: `blk_{sessionId}_{seq}`
2. `seq`는 이번 build 내에서만 증가
3. 기존 blockId와 충돌 시 +1 재시도

## 7. summarize_block 규칙
1. 변경된 블록만 실행
2. 출력 tags
   - `CONTEXT`, `PROBLEM`, `TRIAL[]`, `SOLUTION`, `INSIGHT`
3. code_snippets 추출
   - 코드/설정/명령어 패턴 기반
4. confidence 계산
   - LLM score 또는 규칙 기반 점수

## 8. LLM 연동 상세
1. Structured output 프롬프트 고정
2. 1회 재시도 후 실패 시 규칙 기반 fallback
3. LLM 응답 검증 실패 로그 기록

## 9. 통계/로그
1. `stats`
   - `numMessages`, `numBlocks`, `llmCalls_shift`, `llmCalls_summarize`
2. 로그
   - request id, 처리시간, 에러코드, LLM 호출 수

## 10. 테스트/검증
1. 샘플 10개 입력에서 스키마 100% 통과
2. 동일 입력 3회 반복 결과 동일성 확인
3. 1000+ 메시지 입력에서 timeout 없이 완료

## 11. 개발 순서 (실행 절차)
1. DTO/스키마 정의
2. 입력 검증 로직 구현
3. build_session_blocks 코어 로직 구현
4. 결정 규칙 + LLM 연동
5. summarize_block 구현
6. 응답/통계/로그 완성
7. 테스트 데이터로 검증