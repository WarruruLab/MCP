# MCP 현재 구현 상태 정리

기준일: 2026-03-11

## 1. 결론 요약

현재 `src` 기준으로 보면 이 프로젝트는 **Batch 전용 MCP 서버의 초기 MVP가 구현된 상태**다.

- 완료된 것
  - FastAPI 서버 진입점 존재
  - `POST /v1/session-blocks:build` 엔드포인트 존재
  - 요청 DTO/응답 DTO 정의됨
  - 메시지 정렬 및 기본 검증 구현됨
  - 규칙 기반 `APPEND / NEW_BLOCK` 결정 로직 구현됨
  - 애매 구간용 LLM 호출 인터페이스는 존재함
  - 변경 블록에 대한 간단 요약 및 코드 스니펫 추출 구현됨

- 아직 부족한 것
  - 실제 LLM 연동 없음, 현재는 stub
  - 요약 품질이 매우 단순한 키워드 규칙 수준
  - 기존 블록 문맥을 활용한 incremental 처리 완성도 낮음
  - 테스트 코드 없음
  - Real-time API 없음
  - 로그/메트릭/재시도/structured output 검증 같은 운영 안정화 요소 없음

즉, 문서상 표현대로 "실행 가능한 상태"는 맞지만, **실서비스 연결 전 단계의 프로토타입**으로 보는 것이 정확하다.

## 2. 파일별 확인 결과

### `src/mcp/main.py`

- FastAPI 앱 생성 완료
- `POST /v1/session-blocks:build` 라우트 구현 완료
- 입력 검증 수행
  - `sessionId` 비어있는지 확인
  - `messages` 존재 여부 확인
  - `role` 정규화 및 허용값 검증
  - `messageId`, `content`, `timestamp` 검증
- `ValueError`를 `400`으로 변환

판단:
- Batch API의 최소 진입점은 구현됨
- 다만 요청/응답 trace, 로깅, 세부 예외 분류는 없음

### `src/mcp/models.py`

- Request/Response DTO 정의 완료
- 아래 구조가 문서와 대체로 일치함
  - `BuildRequestDTO`
  - `BuildOptionsDTO`
  - `SessionBlockDTO`
  - `BuildStatsDTO`
  - `BuildResponseDTO`

판단:
- 스키마 뼈대는 잘 있음
- 하지만 `analysisMode` 허용값 검증, 필드 단위 제약, 응답 메타 정합성 검증은 약함

### `src/mcp/core/builder.py`

- 핵심 파이프라인 구현 완료
  - 메시지 정규화
  - timestamp 기준 정렬
  - 기존 블록 로드
  - 메시지 순회
  - `APPEND / NEW_BLOCK / LLM` 분기
  - 블록 생성 및 `messageToBlock` 매핑
  - 변경 블록 summarize
  - 최종 응답 생성

판단:
- 현재 프로젝트에서 가장 많이 구현된 부분
- 문서의 Batch 흐름을 실제 코드로 옮긴 핵심 모듈

중요 한계:
- `existingBlocks`의 마지막 메시지가 이번 요청의 `messages` 안에 없으면, 기존 블록의 마지막 문맥을 복원하지 못한다.
- 그 경우 첫 신규 메시지는 사실상 `first_message`처럼 처리되어 새 블록이 시작될 가능성이 높다.
- 따라서 현재 `INCREMENTAL` 모드는 "기존 블록을 이어서 정확히 붙이는 구현"이라고 보기 어렵다.

### `src/mcp/core/decision.py`

- Jaccard 유사도 기반 유사도 계산 구현
- 시간 간격 기반 분기 구현
- 저유사도면 `NEW_BLOCK`, 고유사도면 `APPEND`
- 중간 구간은 `LLM`으로 넘기는 구조 구현

판단:
- 휴리스틱 초안은 있음
- 계획 문서의 1차 규칙 + 2차 LLM 타이브레이크 구조와 방향은 맞음
- 다만 토큰화가 단순 공백 분리 수준이라 한국어/코드 혼합 대화에서는 품질 한계가 큼

### `src/mcp/core/summarize.py`

- fenced code block 기반 코드 스니펫 추출 구현
- 요약은 키워드 기반 간단 태깅 구현
  - `error`, `exception` -> `PROBLEM`
  - `fix`, `resolve` -> `SOLUTION`
  - `try`, `attempt` -> `TRIAL`

판단:
- MVP 데모용으로는 가능
- 실제 `CONTEXT`, `INSIGHT` 품질은 거의 비어 있음
- 문서에서 기대한 "블로그 초안 생성에 유용한 블록 품질"까지는 아직 도달하지 못함

### `src/mcp/llm/client.py`

- `LlmClient` 클래스 존재
- `decide_append_or_new()` 인터페이스 존재
- 그러나 실제 모델 호출은 없고, context 길이의 짝/홀수로 결과를 결정하는 deterministic stub임

판단:
- LLM 연동은 미구현
- 현재 코드에서 LLM 관련 부분은 구조만 잡혀 있고 기능은 가짜 응답이다

