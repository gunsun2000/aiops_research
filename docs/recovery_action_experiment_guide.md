# 실제 장애별 복구 Action 및 Reward 정책 실험

이 문서는 Chaos Mesh 실제 장애, Prometheus Metric, Kubernetes real Action을 사용한 복구 비교 실험의 방법과 최종 결과를 정리합니다.

CPU 95% 숫자를 직접 입력하는 인공 알람 실험이 아닙니다.

## 1. 연구 질문

1. `observe_only`, `rollout_restart`, `scale_out` 중 장애별로 어떤 Action이 높은 평가를 받는가?
2. 동일한 실측 결과에 HA·응용관리·인프라·비용 Reward 가중치를 다르게 적용하면 선택 Action이 달라지는가?

Reward는 강화학습 모델을 학습시키는 보상이 아닙니다. 실제 복구 결과를 네 Agent 관점으로 재평가하는 정책 점수입니다.

## 2. 실험 환경

```text
연구실 Ubuntu 서버
-> 개인용 kind Kubernetes cluster
-> Online Boutique 전체 서비스
-> Chaos Mesh
-> kube-prometheus-stack
-> Blackbox Exporter
-> AIOps 4-Agent Recovery Runner
```

기존 공용 Kubernetes는 사용하지 않고 사용자 전용 kubeconfig와 kind cluster에서 실험했습니다.

## 3. 실험 행렬

### 장애 4종

| 장애 | 대상 | 주입 방식 | 장애·복구 판단 근거 |
| --- | --- | --- | --- |
| `pod-kill` | `paymentservice` | Chaos Mesh PodChaos | Pod UID 교체와 Available Replica |
| `cpu-stress` | `paymentservice` | Chaos Mesh StressChaos | Container CPU rate |
| `memory-stress` | `checkoutservice` | Chaos Mesh StressChaos | Container memory working set |
| `network-delay` | `paymentservice` | Chaos Mesh NetworkChaos | Blackbox TCP probe duration |

### 후보 Action 3종

| Action | 실제 실행 |
| --- | --- |
| `observe_only` | Kubernetes 자체 복구를 관찰하고 변경 명령을 실행하지 않음 |
| `rollout_restart` | `kubectl rollout restart deployment/<name>` |
| `scale_out` | Replica를 1개에서 3개로 증가 |

### 반복 수

```text
파일럿: 4장애 × 3Action × 1회 = 12 treatments
본 실험: 4장애 × 3Action × 3회 = 36 treatments
```

## 4. Reward 정책

| 정책 | HA | 응용관리 | 인프라 | 비용 |
| --- | ---: | ---: | ---: | ---: |
| `balanced` | 0.30 | 0.30 | 0.20 | 0.20 |
| `ha_first` | 0.50 | 0.25 | 0.15 | 0.10 |
| `cost_first` | 0.25 | 0.20 | 0.15 | 0.40 |
| `infra_first` | 0.25 | 0.20 | 0.40 | 0.15 |

평가 구조:

```text
ActionScore
= HA 관점 점수 × HA 가중치
+ 응용관리 점수 × 응용관리 가중치
+ 인프라 점수 × 인프라 가중치
+ 비용 점수 × 비용 가중치
```

- `predicted_reward`: 해당 Reward 정책을 적용한 Action 선택 점수
- `observed_outcome_score`: 네 Agent 관점 점수의 단순 평균

정책별 `selected_action`은 `predicted_reward` 순위로 결정됩니다. 따라서 Raw Metric이 가장 빨리 회복된 Action과 정책상 최종 선택 Action은 다를 수 있습니다.

## 5. Treatment 실행 절차

```text
기존 Chaos 삭제
-> 대상 Deployment replica=1로 초기화
-> Kubernetes·Prometheus 초기 상태 저장
-> Chaos Mesh 실제 장애 적용
-> 장애 조건 관측 대기
-> 후보 Action 1개 실행
-> Metric 회복과 Deployment·Pod 상태 측정
-> Chaos 삭제 및 replica=1 복원
-> outcomes.jsonl에 결과 1행 저장
```

장애 조건이나 회복 조건을 관측하지 못하면 성공으로 처리하지 않습니다.

```json
{
  "measurement_valid": false,
  "error": "metric wait timed out ..."
}
```

## 6. 서버 준비

```bash
cd ~/geonhae/aiops_research
conda activate aiops_research
git pull origin master
python -m pip install -e ".[dev,autogen]"

export PATH="$HOME/bin:$PATH"
export KUBECONFIG="$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml"

python -m pytest
kubectl get nodes
```

