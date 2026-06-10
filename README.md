# AIOps 4-Agent Kubernetes 자동화 프로토타입

Kubernetes/AIOpsLab 환경에서 **AI 에이전트 레이어**를 검증하는
4-agent AIOps 자동 감시/관리 프로토타입입니다.

처음 보는 사람은 아래 문서를 먼저 보면 됩니다.

- 설치와 실행 가이드: [docs/install_and_run_guide.md](docs/install_and_run_guide.md)
- 초기 연구 검증 완료 정리: [docs/first_stage_research_completion.md](docs/first_stage_research_completion.md)

가장 많이 쓰는 실행 흐름은 아래와 같습니다.

| 목적 | 환경 | 명령 |
| --- | --- | --- |
| 우리 코드 테스트 | `aiops_research` | `python -m pytest` |
| Optional CPU 95% smoke test | `aiops_research` | `aiops-k8s-agents run ...` |
| AutoGen GroupChat | `aiops_research` | `aiops-k8s-agents autogen-run ...` |
| AIOpsLab 자동 detection | `aiopslab` | `bash scripts/server_aiopslab_auto_detection.sh` |
| AIOpsLab 반복 실험 | `aiopslab` | `RUNS=3 SLEEP_SECONDS=15 bash scripts/server_aiopslab_repeat_detection.sh` |
| Full-stack Chaos/Prometheus loop | `aiops_research` | `bash scripts/server_full_stack_feedback_loop.sh` |

중요한 점은 하나입니다.

```text
지금 저장소 = AIOpsLab 본 실험장이 아니라,
AIOpsLab에 붙일 4-agent Kubernetes 자동 제어 모듈
```

즉, 이 저장소의 목표는 **에이전트 판단 로직**, **명령어 생성**,
**명령어 안전 검증**, **AutoGen GroupChat 흐름**, **AIOpsLab 자동 detection
실험**을 한 프로젝트 안에서 검증하는 것입니다. 현재는 로컬 검증을 거쳐
연구실 서버 개인 kind 클러스터에서 AIOpsLab 공식 detection 문제까지 실행했습니다.

## 전체 연구 목표

이 연구의 최종 목표는 Kubernetes 기반 마이크로서비스 환경에서 장애나 과부하가
발생했을 때, 4개의 AI 에이전트가 서로 의견을 검토한 뒤 안전한 복구/최적화
명령을 자동으로 생성하고 실행하는 것입니다.

최종적으로 만들고 싶은 흐름은 아래와 같습니다.

```text
Prometheus metric / log / alert
-> 4-agent AutoGen GroupChat
-> action/reward 기반 합의
-> CommandValidator 안전 검증
-> kubectl 명령 생성
-> Kubernetes에서 복구/최적화 실행
-> 실행 결과를 다시 metric으로 관찰
```

## 그림의 두번째 부분을 파일에 넣는다는 의미

그림의 두번째 부분은 **AI 에이전트 레이어**입니다. 현재 저장소에 만든 파일들은
이미 이 부분을 구현하는 역할을 합니다.

전체 그림에 붙이면 구조는 이렇게 바뀝니다.

```text
기존 인프라만 있는 상태:
Prometheus / Kubernetes / Online Boutique

현재 만든 파일을 추가한 뒤:
Prometheus / Kubernetes / Online Boutique
-> 4-agent AI 판단 레이어
-> 안전 검증된 kubectl 명령 생성
-> Kubernetes 자원 제어
```

즉, 이 저장소는 AIOpsLab 위에서 직접 서비스를 띄우는 코드가 아니라,
**AIOpsLab에서 나온 metric과 alert를 보고 무엇을 실행할지 결정하는 두뇌 역할**을
합니다.

