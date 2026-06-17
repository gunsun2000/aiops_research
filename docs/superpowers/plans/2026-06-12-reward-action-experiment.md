# Reward Sensitivity and Recovery Action Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chaos Mesh 실제 장애 4종에 대해 복구 action별 실측 성능을 비교하고, reward 가중치 변화가 최종 action 선택에 미치는 영향을 재현 가능한 형태로 평가한다.

**Architecture:** 기존 deterministic 4-Agent 및 AutoGen 코드는 유지한다. 별도의 recovery experiment 계층에서 허용된 `observe`, `rollout_restart`, `scale_out` action을 안전하게 실행하고, 실행 전후의 Kubernetes 상태와 장애별 metric을 `RecoveryOutcome`으로 저장한다. Reward 정책은 이 실측 outcome을 입력으로 후보 action을 순위화하며, action 선택에 사용한 predicted score와 실제 outcome score를 분리한다.

**Tech Stack:** Python 3.11+, dataclasses, argparse, pytest, kubectl, Prometheus HTTP API, Chaos Mesh, Bash

---

### Task 1: Recovery action domain model

**Files:**
- Create: `src/aiops_k8s_agents/recovery_experiments.py`
- Test: `tests/test_recovery_experiments.py`

- [ ] Define `RecoveryActionKind`, `RecoveryAction`, `RecoveryOutcome`, `RewardWeights`, `ActionEvaluation`.
- [ ] Define the fixed policies `balanced`, `ha_first`, `cost_first`, and `infra_first`.
- [ ] Reject weights that are negative or do not sum to 1.0.
- [ ] Verify the new model tests fail before implementation and pass afterward.

### Task 2: Safe observe, restart, and scale execution

**Files:**
- Modify: `src/aiops_k8s_agents/validator.py`
- Modify: `src/aiops_k8s_agents/executor.py`
- Modify: `src/aiops_k8s_agents/models.py`
- Test: `tests/test_validator.py`
- Test: `tests/test_executor.py`

- [ ] Write failing tests for allowlist validation of restart and observe actions.
- [ ] Write failing tests for exact restart rendering and mock/dry-run/real argv.
- [ ] Add structured `RestartAction` and `ObserveAction`; never accept free-form shell text.
- [ ] Add executor methods that emit only bounded kubectl templates.
- [ ] Run focused tests and the existing validator/executor regression tests.

### Task 3: Outcome-based reward scoring and action ranking

**Files:**
- Modify: `src/aiops_k8s_agents/recovery_experiments.py`
- Test: `tests/test_recovery_experiments.py`

- [ ] Score HA from recovery success and availability recovery.
- [ ] Score application management from metric recovery and normalized recovery time.
- [ ] Score infrastructure from replica/resource overhead.
- [ ] Score cost from action and replica overhead.
- [ ] Apply a blocking safety penalty when validation fails.
- [ ] Rank candidates deterministically by total score, then lower resource cost, then action name.
- [ ] Prove with tests that changing reward policies can change the selected action for the same measured outcomes.

### Task 4: CLI for bounded action execution and offline scoring

**Files:**
- Modify: `src/aiops_k8s_agents/cli.py`
- Test: `tests/test_cli.py`

- [ ] Add `execute-recovery-action` for one structured action in `mock`, `dry-run`, or `real` mode.
- [ ] Add `score-recovery-experiments` to read pilot JSONL and emit JSON, CSV, and Markdown policy comparisons.
- [ ] Include scenario, repetition, action, outcome components, selected policy, and total score in the output.
- [ ] Verify invalid action kinds and non-allowlisted targets are rejected.

### Task 5: Chaos Mesh pilot runner

**Files:**
- Create: `scripts/server_recovery_action_pilot.sh`
- Create: `config/recovery_action_experiments.json`
- Test: `tests/test_recovery_action_runner.py`

- [ ] Fix the experiment matrix to four faults, three actions, and configurable repetitions.
- [ ] Reset the deployment before every treatment.
- [ ] Apply one Chaos Mesh manifest, wait for the fault window, execute one bounded action, poll outcome, delete chaos, and reset again.
- [ ] Store one JSONL record per treatment under `runs/recovery-action-pilot/`.
- [ ] Record timestamps, metric before/after, deployment/pod before/after, recovery seconds, replica delta, command count, and safety validity.
- [ ] Continue cleanup after a failed treatment and mark the failure explicitly.

### Task 6: Measurement validity checks

**Files:**
- Modify: `config/recovery_action_experiments.json`
- Modify: `scripts/server_recovery_action_pilot.sh`
- Test: `tests/test_recovery_action_runner.py`

- [ ] Use deployment availability for `pod-kill`.
- [ ] Use container CPU usage plus deployment availability for `cpu-stress`.
- [ ] Use container memory working set plus deployment availability for `memory-stress`.
- [ ] Require an explicit Online Boutique latency query or active probe for `network-delay`; reject `max(up)` as invalid evidence.
- [ ] Save missing or invalid metrics as measurement failures instead of PASS.

### Task 7: Documentation and verification

**Files:**
- Modify: `docs/experiments/full_stack_experiment_guide.md`
- Modify: `README.md`

- [ ] Document the 12-treatment pilot command and the 36-treatment main experiment command.
- [ ] Document that the CPU 95% artificial alert is excluded from this research experiment.
- [ ] Document predicted reward versus observed outcome score.
- [ ] Run `python -m pytest` and confirm the entire suite passes.
- [ ] Run the local scoring fixture and verify JSON/CSV/Markdown artifacts.

## Server execution sequence

```bash
# Pilot: 4 faults x 3 actions x 1 repetition = 12 treatments
REPETITIONS=1 MODE=real bash scripts/server_recovery_action_pilot.sh

# Score the same outcomes under four reward policies
aiops-k8s-agents score-recovery-experiments \
  --input runs/recovery-action-pilot/outcomes.jsonl \
  --output-dir runs/recovery-action-pilot/analysis

# Main experiment after pilot QA: 4 x 3 x 3 = 36 treatments
REPETITIONS=3 MODE=real bash scripts/server_recovery_action_pilot.sh
```

## Acceptance criteria

- No CPU 95% artificial alert is used by the experiment runner.
- Every executed command is produced from a structured allowlisted action.
- All 12 pilot treatments create independently identifiable records.
- Invalid network latency evidence cannot be counted as a successful measurement.
- At least one controlled fixture demonstrates a policy-dependent action ranking change.
- Existing 4-Agent, AIOpsLab, and full-stack tests remain green.