## 7. Full Prometheus 연결

별도 터미널을 열고 다음 명령을 계속 실행합니다.

```bash
kubectl port-forward \
  -n monitoring-full \
  service/kube-prometheus-stack-prometheus \
  9091:9090
```

실험 터미널에서 준비 상태를 확인합니다.

```bash
export PROM=http://127.0.0.1:9091
curl -sS "$PROM/-/ready"
```

정상 출력:

```text
Prometheus Server is Ready.
```

## 8. Network delay 측정

`up`은 수집 대상의 생존 여부이며 서비스 지연시간이 아닙니다. 이 실험은 Blackbox Exporter가 `paymentservice:50051`에 TCP 연결을 수행한 시간을 사용합니다.

정상 상태 확인:

```bash
curl -sSG "$PROM/api/v1/query" \
  --data-urlencode 'query=probe_success{target="paymentservice"}' \
  | python -m json.tool
```

실험 Query:

```bash
export NETWORK_LATENCY_QUERY='max(probe_duration_seconds{target="paymentservice"})'
```

서버에서 실제 확인된 예:

| 상태 | Probe duration |
| --- | ---: |
| 정상 Baseline | 약 0.0037초 |
| Network delay 주입 | 약 0.2337초 |
| 장애 회복 후 | 약 0.0033초 |

즉 NetworkChaos가 실제 서비스 연결 지연을 증가시켰고, 장애 종료 후 Baseline 수준으로 회복됐습니다.

## 9. 12회 파일럿

```bash
MODE=real \
REPETITIONS=1 \
PROMETHEUS_URL="$PROM" \
NETWORK_LATENCY_QUERY="$NETWORK_LATENCY_QUERY" \
bash scripts/server_recovery_action_pilot.sh
```

2026년 6월 15일 완료 결과:

```text
total_treatments: 12
valid_measurements: 12
successful_recoveries: 12
```

결과 위치:

```text
runs/recovery-action-pilot/20260615_121554/
```

## 10. 36회 본 실험

```bash
MODE=real \
REPETITIONS=3 \
PROMETHEUS_URL="$PROM" \
NETWORK_LATENCY_QUERY="$NETWORK_LATENCY_QUERY" \
bash scripts/server_recovery_action_pilot.sh
```

2026년 6월 15일 완료 결과:

```text
total_treatments: 36
valid_measurements: 36
successful_recoveries: 36
```

결과 위치:

```text
runs/recovery-action-pilot/20260615_123017/outcomes.jsonl
runs/recovery-action-pilot/20260615_123017/analysis/reward_policy_comparison.json
runs/recovery-action-pilot/20260615_123017/analysis/reward_policy_comparison.csv
runs/recovery-action-pilot/20260615_123017/analysis/reward_policy_comparison.md
```

## 11. 36회 결과표

### 최종 선택 Action

| 정책 | CPU stress | Memory stress | Network delay | Pod kill |
| --- | --- | --- | --- | --- |
| `balanced` | `observe_only` | `rollout_restart` | `rollout_restart` | `observe_only` |
| `ha_first` | `observe_only` | `rollout_restart` | `rollout_restart` | `observe_only` |
| `cost_first` | `observe_only` | `observe_only` | `observe_only` | `observe_only` |
| `infra_first` | `observe_only` | `rollout_restart` | `rollout_restart` | `observe_only` |

### Balanced 정책 Reward 순위

| 장애 | 1위 | 2위 | 3위 |
| --- | --- | --- | --- |
| CPU stress | 관찰 `0.850` | 재시작 `0.781` | Scale-out `0.594` |
| Memory stress | 재시작 `0.900` | 관찰 `0.850` | Scale-out `0.611` |
| Network delay | 재시작 `0.881` | 관찰 `0.866` | Scale-out `0.690` |
| Pod kill | 관찰 `0.976` | 재시작 `0.906` | Scale-out `0.714` |

### 정책 변화가 만든 선택 차이

- Balanced·HA·Infra 정책은 Memory stress와 Network delay에서 `rollout_restart`를 선택했습니다.
- Cost-first 정책은 Action 비용을 강하게 반영해 모든 장애에서 `observe_only`를 선택했습니다.
- CPU stress와 Pod kill은 모든 정책에서 `observe_only`가 1위였습니다.
- `scale_out`은 Replica 비용과 인프라 부담 때문에 현재 조건에서 모든 장애의 3위였습니다.

## 12. 연구 해석

### 장애별 Action 선택

