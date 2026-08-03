# AIOps 4-Agent Kubernetes 장애 복구 연구

![AIOps 4-Agent architecture](docs/assets/architecture_overview.png)

이 저장소는 **4개의 AI Agent가 Kubernetes 서비스 장애를 판단하고, 안전 검증을 거친 복구 action만 실행하는 AIOps 연구 프로토타입**입니다.

## 공식 연구 문서

교수님·외부 검토자에게 공유하는 문서는 Markdown 원문이 아니라 아래의 Word 문서를 기준으로 합니다.

| 문서 | 용도 |
| --- | --- |
| [AIOps 4-Agent 연구 보고서](docs/deliverables/AIOps_4Agent_Research_Report.docx) | 연구 배경, 아키텍처, 실험 설계, 결과, 한계와 후속 연구 |
| [AIOps 실험 실행 및 검증 가이드](docs/deliverables/AIOps_Experiment_Operations_Guide.docx) | 설치, Control Plane, mock/dry-run/real 실험, 정량 분석 재현 |
| [4-Agent Action 및 Reward 정책 명세서](docs/deliverables/AIOps_Agent_Policy_Specification.docx) | Agent 역할, 합의, action/reward, 승인·거부와 안전 경계 |

Markdown 문서는 코드와 함께 갱신하기 쉬운 기술 원본으로 유지합니다. DOCX는 다음 명령으로 다시 생성할 수 있습니다.

```bash
python -m pip install -e ".[docs]"
python scripts/build_research_documents.py
```

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
python -m pip install -e ".[dev,autogen,ui,docs]"
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

## Control Plane과 실험 실행 경계

웹 Control Plane은 등록된 장애 시나리오를 영속 Job으로 실행하고, 하나의
`experiment_id` 아래에서 장애 주입, Evidence 수집, 4-Agent 상호감시,
안전 검증, Kubernetes Action, 복구 관찰, cleanup 이벤트를 추적합니다.
Job과 이벤트는 기본적으로
`runs/control-plane/experiment-jobs.sqlite3`에 저장되며, SSE로 화면에
실시간 전달됩니다. 실행 취소는 안전한 단계 경계에서 처리되고 cleanup은 항상
시도합니다. 서버 재시작 시 진행 중이던 Job은 자동 재실행하지 않고
`interrupted`로 표시하여 중복 장애 주입을 방지합니다.

실행 모드는 다음처럼 구분합니다.

| 모드 | Evidence 및 실행 경계 |
| --- | --- |
| `mock` | `FakeEvidenceProvider` 기반 합성 Evidence. Kubernetes를 변경하지 않음 |
| `dry-run` | 실제 대상과 명령을 검증하지만 Kubernetes 상태를 변경하지 않음 |
| `real` | Ubuntu 서버의 Prometheus, Chaos Mesh, Kubernetes를 사용해 제한된 Action을 실행 |

`real` 웹 실행은 서버 환경변수 `CONFIRM_REAL_RUN=YES`와 UI 확인 문구
`EXECUTE REAL EXPERIMENT`가 모두 필요합니다. 이 Gate를 통과해도 등록된
시나리오, allowlist, replica 제한, target lock, Validator와 cleanup 경계는
그대로 적용됩니다. Windows에서 통과한 테스트와 `mock` 결과는 실제 클러스터
실험 근거가 아닙니다.

```bash
python -m pip install -e ".[ui,dev,autogen]"
aiops-control-plane
```

브라우저:

```text
http://127.0.0.1:18080/
```

상세 UI 가이드는 [docs/submission/control_plane_ui_guide.md](docs/submission/control_plane_ui_guide.md)에,
real runtime 검증 절차는 [docs/experiments/platform_real_runtime_guide.md](docs/experiments/platform_real_runtime_guide.md)에 있습니다.

### 현재 통합 범위

- 완료: core runtime, Prometheus/Kubernetes/Chaos Mesh adapter, lifecycle cleanup
- 완료: SQLite 영속 Job, 백그라운드 실행, SSE replay, 취소, 웹 `mock/dry-run/real` 요청
- 완료: 3영역 연구 콘솔에서 조건, 4-Agent 상호검토, 안전 검사, 결과를 동일 Job으로 표시
- 미통합: AutoGen GroupChat의 웹 Job 실행
- 미통합: AIOpsLab benchmark의 웹 Job 실행