| 그림 요소 | 현재 파일/모듈 | 역할 |
| --- | --- | --- |
| AI-MCMP 통합 관리 에이전트 | `AIMCMPCoordinator`, `AutoGenGroupChatCoordinator` | 4개 에이전트 의견을 모아 최종 실행 여부 결정 |
| AI서비스 HA 지원 에이전트 | `AIServiceHASupportAgent` | 장애 위험을 보고 scale-out 같은 HA 복구 필요성 판단 |
| AI응용관리 자동화 에이전트 | `AIApplicationManagementAgent` | 실제 Kubernetes 응용 제어 액션 생성 |
| AI반도체 인프라 운용 자동화 에이전트 | `AISemiconductorInfraOpsAgent` | replica 증가가 인프라 자원 관점에서 가능한지 검토 |
| 비용 최적화 지원 에이전트 | `CostOptimizationAgent` | replica 증가가 비용 정책 안에 있는지 검토 |
| 최종 실행 액션 생성 | `ScaleAction`, `CommandValidator`, `KubernetesExecutor` | 안전한 `kubectl scale` 명령으로 변환하고 실행 |

4대 에이전트는 이제 연구 장표의 역할과 맞게 파일을 분리했습니다. 즉,
`agents.py`는 기존 import가 깨지지 않도록 남겨 둔 호환용 입구이고, 실제 판단
로직은 `ha_agent.py`, `application_agent.py`, `infra_agent.py`,
`cost_agent.py`, `coordinator.py`에 나뉘어 있습니다.

이렇게 해두면 CPU 95% 과부하 시나리오뿐 아니라, 연구실 서버에서 AIOpsLab을
붙인 뒤 memory, pod crash, latency, 비용 최적화 같은 시나리오가 늘어나도
각 에이전트 파일에 책임별로 액션/reward 정책을 추가할 수 있습니다.

따라서 두번째 사진 부분의 역할은 아래 한 문장으로 정리할 수 있습니다.

```text
Prometheus가 알려준 장애 상태를 4개 에이전트가 검토하고,
실행해도 안전한 Kubernetes 복구 명령으로 바꾸는 중간 판단 계층
```

## 현재 상태

| 구분 | 상태 |
| --- | --- |
| 4개 에이전트 판단 로직 | 완료 |
| action/reward 설계 | 완료 |
| AutoGen GroupChat 연결 | 완료 |
| kubectl 명령 생성/검증 | 완료 |
| kind dry-run 검증 | 완료 |
| Prometheus 입력 경로 검증 | 완료 |
| 로컬 kind real scale | 완료 |
| CI/CD 자동 테스트 | 완료 |
| AIOpsLab Hotel Reservation detection 반복 실험 | 완료 |
| 공용/full-scale Kubernetes 확장 실험 | 다음 단계 |

현재 로컬에서 확인한 대표 성공 명령은 아래입니다.

```powershell
kubectl scale deployment paymentservice --replicas=3 -n online-boutique
```

이 명령은 로컬 kind 클러스터에서 실제로 실행했고, `paymentservice`가 `3/3`
Running 상태가 되는 것까지 확인했습니다.

## 4개 에이전트 역할

| 에이전트 | 하는 일 |
| --- | --- |
| `AIServiceHASupportAgent` | 장애 위험을 보고 HA 복구 액션이 필요한지 판단 |
| `AIApplicationManagementAgent` | 실제 애플리케이션 제어 액션 생성 |
| `AISemiconductorInfraOpsAgent` | GPU/NPU/가속기 자원 여유가 있다고 보고 인프라 관점 검토 |
| `CostOptimizationAgent` | 비용 관점에서 실행해도 되는지 검토 |

CPU 95% synthetic alert는 현재 주 연구 장애가 아니라 optional smoke test입니다. 주 실험은 AIOpsLab/Chaos Mesh가 주입하는 실제 장애를 사용합니다. 이 smoke test의 최종 명령 예시는 아래입니다.

```powershell
kubectl scale deployment paymentservice --replicas=3 -n online-boutique
```

현재 action/reward 예시는 아래와 같습니다.

| 에이전트 | 대표 action | reward |
| --- | --- | ---: |
| `AIServiceHASupportAgent` | `ha_scale_out_required` | `+0.90` |
| `AIApplicationManagementAgent` | `app_scale_deployment` | `+0.85` |
| `AISemiconductorInfraOpsAgent` | `infra_capacity_approved` | `+0.70` |
| `CostOptimizationAgent` | `cost_budget_approved` | `+0.60` |

