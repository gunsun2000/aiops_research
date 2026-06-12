# 실제 장애별 복구 Action 및 Reward 민감도 실험

이 실험은 CPU 95% 숫자를 직접 입력하는 인공 알람 테스트가 아니다. 연구실 서버의 개인용 kind 클러스터에서 Chaos Mesh로 실제 장애를 주입하고, 서로 다른 복구 action을 실행한 뒤 Prometheus와 Kubernetes 상태로 결과를 측정한다.

## 1. 연구 질문

1. 같은 장애에서 `observe_only`, `rollout_restart`, `scale_out` 중 어떤 action이 가장 좋은가?
2. 동일한 실측 결과에 HA, 응용관리, 인프라, 비용 reward 가중치를 다르게 적용하면 선택되는 action이 달라지는가?

Reward 가중치는 action을 학습시키는 강화학습 보상이 아니다. 실제 결과를 네 가지 운영 관점으로 다시 평가하는 정책 점수다.

## 2. 고정 실험 행렬

| 장애 | 대상 | 실제 주입 도구 | 핵심 측정값 |
| --- | --- | --- | --- |
| `pod-kill` | `paymentservice` | Chaos Mesh PodChaos | deployment available replica |
| `cpu-stress` | `paymentservice` | Chaos Mesh StressChaos | container CPU usage |
| `memory-stress` | `checkoutservice` | Chaos Mesh StressChaos | container memory working set |
| `network-delay` | `paymentservice` | Chaos Mesh NetworkChaos | 실제 서비스 p95 latency |

각 장애마다 다음 세 action을 각각 독립적으로 실행한다.

| action | 실행 내용 |
| --- | --- |
| `observe_only` | 변경 명령 없이 Kubernetes 상태만 관찰 |
| `rollout_restart` | 대상 deployment를 안전하게 재시작 |
| `scale_out` | 대상 deployment를 1 replica에서 3 replicas로 증가 |

파일럿은 `4 장애 x 3 action x 1회 = 12 treatments`, 본 실험은 `4 x 3 x 3회 = 36 treatments`다.

## 3. 매 Treatment 실행 절차

```text
기존 Chaos 삭제 및 replica=1 초기화
-> Kubernetes/Prometheus 초기 상태 저장
-> Chaos Mesh 실제 장애 적용
-> 장애 metric 조건이 관측될 때까지 대기
-> 구조화되고 allowlist를 통과한 action 1개 실행
-> 회복 metric과 deployment/pod 상태 측정
-> Chaos 삭제 및 replica=1 재초기화
-> outcomes.jsonl에 결과 1행 저장
```

측정 query가 없거나 장애 조건이 관측되지 않으면 성공으로 처리하지 않는다. `measurement_valid=false`와 오류 원인을 기록하고 다음 treatment로 넘어간다.

## 4. 서버 사전 준비

```bash
cd ~/geonhae/aiops_research
conda activate aiops_research
git pull origin master
python -m pip install -e ".[dev,autogen]"

export PATH="$HOME/bin:$PATH"
export KUBECONFIG=~/geonhae/kubeconfigs/kind-geonhae-aiops.yaml
kubectl get nodes
```

full Prometheus를 별도 터미널에서 연결한다.

```bash
kubectl port-forward \
  -n monitoring-full \
  service/kube-prometheus-stack-prometheus \
  9091:9090
```

## 5. Network-delay용 실제 Latency Query 설정

`max(up)`은 Prometheus 생존 여부일 뿐 서비스 latency가 아니므로 이 실험에서는 거부된다. 먼저 현재 수집 중인 latency/duration 계열 metric 이름을 확인한다.

```promql
count by (__name__) ({__name__=~".*(latency|duration).*"})
```

Online Boutique 요청 지연을 나타내는 histogram을 확인한 뒤 서버 터미널에 p95 query를 설정한다.

```bash
export NETWORK_LATENCY_QUERY='<확인한 histogram metric으로 만든 p95 PromQL>'
```

이 변수가 없으면 실험은 Kubernetes를 변경하기 전에 중단된다.

## 6. 12회 파일럿 실험

```bash
MODE=real \
REPETITIONS=1 \
PROMETHEUS_URL=http://127.0.0.1:9091 \
bash scripts/server_recovery_action_pilot.sh
```

결과 위치는 실행 시각별로 분리된다.

```text
runs/recovery-action-pilot/<실행시각>/outcomes.jsonl
runs/recovery-action-pilot/<실행시각>/analysis/reward_policy_comparison.json
runs/recovery-action-pilot/<실행시각>/analysis/reward_policy_comparison.csv
runs/recovery-action-pilot/<실행시각>/analysis/reward_policy_comparison.md
```

파일럿 결과 행 수를 확인한다.

```bash
wc -l runs/recovery-action-pilot/<실행시각>/outcomes.jsonl
```

정상적인 1회 파일럿이면 `12`가 출력되어야 한다.

## 7. 36회 본 실험

파일럿의 12개 record에서 metric과 cleanup이 유효한 것을 확인한 뒤 반복 수만 변경한다.

```bash
MODE=real \
REPETITIONS=3 \
PROMETHEUS_URL=http://127.0.0.1:9091 \
bash scripts/server_recovery_action_pilot.sh
```

본 실험의 `outcomes.jsonl`은 36행이어야 한다.

## 8. Reward 정책 비교

동일한 실측 outcome을 다음 네 정책으로 다시 채점한다.

| 정책 | HA | 응용관리 | 인프라 | 비용 |
| --- | ---: | ---: | ---: | ---: |
| `balanced` | 0.30 | 0.30 | 0.20 | 0.20 |
| `ha_first` | 0.50 | 0.25 | 0.15 | 0.10 |
| `cost_first` | 0.25 | 0.20 | 0.15 | 0.40 |
| `infra_first` | 0.25 | 0.20 | 0.40 | 0.15 |

`predicted_reward`는 정책 가중치를 적용한 선택 점수이고, `observed_outcome_score`는 네 관점의 단순 평균으로 저장한다. 따라서 정책에 따른 선택 변화와 실제 관측 결과를 혼동하지 않는다.

## 9. 무엇이 실제 실험 결과인가

- pytest 통과: 코드와 안전 규칙의 검증 결과
- 임시 fixture 분석: reward 계산기의 검증 결과
- `outcomes.jsonl`: Chaos Mesh 장애와 Kubernetes action을 실제 수행한 연구 측정값
- `reward_policy_comparison.*`: 동일한 실제 측정값에 reward 정책을 적용한 비교 결과

논문과 발표에는 `outcomes.jsonl`에서 집계한 결과만 실제 장애 대응 성능으로 사용한다.
