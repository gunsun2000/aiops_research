# 로컬 테스트 및 실험 명령어 모음

이 문서는 현재 프로토타입에서 바로 실행할 수 있는 테스트/실험 명령어를 한곳에
모은 치트시트입니다. 기본 원칙은 `mock -> dry-run -> real` 순서입니다.

## 가장 먼저 보기: 현재 서버 Real 실험 재현

현재 연구의 주요 결과는 CPU 95% Smoke Test가 아니라 다음 두 실험입니다.

```text
AIOpsLab Hotel Reservation 자동 탐지 12회
Chaos Mesh 실제 장애 4종 × Action 3종 × 반복 3회 = 36 treatments
```

### 1. 서버 환경 준비

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

2026년 6월 15일 기준 코드 검증 결과는 `92 passed`입니다.

### 2. Full Prometheus Port-forward

별도 서버 터미널에서 다음 명령을 계속 실행합니다.

```bash
kubectl port-forward \
  -n monitoring-full \
  service/kube-prometheus-stack-prometheus \
  9091:9090
```

실험 터미널에서는 다음 환경 변수를 설정합니다.

```bash
export PROM=http://127.0.0.1:9091
export NETWORK_LATENCY_QUERY='max(probe_duration_seconds{target="paymentservice"})'

curl -sS "$PROM/-/ready"
```

정상 출력:

```text
Prometheus Server is Ready.
```

### 3. 12회 파일럿

```bash
MODE=real \
REPETITIONS=1 \
PROMETHEUS_URL="$PROM" \
NETWORK_LATENCY_QUERY="$NETWORK_LATENCY_QUERY" \
bash scripts/server_recovery_action_pilot.sh
```

검증된 결과:

```text
total_treatments: 12
valid_measurements: 12
successful_recoveries: 12
```

### 4. 36회 본 실험

```bash
MODE=real \
REPETITIONS=3 \
PROMETHEUS_URL="$PROM" \
NETWORK_LATENCY_QUERY="$NETWORK_LATENCY_QUERY" \
bash scripts/server_recovery_action_pilot.sh
```

검증된 결과:

```text
total_treatments: 36
valid_measurements: 36
successful_recoveries: 36
```

### 5. 최신 결과 확인

```bash
LATEST=$(ls -dt runs/recovery-action-pilot/*/ | head -1)

echo "$LATEST"
wc -l "${LATEST}outcomes.jsonl"
cat "${LATEST}analysis/reward_policy_comparison.md"
```

## Recovery 정량 그래프/통계 분석

36회 real recovery action 실험이 끝난 뒤 평균 복구 시간, 성공률, reward 차이를 그래프로 만들려면 다음을 실행합니다.

```bash
LATEST=$(ls -dt runs/recovery-action-pilot/*/ | head -1)

aiops-k8s-agents summarize-recovery-statistics \
  --input "${LATEST}outcomes.jsonl" \
  --output-dir "${LATEST}statistics"
```

또는 서버 스크립트로 실행합니다.

```bash
bash scripts/server_recovery_statistics.sh
```

생성 파일:

```text
${LATEST}statistics/quantitative_summary.md
${LATEST}statistics/scenario_action_statistics.csv
${LATEST}statistics/policy_reward_statistics.csv
${LATEST}statistics/mean_recovery_seconds_by_action.svg
${LATEST}statistics/success_rate_by_action.svg
${LATEST}statistics/reward_by_policy.svg
```

자세한 해석은 `docs/recovery_quantitative_analysis_guide.md`를 참고합니다.

유효하지 않은 Treatment가 있는지 확인합니다.

```bash
python - "$LATEST/outcomes.jsonl" <<'PY'
import json, sys

rows = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8")]
print("total:", len(rows))
print("valid:", sum(row.get("measurement_valid", False) for row in rows))
print("recovered:", sum(row.get("recovery_success", False) for row in rows))

for row in rows:
    if not row.get("measurement_valid"):
        print("failed:", row["treatment_id"], row.get("error", ""))
PY
```

### 6. 현재 결과 파일

