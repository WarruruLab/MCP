# 🔍 MCP Server — 대화 메시지를 구조화된 블록으로

> **"로그를 글로 만들기 위해선, 먼저 의미 단위로 나눠야 한다"**
>
> 대화 메시지 묶음을 입력받아, 의미상 이어지는 메시지들을 session block 단위로 재구성하고
> 각 블록에 요약 태그와 코드 스페닛을 붙여 반환하는 MCP 서버입니다.

<br/>

## 개발 방식

> **설계는 직접, 코드는 AI에게**

저는 Spring Boot · Java가 주력이고 Python에 익숙하지 않습니다. 그래서 이 서버는 설계와 코드 작성 역할을 분리하는 방식으로 개발했습니다.

| 역할 | 담당 | 내용 |
|:---|:---:|:---|
| 설계 결정 | AI | `plan.md`에 구조·기준값·예외 처리 방식을 정리 후 검토 |
| 코드 작성 | AI | 결정된 설계를 바탕으로 Python 코드 생성 |
| 검증 | 직접 | 실제로 실행하고 테스트하며 결과 확인 |

**이렇게 한 이유**: Python 문법을 배우는 것보다 어떤 서버를 왜 만드는지 설계 능력이 지금 저에게 더 중요했습니다. 또 설계 의도 없이 코드만 받아 붙여넣는 것과, 명확한 요구사항을 전달하고 결과를 검증하는 것은 다르다고 생각했기 때문입니다.

---

<br/>

## WarruruLab 전체 파이프라인

> MCP Server는 **WarruruLab**의 두 번째 서비스입니다.

| | 개발톡(DevTalk) | MCP Server | 개발로그(DevLog) |
|:---:|:---:|:---:|:---:|
| **역할** | AI 대화로 문제 해결 로그 생성 | 메시지를 의미 단위 블록으로 분류 | 블록 선택 → 블로그 초안 생성 |
| **기술** | Spring Boot · Java 21 | FastAPI · Python · Ollama | Spring Boot · Java 21 |
| **출력** | Session · Message 저장 | session_block (tags + 코드 스페닛) | 블로그 글 초안 |

서비스 간 호출은 개발로그(DevLog)가 주도하며, MCP Server는 요청이 오면 분석 결과를 반환하는 역할입니다.

```
[Step 2] 블록 분류                               구현 중
DevLog ──── REST ────▶ MCP Server
            메시지 전달 → session_block 반환
```

