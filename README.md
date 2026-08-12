# AIOps 4-Agent Kubernetes 장애 복구 연구

4개의 역할 기반 Agent가 Kubernetes 장애를 진단하고, 상호 검토와 안전 검증을
통과한 복구 Action만 실행하는 연구 프레임워크입니다.

![AIOps 4-Agent architecture](docs/assets/architecture_overview.png)

## 핵심 흐름

```text
Chaos Mesh / AIOpsLab
        -> Evidence: Prometheus + Kubernetes
        -> Coordinator + 4-Agent 판단
        -> 상호 검토 / Action / Reward
        -> Python Validator
        -> Kubernetes 복구 Action
        -> Recovery Monitor / 결과 분석
```

| 구성 | 역할 |
| --- | --- |
| HA Agent | 가용성·장애 영향·복구 필요성 판단 |
| Application Agent | observe / rollout restart / scale-out 제안 |
| Infrastructure Agent | replica·자원·인프라 제약 검토 |
| Cost Agent | 비용 증가와 과잉 대응 검토 |
| Coordinator | Agent 의견 수집, 합의와 재협상 관리 |
| Python Validator | allowlist, namespace, deployment, replica, 명령 안전성 검증 |
| AutoGen | 선택 가능한 LLM GroupChat 경로. API 키가 있을 때만 사용 |
| AIOpsLab | 별도 장애 탐지 benchmark. Chaos Mesh 복구 실험과 구분 |

## 실행 모드

| 모드 | 의미 |
| --- | --- |
| `mock` | 합성 Evidence로 전체 흐름을 확인. 클러스터 변경 없음 |
| `dry-run` | 대상·명령·정책을 검증. 클러스터 변경 없음 |
| `real` | Ubuntu 클러스터에서 Chaos Mesh와 Kubernetes Action을 실제 실행 |

`mock`과 `dry-run` 결과는 실제 장애 복구 성능의 근거가 아닙니다. `real`은
allowlist, replica 제한, Validator, cleanup, 실행 확인 문구를 모두 통과해야 합니다.

## Ubuntu에서 처음 실행하기

아래 절차는 이미 Kind 또는 Kubernetes, Online Boutique,
`kube-prometheus-stack`, Chaos Mesh가 준비된 서버를 기준으로 합니다.
이 저장소는 클러스터와 외부 AIOpsLab 저장소를 자동 설치하지 않습니다.

### 1. 프로젝트와 Python 환경

```bash
git clone https://github.com/gunsun2000/aiops_research.git
cd aiops_research

conda create -n aiops_research python=3.13 -y
conda activate aiops_research
python -m pip install -e ".[dev,autogen,ui,docs]"
```