```text
12회 파일럿:
runs/recovery-action-pilot/20260615_121554/

36회 본 실험:
runs/recovery-action-pilot/20260615_123017/
```

상세한 설계와 해석은 [실제 장애별 복구 Action 및 Reward 정책 실험](recovery_action_experiment_guide.md)을 참고합니다.

> 중요: 위 36회 실험은 실제 Chaos Mesh·Prometheus·Kubernetes `real` 실험이지만, AutoGen GroupChat이 Action을 직접 선택한 실험은 아닙니다. AutoGen real 비교는 후속 실험입니다.

## 0. 실험 가능 범위

| 실험 | Docker 필요 | OpenAI API 필요 | 설명 |
| --- | --- | --- | --- |
| Python 단위 테스트 | 아니오 | 아니오 | 코드/validator/agent 로직 검증 |
| deterministic 4-agent mock | 아니오 | 아니오 | LLM 없이 고정 정책 에이전트 검증 |
| AutoGen GroupChat mock | 아니오 | 예 | 실제 OpenAI API로 4개 에이전트 토론 |
| kind dry-run | 예 | 아니오 | 로컬 Kubernetes API에서 server dry-run 검증 |
| Prometheus local 입력 | 예 | 아니오 | 로컬 Prometheus API 경로 검증 |
| 로컬 kind real scale | 예 | 아니오 | 내 PC의 kind 클러스터에 실제 scale 실행 |
| 연구실 서버 real | 서버 K8s 필요 | 선택 | AIOpsLab/Online Boutique 풀 스케일 실행 |

## 1. Windows 가상환경 준비

PowerShell 실행 정책 때문에 activation이 막히면 현재 창에서만 임시 허용합니다.

```powershell
Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process
```

가상환경 생성 및 활성화:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

패키지 설치:

```powershell
python -m pip install --upgrade pip
python -m pip install -e ".[dev,autogen]"
```

