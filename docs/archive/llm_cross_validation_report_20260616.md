# 2종 LLM / 코딩 에이전트 교차 검증 결과

일자: 2026-06-16

대상:

- `go/aiops-guard/internal/guard/guard.go`
- `go/aiops-guard/internal/guard/guard_test.go`
- `go/aiops-guard/cmd/aiops-guard/main.go`
- `examples/go_guard_scale_action.json`
- `src/aiops_k8s_agents/validator.py`
- `src/aiops_k8s_agents/executor.py`

## 1. 검증 목적

기존 AIOps 4-Agent 구조에 대해 다음 요구사항을 만족하는지 확인했습니다.

- Go 언어 기반 안전 실행 계층이 실제로 존재하는가
- Python validator와 Go guard가 같은 Kubernetes action 계약을 검증하는가
- 최소 2종 이상의 LLM/코딩 에이전트가 독립적으로 교차 검증했는가
- 위험한 `kubectl` action이 allowlist와 action policy를 우회할 수 없는가

## 2. 사용한 코딩 에이전트

| 구분 | 모델 / 역할 | 검증 방식 |
| --- | --- | --- |
| Reviewer A | `gpt-5.4` coding agent | Go guard와 Python validator의 보안·계약 불일치 검토 |
| Reviewer B | `gpt-5.4-mini` coding agent | 동일 범위에 대해 독립 검토, Reviewer A 결과 미참조 |

두 리뷰어는 파일을 수정하지 않고 read-only 방식으로 독립 검토했습니다.

## 3. 1차 리뷰 결과

두 리뷰어 모두 최종 verdict를 `CONCERNS`로 보고했습니다.

### 공통 지적 1: `observe_only` 명령 계약 불일치

Python은 다음 명령을 사용했습니다.

```bash
kubectl get deployment paymentservice -n online-boutique -o json
```

Go guard는 다음 명령을 사용했습니다.

```bash
kubectl get deployment paymentservice -n online-boutique
```

문제:

- Python 경로는 JSON 출력을 기대합니다.
- Go 경로는 사람이 읽는 표 형태 출력을 반환합니다.
- 같은 action을 두 언어가 다르게 렌더링하므로 교차 검증 결과가 흔들릴 수 있습니다.

수정:

- Go `observe_only` 렌더링을 Python과 동일하게 `-o json` 포함으로 변경했습니다.
- Go 테스트 기대값도 `-o json` 포함으로 수정했습니다.

### 공통 지적 2: non-scale action에서 `replicas` 처리 불일치

Python validator는 `scale_out`이 아닌 action에 `replicas`가 들어오면 거부했습니다.

Go guard는 `observe_only`, `rollout_restart`에 `replicas`가 들어와도 통과시켰습니다.

문제:

- 구조화 action 계약이 모호해집니다.
- LLM이 잘못 섞은 action을 한쪽 validator만 통과시키는 문제가 생깁니다.

수정:

- Go guard도 `observe_only`, `rollout_restart`에 `replicas`가 존재하면 거부하도록 변경했습니다.
- Go 테스트 `TestRejectsReplicasOnNonScaleActions`를 추가했습니다.

### 공통 지적 3: Python이 Go recovery/dry-run 명령을 충분히 검증하지 못함

기존 Python `validate_command`는 scale 명령 중심이었습니다.

문제:

- Go guard가 생성하는 `observe_only`, `rollout_restart`, `dry-run` 명령을 Python 쪽에서 다시 검증하기 어렵습니다.
- “Python validator + Go guard”의 양방향 교차 검증 범위가 scale-out에 치우칩니다.

수정:

- Python에 `validate_recovery_command`를 추가했습니다.
- 다음 명령을 구조화 action으로 역변환하여 검증할 수 있게 했습니다.

```bash
kubectl get deployment paymentservice -n online-boutique -o json
kubectl rollout restart deployment paymentservice -n online-boutique --dry-run=server
kubectl scale deployment paymentservice --replicas=3 -n online-boutique --dry-run=server
```

## 4. 수정 후 교차 검증 구조

현재 구조는 다음과 같습니다.

```text
Python 4-Agent
-> RecoveryAction 생성
-> Python validator 1차 검증
-> Go aiops-guard 2차 검증 및 kubectl 명령 렌더링
-> Python validate_recovery_command로 Go 명령 재검증 가능
-> mock / dry-run / real 실행
```

이제 Python과 Go가 같은 action 계약을 기준으로 다음 항목을 모두 검사합니다.

| 검증 항목 | Python | Go |
| --- | --- | --- |
| namespace allowlist | 지원 | 지원 |
| deployment allowlist | 지원 | 지원 |
| Kubernetes 이름 규칙 | 지원 | 지원 |
| `scale_out` replica 범위 | 지원 | 지원 |
| non-scale action의 replica 거부 | 지원 | 지원 |
| `observe_only` JSON 출력 계약 | 지원 | 지원 |
| dry-run server flag 검증 | 지원 | 지원 |

## 5. 추가된 테스트

Python:

- `test_validates_recovery_commands_from_go_guard`
- `test_rejects_recovery_commands_that_drift_from_go_contract`

Go:

- `TestRejectsReplicasOnNonScaleActions`
- `TestRolloutRestartDryRunCommand`
- 기존 `TestObserveOnlyRendersReadOnlyKubectlCommand`를 `-o json` 기준으로 수정

## 6. 검증 상태

로컬 Windows 환경:

```text
python -m pytest tests\test_validator.py tests\test_executor.py
26 passed
```

주의:

- 현재 로컬 Windows 환경에는 Go toolchain이 없어 `go test`를 직접 실행하지 못했습니다.
- 서버 `aiops_research` conda 환경에는 Go가 설치되어 있으므로, 서버에서 `go test ./...`를 다시 실행해야 합니다.

서버 검증 명령:

```bash
cd ~/geonhae/aiops_research
git pull origin master

cd go/aiops-guard
go test ./...
go run ./cmd/aiops-guard --input ../../examples/go_guard_scale_action.json
```

## 7. 현재 결론

이번 교차 검증은 단순한 형식 검토가 아니라, 두 독립 코딩 에이전트가 실제 계약 불일치를 찾아냈고, 그 결과를 코드와 테스트에 반영한 검증입니다.

따라서 현재 상태는 다음처럼 표현할 수 있습니다.

> 본 연구는 Python 기반 4-Agent 판단 계층과 Go 기반 Kubernetes action guard를 분리하여 구현했으며, 서로 다른 2종 코딩 에이전트의 독립 리뷰를 통해 Python-Go action 계약 불일치를 발견하고 수정하였다. 이를 통해 LLM 기반 action 생성 결과를 다중 언어·다중 에이전트 방식으로 교차 검증할 수 있는 구조를 확보하였다.

아직 남은 일:

- Python runner가 Go guard를 자동 호출하도록 완전 통합
- 서버에서 수정 후 Go 테스트 재실행
- GitHub Actions에서 Python + Go CI 결과 확인
