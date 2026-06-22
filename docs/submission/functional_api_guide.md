# 기능/API 가이드

현재 프로젝트의 실행 표면은 HTTP API 서버가 아니라 CLI이다.
다만 각 CLI는 구조화된 JSON 입력/출력을 가지므로, 향후 FastAPI 또는 Go API 서버로 감싸기 쉽다.

## 1. Agent Registry 기능

### Agent 목록 조회

```bash
aiops-k8s-agents list-agents \
  --registry config/agent_registry.json
```

출력 핵심:

```json
{
  "command": "list-agents",
  "agents": [
    {
      "name": "AIApplicationManagementAgent",
      "bounded_actions": ["app_scale_deployment"]
    }
  ]
}
```

### Agent action 검증

```bash
aiops-k8s-agents validate-agent-action \
  --registry config/agent_registry.json \
  --agent AIApplicationManagementAgent \
  --action app_scale_deployment
```

성공 조건:

```json
{
  "valid": true
}
```

## 2. CPU/GPU VM 추론 배치 추천

```bash
aiops-k8s-agents recommend-inference-placement \
  --config config/inference_optimization.json \
  --workload llm-chat-inference
```

출력 핵심:

```json
{
  "valid": true,
  "selected_resource": "gpu-vm-l4",
  "action": "deploy_on_gpu_vm",
  "slo_satisfied": true
}
```

## 3. Kubernetes action 실행

Go guard를 사용하는 real 실행 예시:

```bash
aiops-k8s-agents execute-recovery-action \
  --mode real \
  --guard-backend go \
  --action rollout_restart \
  --namespace online-boutique \
  --deployment paymentservice \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice
```

## 4. Safety-Bounded Closed-Loop Autonomous 4-Agent 실행

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

출력 핵심:

```json
{
  "command": "autonomous-run",
  "final_status": "recovered",
  "diagnosis": {"cause": "cpu_saturation"},
  "selected_action": {"kind": "scale_out"},
  "validation_result": {"valid": true},
  "recovery_monitoring": {"recovery_success": true}
}
```

이 기능은 API 서버가 아니라 CLI 기반 structured JSON interface이다. 향후 Go Echo/Swagger API를 만들 경우 이 출력 구조를 HTTP response schema로 옮기면 된다.

## 5. Recovery Action 실험

36회 본 실험:

```bash
export NETWORK_LATENCY_QUERY='max(probe_duration_seconds{target="paymentservice"})'

GUARD_BACKEND=go \
MODE=real \
REPETITIONS=3 \
PROMETHEUS_URL=http://127.0.0.1:9091 \
bash scripts/server_recovery_action_pilot.sh
```

결과 확인:

```bash
LATEST=$(ls -dt runs/recovery-action-pilot/*/ | head -1)
wc -l "$LATEST/outcomes.jsonl"
cat "$LATEST/analysis/reward_policy_comparison.md"
```

## 6. Recovery 정량 통계/그래프 생성

평균 복구 시간, 성공률, reward 정책별 선택 점수 그래프를 생성한다.

```bash
LATEST=$(ls -dt runs/recovery-action-pilot/*/ | head -1)

aiops-k8s-agents summarize-recovery-statistics \
  --input "$LATEST/outcomes.jsonl" \
  --output-dir "$LATEST/statistics"
```

출력 산출물:

```text
quantitative_summary.md
scenario_action_statistics.csv
policy_reward_statistics.csv
mean_recovery_seconds_by_action.svg
mean_recovery_seconds_by_action.png
success_rate_by_action.svg
success_rate_by_action.png
reward_by_policy.svg
reward_by_policy.png
```

## 7. OpenAPI 문서

향후 API 서버화를 위한 인터페이스 초안은 다음 파일에 정리되어 있다.

```bash
docs/submission/openapi_agent_registry.yaml
```