활성화 없이 직접 실행해야 할 때:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\aiops-k8s-agents.exe run --help
```

## 2. 기본 검증 테스트

전체 테스트:

```powershell
python -m pytest
```

성공 기준:

```text
... passed
```

AutoGen 관련 테스트만 실행:

```powershell
python -m pytest tests\test_autogen_groupchat.py
```

CLI 설치 확인:

```powershell
aiops-k8s-agents run --help
aiops-k8s-agents autogen-run --help
aiops-k8s-agents prometheus-run --help
```

## 2-1. 실험 결과 JSON 저장

모든 CLI 명령은 `--save-result-dir <dir>` 옵션을 지원합니다. 이 옵션을 넣으면
화면에 출력된 최종 JSON과 같은 내용을 timestamp 파일로 저장합니다.

```powershell
aiops-k8s-agents run --mode mock --namespace online-boutique --service paymentservice --metric cpu --value 95 --threshold 80 --message "paymentservice CPU usage is 95 percent" --allowed-namespace online-boutique --allowed-deployment paymentservice --save-result-dir runs
```

파일명 예시:

```text
runs/20260601-153012-123456_run_mock.json
runs/20260601-153130-123456_autogen_run_dry_run.json
runs/20260601-153245-123456_autogen_prometheus_run_dry_run.json
```

최근 실험 결과 확인:

```powershell
Get-ChildItem .\runs -Filter *.json | Sort-Object LastWriteTime -Descending | Select-Object -First 5
```

최근 결과 내용 보기:

```powershell
Get-Content (Get-ChildItem .\runs -Filter *.json | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
```

`scripts\run_autogen_mock.ps1`, `scripts\run_autogen_dry_run.ps1`,
`scripts\run_prometheus_local.ps1`, `scripts\run_prometheus_autogen_local.ps1`는
기본적으로 `--save-result-dir runs`를 사용합니다. `runs/`는 실험 산출물이므로
git에는 올리지 않습니다.

## 3. deterministic 4-agent mock 실험

OpenAI API와 Docker 없이 바로 실행할 수 있는 가장 기본 실험입니다.

```powershell
aiops-k8s-agents run --mode mock --namespace online-boutique --service paymentservice --metric cpu --value 95 --threshold 80 --message "paymentservice CPU usage is 95 percent" --allowed-namespace online-boutique --allowed-deployment paymentservice
```

성공하면 핵심 출력은 아래처럼 나옵니다.

```json
{
  "command": "kubectl scale deployment paymentservice --replicas=3 -n online-boutique",
  "mode": "mock",
  "valid": true,
  "stdout": "mock: 명령어를 검증했으며 실제 실행하지 않았습니다",
  "stderr": ""
}
```

## 4. AutoGen 실제 LLM GroupChat mock 실험

OpenAI API 키를 현재 PowerShell 창에 넣습니다. API 키는 코드나 문서에 저장하지
않습니다.

```powershell
$env:OPENAI_API_KEY="sk-..."
```

키가 들어갔는지 확인:

```powershell
if ($env:OPENAI_API_KEY) { "API 키 들어있음" } else { "API 키 없음" }
```

AutoGen GroupChat 실행:

```powershell
aiops-k8s-agents autogen-run --mode mock --namespace online-boutique --service paymentservice --metric cpu --value 95 --threshold 80 --message "paymentservice CPU usage is 95 percent" --allowed-namespace online-boutique --allowed-deployment paymentservice
```

4개 에이전트가 어떤 판단을 냈는지 눈으로 한 번 확인하려면 `--show-transcript`를
붙입니다.

```powershell
aiops-k8s-agents autogen-run --mode mock --show-transcript --namespace online-boutique --service paymentservice --metric cpu --value 95 --threshold 80 --message "paymentservice CPU usage is 95 percent" --allowed-namespace online-boutique --allowed-deployment paymentservice
```

출력 JSON의 `metadata.transcript`에서 아래와 같은 형태를 확인합니다.

```text
AIServiceHASupportAgent: action=ha_scale_out_required approved=True reward=0.90 reason=...
AIApplicationManagementAgent: action=app_scale_deployment approved=True reward=0.85 reason=...
AISemiconductorInfraOpsAgent: action=infra_capacity_approved approved=True reward=0.70 reason=...
CostOptimizationAgent: action=cost_budget_approved approved=True reward=0.60 reason=...
```

같은 실험을 스크립트로 실행:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_autogen_mock.ps1
```

정상 성공 형태:

```json
{
  "command": "kubectl scale deployment paymentservice --replicas=3 -n online-boutique",
  "mode": "mock",
  "valid": true,
  "stdout": "mock: 명령어를 검증했으며 실제 실행하지 않았습니다",
  "stderr": "",
  "metadata": {
    "coordinator": "AI-MCMP",
    "autogen": "groupchat",
    "consensus": "approved",
    "agents": "AIServiceHASupportAgent,AIApplicationManagementAgent,AISemiconductorInfraOpsAgent,CostOptimizationAgent",
    "reward_total": "3.05"
  }
}
```

중간에 아래 경고가 보여도 최종 JSON에서 `"valid": true`, `"stderr": ""`이면
성공으로 봅니다.

```text
Pydantic serializer warnings
```

대표 실패 의미:

```text
Missing credentials
```

API 키가 현재 PowerShell 창에 없습니다.

```text
401 invalid_api_key
```

API 키가 틀렸거나 폐기되었습니다.

```text
429 insufficient_quota
```

API 키는 맞지만 OpenAI API 결제/크레딧/quota 문제가 있습니다.

## 5. Docker/kind 상태 확인

Docker Desktop의 kind 컨테이너가 꺼져 있으면 dry-run/Prometheus/Chaos Mesh 실험은
안 됩니다. Docker Desktop에서 `aiops-local-control-plane` 컨테이너의 파란
play/action 버튼을 눌러 켠 뒤 확인합니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\local_kind_status.ps1
```

정상일 때 봐야 할 핵심:

```text
Kubernetes Nodes
aiops-local-control-plane   Ready

Online Boutique
paymentservice   3/3

Minimal Prometheus
prometheus-...   Running
```

직접 Docker 컨테이너 상태를 볼 때:

```powershell
$env:PATH = "C:\Program Files\Docker\Docker\resources\bin;" + $env:PATH
docker ps -a --filter name=aiops-local-control-plane --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

멈춘 컨테이너를 직접 시작할 때:

```powershell
$env:PATH = "C:\Program Files\Docker\Docker\resources\bin;" + $env:PATH
docker start aiops-local-control-plane
```

## 6. kind Kubernetes dry-run 실험

Docker Desktop이 실행 중이어야 합니다. `aiops-local-control-plane` 컨테이너가
멈춰 있으면 이 스크립트가 자동으로 `docker start`를 수행한 뒤 kubeconfig를
갱신하고 dry-run을 실행합니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_local_dry_run.ps1
```

성공 핵심 출력:

```json
{
  "command": "kubectl scale deployment paymentservice --replicas=3 -n online-boutique",
  "mode": "dry-run",
  "valid": true,
  "stdout": "deployment.apps/paymentservice scaled (server dry run)",
  "stderr": ""
}
```

직접 실행하고 싶으면 현재 PowerShell PATH에 kubectl/kind/Docker 경로를 먼저 붙입니다.

```powershell
$env:PATH = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Kubernetes.kubectl_Microsoft.Winget.Source_8wekyb3d8bbwe;$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Kubernetes.kind_Microsoft.Winget.Source_8wekyb3d8bbwe;C:\Program Files\Docker\Docker\resources\bin;$env:PATH"
```

그 다음:

```powershell
aiops-k8s-agents run --mode dry-run --namespace online-boutique --service paymentservice --metric cpu --value 95 --threshold 80 --message "paymentservice CPU usage is 95 percent" --allowed-namespace online-boutique --allowed-deployment paymentservice
```

## 6-1. AutoGen GroupChat + kind dry-run 실험

다음 단계 실험입니다. 실제 OpenAI API로 4개 에이전트가 합의한 뒤, 생성된 같은
명령을 로컬 kind Kubernetes API에 `--dry-run=server`로 검증합니다.

필요 조건:

- Docker Desktop에서 `aiops-local-control-plane` 컨테이너가 실행 중입니다.
- 컨테이너가 멈춰 있으면 스크립트가 자동으로 다시 시작합니다.
- 현재 PowerShell 창에 `OPENAI_API_KEY`가 설정되어 있습니다.
- `python -m pytest`와 AutoGen mock이 먼저 성공했습니다.

실행:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_autogen_dry_run.ps1
```

성공 기준:

```json
{
  "command": "kubectl scale deployment paymentservice --replicas=3 -n online-boutique",
  "mode": "dry-run",
  "valid": true,
  "stdout": "deployment.apps/paymentservice scaled (server dry run)",
  "stderr": ""
}
```

## 7. Prometheus 입력 경로 실험

Prometheus mock 응답 파일만 사용:

```powershell
aiops-k8s-agents prometheus-run --mode mock --mock-response-file examples\prometheus_cpu_high_response.json --query "cpu_query" --metric cpu --threshold 80 --default-namespace online-boutique --default-service paymentservice --allowed-namespace online-boutique --allowed-deployment paymentservice
```

로컬 kind에 배포된 Prometheus API를 실제로 호출:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_prometheus_local.ps1
```

이 스크립트는 내부에서 `kubectl port-forward`를 잠깐 열고, `http://127.0.0.1:9090`
Prometheus API를 호출한 뒤 port-forward를 종료합니다.

## 7-1. Prometheus 실제 입력 + AutoGen GroupChat + kind dry-run

연구 그림에 가장 가까운 로컬 통합 실험입니다.

```text
Prometheus API
-> AlertEvent
-> AutoGen 4-agent GroupChat
-> ScaleAction
-> CommandValidator
-> kubectl scale --dry-run=server
```

필요 조건:

- 현재 PowerShell 창에 `OPENAI_API_KEY`가 설정되어 있습니다.
- Docker Desktop이 실행 중입니다.
- `monitoring` namespace의 Prometheus pod가 Running입니다.
- AutoGen mock과 AutoGen dry-run이 먼저 성공했습니다.

실행:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_prometheus_autogen_local.ps1
```

Prometheus 입력까지 포함한 AutoGen 발화 요약을 보고 싶으면 직접 명령에
`--show-transcript`를 붙여 실행합니다.

성공 기준:

```json
{
  "command": "kubectl scale deployment paymentservice --replicas=3 -n online-boutique",
  "mode": "dry-run",
  "valid": true,
  "stdout": "deployment.apps/paymentservice scaled (server dry run)",
  "stderr": "",
  "metadata": {
    "autogen": "groupchat",
    "input_source": "prometheus",
    "consensus": "approved"
  }
}
```

현재 로컬 Prometheus 실험은 `up` query를 사용합니다. 이 query는 진짜 CPU 사용률
계산식은 아니지만, Prometheus API에서 실제 값을 읽어 `AlertEvent`로 바꾸고
AutoGen까지 넘기는 데이터 경로를 검증합니다. 연구실 서버에서는 이 부분을 실제
CPU/GPU/NPU metric query로 교체합니다.

## 8. 로컬 kind real scale 실험

주의: 연구실 서버가 아니라 내 PC 안의 kind 클러스터에 실제 scale 명령을 실행합니다.
`mock`과 `dry-run`이 성공한 뒤에만 실행합니다.

```powershell
$env:PATH = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Kubernetes.kubectl_Microsoft.Winget.Source_8wekyb3d8bbwe;$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Kubernetes.kind_Microsoft.Winget.Source_8wekyb3d8bbwe;C:\Program Files\Docker\Docker\resources\bin;$env:PATH"
```

```powershell
aiops-k8s-agents run --mode real --namespace online-boutique --service paymentservice --metric cpu --value 95 --threshold 80 --message "paymentservice CPU usage is 95 percent" --allowed-namespace online-boutique --allowed-deployment paymentservice
```

rollout 확인:

```powershell
kubectl rollout status deployment/paymentservice -n online-boutique --timeout=120s
kubectl get deployment paymentservice -n online-boutique
```

## 9. Chaos Mesh pod kill 실험

Docker/kind와 Chaos Mesh가 Running일 때만 사용합니다.

```powershell
$env:PATH = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Kubernetes.kubectl_Microsoft.Winget.Source_8wekyb3d8bbwe;C:\Program Files\Docker\Docker\resources\bin;$env:PATH"
```

PodChaos 주입:

```powershell
kubectl apply -f .\k8s\paymentservice-pod-kill.yaml
```

복구 확인:

```powershell
kubectl get pods -n online-boutique -l app=paymentservice
kubectl rollout status deployment/paymentservice -n online-boutique --timeout=120s
```

실험 종료 후 Chaos 삭제:

```powershell
kubectl delete -f .\k8s\paymentservice-pod-kill.yaml
```

## 10. 10회 반복 안정성 확인

같은 CPU 과부하 시나리오에서 항상 같은 명령이 나오는지 확인합니다.

```powershell
$commands = @()
$allValid = $true
for ($i=1; $i -le 10; $i++) {
  $result = aiops-k8s-agents run --mode mock --namespace online-boutique --service paymentservice --metric cpu --value 95 --threshold 80 --message "paymentservice CPU usage is 95 percent" --allowed-namespace online-boutique --allowed-deployment paymentservice | ConvertFrom-Json
  $commands += $result.command
  if (-not $result.valid) { $allValid = $false }
}
[pscustomobject]@{
  runs = 10
  all_valid = $allValid
  unique_commands = ($commands | Select-Object -Unique).Count
  command = $commands[0]
} | ConvertTo-Json
```

성공 기준:

```json
{
  "runs": 10,
  "all_valid": true,
  "unique_commands": 1,
  "command": "kubectl scale deployment paymentservice --replicas=3 -n online-boutique"
}
```

## 11. 서버 이관 후 Ubuntu 명령어

서버에서는 Windows PowerShell 대신 Bash를 사용합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,autogen]"
python -m pytest
```

OpenAI API 키:

```bash
export OPENAI_API_KEY="sk-..."
```

서버 dry-run:

```bash
aiops-k8s-agents run \
  --mode dry-run \
  --namespace online-boutique \
  --service paymentservice \
  --metric cpu \
  --value 95 \
  --threshold 80 \
  --message "paymentservice CPU usage is 95 percent" \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice
```

서버 real 실행은 kubeconfig, namespace, deployment allowlist를 확인한 뒤에만 사용합니다.

```bash
aiops-k8s-agents run \
  --mode real \
  --namespace online-boutique \
  --service paymentservice \
  --metric cpu \
  --value 95 \
  --threshold 80 \
  --message "paymentservice CPU usage is 95 percent" \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice
```

## 12. 최종 성공 기준

서버 이관 전 로컬 기준:

- `python -m pytest`가 통과합니다.
- deterministic mock에서 `"valid": true`가 나옵니다.
- AutoGen mock에서 `"valid": true`와 `"consensus": "approved"`가 나옵니다.
- dry-run에서 `"deployment.apps/paymentservice scaled (server dry run)"`가 나옵니다.
- Prometheus 입력 경로에서 `"input_source": "prometheus"`가 metadata에 들어갑니다.
- `mock`과 `dry-run`의 command 문자열이 동일합니다.

최종 명령어는 아래와 같아야 합니다.

```bash
kubectl scale deployment paymentservice --replicas=3 -n online-boutique
```

## 13. 서버 개인용 kind 통합 실험 명령어

연구실 공용 Kubernetes kubeconfig 권한이 없을 때는 개인용 kind 클러스터에서 아래
범위까지 실험합니다.

```text
Prometheus
-> feedback-loop
-> 4-agent action/reward
-> kubectl dry-run 또는 real
-> Kubernetes 상태 snapshot 저장
```

서버 터미널 기본 환경:

```bash
cd ~/geonhae/aiops_research
conda activate aiops_research
export PATH="$HOME/bin:$PATH"
export KUBECONFIG=~/geonhae/kubeconfigs/kind-geonhae-aiops.yaml
```

서버 kind 상태 확인:

```bash
bash scripts/server_kind_status.sh
```

deterministic 피드백 루프:

```bash
ITERATIONS=3 INTERVAL_SECONDS=10 MODE=dry-run bash scripts/server_feedback_loop.sh
```

AutoGen GroupChat 피드백 루프:

```bash
export OPENAI_API_KEY="sk-..."
USE_AUTOGEN=1 ITERATIONS=3 INTERVAL_SECONDS=10 MODE=dry-run bash scripts/server_feedback_loop.sh
```

real mode 피드백 루프는 dry-run이 성공한 뒤에만 실행합니다.

```bash
ITERATIONS=1 MODE=real bash scripts/server_feedback_loop.sh
```

결과 파일 확인:

```bash
ls -lt runs | head
cat "$(ls -t runs/*.json | head -n 1)"
```

Chaos Mesh pod kill 장애 주입:

```bash
bash scripts/server_chaos_pod_kill_once.sh
```

직접 `feedback-loop` 명령을 실행하려면:

```bash
aiops-k8s-agents feedback-loop \
  --mode dry-run \
  --prometheus-url http://127.0.0.1:9090 \
  --query up \
  --metric cpu \
  --threshold 0.5 \
  --default-namespace online-boutique \
  --default-service paymentservice \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice \
  --iterations 3 \
  --interval-seconds 10 \
  --save-result-dir runs
```

성공 기준:

- `failed`가 `0`입니다.
- 각 record의 `result.valid`가 `true`입니다.
- 각 record에 `before`, `result`, `after`가 저장됩니다.
- `after.deployment_status.ready_replicas`가 `3`입니다.

## 14. AIOpsLab 공식 문제를 4-agent가 자동으로 풀기

이 단계는 사람이 AIOpsLab 프롬프트에 직접 `get_logs`, `get_metrics`, `submit`을 입력하던 과정을
우리 AI-MCMP 4-agent 정책으로 자동화합니다.

서버 기본 환경:

```bash
cd ~/geonhae/aiops_research
conda activate aiopslab
export PATH="$HOME/bin:$PATH"
export KUBECONFIG=~/geonhae/kubeconfigs/kind-geonhae-aiops.yaml
```

최신 코드 가져오기:

```bash
git pull origin master
```

AIOpsLab 자동 detection 실행:

```bash
bash scripts/server_aiopslab_auto_detection.sh
```

직접 Python runner를 실행하려면:

```bash
python scripts/server_aiopslab_auto_detection.py \
  --aiopslab-root ~/geonhae/external/AIOpsLab \
  --problem-id misconfig_app_hotel_res-detection-1 \
  --namespace test-hotel-reservation \
  --service geo \
  --kubeconfig ~/geonhae/kubeconfigs/kind-geonhae-aiops.yaml \
  --save-result-dir runs
```

자동화 흐름:

```text
AIOpsLab problem start
-> 4-agent가 get_logs("test-hotel-reservation", "geo") 호출
-> 로그에서 panic/no reachable servers 같은 장애 근거 확인
-> 4-agent가 get_metrics("test-hotel-reservation", 10) 호출
-> action/reward 합의 기록
-> 4-agent가 submit("Yes") 또는 submit("No") 제출
-> AIOpsLab 평가 결과 저장
```

성공 기준:

```text
Correct detection: Yes
Detection Accuracy: Correct
Saved report: .../runs/<timestamp>_aiopslab_auto_detection.json
```

참고:

- 개인 kind 환경에서는 OpenEBS NDM daemon pod가 `ContainerCreating`에 머물 수 있습니다.
- runner는 AIOpsLab 원본을 크게 고치지 않고, 실행 중 `openebs-ndm-*` daemon pod만 Ready 판정에서 제외합니다.
- `openebs-localpv-provisioner`, `openebs-ndm-operator`, exporter pod들은 여전히 Ready 상태를 요구합니다.
- AIOpsLab이 Prometheus port-forward를 `32001` 같은 동적 포트로 열면 runner가 Prometheus client URL도 같은 포트로 맞춥니다.

## 15. AIOpsLab 자동 detection 반복 실험과 결과표 생성

단발 성공을 논문/보고서용 결과로 만들려면 같은 문제를 여러 번 반복하고 TTD, steps, reward, metric 수집 성공 여부를
표로 정리합니다.

서버에서 3회 반복 실행:

```bash
cd ~/geonhae/aiops_research
conda activate aiopslab
git pull origin master
export PATH="$HOME/bin:$PATH"
export KUBECONFIG=~/geonhae/kubeconfigs/kind-geonhae-aiops.yaml

RUNS=3 SLEEP_SECONDS=15 bash scripts/server_aiopslab_repeat_detection.sh
```

이미 저장된 JSON report만 다시 요약하려면:

```bash
bash scripts/server_aiopslab_summarize_runs.sh
```

직접 CLI로 요약하려면:

```bash
aiops-k8s-agents summarize-aiopslab-runs \
  --runs-dir runs \
  --output-md runs/aiopslab_detection_summary.md \
  --output-csv runs/aiopslab_detection_summary.csv
```

생성되는 파일:

```text
runs/aiopslab_detection_summary.md
runs/aiopslab_detection_summary.csv
```

요약 지표:

- `total_runs`: 반복 실험 횟수
- `correct_runs`: AIOpsLab 평가가 Correct인 횟수
- `metric_success_runs`: Prometheus metric CSV 수집 성공 횟수
- `average_ttd_seconds`: 평균 detection 시간
- `average_steps`: 평균 API action 단계 수
- `average_final_reward`: 최종 제출 단계의 평균 reward 합
- `phase_coverage`: 참고 PPT의 `detection/localization/analysis/mitigation` 중 해당 반복 실험에서 실제 사용된 단계

## 16. 초기 연구 검증 단계 최종 결과 확인

서버에서 최종 요약표를 확인합니다.

```bash
cd ~/geonhae/aiops_research
cat runs/aiopslab_detection_summary.md
```

CSV 파일도 함께 확인할 수 있습니다.

```bash
cat runs/aiopslab_detection_summary.csv
```

2026-06-09 기준 서버 반복 실험 결과:

```text
total_runs: 12
correct_runs: 12
metric_success_runs: 11
average_ttd_seconds: 4.117
average_steps: 3.000
average_final_reward: 3.100
```

보고서나 발표자료에는 아래 문장을 사용할 수 있습니다.

```text
AIOpsLab Hotel Reservation detection 문제를 대상으로 4-agent 자동 탐지 실험을 12회 반복 수행한 결과,
12회 모두 Correct detection으로 평가되었다. 평균 TTD는 4.117초, 평균 action step은 3.0,
평균 최종 reward는 3.10으로 측정되었다.
```

## 17. Full-stack 확장 실험

이 단계는 minimal 환경을 지우는 것이 아니라, 별도 full-stack 모드를 추가해서 장애와 정책 변수를 바꾸는 실험입니다.

고정 환경:

```text
kube-prometheus-stack
Online Boutique 전체 서비스
Chaos Mesh
4-agent runner
runs/full-stack* 결과 저장 구조
```

실험 매트릭스 확인:

```bash
aiops-k8s-agents list-full-stack-experiments \
  --config config/full_stack_experiments.json
```

full-stack 설치:

```bash
cd ~/geonhae/aiops_research
conda activate aiops_research
git pull origin master
python -m pip install -e ".[dev,autogen]"

export PATH="$HOME/bin:$PATH"
export KUBECONFIG=~/geonhae/kubeconfigs/kind-geonhae-aiops.yaml

bash scripts/server_full_stack_setup.sh
```

단일 장애 주입:

```bash
SCENARIO=pod-kill bash scripts/server_full_stack_apply_chaos.sh
SCENARIO=cpu-stress bash scripts/server_full_stack_apply_chaos.sh
SCENARIO=memory-stress bash scripts/server_full_stack_apply_chaos.sh
SCENARIO=network-delay bash scripts/server_full_stack_apply_chaos.sh
```

4-agent feedback loop:

```bash
SCENARIO=cpu-stress \
ITERATIONS=3 \
INTERVAL_SECONDS=10 \
MODE=dry-run \
bash scripts/server_full_stack_feedback_loop.sh
```

여러 장애를 순서대로 실행:

```bash
ITERATIONS=3 \
INTERVAL_SECONDS=10 \
MODE=dry-run \
bash scripts/server_full_stack_experiment_matrix.sh
```

자세한 설명은 `docs/full_stack_experiment_guide.md`를 보면 됩니다.

## Go guard 통합 실행

현재 프로젝트는 Python 4-Agent 판단과 Go 기반 최종 안전 검증기를 하나의 실행 경로로 연결합니다.
서버 실험 스크립트는 기본적으로 `GUARD_BACKEND=go`를 사용하므로, 4-Agent가 만든 action은 Go `aiops-guard`를 한 번 더 통과한 뒤 `kubectl` 명령으로 실행됩니다.

단일 recovery action 검증:

```bash
aiops-k8s-agents execute-recovery-action \
  --mode dry-run \
  --guard-backend go \
  --action rollout_restart \
  --namespace online-boutique \
  --deployment paymentservice \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice
```

실제 Chaos Mesh 반복 실험:

```bash
GUARD_BACKEND=go \
MODE=real \
REPETITIONS=3 \
PROMETHEUS_URL=http://127.0.0.1:9091 \
bash scripts/server_recovery_action_pilot.sh
```

full-stack feedback loop:

```bash
GUARD_BACKEND=go \
MODE=dry-run \
SCENARIO=cpu-stress \
ITERATIONS=3 \
bash scripts/server_full_stack_feedback_loop.sh
```

`GUARD_BACKEND=python`으로 바꾸면 기존 Python validator-only 경로로 되돌릴 수 있습니다.