Optional CPU 95% smoke test에서는 총 reward가 `3.05`가 되고, 모든 에이전트가 승인하면
최종 scale 명령이 생성됩니다.

## 제일 중요한 실행 순서

Windows PowerShell에서 아래 순서만 기억하면 됩니다.

```powershell
python -m pytest
```

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_autogen_mock.ps1
```

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_autogen_dry_run.ps1
```

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_prometheus_autogen_local.ps1
```

마지막으로 실제 적용 상태를 확인합니다.

```powershell
kubectl get deployment paymentservice -n online-boutique
kubectl get pods -n online-boutique -l app=paymentservice
```

정상이면 `paymentservice`가 `3/3`이고 pod 3개가 `Running`이어야 합니다.

## CI/CD 자동 테스트

별도 운영/평가 연구 기능은 빼고, 프로젝트 안정성을 위한 CI/CD만 남겼습니다.
현재 남긴 자동화는 GitHub에 코드를 push하거나 pull request를 만들 때 테스트가 자동으로
돌아가게 하는 기능입니다.

| 구분 | 파일 | 의미 |
| --- | --- | --- |
| CI/CD | `.github/workflows/ci.yml` | GitHub push/PR 때 자동으로 Python 패키지 설치, `pytest`, CLI 설치 확인 실행 |

즉, 이 프로젝트의 중심은 여전히 4-agent AIOps 자동 제어이고, CI/CD는 코드가
깨졌는지 자동으로 확인하는 보조 장치입니다.

로컬에서 같은 검증을 직접 하려면 아래 명령만 실행하면 됩니다.

```powershell
python -m pytest
```

## 서버 개인용 kind 통합 실험

관리자 kubeconfig가 없어도 연구실 서버 안에 개인용 kind 클러스터를 만들면 아래
범위까지는 연구 실험으로 진행할 수 있습니다.

```text
개인용 kind Kubernetes
-> paymentservice deployment
-> Prometheus API
-> 4-agent 판단 및 reward 합의
-> kubectl dry-run / real scale
-> Chaos Mesh pod-kill 장애 주입
-> Kubernetes 복구 상태 확인
```

현재 이 단계에서 확인할 수 있는 연구 증거는 다음과 같습니다.

| 증거 | 의미 |
| --- | --- |
| `python -m pytest` 통과 | 서버에서도 코드가 정상 동작 |
| `feedback-loop` 리포트 | Prometheus 입력, 에이전트 판단, 명령어, reward, pod 상태 저장 |
| `deployment.apps/paymentservice scaled` | 실제 Kubernetes scale 실행 |
| PodChaos 적용 후 새 pod 생성 | Chaos Mesh 장애 주입과 Kubernetes 복구 확인 |

서버에서 반복 실험을 실행할 때는 아래 스크립트를 사용할 수 있습니다.

```bash
bash scripts/server_kind_status.sh
```

```bash
bash scripts/server_feedback_loop.sh
```

AutoGen까지 포함한 피드백 루프는 아래처럼 실행합니다.

```bash
USE_AUTOGEN=1 ITERATIONS=3 INTERVAL_SECONDS=10 bash scripts/server_feedback_loop.sh
```

pod kill 장애 주입 실험은 아래처럼 실행합니다.

```bash
bash scripts/server_chaos_pod_kill_once.sh
```

`feedback-loop`는 각 반복마다 Kubernetes 상태와 에이전트 실행 결과를 JSON으로
저장합니다. 기본 저장 위치는 `runs/`입니다.

## 헷갈리면 이것만 구분하기

| 용어 | 뜻 |
| --- | --- |
| `mock` | Kubernetes 없이 명령어가 맞는지만 확인 |
| `dry-run` | Kubernetes API에 검증만 요청하고 실제 실행은 안 함 |
| `local real` | 내 PC의 kind 클러스터에 실제 scale 실행 |
| `server real` | 연구실 서버의 AIOpsLab 환경에서 실제 실행 |

항상 이 순서를 지킵니다.

```text
mock -> dry-run -> local real -> 서버 dry-run -> 서버 real
```

## AIOpsLab은 언제 쓰나?

이제 AIOpsLab 본 실험까지 연결했습니다.

현재 서버 개인 kind 클러스터에서 AIOpsLab 공식 Hotel Reservation detection 문제를
실행했고, 사람이 직접 입력하던 `get_logs -> get_metrics -> submit` 흐름을
AI-MCMP 4-agent 정책으로 자동화했습니다.

```text
AIOpsLab 설치
-> Hotel Reservation 서비스 배포
-> AIOpsLab 장애 주입
-> 4-agent가 logs/metrics 관찰
-> action/reward 합의
-> Referee가 AIOpsLab API call 검증
-> submit("Yes") 또는 submit("No") 자동 제출
-> AIOpsLab 평가 결과 저장
```

## 서버에서 완료한 일과 다음 확장

연구실 서버에서는 기존 공용 Kubernetes 설정을 건드리지 않고, 개인 kind 클러스터를
만들어 안전하게 실험했습니다.

| 단계 | 상태 | 목표 |
| --- | --- | --- |
| 1 | 완료 | Python/conda 환경 구성 |
| 2 | 완료 | 개인 kind 클러스터 생성 |
| 3 | 완료 | Optional CPU 95% smoke test로 scale action 검증 |
| 4 | 완료 | Prometheus / Chaos Mesh 기본 실험 |
| 5 | 완료 | AIOpsLab Hotel Reservation detection 자동 실행 |
| 6 | 완료 | AIOpsLab 반복 실험 결과표 생성 |
| 7 | 다음 단계 | 다른 AIOpsLab problem family로 확장 |
| 8 | 다음 단계 | baseline 비교와 통계 분석 |

서버 실험에서도 real action으로 바로 가지 않고, 아래 순서를 기준으로 검증했습니다.

```text
서버 mock -> 서버 dry-run -> 서버 real
```

## 다음 확장 성공 기준

현재 초기 검증 이후, 공용/full-scale Kubernetes 환경으로 확장할 때 확인해야 하는 목표는 아래입니다.

| 목표 | 성공 기준 |
| --- | --- |
| 장애 감지 | Prometheus/alert 입력이 4-agent 시스템으로 들어옴 |
| 에이전트 합의 | 4개 에이전트가 action/reward를 내고 최종 합의함 |
| 안전 검증 | allowlist와 validator를 통과한 명령만 실행됨 |
| 자동 복구 | 과부하/장애 상황에서 replica scale-out 등 복구 액션 수행 |
| 결과 관찰 | 실행 후 pod 상태, metric, 복구 시간을 기록 |
| 연구 증거 | mock/dry-run/real 결과 JSON과 metric 로그를 실험 결과로 저장 |

최종 논문/보고서에서는 아래 흐름을 증명하는 것이 핵심입니다.

```text
장애 주입
-> metric 변화 감지
-> 4-agent 판단 및 reward 합의
-> 안전한 Kubernetes 명령 생성
-> 실제 복구 실행
-> 복구 시간/자원 사용량/비용 변화 분석
```

## 자세한 문서

- 전체 실행 명령어: [docs/experiment_commands.md](docs/experiment_commands.md)
- 설치와 실행 가이드: [docs/install_and_run_guide.md](docs/install_and_run_guide.md)
- action/reward 설계: [docs/agent_action_reward_policy.md](docs/agent_action_reward_policy.md)
- 교수님 참고 PPT 반영 항목: [docs/research_reference_integration.md](docs/research_reference_integration.md)
- 초기 연구 검증 완료 정리: [docs/first_stage_research_completion.md](docs/first_stage_research_completion.md)
- AutoGen 설명: [docs/autogen_groupchat.md](docs/autogen_groupchat.md)
- 서버 이관 절차: [docs/server_migration_runbook.md](docs/server_migration_runbook.md)

## 최신 단계: AIOpsLab 자동 detection 연결

현재 프로젝트는 서버 개인 kind 클러스터에서 AIOpsLab 공식 Hotel Reservation detection 문제를 실행한 뒤,
사람이 직접 입력하던 `get_logs -> get_metrics -> submit` 흐름을 AI-MCMP 4-agent 정책으로 자동화하는
runner를 포함합니다.

서버에서 실행:

```bash
cd ~/geonhae/aiops_research
conda activate aiopslab
git pull origin master
export PATH="$HOME/bin:$PATH"
export KUBECONFIG=~/geonhae/kubeconfigs/kind-geonhae-aiops.yaml
bash scripts/server_aiopslab_auto_detection.sh
```

반복 실험과 결과표 생성:

```bash
RUNS=3 SLEEP_SECONDS=15 bash scripts/server_aiopslab_repeat_detection.sh
```

성공 기준:

```text
Correct detection: Yes
Detection Accuracy: Correct
Saved report: .../runs/<timestamp>_aiopslab_auto_detection.json
runs/aiopslab_detection_summary.md
runs/aiopslab_detection_summary.csv
```

2026-06-09 서버 반복 실험 요약:

```text
total_runs: 12
correct_runs: 12
metric_success_runs: 11
average_ttd_seconds: 4.117
average_steps: 3.000
average_final_reward: 3.100
```

## Full-stack 확장 실험

다음 확장 단계로 `minimal`, `AIOpsLab`, `full-stack`을 분리해서 운영할 수 있게 했습니다.

```text
minimal = 빠른 sanity check
AIOpsLab = 공식 benchmark 검증
full-stack = 장애/metric/action 변수를 바꾸는 확장 실험
```

새로 추가된 full-stack 구성:

- `kube-prometheus-stack`
- Online Boutique 전체 서비스
- Chaos Mesh `pod-kill`, `cpu-stress`, `memory-stress`, `network-delay`
- 4-agent feedback loop
- 실험 변수 매트릭스: `config/full_stack_experiments.json`

서버에서 시작:

```bash
cd ~/geonhae/aiops_research
conda activate aiops_research
git pull origin master
python -m pip install -e ".[dev,autogen]"

