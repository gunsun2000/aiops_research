# 시험 가이드

## 1. Python 단위 테스트

로컬 또는 서버에서 다음을 실행한다.

```bash
cd ~/geonhae/aiops_research
conda activate aiops_research
python -m pytest
```

Windows 로컬에서는:

```powershell
cd C:\Users\geonhae\Documents\aiops_research
.\.venv\Scripts\python.exe -m pytest
```

## 2. Go guard 테스트

```bash
cd ~/geonhae/aiops_research/go/aiops-guard
go test ./...
go run ./cmd/aiops-guard --input ../../examples/go_guard_scale_action.json
```

## 3. Agent Registry 시험

```bash
aiops-k8s-agents list-agents \
  --registry config/agent_registry.json

aiops-k8s-agents validate-agent-action \
  --registry config/agent_registry.json \
  --agent AIApplicationManagementAgent \
  --action app_scale_deployment
```

기대 결과:

- 4개 Agent가 조회된다.
- `app_scale_deployment`는 허용된다.
- registry에 없는 action은 거부된다.

## 4. 추론 최적화 시험

```bash
aiops-k8s-agents recommend-inference-placement \
  --config config/inference_optimization.json \
  --workload llm-chat-inference
```

기대 결과:

- `selected_resource`: `gpu-vm-l4`
- `action`: `deploy_on_gpu_vm`
- `slo_satisfied`: `true`

```bash
aiops-k8s-agents recommend-inference-placement \
  --config config/inference_optimization.json \
  --workload text-classifier
```

기대 결과:

- `selected_resource`: `cpu-vm-standard`
- `action`: `deploy_on_cpu_vm`

## 5. Kubernetes real 실험

전제:

```bash
export PATH="$HOME/bin:$PATH"
export KUBECONFIG="$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml"
kubectl get nodes
```

Prometheus port-forward가 별도 터미널에서 실행 중이어야 한다.

```bash
kubectl port-forward \
  -n monitoring-full \
  service/kube-prometheus-stack-prometheus \
  9091:9090
```

36회 recovery action 실험:

```bash
export NETWORK_LATENCY_QUERY='max(probe_duration_seconds{target="paymentservice"})'

GUARD_BACKEND=go \
MODE=real \
REPETITIONS=3 \
PROMETHEUS_URL=http://127.0.0.1:9091 \
bash scripts/server_recovery_action_pilot.sh
```

성공 기준:

- `outcomes.jsonl`이 36줄이어야 한다.
- `analysis/reward_policy_comparison.md`가 생성되어야 한다.
- 장애별 action ranking이 기록되어야 한다.

## 6. CI/CD

GitHub Actions는 push 또는 pull request 시 다음을 검증한다.

- Python test
- Go guard test
- 기본 코드 품질 확인

워크플로 파일:

```bash
.github/workflows/ci.yml
```
