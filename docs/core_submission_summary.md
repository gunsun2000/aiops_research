# AIOps 4-Agent 연구 핵심 요약

이 문서는 발표나 점검 회의에서 바로 설명할 수 있도록, 현재 저장소의 연구 범위와 완료 상태를 요약한 문서입니다.

## 1. 연구 한 줄 요약

본 연구는 Kubernetes 서비스 장애 상황에서 4개의 AI Agent가 역할별로 장애를 판단하고, action/reward 기반 교차 검증과 안전 검증을 거친 뒤, 검증된 복구 action만 실행하는 **Safety-Bounded Closed-Loop 4-Agent AIOps Framework**를 구현하고 검증한다.

## 2. 현재 연구 본체

| 구분 | 내용 |
| --- | --- |
| 대상 환경 | Kubernetes, Online Boutique, AIOpsLab, Chaos Mesh, Prometheus |
| 핵심 구조 | AI-MCMP Coordinator + 4-Agent |
| 주요 Agent | HA, 응용관리, 인프라 운용, 비용 최적화 |
| 안전 검증 | Python Validator + 선택적 Go Guard |
| 실행 모드 | mock, dry-run, real |
| 결과 분석 | JSONL/CSV/Markdown/PNG/SVG 기반 정량 분석 |

## 3. 현재 구현 완료 항목

| 항목 | 상태 | 주요 파일 |
| --- | --- | --- |
| 4-Agent 역할 구조 | 완료 | `src/aiops_k8s_agents/`, `config/agent_registry.json` |
| Action/Reward 정책 | 완료 | `config/recovery_action_experiments.json`, `docs/design/agent_action_reward_policy.md` |
| Python Validator | 완료 | `src/aiops_k8s_agents/validator.py` |
| 선택적 Go Guard | 완료 | `go/aiops-guard/` |
| AutoGen GroupChat 보조 경로 | 완료 | `src/aiops_k8s_agents/autogen_groupchat.py` |
| Autonomous mock/test loop | 완료 | `src/aiops_k8s_agents/autonomous.py`, `src/aiops_k8s_agents/evidence.py` |
| Kubernetes snapshot provider | 제한적 구현 | `src/aiops_k8s_agents/evidence.py` |
| Chaos Mesh real 장애 실험 | 완료 | `k8s/chaos/`, `scripts/server_recovery_action_pilot.sh` |
| AIOpsLab benchmark 연동 | 완료 | `scripts/server_aiopslab_auto_detection.py` |
| 정량 그래프 생성 | 완료 | `src/aiops_k8s_agents/recovery_statistics.py` |

## 4. 현재 제외한 항목

다음 항목은 별도 과제 성격이 강해서 대학원 연구 본체에서 제거했습니다.

| 제외 항목 | 제외 이유 |
| --- | --- |
| Ops LLM 선정 모듈 | 연구 중심이 LLM 모델 비교가 아님 |
| CPU/GPU VM 기반 AI App 배치 | 장애 복구 연구 본체와 직접 관련이 약함 |
| AI App deployment manifest 생성 | 현재 목표는 장애 감시/복구 action 검증 |
| Swagger/OpenAPI 문서 | API 서버 개발 범위가 아님 |
| service operations 통합 CLI | 별도 AI 서비스 배포/운영 파이프라인 성격 |

Go Guard는 별도 과제 기능이 아니라, 현재 연구에서 **이중 안전 검증 근거**로 남겼습니다.

## 5. 핵심 실험

### AIOpsLab benchmark

- 목적: AIOpsLab 환경에서 장애 탐지/분석 흐름이 동작하는지 확인
- 대상: Hotel Reservation detection 문제
- 의미: 외부 AIOps benchmark와 4-Agent 구조를 연결할 수 있음을 확인

### Chaos Mesh real 장애 실험

| 장애 시나리오 | 대상 서비스 | 의미 |
| --- | --- | --- |
| `pod-kill` | `paymentservice` | Kubernetes self-healing과 과잉 action 여부 확인 |
| `cpu-stress` | `paymentservice` | CPU 부하 상황에서 action 선택 비교 |
| `memory-stress` | `checkoutservice` | memory 장애 상황에서 restart/scale action 비교 |
| `network-delay` | `paymentservice` | network 지연 상황에서 복구 action 비교 |

### Recovery action matrix

```text
4개 장애 x 3개 action x 3회 = 36회

장애: pod-kill, cpu-stress, memory-stress, network-delay
Action: observe_only, rollout_restart, scale_out
```

## 6. 발표에 사용할 결과물

| 결과물 | 위치 | 의미 |
| --- | --- | --- |
| 실험 결과 JSONL | `runs/recovery-action-pilot/<run>/outcomes.jsonl` | 반복 실험 원본 |
| reward 비교표 | `runs/recovery-action-pilot/<run>/analysis/reward_policy_comparison.md` | 정책별 action ranking |
| 정량 요약 | `runs/recovery-action-pilot/<run>/statistics/quantitative_summary.md` | 성공률, 평균 복구 시간, reward 요약 |
| 그래프 PNG | `runs/recovery-action-pilot/<run>/statistics/*.png` | 발표용 시각화 |
| 그래프 SVG | `runs/recovery-action-pilot/<run>/statistics/*.svg` | 논문/문서용 벡터 이미지 |

## 7. 현재 연구 단계

현재 단계는 **1차 연구: 4-Agent AIOps 구조 구현 및 통합 가능성 검증**으로 정리할 수 있습니다.

이미 완료한 것:

- 4-Agent 구조 설계 및 구현
- Action/Reward 정책 설계
- Python Validator와 Go Guard 기반 안전 검증
- Chaos Mesh 기반 실제 장애 주입
- Prometheus/Kubernetes 기반 상태 관측
- recovery action 반복 실험
- 결과 저장 및 정량 그래프 생성

다음 단계:

- single-agent baseline 비교
- Agent 제거 ablation 실험
- reward 민감도 분석
- AutoGen multi-round real action 선택
- Prometheus metric + log enrichment 기반 evidence fusion
