# 에이전트별 액션 및 Reward 설계

이 문서는 AI-MCMP 통합 관리 에이전트가 4개 전문 에이전트의 판단을 합의할 때
사용하는 1차 액션/리워드 정책입니다. 현재 단계는 강화학습을 실제로 학습시키는
단계가 아니라, 향후 학습/평가에 사용할 보상 설계의 초기 기준선을 코드에 고정하는
단계입니다.

## 기본 원칙

- 각 에이전트는 `action`, `reward`, `approved`, `reason`을 반환합니다.
- `approved=True`는 최종 Kubernetes 실행 액션에 찬성한다는 뜻입니다.
- `approved=False`는 실행하지 않거나 현재 액션을 차단해야 한다는 뜻입니다.
- reward는 현재 로컬 프로토타입의 정책 점수이며, 서버 실험 데이터가 쌓이면 조정합니다.
- Coordinator는 모든 에이전트가 승인한 경우에만 `kubectl scale deployment`를 실행합니다.

## 1. AI서비스 HA 지원 에이전트

역할: 서비스 장애 징후를 보고 HA 관점에서 복구 액션이 필요한지 판단합니다.

| 조건 | 액션 | 승인 | Reward | 의미 |
| --- | --- | --- | ---: | --- |
| CPU 사용량이 임계치 이상 | `ha_scale_out_required` | 승인 | `+0.90` | 장애 예방을 위해 scale-out 필요 |
| CPU 사용량이 임계치 미만 | `ha_no_action` | 거부 | `+0.20` | 불필요한 복구 액션을 피함 |

## 2. AI응용관리 자동화 에이전트

역할: HA 에이전트가 복구 필요성을 인정하면 실제 애플리케이션 제어 액션을 제안합니다.

| 조건 | 액션 | 승인 | Reward | 의미 |
| --- | --- | --- | ---: | --- |
| 원인이 `cpu_saturation` | `app_scale_deployment` | 승인 | `+0.85` | 대상 deployment를 3개 replica로 확장 |

현재 v1에서는 응용관리 액션을 scale-out 하나로 제한합니다. 이후 단계에서
`rollout_restart`, `traffic_shift`, `rollback` 같은 액션을 추가할 수 있습니다.

## 3. AI반도체 인프라 운용 자동화 에이전트

역할: 현재 프로토타입에서는 Kubernetes replica/deployment 안전성과 인프라 수용 가능성을
검토합니다. 실제 GPU/NPU 클러스터 스케줄링과 accelerator-level orchestration은 후속 확장입니다.

| 조건 | 액션 | 승인 | Reward | 의미 |
| --- | --- | --- | ---: | --- |
| 요청 replica가 권장 상한 이하 | `infra_capacity_approved` | 승인 | `+0.70` | 인프라 자원 범위 안에서 scale-out 가능 |
| 요청 replica가 권장 상한 초과 | `infra_capacity_rejected` | 거부 | `-0.60` | 자원 부족 가능성이 있어 실행 차단 |

## 4. 비용 최적화 지원 에이전트

역할: 제안 액션이 1차 비용 정책 안에 있는지 검토합니다.

| 조건 | 액션 | 승인 | Reward | 의미 |
| --- | --- | --- | ---: | --- |
| 요청 replica가 비용 안전 상한 이하 | `cost_budget_approved` | 승인 | `+0.60` | 비용 정책 안에서 실행 가능 |
| 요청 replica가 비용 안전 상한 초과 | `cost_budget_rejected` | 거부 | `-0.70` | 비용 초과 위험이 있어 실행 차단 |

## Optional CPU 95% smoke test의 Reward 합계

입력:

```text
namespace=online-boutique
service=paymentservice
metric=cpu
value=95
threshold=80
```

에이전트별 결과:

```text
AIServiceHASupportAgent: ha_scale_out_required = +0.90
AIApplicationManagementAgent: app_scale_deployment = +0.85
AISemiconductorInfraOpsAgent: infra_capacity_approved = +0.70
CostOptimizationAgent: cost_budget_approved = +0.60
```

총 reward:

```text
3.05
```

최종 명령:

```bash
kubectl scale deployment paymentservice --replicas=3 -n online-boutique
```

## 향후 확장 방향

- Prometheus 실제 metric을 받아 reward를 사후 평가값으로 보정합니다.
- Chaos Mesh 장애 주입 후 복구 시간, SLA 회복 여부, 비용 증가량을 reward에 반영합니다.
- 액션 종류가 늘어나면 각 에이전트의 reward table을 별도 설정 파일로 분리합니다.
