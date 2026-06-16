# Go 개발 및 2종 LLM 교차 검증 설계

이 문서는 기존 AIOps 4-Agent 연구를 다음 요구사항에 맞게 확장한 내용을 정리합니다.

- Go 언어 개발 필수
- 최소 2종 이상 LLM 또는 코딩 에이전트 활용 필수
- 생성된 Kubernetes 제어 action에 대한 교차 검증 필수

## 1. 왜 Go 계층을 추가했는가

기존 구조에서는 Python 기반 4-Agent가 장애 상태를 보고 action을 판단하고, Python validator가 `kubectl` 명령을 검증했습니다.

이번 변경에서는 최종 Kubernetes 실행 직전에 Go 기반 `aiops-guard`를 추가했습니다.

```text
Prometheus / AIOpsLab / Chaos Mesh
-> Python 4-Agent 판단
-> Action / Reward 계산
-> Python Validator 1차 검증
-> Go aiops-guard 2차 검증
-> kubectl mock / dry-run / real 실행
-> Kubernetes 상태 재관측
```

Go 계층의 역할은 LLM 또는 Python 코드가 만든 결과를 그대로 믿지 않고, 별도의 언어와 별도의 실행 바이너리에서 다시 검증하는 것입니다.

## 2. Python과 Go의 역할 분리

| 계층 | 구현 언어 | 역할 |
| --- | --- | --- |
| 관측 및 실험 오케스트레이션 | Python | Prometheus, AIOpsLab, Chaos Mesh, 반복 실험 실행 |
| 4-Agent 판단 | Python / AutoGen | HA, 응용관리, 인프라, 비용 관점의 action 평가 |
| Reward 비교 | Python | 장애별 후보 action 점수화 및 정책별 선택 |
| 1차 안전 검증 | Python | namespace, deployment, replicas, mode 검증 |
| 2차 안전 검증 및 실행 | Go | 구조화 action 재검증, kubectl 명령 렌더링, mock/dry-run/real 실행 |

이 구조에서 Go는 전체 연구를 대체하는 언어가 아니라, 최종 제어 명령의 안전성과 재현성을 담당하는 작은 핵심 모듈입니다.

## 3. Go aiops-guard 입력 계약

Go guard는 LLM 자유 텍스트를 직접 받지 않습니다. 반드시 구조화된 JSON action만 받습니다.

```json
{
  "mode": "mock",
  "namespace": "online-boutique",
  "deployment": "paymentservice",
  "action": "scale_out",
  "replicas": 3,
  "allowed_namespaces": ["online-boutique"],
  "allowed_deployments": ["paymentservice", "checkoutservice"],
  "min_replicas": 1,
  "max_replicas": 5
}
```

현재 허용 action은 다음 3개입니다.

| action | kubectl 명령 |
| --- | --- |
| `observe_only` | `kubectl get deployment <deployment> -n <namespace>` |
| `rollout_restart` | `kubectl rollout restart deployment <deployment> -n <namespace>` |
| `scale_out` | `kubectl scale deployment <deployment> --replicas=<N> -n <namespace>` |

`dry-run` 모드에서는 변경성 action에 `--dry-run=server`를 추가합니다.

## 4. Go 계층의 안전 정책

`aiops-guard`는 다음 조건을 통과하지 못하면 실제 실행을 하지 않습니다.

| 검증 항목 | 목적 |
| --- | --- |
| mode allowlist | `mock`, `dry-run`, `real` 외 실행 차단 |
| action allowlist | 삭제, namespace 변경 등 위험 action 차단 |
| Kubernetes 이름 규칙 | 이상한 namespace/deployment 문자열 차단 |
| namespace allowlist | 허용된 namespace 외 접근 차단 |
| deployment allowlist | 허용된 service 외 제어 차단 |
| replica 범위 | 과도한 scale-out 방지 |
| mock 실행 차단 | mock에서는 `kubectl` runner 호출 자체를 하지 않음 |

## 5. 실행 방법

```bash
cd go/aiops-guard
go test ./...
go run ./cmd/aiops-guard --input ../../examples/go_guard_scale_action.json
```

예상 출력:

```json
{
  "command": "kubectl scale deployment paymentservice --replicas=3 -n online-boutique",
  "mode": "mock",
  "valid": true,
  "stdout": "mock: command validated and not executed",
  "stderr": ""
}
```

## 6. 2종 LLM 또는 코딩 에이전트 교차 검증 방식

연구 요구사항에서 말하는 “최소 2종 이상 LLM 활용”은 단순히 모델 이름을 두 개 적는 것이 아니라, 같은 action을 서로 다른 에이전트가 독립적으로 검토하게 만드는 방식으로 해석하는 것이 안전합니다.

권장 구조는 다음과 같습니다.

```text
LLM / Coding Agent A
-> 4-Agent policy와 Python runner 구현

LLM / Coding Agent B
-> Go aiops-guard와 JSON 계약 독립 검토
-> allowlist 우회 가능성 확인
-> real mode 실행 안전성 확인
-> Python validator 결과와 Go guard 결과 비교
```

현재 저장소에는 2차 검증을 수행할 수 있는 Go 검증 대상과 체크리스트가 준비되어 있습니다. 다만 실제로 다른 LLM 또는 다른 코딩 에이전트가 리뷰를 수행하기 전까지는 “2종 LLM 검증 완료”라고 쓰면 안 됩니다.

## 7. 2차 코딩 에이전트 검증 체크리스트

다른 LLM 또는 코딩 에이전트에게 다음 항목을 그대로 검토시키면 됩니다.

```text
다음 저장소의 Go aiops-guard와 Python validator를 교차 검증해줘.

검토 대상:
- go/aiops-guard/internal/guard/guard.go
- go/aiops-guard/internal/guard/guard_test.go
- src/aiops_k8s_agents/validator.py
- src/aiops_k8s_agents/executor.py
- examples/go_guard_scale_action.json

검토 질문:
1. allowlist를 우회해서 다른 namespace나 deployment를 제어할 수 있는가?
2. real mode에서 validator 실패 action이 실행될 가능성이 있는가?
3. dry-run mode에서 변경성 kubectl 명령이 실제로 실행될 위험이 있는가?
4. Python validator와 Go guard의 허용 action 범위가 충돌하지 않는가?
5. replica 범위 검증이 양쪽에서 일관적인가?
6. Go 테스트에 빠진 위험 케이스가 있는가?
7. 연구 발표에서 과장하면 안 되는 부분은 무엇인가?
```

## 8. 현재 상태와 남은 일

| 항목 | 상태 |
| --- | --- |
| Go 안전 실행 모듈 추가 | 완료 |
| Go 단위 테스트 추가 | 완료 |
| GitHub Actions에서 Go 테스트 실행 | 완료 |
| JSON action 계약 예시 추가 | 완료 |
| 2종 LLM 검증 절차 문서화 | 완료 |
| 실제 두 번째 LLM/코딩 에이전트 리뷰 수행 | 미완료 |
| Python runner가 Go guard를 자동 호출하도록 통합 | 다음 단계 |

정리하면, 이번 변경은 연구 방향을 “Python만으로 만든 AIOps prototype”에서 “Python 4-Agent 판단 + Go 안전 실행 계층 + 2종 코딩 에이전트 교차 검증 가능한 구조”로 확장한 것입니다.