export PATH="$HOME/bin:$PATH"
export KUBECONFIG=~/geonhae/kubeconfigs/kind-geonhae-aiops.yaml

bash scripts/server_full_stack_setup.sh
```

실험 매트릭스 확인:

```bash
aiops-k8s-agents list-full-stack-experiments \
  --config config/full_stack_experiments.json
```

자세한 실행 순서는 [docs/full_stack_experiment_guide.md](docs/full_stack_experiment_guide.md)를 보면 됩니다.

## 최종 real 검증과 결과 요약

개인 kind 클러스터에서만 실행합니다. 아래 명령은 네 장애 시나리오를 실제
`kubectl scale` 모드로 실행하고, 각 시나리오 전후 replica를 1로 초기화합니다.

```bash
cd ~/geonhae/aiops_research
git pull origin master
conda activate aiops_research
python -m pip install -e ".[dev,autogen]"

export PATH="$HOME/bin:$PATH"
export KUBECONFIG=~/geonhae/kubeconfigs/kind-geonhae-aiops.yaml

CONFIRM_REAL_RUN=YES \
ITERATIONS=3 \
bash scripts/server_finalize_research.sh
```

AutoGen과 기본 모델 `gpt-5.5`를 사용한 최종 검증은 다음처럼 실행합니다.

```bash
CONFIRM_REAL_RUN=YES \
USE_AUTOGEN=1 \
ITERATIONS=3 \
bash scripts/server_finalize_research.sh
```

결과는 실행 시각별 폴더에 저장됩니다.

```text
runs/final-real/<실행시각>/final_summary.md
runs/final-real/<실행시각>/final_summary.csv
```

`final_summary.md`에서 다음 조건이 모두 확인되면 구현 검증을 완료한 것으로 봅니다.

- 네 시나리오 모두 `passed == iterations`
- `total_failed == 0`
- `real_scale_verified_scenarios == 4`
- 각 시나리오의 replica 변화가 `1 -> 3`
