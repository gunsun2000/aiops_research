# Full-stack 확장 실험 가이드

이 문서는 `minimal`, `AIOpsLab`, `full-stack`을 분리해서 운영하기 위한 실행 가이드입니다.

실제 장애 4종에 대해 `observe_only`, `rollout_restart`, `scale_out`을 비교하고 reward 가중치 민감도를 분석하는 최종 절차는 [recovery_action_experiment_guide.md](recovery_action_experiment_guide.md)를 사용합니다. 해당 실험에는 CPU 95% 인공 알람을 사용하지 않습니다.

핵심 원칙은 아래와 같습니다.

```text
minimal = 빠른 sanity check
AIOpsLab = 공식 benchmark 검증
full-stack = 장애/metric/action 변수를 바꾸는 확장 실험
```

즉, 기존 minimal 환경을 지우지 않습니다. 연구실 서버의 개인 kind 클러스터 안에 full-stack 실험 모드를 추가하고, 그 위에서 변수만 하나씩 바꿉니다.

## 1. Full-stack 고정 환경

| 요소 | 내용 |
| --- | --- |
| Monitoring | `kube-prometheus-stack` |
| Application | Online Boutique 전체 서비스 |
| Fault Injection | Chaos Mesh |
| Agent Layer | 4-agent runner |
| Result Archive | `runs/full-stack*` |

설치되는 Prometheus stack은 `k8s/kube-prometheus-stack-values.yaml` 값을 사용합니다.

## 2. 변화시키는 변수

변수는 `config/full_stack_experiments.json`에 정리되어 있습니다.

```bash
aiops-k8s-agents list-full-stack-experiments \
  --config config/full_stack_experiments.json
```

현재 준비된 장애 scenario:

| scenario | 장애 | metric | 대상 |
| --- | --- | --- | --- |
| `cpu-stress` | CPU 부하 | `cpu` | `paymentservice` |
| `memory-stress` | memory 부하 | `restart_count` | `checkoutservice` |
| `pod-kill` | pod kill | `availability` | `paymentservice` |
| `network-delay` | network delay | `latency` | `paymentservice` |

현재 준비된 비교 변수:

| variable | 비교 목적 |
| --- | --- |
| `fault_type` | 장애 종류별 대응 비교 |
| `agent_policy` | 4-agent 전체와 agent ablation 비교 |
| `llm_model` | deterministic 정책과 AutoGen LLM 모델 비교 |
| `reward_policy` | reward 설계 민감도 비교 |
| `baseline` | single-agent/manual/no-agent baseline 비교 |

## 3. 서버에서 full-stack 설치

서버에서 실행합니다.

```bash
cd ~/geonhae/aiops_research
conda activate aiops_research
git pull origin master
python -m pip install -e ".[dev,autogen]"

export PATH="$HOME/bin:$PATH"
export KUBECONFIG=~/geonhae/kubeconfigs/kind-geonhae-aiops.yaml

bash scripts/server_full_stack_setup.sh
```

설치 후 상태 확인:

```bash
kubectl get pods -n monitoring-full
kubectl get pods -n online-boutique
```

Prometheus UI 확인:

```bash
kubectl port-forward -n monitoring-full service/kube-prometheus-stack-prometheus 9091:9090
```

브라우저:

```text
http://127.0.0.1:9091
```

Grafana UI 확인:

```bash
kubectl port-forward -n monitoring-full service/kube-prometheus-stack-grafana 3000:80
```

브라우저:

```text
http://127.0.0.1:3000
```

## 4. 단일 장애 주입

```bash
SCENARIO=pod-kill bash scripts/server_full_stack_apply_chaos.sh
SCENARIO=cpu-stress bash scripts/server_full_stack_apply_chaos.sh
SCENARIO=memory-stress bash scripts/server_full_stack_apply_chaos.sh
SCENARIO=network-delay bash scripts/server_full_stack_apply_chaos.sh
```

장애 정리:

```bash
ACTION=delete SCENARIO=pod-kill bash scripts/server_full_stack_apply_chaos.sh
ACTION=delete SCENARIO=cpu-stress bash scripts/server_full_stack_apply_chaos.sh
ACTION=delete SCENARIO=memory-stress bash scripts/server_full_stack_apply_chaos.sh
ACTION=delete SCENARIO=network-delay bash scripts/server_full_stack_apply_chaos.sh
```

## 5. 4-agent feedback loop 실행

CPU stress scenario:

```bash
SCENARIO=cpu-stress \
ITERATIONS=3 \
INTERVAL_SECONDS=10 \
MODE=dry-run \
bash scripts/server_full_stack_feedback_loop.sh
```

실제 scale까지 실행하려면:

```bash
SCENARIO=cpu-stress \
ITERATIONS=3 \
INTERVAL_SECONDS=10 \
MODE=real \
bash scripts/server_full_stack_feedback_loop.sh
```

AutoGen GroupChat까지 포함하려면:

```bash
USE_AUTOGEN=1 \
SCENARIO=cpu-stress \
ITERATIONS=3 \
INTERVAL_SECONDS=10 \
MODE=dry-run \
bash scripts/server_full_stack_feedback_loop.sh
```