연관 레포: [개발톡(DevTalk)](#) · [개발로그(DevLog)](#)

---

<br/>

## 현재 구현 상태

**Batch 완료, Ubuntu 서버에서 동작 확인**

MCP Server는 DevTalk 메시지를 DevLog에서 사용할 수 있는 `session_block` 구조로 재구성하는 분석 서버입니다. 메시지를 받아 `APPEND / NEW_BLOCK`을 판단하고, `messageToBlock`, `tags`, 코드 스페닛 목록을 만들어 반환합니다.

**Batch를 선택한 이유**

MCP Server의 분석 방식은 두 가지로 나뉩니다.

- **Batch**: 사용자가 분석 버튼을 누르는 시점에 세션 전체 메시지를 한 번에 처리합니다.
- **Real-time**: 대화 중 메시지가 들어올 때마다 즉시 분석합니다.

Real-time이 UX 면에서 더 자연스럽지만, 해결해야 할 문제가 더 많습니다.

Batch는 사용자가 버튼을 누른 시점에 분석이 시작되고, 결과가 나올 때까지 기다립니다. 흐름이 단순합니다.

Real-time은 대화 중에 메시지가 들어올 때마다 분석이 함께 일어나야 합니다. 여기서 문제가 생깁니다. LLM 분석은 시간이 걸리는데, 사용자는 AI 답변을 바로 받아야 합니다. 분석이 끝날 때까지 대화를 기다리게 할 수는 없습니다. 그래서 대화 응답과 블록 분석을 완전히 별도로 처리해야 합니다.

그런데 이렇게 분리하면 새로운 문제가 생깁니다. 분석이 백그라운드에서 돌다가 실패하면 어떻게 되는지, 메시지가 빠르게 연속으로 들어오면 순서가 뒤바뀌지는 않는지, 서버가 재시작되면 분석 중이던 메시지는 어떻게 처리하는지를 모두 설계해야 합니다. Batch였다면 그냥 버튼 다시 누르면 끝나는 문제들입니다.

지금은 분석 흐름 자체를 먼저 안정적으로 검증하는 것이 우선입니다. Batch로 전체 파이프라인이 제대로 동작하는 것을 확인한 뒤 Real-time으로 전환할 예정입니다.

**1차·2차로 나눈 이유**

Batch는 세션 전체를 한 번에 처리하므로, 메시지가 많을수록 LLM 호출 수가 그대로 늘어납니다. 모든 메시지를 Ollama에 보내면 처리 속도가 느려지고 비용 부담도 커집니다. 시간 간격이나 단어 겹침 비율로 명확하게 판단할 수 있는 경우는 서버가 직접 처리해 LLM 호출을 최소화했습니다.

- **1차 — 서버가 직접 판단 (LLM 호출 없음)**: 시간 간격 10분 초과, 단어 겹침 비율 0.20 미만 / 0.45 초과인 경우 즉시 결정합니다.
- **2차 — Ollama 판단**: 1차에서 결정하지 못한 0.20~0.45 구간만 Ollama에 위임합니다.

태그 추출은 현재 Ollama와 무관하며, 키워드 규칙만으로 동작합니다.

| 항목 | 상태 | 설명 |
|:---|:---:|:---|
| `POST /v1/session-blocks:build` | ✅ 완료 | FULL · INCREMENTAL 모두 정상 |
| 규칙 기반 블록 배정 | ✅ 완료 | 시간 간격 · 유사도 기준 동작 확인 |
| Ollama 연결 및 호출 구조 | ✅ 완료 | Ubuntu 서버에서 Ollama 연결 확인 |
| Ollama 실제 호출 확인 | ⚠️ 미확인 | 테스트 입력이 모두 1단계 규칙으로만 처리됨 (Ollama 호출 횟수 = 0) |
| tags · 코드 스페닛 추출 | ✅ 완료 | 키워드 규칙으로 추출, 정확도 개선 여지 있음 |
| 운영 로그 · 처리 현황 수치 | ❌ 미완료 | 추후 추가 예정 |

> Ollama가 실제로 호출되려면 단어 겹침 비율이 0.20~0.45 사이인 입력이 필요합니다.
> 지금까지는 이 구간을 벗어난 입력만 테스트했으며, Ollama 연결 자체는 정상입니다.

<br/>

## 기술 스택

| 영역 | 기술 | 선택 이유 |
|:---|:---|:---|
| Server | FastAPI · Python · uvicorn | MCP · AI 생태계 라이브러리가 Python에 집중되어 있음 |
| LLM | Ollama (`qwen2.5:3b`) | 외부 API 없이 로컬에서 실행, 비용 없음 |
| 검증 | Pydantic | 요청 · 응답 스키마 강제, LLM 출력 검증 |
| 배포 | Ubuntu · systemd | 개인 서버에 상시 운영 |
| 테스트 | unittest | 핵심 로직 단위 테스트 |

<br/>

## 아키텍처

```
메시지 목록 입력 (POST /v1/session-blocks:build)
  ↓
입력 검증 · timestamp 기준 정렬
  ↓
메시지 순회 → APPEND / NEW_BLOCK 결정
  ├── 1차: 규칙 기반 (시간 간격 · 단어 겹침 비율)
  └── 2차: 애매한 구간만 Ollama 판단
  ↓
변경된 블록만 태그 · 코드 스페닛 생성
  ↓
blocks · messageToBlock · stats 반환
```

**분석 모드**: `FULL`은 처음부터 전체 재분석, `INCREMENTAL`은 기존 블록에 새 메시지만 이어붙입니다. INCREMENTAL 요청 시 `lastMessage`를 함께 넘기면 직전 문맥을 복원해 더 자연스럽게 연결됩니다.

**태그 구조**: 블록 전체를 대표하는 요약 정보입니다. 개별 메시지가 아니라 블록 안의 모든 메시지를 보고 생성합니다.

| 태그 | 의미 | 현재 방식 | 이후 방식 |
|:---|:---|:---|:---|
| `CONTEXT` | 어떤 작업 흐름인지 | 첫 메시지 문장 추출 | AI가 블록 전체를 보고 요약 |
| `PROBLEM` | 핵심 문제 | `error`, `오류` 등 키워드 문장 추출 | AI 요약 |
| `TRIAL` | 시도한 내용 (최대 3개) | `try`, `시도` 등 키워드 문장 추출 | AI 요약 |
| `SOLUTION` | 해결 방법 | `fix`, `해결` 등 키워드 문장 추출 | AI 요약 |
| `INSIGHT` | 남는 인사이트 | `원인`, `결국` 등 키워드 문장 추출 | AI 요약 |

**코드 스페닛**: 대화 중 등장한 코드와 명령어를 따로 추출해 저장합니다. 코드 펜스(` ```python ` 등), `$ ...` 쉘 명령어, `python`·`pip`·`docker`·`git` 등으로 시작하는 줄이 대상입니다.

### 블록 출력 구조

```json
{
  "blockId": "blk_sess_123_1",
  "messageIds": ["msg_001", "msg_002", "msg_007"],
  "tags": {
    "CONTEXT": "Redis 연결 설정 문제",
    "PROBLEM": "API 서버 시작 시 Redis 연결 오류 발생",
    "TRIAL": ["application.yml 수정 시도"],
    "SOLUTION": "OLLAMA_BASE_URL 환경변수 누락이 원인",
    "INSIGHT": "도커 네트워크 내부 hostname 사용 필요"
  },
  "code_snippets": [
    { "language": "yaml", "content": "spring.data.redis.host: redis", "sourceMessageId": "msg_007" }
  ],
  "confidence": 0.5
}
```

<br/>

## 장점과 한계

**장점**

- 흐름이 단순해서 동작을 설명하기 쉽다
- 실패 원인을 추적하기 쉽다
- Ollama 의존도를 낮춰 장애에 덜 민감하다
- 전체 분석 흐름이 처음부터 끝까지 명확하다
- 처음 분석(FULL)과 추가 분석(INCREMENTAL) 두 가지 모드를 모두 지원한다

**한계**

- 단어 겹침 비율이 단어 중복 기반이라 한국어/코드 혼합 대화에서 정확도 한계가 있다
- 태그 요약이 키워드 기반이라 문맥 이해 수준이 낮다
- Ollama 실패 시 대신 처리하는 방식이 단순하다 (문자열 길이 짝/홀수로 결정)
- Ollama 실제 호출이 아직 검증되지 않았다

<br/>

## 프로젝트 구조

```
mcp/
├── src/mcp/
│   ├── main.py              # FastAPI 앱 · 엔드포인트
│   ├── models.py            # Request · Response DTO (Pydantic)
│   ├── core/
│   │   ├── builder.py       # 핵심 파이프라인 (build_session_blocks)
│   │   ├── decision.py      # APPEND / NEW_BLOCK 결정 로직
│   │   └── summarize.py     # tags · 코드 스페닛 추출
│   ├── llm/
│   │   └── client.py        # Ollama 호출 · 실패 시 규칙으로 대신 처리
│   └── utils/
│       └── validate.py      # 입력 검증 · role 정규화
│
├── tests/
│   └── test_builder.py      # 태그 추출 · 코드 스페닛 · incremental 테스트
│
├── examples/
│   ├── full_build_request.json
│   ├── incremental_build_request.json
│   └── ollama_ambiguous_request.json
│
├── deploy/
│   ├── mcp.service          # systemd 서비스 파일
│   ├── setup_ubuntu.sh      # 초기 배포 스크립트
│   └── check_ubuntu.sh      # 배포 후 점검 스크립트
│
├── .env.example
└── requirements.txt
```

<br/>

## 실행

### 사전 준비

- Python 3.8+
- Ollama 설치 후 모델 준비 (없어도 규칙으로 대신 처리되며 동작)

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

> Ollama는 **블록 배정 결정**에만 관여합니다. 태그 추출과 코드 스페닛 추출은 Ollama와 완전히 무관하며, 항상 키워드 규칙으로만 동작합니다.
> Ollama가 없거나 연결에 실패하면 블록 배정의 애매한 구간만 규칙으로 대신 처리되며, 태그와 코드 추출은 영향을 받지 않습니다.
