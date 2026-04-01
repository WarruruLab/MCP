# MCP

이 저장소의 목표는 DevTalk 원본 메시지를 실시간으로 분석해, DevLog가 조립 가능한 **서사 단위 block**으로 유지하는 MCP 서버를 만드는 것이다.

이 block은 "한 이슈 전체"가 아니다. block 하나는 개발 흐름 안의 **한 단계**를 뜻한다.

예시:

- 문제 A 발견
- 방법 B, C, D 제안
- 방법 B 시도
- 방법 B 실패
- 방법 C 시도
- 방법 C 실패
- 방법 D 시도
- 방법 D 성공

사용자는 이 block들을 선택해서 원하는 흐름만 남길 수 있다.

- 실패 과정을 빼고 싶으면 실패 block을 제외
- 해결 과정만 강조하고 싶으면 성공 block만 선택
- 시행착오를 보여주고 싶으면 trial / failed block 포함

즉 MCP의 목적은 요약문 한 덩어리를 만드는 것이 아니라, **사용자가 직접 편집 가능한 개발 서사 조각을 만드는 것**이다.

## 제품 정의

MCP는 DevTalk와 DevLog 사이의 중간 계층이다.

- DevTalk에서 새 메시지 1개를 받는다.
- 현재 block 흐름과 비교한다.
- local LLM이 이 메시지가 어떤 block에 속하는지 분류한다.
- MCP가 block 상태를 갱신한다.
- DevLog는 block 목록을 보여주고 사용자가 원하는 흐름으로 글을 조립하게 한다.

## block의 의미

block은 여러 tag를 한꺼번에 다 채우는 큰 묶음이 아니다.

block 하나는 아래 중 하나 같은 역할만 가진다.

- `problem`
- `proposal`
- `trial`
- `result`
- `insight`

그리고 각 block은 역할에 맞는 일부 정보만 가진다.

예시:

- problem block: 문제 설명
- proposal block: 후보 해결책 목록
- trial block: 특정 방법 시도
- result block: 해당 시도의 실패 또는 성공
- insight block: 원인, 교훈, 판단 변화

## 핵심 설계 원칙

- 분류 판단은 local LLM이 맡는다.
- 서버는 순서 보장, 멱등 처리, 상태 저장, 응답 검증을 맡는다.
- 모든 block에 모든 tag를 넣지 않는다.
- block은 조립 가능한 최소 서사 단위로 유지한다.
- 요약은 block별 한 줄 summary 중심으로 관리한다.

## 목표 block 스키마

```json
{
  "blockId": "blk_123",
  "topic": "Redis timeout issue",
  "blockType": "trial",
  "status": "failed",
  "summary": "Increased timeout and retried the API call, but the issue remained.",
  "messageIds": ["msg_21", "msg_22"],
  "tags": {
    "method": "increase timeout",
    "result": "failed"
  }
}
```

핵심 필드:

- `topic`: 상위 주제
- `blockType`: 이 block의 역할
- `status`: `open | neutral | failed | success`
- `summary`: 사용자가 바로 읽는 한 줄 설명
- `messageIds`: 원본 메시지 연결
- `tags`: block 타입에 따라 일부만 사용

## 현재 코드 상태

현재 코드베이스에는 batch 기반 baseline 구현이 남아 있다.

- `POST /v1/session-blocks:build`
- 규칙 기반 판정
- Ollama 보조 판정
- 5-tag 방식의 summarize

하지만 앞으로의 기준 구조는 **real-time block classification**이며, 5-tag를 모든 block에 채우는 방식은 핵심 모델이 아니다.

## 문서

- [현재 상태 정리](./current_status.md)
- [실시간 전환 개발 계획](./mcp_dev_plan.md)
- [개발 시작용 plan](./plan.md)
- [Ubuntu 서버 실행 가이드](./ubuntu_server_guide.md)
- [환경변수 예시](./.env.example)

## 실행

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn mcp.main:app --app-dir src --host 0.0.0.0 --port 8000
```

## 테스트

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```
