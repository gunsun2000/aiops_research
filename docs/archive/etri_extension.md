# 별도 과제 성격 확장 기능 보관 설명

이 문서는 대학원 연구 본체에서 제외하거나 뒤로 내린 기능을 정리한다.

현재 `aiops_research`의 중심은 **4-Agent 기반 AIOps 장애 감시/복구 연구**이다. 아래 기능들은 별도 과제 대응 과정에서 구현했거나 문서화했지만, 대학원 연구 본문에서는 핵심 실험으로 사용하지 않는다.

## 연구 본체에 남기는 요소

| 요소 | 이유 |
| --- | --- |
| 4-Agent 구조 | 연구 핵심 |
| Agent Registry | Agent 역할과 허용 action을 명확히 표현 |
| Action/Reward 정책 | 장애별 action 선택 근거와 설명 가능성 제공 |
| AIOpsLab / Chaos Mesh / Prometheus / Kubernetes 실험 | 실제 장애 기반 검증 |
| Python Validator | 기본 안전 검증 경로 |
| Recovery Monitor | 폐루프 복구 판단 |
| JSONL/CSV/Markdown/PNG/SVG 결과 저장 | 재현성과 정량 분석 |

## 선택적으로 보관하는 요소

| 요소 | 보관 이유 |
| --- | --- |
| Go Guard | Python Validator와 별도의 이중 검증 확장으로 활용 가능 |
| AutoGen GroupChat | structured multi-agent prototype 및 후속 real 비교 실험에 활용 가능 |
| LLM/코딩 Agent 교차 검증 기록 | 개발 과정의 검증 이력으로 보관 |

## 대학원 연구 본문에서 내리는 요소

| 요소 | 이유 |
| --- | --- |
| Ops LLM 선정 | 논문 중심이 LLM 성능 비교가 아니면 과도함 |
| CPU/GPU VM 기반 AI 응용 배포/제어 | 별도 과제 성격이 강함 |
| AI App deployment manifest 생성 | 장애 복구 연구 본체와 직접 관련이 약함 |
| Swagger / API / OpenAPI 문서 | 과제 산출물 성격 |
| 멀티클라우드 VM 연동 설명 | 별도 과제 또는 향후 확장에 적합 |

## 관련 문서

| 문서 | 성격 |
| --- | --- |
| `docs/design/go_and_llm_cross_validation.md` | Go Guard와 LLM/코딩 Agent 교차 검증 기록 |
| `docs/design/ops_llm_selection_guide.md` | Ops LLM 선정 보조 문서 |
| `docs/design/inference_optimization_guide.md` | CPU/GPU VM 배치 추천 보조 문서 |
| `docs/design/ai_application_deployment_strategy.md` | AI 응용 배포/제어 전략 보조 문서 |
| `docs/experiments/service_operations_environment.md` | AI 서비스 운영 통합 파이프라인 runbook |
| `docs/submission/functional_api_guide.md` | CLI/API 산출물 문서 |
| `docs/submission/service_control_framework_mapping.md` | 과제 항목과 구현 매핑 문서 |
| `docs/submission/openapi_agent_registry.yaml` | OpenAPI 초안 |

## 논문/발표에서의 표현

아래처럼 표현하면 연구 본체와 확장 기능이 섞이지 않는다.

> 본 연구의 중심은 4-Agent 기반 AIOps 장애 감시/복구 구조이다. Go Guard, Ops LLM 선정, CPU/GPU VM 배치, AI App deployment manifest 기능은 개발 과정에서 구현한 확장 모듈이며, 본 논문에서는 안전 검증 또는 후속 확장 가능성으로만 다룬다.
