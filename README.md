# MCP Server — 대화 메시지를 구조화된 블록으로

> **"로그를 글로 만들기 위해선, 먼저 의미 단위로 나눠야 한다"**
>
> 대화 메시지 묶음을 입력받아, 의미상 이어지는 메시지들을 `session block` 단위로 재구성하고
> 각 블록에 요약 정보와 코드 스니펫을 붙여 반환하는 MCP 서버입니다.

<br/>

## 개발 방식

> **설계는 직접, 코드는 AI에게**

저는 Spring Boot · Java가 주력이고 Python에 익숙하지 않습니다. 그래서 이 서버는 설계와 코드 작성 역할을 분리하는 방식으로 개발했습니다.

| 역할 | 담당 | 내용 |
|:---|:---:|:---|
| 설계 결정 | 직접 + AI | `plan.md`에 구조, block 의미, 예외 처리 방식을 정리 후 검토 |
| 코드 작성 | AI | 결정된 설계를 바탕으로 Python 코드 생성 |
| 검증 | 직접 | 실제로 실행하고 테스트하며 결과 확인 |

**이렇게 한 이유**: Python 문법 자체보다 어떤 구조의 서버를 왜 만드는지가 더 중요했습니다. 단순히 코드를 받아 붙여넣는 것이 아니라, block의 의미와 제품 흐름을 먼저 정하고 그에 맞는 구현을 검증하는 방식을 택했습니다.

---

<br/>

## WarruruLab 전체 파이프라인

> MCP Server는 **WarruruLab**의 두 번째 서비스입니다.

| | 개발톡(DevTalk) | MCP Server | 개발로그(DevLog) |
|:---:|:---:|:---:|:---:|
| **역할** | AI 대화로 문제 해결 로그 생성 | 메시지를 의미 단위 block으로 분류 | block 선택 → 블로그 초안 생성 |
| **기술** | Spring Boot · Java 21 | FastAPI · Python · Ollama | Spring Boot · Java 21 |
| **출력** | Session · Message 저장 | session_block | 블로그 글 초안 |

서비스 간 호출은 개발로그(DevLog)가 주도하며, MCP Server는 요청이 오면 분석 결과를 반환하는 역할입니다.

```
[Step 2] 블록 분류                               구현 방향 전환 중
DevLog ──── REST ────▶ MCP Server
            메시지 전달 → session_block 반환
```