### `src/mcp/utils/validate.py`

- role 정규화 구현
  - `ai` -> `assistant`
- ISO8601 timestamp 파싱 구현
- 빈값 검증 구현
- 허용 role 검증 구현

판단:
- 기본 유효성 검사는 있음
- 실무용 스키마 강제, 세부 필드 검증, 에러 코드 체계화는 아직 아님

## 3. 문서 대비 실제 완성도

### 완료된 항목

- Batch 엔드포인트의 기본 형태
- 메시지 검증/정렬
- 블록 생성 및 매핑
- 규칙 기반 결정 로직
- 변경 블록 summarize 처리
- 응답에 `stats` 포함

### 부분 완료 항목

- `INCREMENTAL` 지원
  - 형식상 존재
  - 실제로는 기존 블록 마지막 문맥 활용이 부족해서 완성이라고 보기 어려움
- LLM 연동
  - 호출 포인트는 존재
  - 실제 모델 연동은 미완료
- summarize
  - 함수는 존재
  - 품질은 매우 기초 수준

### 미완료 항목

- Ollama structured outputs
- Pydantic 기반 LLM 응답 검증
- LLM 실패 재시도 / fallback 고도화
- chunk 처리
- timeout 대응
- baseline 성능 측정 결과 문서
- Real-time API (`/v1/session-blocks:ingest-message`)
- 테스트 코드
- 운영 로그/메트릭

## 4. 현재 구현 수준을 한 문장으로 평가

현재 코드는 **"Batch API 프로토타입이 돌아갈 수는 있지만, 결과 품질과 증분 처리 정확도는 아직 연구용 초기 단계"**라고 정리하는 것이 맞다.

## 5. 지금 바로 다음 우선순위

1. `LlmClient`를 실제 Ollama 호출로 교체
2. `builder.py`에서 기존 블록 마지막 메시지 문맥을 정확히 받도록 데이터 구조 보강
3. `summarize.py` 품질 개선
4. 샘플 입력 기반 테스트 추가
5. 성능/품질 baseline 문서화

## 6. 참고 파일

- `plan.md`
- `mcp_dev_plan.md`
- `mcp_progress.md`
- `src/mcp/main.py`
- `src/mcp/models.py`
- `src/mcp/core/builder.py`
- `src/mcp/core/decision.py`
- `src/mcp/core/summarize.py`
- `src/mcp/llm/client.py`
- `src/mcp/utils/validate.py`

## 7. 수정 이력

### 2026-03-11 추가 수정 1

- `src/mcp/models.py`
  - `ExistingBlockDTO.lastMessage` 필드를 추가했다.
  - 목적은 incremental 요청 시 기존 블록의 마지막 메시지 문맥을 함께 전달받기 위함이다.

- `src/mcp/main.py`
  - `analysisMode`를 `FULL`, `INCREMENTAL`로 검증하도록 추가했다.
  - `existingBlocks[].lastMessage`가 들어오면 `messageId`, `role`, `content`, `timestamp`를 함께 검증하도록 추가했다.

- `src/mcp/core/builder.py`
  - 요청 메시지와 기존 블록의 마지막 메시지를 함께 보관하는 `message_lookup`을 추가했다.
  - 기존 블록의 마지막 메시지 문맥을 `existingBlocks[].lastMessage`에서 복원할 수 있게 바꿨다.
  - 변경 블록 summarize 시 기존 tags를 단순 덮어쓰지 않고 `merge_tags()`로 유지하면서 보강하도록 바꿨다.
  - 이 변경으로 기존 블록에 새 메시지를 append할 때 이전 `tags`가 통째로 사라지는 문제가 줄었다.

- `src/mcp/llm/client.py`
  - 기존의 단순 stub 클라이언트를 실제 Ollama HTTP 호출 구조로 교체했다.
  - 기본값:
    - `OLLAMA_BASE_URL=http://127.0.0.1:11434`
    - `OLLAMA_MODEL=qwen2.5:3b`
    - `OLLAMA_TIMEOUT_SECONDS=10`
  - Ollama 호출 실패 또는 잘못된 JSON 응답 시에는 deterministic fallback으로 내려가도록 했다.

- 검증
  - `python -m compileall src` 통과
  - 샘플 incremental 입력으로 `existingBlocks[].lastMessage`를 전달했을 때 신규 메시지가 기존 블록에 append되는 동작 확인

### 현재 수정 후 상태

- Batch API는 여전히 중심 기능이다.
- 다만 이제 incremental 요청이 기존 블록의 마지막 메시지 문맥을 선택적으로 전달받아 이어갈 수 있게 되었다.
- LLM도 완전한 stub만 있는 상태는 아니고, 로컬 Ollama가 있으면 실제 호출을 시도한다.
- 아직 남은 핵심 작업:
  - 실제 요청 예제로 동작 검증
  - summarize 품질 개선
  - 테스트 코드 추가
  - 성능/품질 baseline 측정