기존 AutoGen 및 AIOpsLab CLI/스크립트는 유지되지만, 현재 웹 Job이 이 두 실행을
대신하거나 검증했다고 해석하지 않습니다.

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

4-Agent 상호감시 mock 실험:

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

### Protocol profile selection

Protocol profiles are discovered only from `config/protocol_profiles` and are
selected by registered ID. File paths and path traversal are not accepted.

```bash
aiops-k8s-agents list-protocol-profiles

aiops-k8s-agents mutual-supervision-run \
  --mode mock \
  --protocol-profile four-agent-role-veto-v1 \
  --namespace online-boutique \
  --deployment paymentservice \
  --metric cpu \
  --threshold 80 \
  --evidence-value 95 \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice \
  --no-save
```

`four-agent-autogen-v1` declares the registered `autogen-round-robin` runtime.
The mutual-supervision CLI does not create a model client from environment
variables or credentials. Selecting that profile without an explicitly
injected model client or decision provider returns `runtime_unavailable`,
performs no execution, and requires human review. Provider output is accepted
only through the structured schema, is rebound to the configured Agent
identity and run/policy metadata, and remains subject to the Python Validator.

This repository currently demonstrates AutoGen runtime support and offline
fake-provider safety tests. Those checks are not evidence of a completed
networked AutoGen experiment or a real Kubernetes experiment. The existing
`autogen-run` and `autogen-prometheus-run` commands remain the standalone
model-client execution paths and require the `autogen` extra plus an
appropriately configured provider credential.

이 명령은 역할별 초기 판단, 동료 Agent의 `approve/revise/veto`,
제한된 재합의 라운드, 안전 검증, 실행 후 4-Agent 재평가를 수행합니다.
실험 기록은 기본적으로 `runs/mutual-supervision/` 아래 JSONL, JSON,
CSV, Markdown으로 저장됩니다. 현재 상호감시 엔진은 재현 가능한
deterministic 정책 경로이며, AutoGen 기반 자유형 다중 라운드 상호감시는
후속 비교 실험으로 분리합니다.

현재 deterministic v1에서는 응용관리 Agent가 제안한 실행 Action을
HA·인프라·비용 Agent가 독립적으로 교차 검토하고, 실행 후에는 4개 Agent가
각 역할 기준으로 결과를 다시 평가합니다. 모든 Agent 판단을 다시 완전 연결형으로
검토하는 일반화된 메시지 그래프는 후속 연구 범위입니다.

`real` 모드는 fake evidence를 허용하지 않습니다. 반드시
`--evidence-source kubernetes`를 사용하며, deployment readiness와 Pod identity
변화를 보수적으로 확인한 경우에만 복구 성공으로 판정합니다. 동일
namespace/deployment에 대한 동시 real 제어는 target lock으로 차단합니다.
Prometheus·로그까지 결합한 full evidence fusion은 후속 확장 범위입니다.

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
| Core real runtime 검증 | [docs/experiments/platform_real_runtime_guide.md](docs/experiments/platform_real_runtime_guide.md) |
| Recovery 실험 | [docs/experiments/recovery_action_experiment_guide.md](docs/experiments/recovery_action_experiment_guide.md) |
| 정량 분석 | [docs/experiments/recovery_quantitative_analysis_guide.md](docs/experiments/recovery_quantitative_analysis_guide.md) |

## 현재 연구 단계

현재 저장소는 mock-safe 검증, bounded core runtime, CLI real 경로와 영속형 웹
실험 Job을 제공하는 **1차 연구 프레임워크**입니다. 이 Windows worktree에서는
실제 Kubernetes/Chaos Mesh/Prometheus 실험을 수행하지 않았으므로 테스트 통과와
웹 mock 결과를 real evidence로 해석하지 않습니다.

다음 단계는 이 구조를 고정한 뒤, 다음 비교 실험을 추가하는 것입니다.

- single-agent baseline 비교
- Agent 제거 ablation 실험
- reward 민감도 분석
- AutoGen multi-round Agent 판단을 현재 웹 Job runtime에 연결
- AIOpsLab benchmark를 동일한 Job/SSE/산출물 구조에 연결
- Prometheus metric, log enrichment, full real-cluster evidence fusion

초기 `CPU 95%` 입력은 smoke test입니다. Chaos Mesh/AIOpsLab 기반 실제 장애
결과는 별도의 승인된 Ubuntu 환경 실행과 artifact 검토가 있어야 주장할 수 있습니다.