연관 레포: [개발톡(DevTalk)](https://github.com/WarruruLab/DevTalk) · [개발로그(DevLog)](https://github.com/WarruruLab/DevLog)

---

<br/>

## 현재 구현 상태

**narrative block 구조로 전환 중**

현재 기준에서 MCP Server의 목표는 **사용자가 직접 조립 가능한 서사 단위 block**을 만드는 것입니다.

예를 들어 하나의 이슈는 아래처럼 여러 block으로 쪼개집니다.

- 문제 A 발견
- 방법 B, C, D 제안
- 방법 B 시도
- 방법 B 실패
- 방법 C 시도
- 방법 C 실패
- 방법 D 시도
- 방법 D 성공

이 구조를 쓰면 DevLog에서 사용자가 원하는 흐름만 선택할 수 있습니다.

- 실패 과정 없이 쓰고 싶으면 실패 block 제외
- 해결 과정만 강조하고 싶으면 성공 block만 선택
- 시행착오를 보여주고 싶으면 trial / failed block 포함

즉 MCP Server의 목표는 "한 덩어리 요약"이 아니라, **편집 가능한 narrative block을 만드는 것**입니다.

현재는 block 의미, block 타입, DB 구조, DevLog와의 연결 방식을 narrative 기준으로 다시 정리하고 있습니다. 핵심은 block 하나가 모든 정보를 다 가지는 것이 아니라, **문제 / 제안 / 시도 / 결과 / 인사이트 중 하나의 역할만 가지도록 설계하는 것**입니다.

| 항목 | 상태 | 설명 |
|:---|:---:|:---|
| narrative block 의미 정의 | ✅ 완료 | 문서와 설계 기준 정리 완료 |
| block type / status 설계 | ✅ 완료 | `problem / proposal / trial / result / insight` 기준 |
| MySQL 테이블 전환안 | ✅ 완료 | narrative block 기준 SQL 파일 작성 |
| README / plan / 개발 문서 정리 | ✅ 완료 | narrative 구조 기준으로 정리 |
| `ingest-message` API | ❌ 미완료 | 다음 단계 구현 대상 |
| local LLM block classifier | ❌ 미완료 | 다음 단계 구현 대상 |
| active block 상태 반영 로직 | ❌ 미완료 | 다음 단계 구현 대상 |

<br/>

## 기술 스택

| 영역 | 기술 | 선택 이유 |
|:---|:---|:---|
| Server | FastAPI · Python · uvicorn | MCP · AI 생태계 라이브러리가 Python에 집중되어 있음 |
| LLM | Ollama (`qwen2.5:3b`) | 외부 API 없이 로컬에서 실행 가능 |
| 검증 | Pydantic | 요청 · 응답 스키마 강제 |
| 배포 | Ubuntu · systemd | 개인 서버에 상시 운영 |
| 테스트 | unittest | 핵심 로직 단위 테스트 |
| DB 방향 | MySQL | DevLog 테이블과 바로 맞물려 운영 예정 |

<br/>

## 아키텍처

### 목표 구조

```
새 메시지 1개 입력 (POST /v1/session-blocks:ingest-message)
  ↓
현재 active block / 최근 문맥 / block 후보 조회
  ↓
local LLM이 기존 block 후보 중 어울리는 block을 선택
  ├── 적합한 block이 있으면 해당 block append
  └── 적합한 block이 없으면 새 block 생성
  ↓
선정된 block의 narrative 역할과 상태 갱신
  ↓
DevLog가 block을 선택해 글 흐름 구성
```

### 기존 태그 구조와 변경 방향

기존에는 block 하나에 아래 5-tag를 모두 넣는 구조를 사용했습니다.

| 태그 | 의미 | 기존 방식 |
|:---|:---|:---|
| `CONTEXT` | 어떤 작업 흐름인지 | 첫 문장 기반 추출 |
| `PROBLEM` | 핵심 문제 | 키워드 문장 추출 |
| `TRIAL` | 시도한 내용 | 키워드 문장 최대 3개 |
| `SOLUTION` | 해결 방법 | 키워드 문장 추출 |
| `INSIGHT` | 인사이트 | 키워드 문장 추출 |

하지만 narrative block 구조에서는 block 하나가 모든 태그를 다 갖지 않습니다.

예를 들어:

- `problem` block: 문제 설명만 가짐
- `proposal` block: 후보 해결책 목록만 가짐
- `trial` block: 특정 방법 시도만 가짐
- `result` block: 성공 또는 실패 결과만 가짐
- `insight` block: 원인과 교훈만 가짐

즉 기존의 5-tag 중심 구조 대신, `blockType + status + summary + partial tags` 구조로 바뀝니다.

### 기존 block 출력 구조

```json
{
  "blockId": "blk_sess_123_1",
  "messageIds": ["msg_001", "msg_002", "msg_007"],
  "tags": {
    "CONTEXT": "Redis 연결 설정 문제",
    "PROBLEM": "API 서버 시작 시 Redis 연결 오류 발생",
    "TRIAL": ["application.yml 수정 시도"],
    "SOLUTION": "환경변수 누락이 원인",
    "INSIGHT": "도커 네트워크 내부 hostname 사용 필요"
  },
  "code_snippets": [
    { "language": "yaml", "content": "spring.data.redis.host: redis", "sourceMessageId": "msg_007" }
  ],
  "confidence": 0.5
}
```

### 목표 block 출력 구조

```json
{
  "blockId": "blk_123",
  "topic": "Redis timeout issue",
  "blockType": "result",
  "status": "success",
  "summary": "Increasing timeout resolved the issue.",
  "messageIds": ["msg_021", "msg_022"],
  "tags": {
    "method": "increase timeout",
    "result": "success"
  }
}
```

LLM은 새 메시지를 독립적으로만 보지 않고, 이미 생성된 block 후보들과 비교해 판단합니다. 즉 기준은 "직전 메시지와 비슷한가"보다 "현재 존재하는 어떤 narrative block에 속하는가"입니다. 어울리는 block이 없을 때만 새 block을 만듭니다.

<br/>

## 장점과 한계

**장점**

- 사용자가 실패 과정 포함 여부를 직접 고를 수 있다
- 하나의 이슈를 문제, 제안, 시도, 결과로 나눠 더 자연스럽게 편집할 수 있다
- DevLog에서 원하는 흐름만 선택해 글을 구성할 수 있다
- block 의미가 더 명확해진다
- DB 구조와 API 방향을 서사 단위 중심으로 맞출 수 있다

**한계**

- narrative block 구조는 아직 코드에 반영되지 않았다
- local LLM 분류기와 `ingest-message` API가 아직 구현되지 않았다
- block 간 관계를 어떻게 유지할지 세부 정책이 더 필요하다

<br/>

## 프로젝트 구조

```
mcp/
├── src/mcp/
│   ├── main.py              # FastAPI 앱 · 엔드포인트
│   ├── models.py            # Request · Response DTO (Pydantic)
│   ├── core/
│   │   ├── builder.py       # 기존 block 생성 로직
│   │   ├── decision.py      # 기존 block 판정 로직
│   │   └── summarize.py     # 기존 tags · 코드 스니펫 추출
│   ├── llm/
│   │   └── client.py        # Ollama 호출 · 분류기 전환 예정
│   └── utils/
│       └── validate.py      # 입력 검증 · role 정규화
│
├── tests/
│   └── test_builder.py      # 기존 block 생성 테스트
│
├── examples/
│   ├── full_build_request.json
│   ├── incremental_build_request.json
│   └── ollama_ambiguous_request.json
│
├── deploy/
│   ├── mcp.service
│   ├── setup_ubuntu.sh
│   └── check_ubuntu.sh
│
├── sql/
│   └── 001_mysql_migrate_session_blocks_to_narrative_blocks.sql
│
├── .env.example
├── plan.md
└── requirements.txt
```

<br/>

## 실행

### 사전 준비

- Python 3.8+
- Ollama 설치 후 모델 준비

```bash
ollama pull qwen2.5:3b
```

### 서버 실행

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn mcp.main:app --app-dir src --host 0.0.0.0 --port 8000
```

### 테스트

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

### Ubuntu 서버 배포

```bash
chmod +x deploy/setup_ubuntu.sh deploy/check_ubuntu.sh
./deploy/setup_ubuntu.sh /opt/mcp mcp
./deploy/check_ubuntu.sh http://127.0.0.1:8000
```

### 환경변수

| 변수명 | 설명 | 기본값 |
|:---|:---|:---|
| `OLLAMA_BASE_URL` | Ollama 서버 주소 | `http://127.0.0.1:11434` |
| `OLLAMA_MODEL` | 사용할 모델명 | `qwen2.5:3b` |
| `OLLAMA_TIMEOUT_SECONDS` | Ollama 응답 제한 시간 | `10` |

> 현재 Ollama는 local LLM 연동 경로의 기준 모델입니다.
> 이후 narrative block 구조가 코드에 반영되면, 메시지 단위 block 분류기로 사용될 예정입니다.
