# AIOps 4-Agent Kubernetes 자동화 프로토타입

교수님이 제안하신 구조에서 **AI 에이전트 레이어**를 로컬에서 먼저 검증하는
프로토타입입니다.

중요한 점은 하나입니다.

```text
지금 저장소 = AIOpsLab 본 실험장이 아니라,
AIOpsLab에 붙일 4-agent Kubernetes 자동 제어 모듈
```

즉, 지금 목표는 큰 서버 없이도 먼저 **에이전트 판단 로직**, **명령어 생성**,
**명령어 안전 검증**, **AutoGen GroupChat 흐름**을 로컬에서 검증하는 것입니다.
나중에 연구실 고성능 서버가 준비되면 같은 코드를 AIOpsLab 환경으로 옮겨
풀스케일 실험을 진행합니다.

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
| AIOpsLab 풀스케일 서버 실험 | 서버 확보 후 진행 |

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

현재 CPU 95% 시나리오의 최종 명령은 아래입니다.

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

CPU 95% 상황에서는 총 reward가 `3.05`가 되고, 모든 에이전트가 승인하면
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

아직 AIOpsLab 본 실험은 하지 않았습니다.

지금은 AIOpsLab에 붙일 **에이전트 제어 엔진**을 만든 단계입니다. 연구실 서버가
준비되면 아래 순서로 연결합니다.

```text
AIOpsLab 설치
-> Online Boutique 배포
-> Chaos Mesh 장애 주입
-> Prometheus metric 수집
-> 4-agent 시스템에 metric 전달
-> 검증된 kubectl 명령 real 실행
```

## 큰 서버로 옮긴 뒤 할 일

연구실 고성능 Ubuntu 서버가 준비되면 로컬에서 만든 코드를 그대로 옮기고,
실험 대상을 가벼운 kind 검증 환경에서 AIOpsLab 풀스케일 환경으로 바꿉니다.

| 단계 | 서버에서 할 일 | 목표 |
| --- | --- | --- |
| 1 | Python 환경과 패키지 설치 | 로컬 코드가 서버에서도 실행되는지 확인 |
| 2 | AIOpsLab 설치 | 실제 연구 실험장 준비 |
| 3 | Online Boutique 전체 배포 | 마이크로서비스 대상 시스템 구성 |
| 4 | Prometheus 연결 | 실제 metric/log/alert 수집 |
| 5 | Chaos Mesh 연결 | 장애를 의도적으로 주입 |
| 6 | `mock` 실행 | 서버에서도 에이전트 판단이 같은지 확인 |
| 7 | `dry-run` 실행 | 서버 Kubernetes API에서 명령 호환성 확인 |
| 8 | `real` 실행 | 검증된 명령으로 실제 복구/최적화 수행 |

서버에서도 바로 `real`로 가지 않고, 반드시 아래 순서를 지킵니다.

```text
서버 mock -> 서버 dry-run -> 서버 real
```

## 최종 성공 기준

큰 서버에서 최종적으로 확인해야 하는 목표는 아래입니다.

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
- action/reward 설계: [docs/agent_action_reward_policy.md](docs/agent_action_reward_policy.md)
- AutoGen 설명: [docs/autogen_groupchat.md](docs/autogen_groupchat.md)
- 서버 이관 절차: [docs/server_migration_runbook.md](docs/server_migration_runbook.md)