결과는 기본적으로 아래에 저장됩니다.

```text
runs/full-stack/
```

## 6. 여러 장애를 순서대로 실행

아래 명령은 `pod-kill`, `cpu-stress`, `memory-stress`, `network-delay`를 순서대로 실행하고 각 결과를 저장합니다.

```bash
ITERATIONS=3 \
INTERVAL_SECONDS=10 \
MODE=dry-run \
bash scripts/server_full_stack_experiment_matrix.sh
```

중간에 한 scenario가 실패해도 스크립트는 cleanup을 수행하고 다음 scenario까지 계속 진행합니다.
실패 scenario가 있어도 리포트 수집용으로 exit code를 0으로 유지하려면 아래처럼 실행합니다.

```bash
ALLOW_SCENARIO_FAILURES=1 \
ITERATIONS=3 \
MODE=dry-run \
bash scripts/server_full_stack_experiment_matrix.sh
```

결과 폴더:

```text
runs/full-stack-matrix/
```

특정 scenario만 돌리고 싶으면:

```bash
SCENARIOS="pod-kill cpu-stress" \
ITERATIONS=3 \
MODE=dry-run \
bash scripts/server_full_stack_experiment_matrix.sh
```

## 7. 주의할 점

한 번에 모든 변수를 바꾸지 않습니다.

좋은 실험:

```text
full-stack 환경 고정
-> 장애 종류만 변경
-> reward 고정
-> LLM 모델 고정
-> 결과 비교
```

나쁜 실험:

```text
장애 종류, LLM 모델, reward, Prometheus 설정을 동시에 변경
-> 어떤 변수 때문에 결과가 바뀌었는지 해석 불가
```

`network-delay`의 기본 query는 안전한 placeholder인 `max(up)`입니다. `up`을 그대로 쓰면 Prometheus가 `kube-system` 같은 다른 namespace series를 먼저 반환할 수 있어서, 기본값은 label을 제거하는 집계 query를 사용합니다. 실제 논문 실험에서는 Online Boutique 또는 ingress에서 latency metric을 노출한 뒤 `QUERY` 환경변수로 교체하는 것이 좋습니다.

예시:

```bash
SCENARIO=network-delay \
METRIC=latency \
THRESHOLD=0.2 \
QUERY='histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{namespace="online-boutique"}[5m])) by (le))' \
bash scripts/server_full_stack_feedback_loop.sh
```

## 8. 서버에서 자주 나는 문제와 해결

### Prometheus query가 `HTTP Error 400`으로 실패할 때

`server_full_stack_feedback_loop.sh`는 기본 PromQL을 직접 넣어 둡니다.
CPU 시나리오의 정상 query는 아래처럼 `[2m]`가 label matcher 바깥에 있어야 합니다.

```text
sum(rate(container_cpu_usage_seconds_total{namespace="online-boutique",pod=~"paymentservice-.*",container!="",image!=""}[2m])) * 100
```

### `deployment가 allowlist에 없습니다`가 뜰 때

full Prometheus stack에서는 metric label에 다른 deployment 이름이 섞일 수 있습니다.
그래서 `pod-kill` 기본 query는 label을 비우기 위해 `max(...)`로 집계합니다.

```text
max(kube_deployment_status_replicas_available{namespace="online-boutique",deployment="paymentservice"})
```

### Online Boutique rollout이 계속 실패할 때

기존 `online-boutique` namespace에 minimal deployment와 full deployment가 섞이면 rollout이 꼬일 수 있습니다.
그럴 때는 실험 namespace만 지우고 다시 배포합니다.

```bash
RESET_ONLINE_BOUTIQUE=1 bash scripts/server_full_stack_setup.sh
```

실패한 상태에서도 pod/log를 보고 싶으면 아래처럼 실행합니다.

```bash
ALLOW_PARTIAL_ROLLOUT=1 bash scripts/server_full_stack_setup.sh
```

## 9. 최종 구현 완료 검증

최종 검증 스크립트는 다음 작업을 한 번에 수행합니다.

```text
kind context 안전 확인
-> 네 장애 시나리오 전후 replica 초기화
-> MODE=real 피드백 루프 실행
-> Chaos Mesh 장애 제거
-> CSV/Markdown 최종 결과 생성
```

deterministic 4-agent 최종 검증:

```bash
CONFIRM_REAL_RUN=YES \
ITERATIONS=3 \
bash scripts/server_finalize_research.sh
```

AutoGen `gpt-5.5` 최종 검증:

```bash
CONFIRM_REAL_RUN=YES \
USE_AUTOGEN=1 \
ITERATIONS=3 \
bash scripts/server_finalize_research.sh
```

안전상 `CONFIRM_REAL_RUN=YES`가 없거나 현재 kubeconfig context가 `kind-*`가
아니면 실행이 중단됩니다. 공용 Kubernetes에서 실행할 때는 관리자의 명시적
승인을 받은 후에만 `ALLOW_NON_KIND_REAL=1`을 사용합니다.

결과 파일:

```text
runs/final-real/<실행시각>/final_summary.md
runs/final-real/<실행시각>/final_summary.csv
```
