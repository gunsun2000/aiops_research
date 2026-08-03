# 시험 가이드

이 문서는 현재 연구 본체를 검증하기 위한 시험 항목을 정리합니다.

## 1. 단위 테스트

```bash
cd ~/geonhae/aiops_research
conda activate aiops_research
python -m pytest
```

검증 내용:

- 4-Agent 판단 로직
- Action/Reward 정책
- Validator 안전 검증
- Executor mock/dry-run/real 명령 생성
- Autonomous mock/test loop
- Recovery action runner
- 정량 분석 로직

## 2. Go Guard 테스트

```bash
cd ~/geonhae/aiops_research/go/aiops-guard
go test ./...
cd ~/geonhae/aiops_research
```

검증 내용:

- Go 기반 최종 action 검증
- namespace/deployment allowlist
- replica limit
- 위험 명령 차단

## 3. Mock 실행 시험

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

성공 기준:

- `"valid": true`
- 실제 Kubernetes resource 변경 없음
- `metadata`에 4-Agent decision, action, reward가 포함됨

## 4. Autonomous mock 시험

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

성공 기준:

- `"valid": true`
- `"metadata.autonomous": "closed_loop"`
- FakeEvidenceProvider 기반 evidence summary 출력

주의:

```text
Autonomous evidence flow는 mock/test 환경에서 FakeEvidenceProvider 기반으로 구현되어 있다.
KubernetesEvidenceProvider는 deployment/pod snapshot 중심의 제한적 provider다.
Prometheus metric, log enrichment, full real-cluster evidence fusion은 후속 확장이다.
```

## 5. 웹 영속 Job 시험

```bash
cd ~/geonhae/aiops_research
conda activate aiops_research
export PORT=18080
aiops-control-plane
```

브라우저에서 `Mock`, `CPU Stress`, `1회`를 선택하고 `실험 실행`을 누릅니다.

성공 기준:

- 실험 ID가 `exp-...` 형식으로 표시됨
- 7단계 타임라인과 이벤트 수가 실시간 갱신됨
- 완료 후 Agent 판단, 최종 Action, Recovery와 Reward가 표시됨
- 새로고침 후 동일 Job과 저장 이벤트가 복원됨
- `runs/control-plane/experiment-jobs.sqlite3`가 생성됨

자동화된 웹/API 계약 시험:

```bash
python -m pytest \
  tests/test_experiment_jobs.py \
  tests/test_experiment_job_runner.py \
  tests/test_control_plane_web.py \
  tests/test_control_plane_ui.py
```

취소 시험은 실행 중 `취소`를 한 번 누르고, 최종 상태가 `cancelled` 또는 안전한
terminal 상태인지 확인합니다. 서버 재시작 시험에서는 진행 중 Job이 자동 재실행되지
않고 `interrupted`로 기록되는지 확인합니다.

## 6. Prometheus 연결 시험

터미널 A:

```bash
kubectl port-forward \
  -n monitoring-full \
  service/kube-prometheus-stack-prometheus \
  9091:9090
```

터미널 B:

```bash
export PROM=http://127.0.0.1:9091
curl -sS "$PROM/-/ready"
curl -sSG "$PROM/api/v1/query" --data-urlencode 'query=up'
```

성공 기준:

- `Prometheus Server is Ready.`
- Prometheus query response에 `"status":"success"` 포함

## 7. Real recovery action 36회 시험

```bash
export NETWORK_LATENCY_QUERY='max(probe_duration_seconds{target="paymentservice"})'

GUARD_BACKEND=go \
MODE=real \
REPETITIONS=3 \
PROMETHEUS_URL="$PROM" \
NETWORK_LATENCY_QUERY="$NETWORK_LATENCY_QUERY" \
bash scripts/server_recovery_action_pilot.sh
```

성공 기준:

```bash
LATEST=$(ls -dt runs/recovery-action-pilot/*/ | head -1)
wc -l "$LATEST/outcomes.jsonl"
```

정상 기준:

```text
36 .../outcomes.jsonl
```

실패 항목 확인:

```bash
python - "$LATEST/outcomes.jsonl" <<'PY'
import json, sys

for line in open(sys.argv[1], encoding="utf-8"):
    row = json.loads(line)
    if not row.get("measurement_valid"):
        print(row.get("treatment_id"), row.get("error"))
PY
```

## 8. 정량 분석 시험

```bash
bash scripts/server_recovery_statistics.sh
```

성공 기준:

```bash
LATEST=$(ls -dt runs/recovery-action-pilot/*/ | head -1)
ls "$LATEST/statistics"
cat "$LATEST/statistics/quantitative_summary.md"
```

다음 파일이 생성되어야 합니다.

- `quantitative_summary.md`
- `quantitative_summary.json`
- `scenario_action_statistics.csv`
- `policy_reward_statistics.csv`
- `mean_recovery_seconds_by_action.png`
- `success_rate_by_action.png`
- `reward_by_policy.png`

## 9. AIOpsLab benchmark 시험

```bash
cd ~/geonhae/aiops_research
conda activate aiopslab

bash scripts/server_aiopslab_auto_detection.sh
```

반복 시험:

```bash
bash scripts/server_aiopslab_repeat_detection.sh
bash scripts/server_aiopslab_summarize_runs.sh
```
