# AIOps 4-Agent Kubernetes 장애 복구 연구

![AIOps 4-Agent architecture](docs/assets/architecture_overview.png)

이 저장소는 **4개의 AI Agent가 Kubernetes 서비스 장애를 판단하고, 안전 검증을 거친 복구 action만 실행하는 AIOps 연구 프로토타입**입니다.

연구의 중심은 다음 장애 감시/복구 흐름입니다.

```text
AIOpsLab / Chaos Mesh 장애 주입
-> Prometheus / Kubernetes 상태 관측
-> AI-MCMP Coordinator
-> 4-Agent 판단
-> Action / Reward 교차 검증
-> Python Validator
-> 선택적 Go Guard
-> kubectl mock / dry-run / real 실행
-> 결과 저장 및 정량 분석
```

## 연구 범위

| 구분 | 현재 처리 |
| --- | --- |
| 4-Agent 장애 판단 | 연구 본체 |
| Action / Reward 정책 | 연구 본체 |
| AIOpsLab / Chaos Mesh / Prometheus / Kubernetes 실험 | 연구 본체 |
| Python Validator | 기본 안전 검증 |
| Go Guard | 선택적 이중 안전 검증 |
| Agent Registry | Agent 역할과 허용 action 관리 |
| AutoGen GroupChat | structured multi-agent 보조 경로 |

## 4-Agent 역할

| Agent | 역할 |
| --- | --- |
| `AIServiceHASupportAgent` | 서비스 장애 진단, 가용성 판단, 복구 필요성 평가 |
| `AIApplicationManagementAgent` | `observe_only`, `rollout_restart`, `scale_out` 복구 action 제안 |
| `AISemiconductorInfraOpsAgent` | Kubernetes replica/deployment 안전성 및 인프라 수용성 검토 |
| `CostOptimizationAgent` | 비용 증가, 과잉 action, replica 증가 정책 검토 |

Agent 등록 정보는 [config/agent_registry.json](config/agent_registry.json)에 있습니다.

## 빠른 실행

서버 기준:

```bash
cd ~/geonhae/aiops_research
git pull origin master
conda activate aiops_research
python -m pip install -e ".[dev,autogen]"
python -m pytest
```

Windows 로컬 기준:

```powershell
cd C:\Users\geonhae\Documents\aiops_research
python -m pytest
```

Go Guard 검증:

```bash
cd go/aiops-guard
go test ./...
```

상세 실행 코드는 [docs/submission/execution_code_guide.md](docs/submission/execution_code_guide.md)에 정리되어 있습니다.

## Control Plane UI

교수님 시연과 연구실 점검을 위해 FastAPI 기반 웹 Control Plane을 제공합니다.
사이드바에서 대시보드, 장애 실험, 4-Agent 판단, 안전 검증, 실험 결과,
연구 문서를 독립 화면으로 전환할 수 있습니다.

```bash
python -m pip install -e ".[ui,dev,autogen]"
aiops-control-plane
```

브라우저:

```text
http://127.0.0.1:18080/
```

상세 가이드는 [docs/submission/control_plane_ui_guide.md](docs/submission/control_plane_ui_guide.md)에 있습니다.

## 핵심 실험

Autonomous mock 확인:

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

Recovery action 비교 실험:

```bash
GUARD_BACKEND=go \
MODE=real \
REPETITIONS=3 \
PROMETHEUS_URL=http://127.0.0.1:9091 \
NETWORK_LATENCY_QUERY='max(probe_duration_seconds{target="paymentservice"})' \
bash scripts/server_recovery_action_pilot.sh
```

실험 구성:

```text
4개 장애 x 3개 action x 3회 = 36회

장애: pod-kill, cpu-stress, memory-stress, network-delay
Action: observe_only, rollout_restart, scale_out
```

정량 분석:

```bash
bash scripts/server_recovery_statistics.sh
```

## 문서 바로가기

| 목적 | 문서 |
| --- | --- |
| 전체 요약 | [docs/core_submission_summary.md](docs/core_submission_summary.md) |
| 문서 지도 | [docs/README.md](docs/README.md) |
| 요구사항 정의 | [docs/submission/requirements_definition.md](docs/submission/requirements_definition.md) |
| 설치 및 실행 | [docs/submission/install_and_run_guide.md](docs/submission/install_and_run_guide.md) |
| 실행 코드 | [docs/submission/execution_code_guide.md](docs/submission/execution_code_guide.md) |
| 시험 가이드 | [docs/submission/test_guide.md](docs/submission/test_guide.md) |
| Agent Registry | [docs/design/agent_registry_guide.md](docs/design/agent_registry_guide.md) |
| Action / Reward 정책 | [docs/design/agent_action_reward_policy.md](docs/design/agent_action_reward_policy.md) |
| Recovery 실험 | [docs/experiments/recovery_action_experiment_guide.md](docs/experiments/recovery_action_experiment_guide.md) |
| 정량 분석 | [docs/experiments/recovery_quantitative_analysis_guide.md](docs/experiments/recovery_quantitative_analysis_guide.md) |

## 현재 연구 단계

현재 저장소는 단순 mock 예제가 아니라, 서버의 Kubernetes/Chaos Mesh/Prometheus 환경에서 real-mode 장애 실험과 정량 분석까지 수행할 수 있는 **1차 연구 프로토타입**입니다.

다음 단계는 이 구조를 고정한 뒤, 다음 비교 실험을 추가하는 것입니다.

- single-agent baseline 비교
- Agent 제거 ablation 실험
- reward 민감도 분석
- AutoGen multi-round real action 선택
- Prometheus metric, log enrichment, full real-cluster evidence fusion

초기 `CPU 95%` 입력은 smoke test이며, 연구 결과의 중심은 Chaos Mesh/AIOpsLab 기반 실제 장애 실험입니다.