- Pod kill은 Kubernetes Controller가 자동으로 Pod를 교체하므로 추가 제어가 과잉 대응이 될 수 있습니다.
- 60초 CPU stress는 자동 종료되므로 현재 부하 강도에서는 관찰이 비용 대비 유리했습니다.
- Memory stress에서는 상태 초기화 효과를 가진 재시작이 응용관리 관점에서 높은 점수를 받았습니다.
- Network delay에서는 재시작의 응용관리 점수가 높아 Balanced·HA·Infra 정책의 1위가 됐습니다.

### Reward 민감도

동일한 36개 실측 결과를 사용해도 비용 가중치를 높이면 Memory와 Network의 선택이 재시작에서 관찰로 바뀌었습니다. 따라서 Reward 값이 단순 출력용 숫자가 아니라 Action 순위 결정에 실제로 관여합니다.

## 13. 현재 결과의 한계

1. 반복 수는 Action별 3회이므로 평균·표준편차·신뢰구간을 추가해야 합니다.
2. 장애 지속시간과 부하 강도가 한 조건으로 고정돼 있습니다.
3. 비용은 실제 클라우드 청구액이 아니라 Replica와 Action 비용을 반영한 정책 점수입니다.
4. 이번 36회 Action은 deterministic Recovery Runner가 실행했습니다.
5. AutoGen GroupChat이 실제 장애를 보고 Action을 직접 선택하는 real 비교는 아직 수행하지 않았습니다.
6. Single-Agent와 Agent 제거 Ablation이 없으므로 4-Agent의 상대적 우수성을 아직 확정할 수 없습니다.

## 14. 결과 확인 명령

```bash
LATEST=$(ls -dt runs/recovery-action-pilot/*/ | head -1)

echo "$LATEST"
wc -l "${LATEST}outcomes.jsonl"
cat "${LATEST}analysis/reward_policy_comparison.md"
```

## 정량 그래프 및 통계 분석

reward ranking뿐 아니라 평균 복구 시간, 성공률, metric 개선도, reward 정책별 선택 점수를 보고서 형태로 정리하려면 다음 명령을 사용한다.

```bash
LATEST=$(ls -dt runs/recovery-action-pilot/*/ | head -1)

aiops-k8s-agents summarize-recovery-statistics \
  --input "${LATEST}outcomes.jsonl" \
  --output-dir "${LATEST}statistics"
```

생성되는 핵심 산출물은 다음과 같다.

| 산출물 | 설명 |
| --- | --- |
| `quantitative_summary.md` | 정량 분석 요약 |
| `scenario_action_statistics.csv` | 장애/action별 평균 복구 시간과 성공률 |
| `policy_reward_statistics.csv` | reward 정책별 action ranking |
| `mean_recovery_seconds_by_action.svg` | 평균 복구 시간 그래프 |
| `mean_recovery_seconds_by_action.png` | 발표 삽입용 평균 복구 시간 그래프 |
| `success_rate_by_action.svg` | 성공률 그래프 |
| `success_rate_by_action.png` | 발표 삽입용 성공률 그래프 |
| `reward_by_policy.svg` | reward 정책별 점수 그래프 |
| `reward_by_policy.png` | 발표 삽입용 reward 정책별 점수 그래프 |

자세한 해석은 `docs/recovery_quantitative_analysis_guide.md`에 정리한다.

유효하지 않은 Treatment 확인:

```bash
python - "$LATEST/outcomes.jsonl" <<'PY'
import json, sys

for line in open(sys.argv[1], encoding="utf-8"):
    row = json.loads(line)
    if not row.get("measurement_valid"):
        print(row["treatment_id"], row.get("error", ""))
PY
```

## 15. 발표·논문에 사용할 정확한 표현

> Chaos Mesh 기반 실제 장애 4종과 Kubernetes 복구 Action 3종을 대상으로 3회 반복하여 총 36개 Treatment를 수행하였다. 모든 Treatment에서 유효한 Metric 측정과 장애 회복을 확인했으며, 동일한 실측 결과에 Reward 가중치를 다르게 적용한 결과 장애 종류와 운영 정책에 따라 선택 Action이 달라짐을 확인하였다.

AutoGen에 대해서는 다음처럼 별도로 표현합니다.

> AutoGen 기반 4-Agent GroupChat과 구조화 Action 생성 경로는 구현 및 Mock/Dry-run 검증을 완료했으며, 실제 장애에서 AutoGen이 Action을 직접 선택하는 비교 실험은 후속 연구로 진행한다.
