# Ubuntu 서버 실행 가이드

기준일: 2026-03-11

## 1. 현재 구현 범위

현재 서버는 **Batch 전용 MCP MVP**다.

지원 범위
- `POST /v1/session-blocks:build`
- `analysisMode`
  - `FULL`
  - `INCREMENTAL`
- `existingBlocks[].lastMessage`를 통한 기존 블록 마지막 문맥 연결
- 규칙 기반 `APPEND / NEW_BLOCK` 결정
- 애매 구간에서 Ollama 타이브레이크 시도
- 블록 tags / code snippets 생성

미지원 범위
- Real-time API
- 운영 메트릭/로그 체계
- chunk 처리
- baseline 성능 측정 자동화

## 2. 우분투 서버 사전 준비

배포용 파일
- `deploy/mcp.service`
- `deploy/setup_ubuntu.sh`
- `deploy/check_ubuntu.sh`
- `.env.example`
- `examples/full_build_request.json`
- `examples/incremental_build_request.json`

권장 패키지
```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip curl
```

프로젝트 진입
```bash
cd /path/to/mcp
```

가상환경 생성
```bash
python3 -m venv .venv
source .venv/bin/activate
```

의존성 설치
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

환경변수 파일 준비
```bash
cp .env.example .env
```

## 3. 서버 실행

개발 확인용
```bash
source .venv/bin/activate
uvicorn mcp.main:app --app-dir src --host 0.0.0.0 --port 8000
```

브라우저 또는 서버 내부에서 헬스 대체 확인
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
        "content": "API 서버를 시작할 때 Redis 연결 오류가 발생했다",
        "timestamp": "2026-03-11T10:00:00Z"
      },
      {
        "messageId": "msg_2",
        "role": "assistant",
        "content": "Redis 호스트 설정을 바꿔보고 다시 테스트해보자",
        "timestamp": "2026-03-11T10:01:00Z"
      }
    ]
  }'
```

## 4. Incremental 요청 테스트

아래 요청은 기존 블록을 이어 붙이는지 확인하는 최소 예제다.

```bash
curl -X POST http://127.0.0.1:8000/v1/session-blocks:build \
  -H "Content-Type: application/json" \
  -d '{
    "sessionId": "sess_demo",
    "analysisMode": "INCREMENTAL",
    "messages": [
      {
        "messageId": "msg_3",
        "role": "user",
        "content": "같은 Redis 오류가 계속 발생한다",
        "timestamp": "2026-03-11T10:02:00Z"
      }
    ],
    "existingBlocks": [
      {
        "blockId": "blk_existing",
        "messageIds": ["msg_1", "msg_2"],
        "tags": {
          "PROBLEM": "API 서버를 시작할 때 Redis 연결 오류가 발생했다"
        },
        "lastMessage": {
          "messageId": "msg_2",
          "role": "assistant",
          "content": "같은 Redis 오류가 발생한다",
          "timestamp": "2026-03-11T10:01:00Z"
        }
      }
    ]
  }'
```

정상 기대 결과
- `msg_3`가 `blk_existing`에 append
- `messageToBlock.msg_3 == "blk_existing"`
- `blocks[0].messageIds == ["msg_1", "msg_2", "msg_3"]`

## 5. 테스트 실행

현재 저장소에는 `unittest` 기반 테스트가 있다.

실행 명령
```bash
source .venv/bin/activate
PYTHONPATH=src python -m unittest discover -s tests -v
```

현재 검증되는 항목
- summarize 태그 추출
- 코드 스니펫 추출
- incremental append 동작
- 잘못된 `analysisMode` 거부

## 6. Ollama 연동

현재 LLM 클라이언트는 Ollama HTTP API를 시도하고, 실패하면 deterministic fallback으로 내려간다.

기본 환경변수
```bash
export OLLAMA_BASE_URL=http://127.0.0.1:11434
export OLLAMA_MODEL=qwen2.5:3b
export OLLAMA_TIMEOUT_SECONDS=10
```

Ollama 설치 후 모델 준비 예시
```bash
ollama pull qwen2.5:3b
```

운영 관점 체크
- Ollama가 없더라도 서버는 동작한다.
- 다만 애매 구간 분기 품질은 fallback보다 실제 Ollama 연결 시 더 좋아질 가능성이 크다.

## 7. systemd 운영 예시

`/etc/systemd/system/mcp.service`

```ini
[Unit]
Description=MCP FastAPI Server
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/path/to/mcp
Environment=PYTHONPATH=/path/to/mcp/src
Environment=OLLAMA_BASE_URL=http://127.0.0.1:11434
Environment=OLLAMA_MODEL=qwen2.5:3b
Environment=OLLAMA_TIMEOUT_SECONDS=10
ExecStart=/path/to/mcp/.venv/bin/uvicorn mcp.main:app --app-dir src --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

적용
```bash
sudo systemctl daemon-reload
sudo systemctl enable mcp
sudo systemctl start mcp
sudo systemctl status mcp
```

로그 확인
```bash
journalctl -u mcp -f
```

자동 설치 스크립트 사용 예시
```bash
chmod +x deploy/setup_ubuntu.sh
./deploy/setup_ubuntu.sh /opt/mcp mcp
```

점검 스크립트 사용 예시
```bash
chmod +x deploy/check_ubuntu.sh
./deploy/check_ubuntu.sh http://127.0.0.1:8000
```

## 8. 배포 직후 최소 점검

1. 서비스 기동 확인
```bash
sudo systemctl status mcp
```

2. 로컬 curl 확인
```bash
curl -X POST http://127.0.0.1:8000/v1/session-blocks:build \
  -H "Content-Type: application/json" \
  -d '{"sessionId":"sess_1","analysisMode":"FULL","messages":[{"messageId":"msg_1","role":"user","content":"테스트 메시지","timestamp":"2026-03-11T10:00:00Z"}]}'
```

3. 테스트 실행
```bash
source .venv/bin/activate
PYTHONPATH=src python -m unittest discover -s tests -v
```

4. Ollama 연결 확인이 필요하면
```bash
curl http://127.0.0.1:11434/api/tags
```

## 9. 다음 운영 우선순위

1. 서버에서 실제 Ollama 연결 상태 확인
2. DevLog 연동용 실제 요청 샘플 축적
3. 실패 로그와 요청 ID 로깅 추가
4. baseline 성능 측정
