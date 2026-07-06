# AIOps 4-Agent Kubernetes 자동화 연구

![AIOps 4-Agent 프로젝트 진행 구조 및 연결 흐름](docs/assets/architecture_overview.png)

이 저장소는 **4개의 AI Agent가 Kubernetes 서비스 장애를 판단하고, Action/Reward 정책과 Python Validator를 거쳐 안전한 복구 Action만 실행하는 AIOps 연구 프로토타입**이다.

연구의 중심은 API 서버나 AI App 배포가 아니라, **Agent 기반 장애 감시, 복구 판단, 안전 검증, Kubernetes 실행, 결과 분석**이다.

```text
AIOpsLab / Chaos Mesh 장애 주입
-> Prometheus / Kubernetes 상태 관측
-> AI-MCMP Coordinator
-> 4-Agent 판단
-> Action / Reward 교차 검증
-> Python Validator
-> kubectl dry-run 또는 real 실행
-> 실행 결과 저장 및 정량 분석
```

## 연구 범위

| 구분 | 현재 처리 |
| --- | --- |
| 4-Agent 장애 판단 | 연구 본체 |
| Action/Reward 정책 | 연구 본체 |
| AIOpsLab / Chaos Mesh / Prometheus / Kubernetes 실험 | 연구 본체 |
| Python Validator | 기본 안전 검증기 |
| Agent Registry | Agent 역할과 허용 action 관리 |
| AutoGen GroupChat | structured multi-agent 보조 경로 |
| Go Guard | 선택적 이중 검증 모듈로 보관 |
| Ops LLM 선정, CPU/GPU VM 배치, Swagger/API | 별도 과제 성격의 보조/보관 기능 |

## 4-Agent 역할

| Agent | 역할 |
| --- | --- |
| `AIServiceHASupportAgent` | 서비스 장애 진단, 가용성 판단, 복구 필요성 평가 |
| `AIApplicationManagementAgent` | 복구 action 후보 제안, Kubernetes 제어 절차 관리 |
| `AISemiconductorInfraOpsAgent` | Kubernetes replica/deployment 안전성과 인프라 수용 가능성 검토 |
| `CostOptimizationAgent` | 비용 증가, 과잉 action, 비용 우선 정책 검토 |

Agent 등록 정보는 [config/agent_registry.json](config/agent_registry.json)에 있다.

## 빠른 시작

서버 기준 기본 실행:

```bash
cd ~/geonhae/aiops_research
git pull origin master
conda activate aiops_research
python -m pip install -e ".[dev,autogen]"
python -m pytest
```

로컬 Windows 기준 테스트:

```powershell
cd C:\Users\geonhae\Documents\aiops_research
python -m pytest
```

상세 설치와 실행 명령은 [docs/submission/execution_code_guide.md](docs/submission/execution_code_guide.md)에 정리되어 있다.

## 대표 실행

### Autonomous mock

실제 Kubernetes resource를 변경하지 않고, fake evidence 기반 폐루프 Agent 판단을 확인한다.

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

### Chaos Mesh real 실험

실제 장애 주입과 recovery action 비교 실험은 아래 문서를 따른다.

- [docs/experiments/recovery_action_experiment_guide.md](docs/experiments/recovery_action_experiment_guide.md)
- [docs/experiments/recovery_quantitative_analysis_guide.md](docs/experiments/recovery_quantitative_analysis_guide.md)

대표 실험 구성:

```text
4개 장애 x 3개 action x 3회 반복 = 36회
장애: pod-kill, cpu-stress, memory-stress, network-delay
Action: observe_only, rollout_restart, scale_out
```

## 문서 바로가기

| 목적 | 문서 |
| --- | --- |
| 핵심 제출 요약 | [docs/core_submission_summary.md](docs/core_submission_summary.md) |
| 전체 문서 지도 | [docs/README.md](docs/README.md) |
| 요구사항 정의서 | [docs/submission/requirements_definition.md](docs/submission/requirements_definition.md) |
| 설치 및 실행 가이드 | [docs/submission/install_and_run_guide.md](docs/submission/install_and_run_guide.md) |
| 실행 코드 설명서 | [docs/submission/execution_code_guide.md](docs/submission/execution_code_guide.md) |
| 시험 가이드 | [docs/submission/test_guide.md](docs/submission/test_guide.md) |
| Agent 등록 관리 | [docs/design/agent_registry_guide.md](docs/design/agent_registry_guide.md) |
| Action/Reward 정책 | [docs/design/agent_action_reward_policy.md](docs/design/agent_action_reward_policy.md) |
| Recovery 실험 | [docs/experiments/recovery_action_experiment_guide.md](docs/experiments/recovery_action_experiment_guide.md) |
| 정량 분석 | [docs/experiments/recovery_quantitative_analysis_guide.md](docs/experiments/recovery_quantitative_analysis_guide.md) |
| 보조/보관 기능 | [docs/archive/etri_extension.md](docs/archive/etri_extension.md) |

## 현재 연구 단계

현재 프로젝트는 단순 mock 예제가 아니라, 연구실 서버의 Kubernetes/Chaos Mesh/Prometheus 환경에서 real-mode 장애 실험과 정량 분석까지 수행한 **1차 연구 프로토타입**으로 정리한다.

다음 단계:

- Prometheus metric, log enrichment, full real-cluster evidence fusion
- AutoGen multi-round real action 선택
- single-agent baseline 비교
- Agent 제거 ablation 실험
- reward 민감도 및 action space 확장

초기의 `CPU 95%` 입력은 smoke test용이며, 현재 연구 결과의 중심은 Chaos Mesh/AIOpsLab 기반 실제 장애 실험이다.
