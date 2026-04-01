# ADR-001: 배치-요약-서버를-실시간-narrative-block-분류기로-전환

## 상태
Accepted

## 결정 시점
2026-04-01

## 배경
기존 MCP 서버는 세션 전체 메시지를 한 번에 받아 요약하는 batch summary 서버를 기준으로 설계되어 있었다. 이 방식은 개발 대화의 흐름을 뒤늦게 압축하는 데에는 유효했지만, DevLog에서 필요한 "선택 가능한 서사 단위"를 만드는 데에는 한계가 있었다.

- 어떤 문제가 있었는가
  - 세션 전체를 한 번에 요약하면 문제 발견, 제안, 시도, 실패, 성공, 인사이트가 하나의 큰 결과물로 뭉개졌다.
  - 사용자가 실패 과정을 제외하거나 특정 시도만 골라 조합하는 편집 흐름에 맞지 않았다.
  - 메시지가 들어올 때마다 즉시 block 상태를 갱신하지 못해 DevLog와의 연동이 느슨했다.
- 왜 기존 방식으로는 부족했는가
  - 기존 5-tag 중심 구조는 block 하나가 모든 정보를 동시에 가지는 전제를 두고 있어 narrative editing보다 summary aggregation에 가까웠다.
  - DevLog가 원하는 것은 완성된 요약문이 아니라, 이후 조합 가능한 problem / proposal / trial / result / insight 단위의 재료였다.
  - batch 중심 구조는 실시간 append, 새 block 생성, 누락 메시지 복구 같은 운영 요구를 자연스럽게 수용하기 어려웠다.
- 어떤 선택지가 존재했는가
  - 기존 batch endpoint를 유지하면서 요약 품질만 개선한다.
  - 규칙 기반 로직으로 메시지를 block에 분류한다.
  - 메시지 단위로 실시간 분류하고, local LLM이 기존 block append 또는 새 block 생성을 판단하게 한다.

구현 상세보다 중요한 맥락은, MCP 서버의 역할을 "세션 요약기"가 아니라 "서사 단위 block 분류기"로 다시 정의해야 했다는 점이었다.

## 결정
MCP 서버의 기본 모델을 batch summary 방식에서 real-time narrative block classification 방식으로 전환한다.

- 무엇을 선택했는가
  - `POST /v1/session-blocks:ingest-message`를 중심으로 메시지 1건씩 처리하는 실시간 분류 경로를 도입한다.
  - block 모델을 `topic`, `blockType`, `status`, `summary`, `messageIds`, `tags` 중심의 narrative block 구조로 재정의한다.
  - local LLM은 자유 생성기가 아니라, 기존 block에 append할지 새 block을 만들지 판단하는 structured classifier로 사용한다.
- 무엇을 하지 않기로 했는가
  - batch summary를 최종 제품 모델로 유지하지 않는다.
  - block 하나에 `CONTEXT / PROBLEM / TRIAL / SOLUTION / INSIGHT`를 모두 채우는 구조를 더 확장하지 않는다.
  - 규칙 기반 분류기를 주 경로로 채택하지 않는다.

## 이유
이 결정은 현재 단계에서 DevLog 편집 흐름과 가장 직접적으로 연결되고, 향후 운영 요구를 수용하기 쉬운 구조이기 때문에 적합하다.

- 왜 이 선택이 현재 단계에 적합한가
  - 사용자가 problem, trial, result 같은 블록을 선택적으로 조합할 수 있어 DevLog 작성 경험과 맞는다.
  - 메시지가 들어올 때마다 active block을 갱신할 수 있어 이후 UI/DB/운영 흐름을 단순화한다.
  - local 환경에서 structured JSON 출력만 안정적으로 만들면 분류 품질을 점진적으로 개선할 수 있다.
- 어떤 트레이드오프를 감수했는가
  - batch보다 구현 복잡도가 올라가고, idempotency, 순서 보장, 예외 복구, reconciliation 같은 운영 이슈를 직접 다뤄야 한다.
  - block 간 관계, 상태 전이, 요약 갱신 규칙을 별도로 설계해야 한다.
  - local LLM의 품질과 지연시간이 시스템 행동에 직접 영향을 준다.
- 다른 선택지를 배제한 이유는 무엇인가
  - batch 유지안은 DevLog의 선택형 편집 모델을 충분히 지원하지 못한다.
  - 규칙 기반 방식은 개발 대화의 문맥 전환과 애매한 메시지 분류를 다루기 어렵다.
  - 기존 5-tag 확장안은 구조가 단순해 보이지만, 실제로는 narrative block을 표현하는 데 계속 예외가 늘어날 가능성이 높았다.

의도적으로 포기한 부분도 있다. 완성된 요약문을 한 번에 잘 만드는 것보다, 이후 조립 가능한 block을 안정적으로 쌓는 것을 우선했다.

## 결과
이 결정으로 MCP 서버의 현재 중심 구조는 이미 실시간 narrative block 처리 방향으로 이동했다.

- 구조적으로 바뀐 점
  - `ingest-message` endpoint가 추가되었고, candidate block 기반의 append / new block 분기 로직이 도입되었다.
  - narrative block DTO와 routing core, reconciliation core가 분리되었다.
  - message processing state는 `received`, `processing`, `processed`, `failed`, `reconcile_pending` 기준으로 정리되었다.
- 코드/문서/운영에 반영된 사항
  - `src/mcp/main.py`, `src/mcp/models.py`, `src/mcp/core/routing.py`, `src/mcp/core/reconciliation.py`, `src/mcp/llm/client.py`에 실시간 경로가 반영되었다.
  - `tests/test_realtime_contract.py`, `tests/test_exception_reconciliation_contract.py`로 실시간 계약과 복구 계약이 추가되었다.
  - `README.md`, `plan.md`, `mcp_dev_plan.md`, `current_status.md`, `DEV_PROGRESS.md`에 전환 방향이 문서화되었다.
  - 기존 batch endpoint는 전환 중 호환성을 위해 남겨두되, 주 경로는 아니게 되었다.
- 이후 단계에 미치는 영향
  - 실제 MySQL persistence, 멱등 처리, retry queue, scheduled reconciliation job 구현이 다음 단계의 핵심이 된다.
  - local LLM 후보 비교와 실서버 평가가 완료되어야 운영 모델을 확정할 수 있다.
  - block 관계 모델과 DevLog 연동 스키마는 추가 조정 가능성이 남아 있다.

앞으로 변경될 수 있는 지점은 LLM 모델 선택, block 간 관계 표현 방식, 예외 복구 정책의 구체적 wiring이다.

## 후속 작업 (선택)
- [ ] MySQL persistence와 message processing state 저장소 연결
- [ ] `sessionId + messageId` 기준 멱등 처리 확정
- [ ] retry 정책과 scheduled reconciliation job 구현
- [ ] local LLM 후보 실서버 비교 후 운영 모델 확정
- [ ] block 관계 모델(`proposal -> trial -> result`)의 명시적 표현 여부 검토
- [ ] 기존 batch endpoint의 유지 범위와 제거 시점 별도 ADR로 분리 검토