공식 [AIOpsLab](https://github.com/microsoft/AIOpsLab)은 별도 checkout과
`aiopslab` 환경에 설치합니다. 처음 준비할 때는 다음을 실행하고, 상세 설치는
AIOpsLab 저장소의 `TutorialSetup.md`를 따릅니다.

```bash
mkdir -p "$HOME/geonhae/external"
git clone https://github.com/microsoft/AIOpsLab.git \
  "$HOME/geonhae/external/AIOpsLab"
conda create -n aiopslab python=3.11 -y
conda activate aiopslab
cd "$HOME/geonhae/external/AIOpsLab"
python -m pip install -e "."

export AIOPSLAB_ROOT="$HOME/geonhae/external/AIOpsLab"
export AIOPSLAB_PYTHON="$HOME/anaconda3/envs/aiopslab/bin/python"
```

### 2. 한 번에 연결 확인 후 Control Plane 시작

```bash
cd ~/geonhae/aiops_research
conda activate aiops_research

export PATH="$HOME/bin:$PATH"
export KUBECONFIG="${KUBECONFIG:-$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml}"
export PROMETHEUS_URL="${PROMETHEUS_URL:-http://127.0.0.1:9091}"
export AIOPS_AUTO_PORT_FORWARD=auto
export AIOPSLAB_ROOT="${AIOPSLAB_ROOT:-$HOME/geonhae/external/AIOpsLab}"
export AIOPSLAB_PYTHON="${AIOPSLAB_PYTHON:-$HOME/anaconda3/envs/aiopslab/bin/python}"
export AIOPS_BIND_ADDRESS=127.0.0.1
export PORT=18180

bash scripts/start_research_console.sh
```

이 스크립트가 시작 전에 다음을 확인합니다.

- Kubernetes context와 node
- `online-boutique`, `monitoring-full` namespace
- Chaos Mesh API resource
- 외부 AIOpsLab Python runtime
- AutoGen API 키 설정 여부

### 3. 연결 상태 확인

Control Plane을 실행한 터미널은 켜 둔 채, 두 번째 터미널에서 실행합니다.

```bash
curl -sS http://127.0.0.1:18180/healthz
curl -sS http://127.0.0.1:18180/api/connections | python -m json.tool
```

정상적인 deterministic/mock 준비 상태는 다음과 같습니다.

```text
Kubernetes: ready = true
Prometheus: ready = true (platform-managed port-forward)
Chaos Mesh: ready = true
AIOpsLab: ready = true
AutoGen: ready = false, status = missing_credentials
missing_prerequisites: []
```

Prometheus가 이미 응답 중이면 기존 연결을 재사용하고, 응답하지 않으면 플랫폼이
자동으로 다음 port-forward를 실행합니다.

```text
kubectl port-forward -n monitoring-full \
  service/kube-prometheus-stack-prometheus 9091:9090
```

따라서 사용자가 매번 Prometheus 포트포워딩 터미널을 별도로 켤 필요는 없습니다.
단, Kubernetes context와 Prometheus Service가 서버에 존재해야 합니다.

웹 브라우저:

```text
http://127.0.0.1:18180/
```

VS Code Remote SSH를 사용하면 원격 `18180`을 로컬 포트로 전달합니다. 예를 들어
로컬 포트가 `18181`이면 브라우저에서 `http://127.0.0.1:18181/`을 사용합니다.
원격 서버의 `PORT`와 VS Code 로컬 전달 포트를 혼동하지 마십시오.

## AutoGen 사용하기

AutoGen은 선택 기능입니다. API 키가 없으면 UI에 `API 키 미설정`으로 표시되고
deterministic, mock, dry-run 경로는 계속 사용할 수 있습니다.

```bash
export OPENAI_API_KEY="<your-api-key>"
export AIOPS_OPENAI_MODEL="gpt-5.5"
aiops-control-plane
```

키는 README, shell history, 요청 body, 결과 파일, Git에 저장하지 마십시오.
AutoGen GroupChat을 실제 호출할 때는 모델 접근 권한과 API quota도 필요합니다.

## 실험 실행

### 웹 Control Plane

1. `Recovery Experiment`에서 장애 시나리오를 선택합니다.
2. `Deterministic` 또는 API 키가 설정된 `AutoGen` Controller를 선택합니다.
3. `Mock`으로 흐름을 먼저 확인합니다.
4. `Dry-run`으로 대상과 안전 정책을 확인합니다.
5. Ubuntu 실험 서버에서만 `Real`을 명시적으로 실행합니다.

### CLI Mock 확인

```bash
aiops-k8s-agents mutual-supervision-run \
  --mode mock \
  --namespace online-boutique \
  --deployment paymentservice \
  --metric cpu \
  --threshold 80 \
  --evidence-value 95 \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice
```

### Chaos Mesh Real 복구 실험

Real 실험은 Prometheus와 클러스터 상태를 먼저 확인한 뒤 실행합니다.

```bash
export CONFIRM_REAL_RUN=YES
export NETWORK_LATENCY_QUERY='max(probe_duration_seconds{target="paymentservice"})'

GUARD_BACKEND=go \
MODE=real \
REPETITIONS=3 \
PROMETHEUS_URL="$PROMETHEUS_URL" \
NETWORK_LATENCY_QUERY="$NETWORK_LATENCY_QUERY" \
bash scripts/server_recovery_action_pilot.sh
```

결과는 `runs/recovery-action-pilot/`에 JSONL, CSV, Markdown, PNG, SVG로 저장됩니다.
정량 결과는 다음 명령으로 생성합니다.

```bash
bash scripts/server_recovery_statistics.sh
```

### AIOpsLab Benchmark

AIOpsLab benchmark는 Chaos Mesh 복구 실험과 별도의 탐지 실험입니다.

```bash
conda activate aiopslab
cd ~/geonhae/aiops_research
bash scripts/server_aiopslab_auto_detection.sh
```

반복 실행과 요약:

```bash
bash scripts/server_aiopslab_repeat_detection.sh
bash scripts/server_aiopslab_summarize_runs.sh
```

## 코드 검증

```bash
conda activate aiops_research
python -m pytest
```

Go Guard가 설치된 checkout에서는 선택적으로 다음을 실행합니다.

```bash
cd go/aiops-guard
go test ./...
```

## 문서 바로가기

| 문서 | 내용 |
| --- | --- |
| [문서 목록](docs/README.md) | 전체 문서 구조 |
| [설치·실행 가이드](docs/submission/install_and_run_guide.md) | 환경별 상세 설치 |
| [Real runtime 가이드](docs/experiments/platform_real_runtime_guide.md) | Prometheus·Chaos Mesh·Kubernetes 검증 |
| [Recovery 실험 가이드](docs/experiments/recovery_action_experiment_guide.md) | 장애별 Action 실험 |
| [정량 분석 가이드](docs/experiments/recovery_quantitative_analysis_guide.md) | 성공률·복구 시간·Reward 분석 |
| [Control Plane UI 가이드](docs/submission/control_plane_ui_guide.md) | 웹 화면과 API |
| [연구 보고서](docs/deliverables/AIOps_4Agent_Research_Report.docx) | 발표·검토용 DOCX |

## 범위의 정확한 표현

- `FakeEvidenceProvider` 기반 autonomous loop는 mock/test용으로 구현되어 있습니다.
- `KubernetesEvidenceProvider`는 deployment/pod snapshot 중심의 보수적 provider입니다.
- Prometheus metric, log enrichment, full real-cluster evidence fusion은 후속 확장입니다.
- AIOpsLab benchmark 결과와 Chaos Mesh recovery 결과는 같은 Control Plane에서
  조회하더라도 서로 다른 실험 근거로 기록합니다.
