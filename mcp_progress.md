# MCP 개발 진행 상황 정리 (현재 즉시 이어서 개발 가능)

## 1. 현재 상태 요약
- FastAPI 기반 MCP 서버 뼈대 완료
- Batch 전용 `/v1/session-blocks:build` 엔드포인트 구현 완료
- 규칙 기반 블록 결정 로직 + LLM stub 연결 완료
- 요약/코드 스니펫 추출 간단 버전 구현 완료
- 실행 가능한 상태

## 2. 생성된 주요 파일
- `requirements.txt`
- `src/mcp/main.py` (FastAPI 엔드포인트)
- `src/mcp/models.py` (Request/Response DTO)
- `src/mcp/core/builder.py` (핵심 처리 파이프라인)
- `src/mcp/core/decision.py` (APPEND/NEW_BLOCK 규칙)
- `src/mcp/core/summarize.py` (tags/code_snippets 간단 추출)
- `src/mcp/llm/client.py` (LLM stub)
- `src/mcp/utils/validate.py` (입력 검증)

## 3. 실행 방법
```bash
pip install -r requirements.txt
uvicorn mcp.main:app --app-dir src --reload
```

## 4. 현재 기능 흐름
1. 요청 검증 (`sessionId`, `messages[]`, `timestamp`, `role`)
2. 메시지 정규화/정렬
3. APPEND vs NEW_BLOCK 결정
   - 규칙 기반 (시간 간격/유사도)
   - 중간 구간은 LLM stub 호출
4. 블록 생성/갱신 및 `messageToBlock` 매핑
5. 변경된 블록만 summarize
6. `stats` 포함 응답

## 5. 바로 진행 가능한 다음 작업
1. LLM 실제 연동 (현재는 stub)
2. summarize 로직 정교화
3. 유사도 계산 개선 (토큰화/벡터 기반)
4. 테스트 케이스 추가 및 검증
5. DevLog 연동용 Client/DTO 추가