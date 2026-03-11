# MCP

현재 이 저장소는 **Batch 기반 MCP 서버 MVP**를 구현한 상태다.

핵심 구현 범위
- `POST /v1/session-blocks:build`
- `FULL`, `INCREMENTAL` 분석 모드
- 규칙 기반 블록 분기 + Ollama 타이브레이크 구조
- 블록 요약(tags)과 코드 스니펫 추출
- `existingBlocks[].lastMessage`를 이용한 incremental 문맥 연결

주요 문서
- [현재 상태 정리](./current_status.md)
- [우분투 서버 실행 가이드](./ubuntu_server_guide.md)
- [배포용 systemd 파일](./deploy/mcp.service)
- [우분투 배포 스크립트](./deploy/setup_ubuntu.sh)
- [우분투 점검 스크립트](./deploy/check_ubuntu.sh)
- [환경변수 예시](./.env.example)
- [FULL 요청 예제](./examples/full_build_request.json)
- [INCREMENTAL 요청 예제](./examples/incremental_build_request.json)
- [Ollama 애매 구간 요청 예제](./examples/ollama_ambiguous_request.json)
- [개발 계획](./mcp_dev_plan.md)
- [상위 기획 문서](./plan.md)

빠른 실행
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn mcp.main:app --app-dir src --host 0.0.0.0 --port 8000
```

기본 테스트
```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

우분투 서버 점검
```bash
chmod +x deploy/setup_ubuntu.sh deploy/check_ubuntu.sh
./deploy/setup_ubuntu.sh /opt/mcp mcp
./deploy/check_ubuntu.sh http://127.0.0.1:8000
```
