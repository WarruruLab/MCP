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
  - 애매 구간용 Ollama 호출 구조 존재, 실패 시 fallback 동작
  - `existingBlocks[].lastMessage`를 이용한 incremental 문맥 연결 구현됨
  - 변경 블록 요약(tags) 및 코드 스니펫 추출 구현됨
  - 기본 자동 테스트 추가됨

- 아직 부족한 것
  - Ollama 실환경 검증이 아직 충분하지 않음
  - 요약 품질은 휴리스틱 수준이며 정교하지 않음
  - API/운영 로그, 메트릭, 재시도 체계 없음
  - Real-time API 없음
  - structured output 검증과 fallback 고도화가 미흡함
  - 성능 baseline 문서가 아직 없음

즉, 현재 상태는 **Batch 기반 서버 MVP는 실행 가능한 수준까지 올라왔지만, 운영 안정화와 실환경 검증은 아직 남아 있는 단계**다.

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

현재 상태:
- `existingBlocks[].lastMessage`가 들어오면 기존 블록의 마지막 문맥을 복원할 수 있다.
- 따라서 incremental 요청에서 이전 블록에 자연스럽게 append될 가능성이 이전보다 높아졌다.
- 다만 이 구조는 호출 측이 `lastMessage`를 정확히 넘겨준다는 전제가 필요하다.

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
- 초기 데모 수준은 넘겼다.
- `CONTEXT`, `PROBLEM`, `TRIAL`, `SOLUTION`, `INSIGHT`를 메시지 기반으로 뽑는다.
- fenced code block 외에 명령어 라인도 스니펫으로 뽑는다.
- 다만 여전히 휴리스틱 기반이라 고품질 요약으로 보기엔 부족하다.

### `src/mcp/llm/client.py`

- `LlmClient` 클래스 존재
- `decide_append_or_new()` 인터페이스 존재
- 그러나 실제 모델 호출은 없고, context 길이의 짝/홀수로 결과를 결정하는 deterministic stub임

판단:
- Ollama HTTP API를 호출하는 구조는 구현되어 있다.
- 다만 서버 환경에서 실제 Ollama 연결 상태를 충분히 검증한 것은 아니다.
- 호출 실패 시 deterministic fallback으로 내려가도록 되어 있다.

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
- incremental 문맥 연결
- 기본 테스트 추가

### 부분 완료 항목

- `INCREMENTAL` 지원
  - `lastMessage` 기반으로 보강됨
  - 다만 호출 측 문맥 전달 정확도에 의존함
- LLM 연동
  - Ollama 호출 구조는 구현됨
  - 실환경 검증과 안정화는 미완료
- summarize
  - 함수와 테스트는 존재
  - 품질은 휴리스틱 수준

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

현재 코드는 **"Batch MCP MVP가 실행 가능한 수준이며, 이제 우분투 서버 실환경 검증과 운영 안정화 단계로 넘어가는 상태"**라고 정리하는 것이 맞다.

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

## 8. 우분투 운영 문서

- `README.md`
- `ubuntu_server_guide.md`

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

### 2026-03-11 추가 수정 2

- `src/mcp/core/summarize.py`
  - 요약 로직을 단순 고정 문구 방식에서 메시지 기반 휴리스틱 방식으로 교체했다.
  - `CONTEXT`는 첫 번째 유효 메시지 문장을 사용한다.
  - `PROBLEM`, `TRIAL`, `SOLUTION`, `INSIGHT`는 메시지별 키워드 탐지 결과를 실제 문장과 함께 태그로 남긴다.
  - fenced code block 외에도 `$ ...`, `python`, `uvicorn`, `git`, `docker`, `npm` 같은 명령어 라인을 `bash` 스니펫으로 추출한다.

- `tests/test_builder.py`
  - summarize 결과 검증 테스트 추가
  - 코드 스니펫 추출 테스트 추가
  - incremental append 동작 테스트 추가
  - API의 잘못된 `analysisMode` 검증 테스트 추가
  - 현재 로컬 환경에 `fastapi`가 없을 때는 API 테스트를 skip 하도록 처리했다.

- `src/mcp/core/builder.py`
  - metadata timestamp 생성을 `datetime.now(UTC)` 기반으로 바꿔 Python 3.13 deprecation warning을 제거했다.

- 검증
  - `python -m compileall src tests` 통과
  - `$env:PYTHONPATH='src'; python -m unittest discover -s tests -v` 통과
  - 테스트 결과:
    - `4`개 실행
    - `3`개 통과
    - `1`개 skip (`fastapi` 미설치 환경)

### 2026-03-11 추가 수정 3

- `README.md`
  - 루트 문서를 우분투 서버 기준 진입 문서로 정리했다.
  - 현재 구현 범위, 핵심 문서 링크, 빠른 실행 명령, 테스트 명령을 넣었다.

- `ubuntu_server_guide.md`
  - 우분투 서버 설치/실행/테스트 절차를 문서화했다.
  - 포함 내용:
    - 서버 사전 준비
    - 가상환경 생성
    - 의존성 설치
    - `uvicorn` 실행
    - `curl` 기반 Batch/Incremental 요청 예제
    - `unittest` 실행
    - Ollama 환경변수 및 확인 절차
    - `systemd` 서비스 예시
    - 배포 직후 최소 점검 절차

- 방향 정리
  - 앞으로는 윈도우 테스트 기준을 버리고 우분투 서버 기준으로만 진행한다.

### 2026-03-11 추가 수정 4

- `deploy/mcp.service`
  - 우분투 `systemd` 서비스 파일을 실제 파일로 추가했다.
  - 기본 경로는 `/opt/mcp`, 서비스명은 `mcp` 기준이다.
  - `.env`를 `EnvironmentFile`로 읽도록 설정했다.

- `deploy/setup_ubuntu.sh`
  - 우분투 서버에서 바로 실행 가능한 초기 배포 스크립트를 추가했다.
  - 수행 내용:
    - apt 패키지 설치
    - 가상환경 생성
    - 의존성 설치
    - `.env.example` -> `.env` 복사
    - `systemd` 서비스 등록
    - 서비스 시작

- `.env.example`
  - Ollama 관련 기본 환경변수 예시 파일을 추가했다.

- 문서 반영
  - `README.md`에 배포 파일 링크 추가
  - `ubuntu_server_guide.md`에 배포 파일 소개와 `setup_ubuntu.sh` 실행 예시 추가

### 2026-03-11 추가 수정 5

- `examples/full_build_request.json`
  - 서버에 올린 뒤 바로 `FULL` 요청 테스트를 할 수 있는 예제 payload를 추가했다.

- `examples/incremental_build_request.json`
  - `existingBlocks[].lastMessage`까지 포함한 incremental 요청 예제 payload를 추가했다.

- `deploy/check_ubuntu.sh`
  - 우분투 서버에서 배포 직후 한 번에 점검할 수 있는 스크립트를 추가했다.
  - 수행 내용:
    - `unittest` 실행
    - FULL 요청 전송
    - INCREMENTAL 요청 전송
    - Ollama 도달 가능 여부 확인

- 문서 반영
  - `README.md`에 점검 스크립트와 예제 payload 링크 추가
  - `ubuntu_server_guide.md`에 `check_ubuntu.sh` 사용 예시 추가
