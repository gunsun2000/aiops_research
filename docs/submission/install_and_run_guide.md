# 설치 및 활용 가이드

이 문서는 현재 연구 본체인 4-Agent Kubernetes 장애 감시/복구 실험을 실행하기 위한 절차를 정리합니다.

## 1. Python 환경

```bash
cd ~/geonhae/aiops_research
conda activate aiops_research
python -m pip install -e ".[dev,autogen]"
```

검증:

```bash
python -m pytest
```

## 2. Go Guard 환경

Go Guard는 선택적 이중 안전 검증 모듈입니다.

```bash
cd ~/geonhae/aiops_research/go/aiops-guard
go test ./...
cd ~/geonhae/aiops_research
```

서버에 Go가 없다면 conda 환경에 설치할 수 있습니다.

```bash
conda activate aiops_research
conda install -c conda-forge go -y
go version
```

## 3. Kubernetes context

```bash
export PATH="$HOME/bin:$PATH"
export KUBECONFIG="$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml"

kubectl config current-context
kubectl get nodes
kubectl get pods -n online-boutique
```

정상 기준:

```text
kind-geonhae-aiops
Ready
```

## 4. Prometheus port-forward

터미널 A에서 실행하고 그대로 켜둡니다.

```bash
kubectl port-forward \
  -n monitoring-full \
  service/kube-prometheus-stack-prometheus \
  9091:9090
```

터미널 B에서 확인합니다.

```bash
export PROM=http://127.0.0.1:9091
curl -sS "$PROM/-/ready"
curl -sSG "$PROM/api/v1/query" --data-urlencode 'query=up'
```

## 5. 기본 기능 확인

Agent Registry:

```bash
aiops-k8s-agents list-agents \
  --registry config/agent_registry.json
```

Mock recovery:

```bash
aiops-k8s-agents run \
  --mode mock \
  --namespace online-boutique \
  --service paymentservice \
  --metric cpu \
  --value 95 \
  --threshold 80 \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice
```

Autonomous mock:

```bash
aiops-k8s-agents autonomous-run \
  --mode mock \
  --namespace online-boutique \
  --deployment paymentservice \
  --metric cpu \
  --threshold 80 \
  --evidence-value 95 \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice
```

## 6. Recovery action real 실험

network-delay metric 확인:

```bash
curl -sSG "$PROM/api/v1/query" \
  --data-urlencode 'query=max(probe_duration_seconds{target="paymentservice"})'

export NETWORK_LATENCY_QUERY='max(probe_duration_seconds{target="paymentservice"})'
```

36회 실험:

```bash
GUARD_BACKEND=go \
MODE=real \
REPETITIONS=3 \
PROMETHEUS_URL="$PROM" \
NETWORK_LATENCY_QUERY="$NETWORK_LATENCY_QUERY" \
bash scripts/server_recovery_action_pilot.sh
```

결과 확인:

```bash
LATEST=$(ls -dt runs/recovery-action-pilot/*/ | head -1)

wc -l "$LATEST/outcomes.jsonl"
cat "$LATEST/analysis/reward_policy_comparison.md"
```

## 7. 정량 그래프 생성

```bash
bash scripts/server_recovery_statistics.sh
```

결과:

```bash
LATEST=$(ls -dt runs/recovery-action-pilot/*/ | head -1)
ls "$LATEST/statistics"
cat "$LATEST/statistics/quantitative_summary.md"
```

## 8. AIOpsLab benchmark

AIOpsLab 공식 실험은 `aiopslab` conda 환경에서 실행합니다.

```bash
cd ~/geonhae/aiops_research
conda activate aiopslab

bash scripts/server_aiopslab_auto_detection.sh
```

반복 실행과 요약:

```bash
bash scripts/server_aiopslab_repeat_detection.sh
bash scripts/server_aiopslab_summarize_runs.sh
```

## 9. 환경 구분

| 환경 | 사용 목적 |
| --- | --- |
| `base` | conda 기본 환경 |
| `aiops_research` | 본 프로젝트 테스트, CLI, recovery 실험 |
| `aiopslab` | 외부 AIOpsLab benchmark 실행 |

일반적으로 코드를 테스트하거나 recovery 실험을 돌릴 때는 `aiops_research`, AIOpsLab 공식 CLI를 사용할 때는 `aiopslab`을 사용합니다.
