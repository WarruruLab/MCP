# Ubuntu 서버 실행 가이드

기준일: 2026-04-01

## 1. 전제

현재 제품 목표는 **실시간 서사 단위 block 분류 MCP 서버**다.

즉 서버는 아래 역할을 지원해야 한다.

- 새 메시지 실시간 분류
- 기존 block 후보 조회 및 적합 block 선택
- narrative block 상태 유지
- DevLog가 선택 가능한 block 목록 제공

현재 코드에는 batch endpoint가 남아 있지만, 운영 방향은 `ingest-message` 중심으로 이동한다.

## 2. 사전 준비

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip curl
```

```bash
cd /path/to/mcp
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

## 3. 환경변수

현재 local LLM 연동 예시는 Docker-style service name 기준이다.

```bash
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=qwen2.5:3b
OLLAMA_TIMEOUT_SECONDS=10
DEVLOG_BASE_URL=http://devlog-backend:8081
DEVLOG_INTERNAL_API_KEY=
DEVLOG_TIMEOUT_SECONDS=10
MCP_CORS_ALLOW_ORIGINS=
```

이 값은 이후 narrative block 분류에 맞는 local LLM으로 교체될 수 있다.

## 4. 서버 실행

```bash
source .venv/bin/activate
uvicorn devlog_mcp_server.main:app --app-dir src --host 0.0.0.0 --port 8000
```

## 5. 현재 기준 검증

현재 코드 기준 즉시 검증 가능한 것은 기존 batch endpoint다.

```bash
curl -X POST http://127.0.0.1:8000/v1/session-blocks:build \
  -H "Content-Type: application/json" \
  -d '{
    "sessionId": "sess_demo",
    "analysisMode": "FULL",
    "messages": [
      {
        "messageId": "msg_1",
        "role": "user",
        "content": "Redis timeout 문제를 처음 발견했다",
        "timestamp": "2026-04-01T10:00:00Z"
      }
    ]
  }'
```

이 검증은 서버 기동 확인 용도다. 제품 목표 검증은 이후 `POST /v1/session-blocks:ingest-message` 기준으로 바뀌어야 한다.

## 6. 테스트 실행

```bash
source .venv/bin/activate
PYTHONPATH=src python -m unittest discover -s tests -v
```

## 7. systemd 예시

```ini
[Unit]
Description=MCP FastAPI Server
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/path/to/mcp
Environment=PYTHONPATH=/path/to/mcp/src
Environment=OLLAMA_BASE_URL=http://ollama:11434
Environment=OLLAMA_MODEL=qwen2.5:3b
Environment=OLLAMA_TIMEOUT_SECONDS=10
Environment=DEVLOG_BASE_URL=http://devlog-backend:8081
Environment=DEVLOG_INTERNAL_API_KEY=
Environment=DEVLOG_TIMEOUT_SECONDS=10
Environment=MCP_CORS_ALLOW_ORIGINS=
ExecStart=/path/to/mcp/.venv/bin/uvicorn devlog_mcp_server.main:app --app-dir src --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable mcp
sudo systemctl start mcp
sudo systemctl status mcp
journalctl -u mcp -f
```

## 8. 운영 우선순위

1. `ingest-message` endpoint 추가
2. narrative block DTO 반영
3. local LLM structured classification 안정화
4. active block state 저장 구조 반영
5. 로깅 / 메트릭 / trace id 추가
