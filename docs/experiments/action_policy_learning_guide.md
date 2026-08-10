# Action Policy Learning Guide

이 문서는 기존 4-Agent Kubernetes 장애 복구 실험에 선택적으로 추가된
Action Policy 기능의 사용법과 연구 범위를 설명한다.

## 연구 위치

Action Policy는 새로운 실행기가 아니다. 기존의 bounded action 후보를
실험 결과의 post-run reward로 순위화하는 advisory policy다.

```text
Evidence
  -> 4-Agent 판단 및 상호검토
  -> Action Policy 추천 순위 참고
  -> Python Validator / Go Guard
  -> Kubernetes 실행
  -> Recovery Evaluator Agent
  -> policy sample 저장
```

추천 결과는 실행 명령을 직접 만들거나 안전 검증을 우회하지 않는다.
실제 실행은 기존 Coordinator, Validator, allowlist, replica limit의
경계를 그대로 따른다.

## 정책 모드

| 모드 | 역할 | 연구 해석 |
| --- | --- | --- |
| `baseline` | `agent_decision_policy.json`의 원래 cause-action 규칙 | 기준선 |
| `learned` | 완료된 측정 결과에서 action별 경험적 평균 reward를 계산 | 선택 정책 비교 |

현재 `learned`는 PPO나 online reinforcement learning이 아니다. 우선
재현 가능한 offline contextual policy ranking으로 구현했다. 따라서
모델이 실행 중에 무제한으로 정책을 바꾸지 않으며, 관측된 안전하고
측정 가능한 결과만 학습 샘플로 사용한다.

## 1. 정책 데이터셋 생성

복구 실험 결과 JSONL을 정책 샘플 JSONL로 변환한다.

```bash
aiops-k8s-agents build-action-policy-dataset \
  --input runs/recovery-action-pilot/<run>/outcomes.jsonl \
  --output runs/action-policy/<run>/policy_samples.jsonl
```

각 샘플에는 `scenario`, `metric`, `cause`, `action`,
`observed_reward`, `recovery_success`, `safety_valid`,
`measurement_valid`, `eligible`가 저장된다.

`eligible`는 다음 조건을 모두 만족해야 한다.

- action이 `observe_only`, `rollout_restart`, `scale_out` 중 하나다.
- safety validation이 성공했다.
- 측정 결과가 유효하다.
- scenario가 등록되어 있다.

## 2. Baseline 추천

```bash
aiops-k8s-agents recommend-action \
  --mode baseline \
  --scenario cpu-stress \
  --metric cpu \
  --cause cpu_saturation
```

## 3. Learned 추천

```bash
aiops-k8s-agents recommend-action \
  --mode learned \
  --samples runs/action-policy/<run>/policy_samples.jsonl \
  --scenario cpu-stress \
  --metric cpu \
  --cause cpu_saturation
```

출력에는 `selected_action`, `ranking`, `training_samples`,
`fallback_reason`, `advisory_only`, `safety_boundary`가 포함된다.
학습 샘플이 없거나 해당 context를 관측하지 못한 경우 baseline action으로
돌아가며, 출력의 `fallback_reason`으로 이를 확인할 수 있다.

## 4. 웹 연구 콘솔

복구 실험의 고급 설정에서 `Baseline Policy` 또는
`Learned Policy (advisory)`를 선택할 수 있다. 웹 요청에는
`action_policy`가 포함되고, 최종 runtime report의
`action_policy_recommendation`에 추천 결과가 기록된다.

웹에서 learned policy의 샘플 파일을 사용하려면 서버 실행 전에 다음
환경 변수를 설정한다.

```bash
export AIOPS_ACTION_POLICY_SAMPLES=/absolute/path/to/policy_samples.jsonl
```

환경 변수가 없으면 learned mode도 안전하게 빈 학습 데이터 fallback으로
동작한다. 이때 실험은 실패하지 않으며 `training_samples: 0`과
`fallback_reason: "no eligible training samples"`가 기록된다.

## 연구상 주의점

- Mock 결과는 Kubernetes real-cluster evidence가 아니다.
- Reward는 Recovery Evaluator Agent의 post-run 평가값을 우선 사용한다.
- Learned 추천과 실제 선택/실행 action을 결과에서 분리해서 분석한다.
- 논문 비교에서는 policy mode, sample count, scenario, controller,
  execution mode, safety validity를 함께 보고한다.
- 다음 단계에서 필요하면 action 후보 확대, confidence bound, offline
  policy evaluation, 이후에만 제한적인 online RL을 별도 실험으로 추가한다.
