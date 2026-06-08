# 로컬 테스트 및 실험 명령어 모음

이 문서는 현재 프로토타입에서 바로 실행할 수 있는 테스트/실험 명령어를 한곳에
모은 치트시트입니다. 기본 원칙은 `mock -> dry-run -> real` 순서입니다.

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
