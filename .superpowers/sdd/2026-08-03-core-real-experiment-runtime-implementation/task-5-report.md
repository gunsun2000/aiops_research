# Task 5 Report: Experiment Runtime Orchestration

## Commit

- Implementation commit: `b06068c` (`feat: orchestrate bounded real experiments`)
- Base commit: `79b4ec5`

## Files

- `src/aiops_k8s_agents/experiment_runtime.py`
- `src/aiops_k8s_agents/experiment_session.py`
- `tests/test_experiment_runtime.py`
- `tests/test_experiment_session.py`

## Implemented

- Added the bounded `ExperimentRuntime` lifecycle: target validation, runtime preflight, real-mode operation locking, registered Chaos Mesh injection, coordinator execution, recovery-stage events, cleanup, and immutable session normalization.
- Preserved mock-mode boundaries: mock runs do not call Chaos Mesh or acquire an external operation lock.
- Added `RuntimeResearchEventBridge` for coordinator stream translation, artifact finalization, immutable event snapshots, and one runtime `experiment_id` across research events, reports, and session stages.
- Cleanup runs after coordinator failures, timeout/interruption signals, and injection failures when an application exists; cleanup failures retain the primary error and set `cleanup_error`, `cleanup_status=cleanup_failed`, and `human_review_required`.
- Added cancellation handling before external operations and terminal status normalization for `cancelled`, `interrupted`, `blocked`, and `cleanup_failed`.

## Tests

- `python -m pytest tests/test_experiment_runtime.py tests/test_experiment_session.py -q`: `14 passed`
- `python -m pytest`: `417 passed, 1 warning`
- `git diff --check`: passed

## Concerns

- Tests use deterministic fakes and do not claim live Kubernetes, Prometheus, Chaos Mesh, or model/API-key validation.
- Timeout handling preserves coordinator-raised timeout/interruption signals and guarantees cleanup; a hard asynchronous preemption mechanism is intentionally outside the existing synchronous coordinator contract.
- The existing CLI behavior was not modified; runtime construction and web integration remain later plan tasks.
