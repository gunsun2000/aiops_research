# Task 5 Report: Experiment Runtime Orchestration

## Commit

- Implementation commit: `b06068c` (`feat: orchestrate bounded real experiments`)
- Review-fix commit: `04e7913` (`fix: enforce experiment runtime safety invariants`)
- Base commit: `79b4ec5`

## Files

- `src/aiops_k8s_agents/experiment_runtime.py`
- `src/aiops_k8s_agents/experiment_session.py`
- `src/aiops_k8s_agents/mutual_supervision.py`
- `tests/test_experiment_runtime.py`
- `tests/test_experiment_session.py`

## Implemented

- Added the bounded `ExperimentRuntime` lifecycle: target validation, runtime preflight, real-mode operation locking, registered Chaos Mesh injection, coordinator execution, recovery-stage events, cleanup, and immutable session normalization.
- Preserved mock-mode boundaries: mock runs do not call Chaos Mesh or acquire an external operation lock.
- Added `RuntimeResearchEventBridge` for coordinator stream translation, artifact finalization, immutable event snapshots, and one runtime `experiment_id` across research events, reports, and session stages.
- Cleanup runs after coordinator failures, timeout/interruption signals, and injection failures when an application exists; cleanup failures retain the primary error and set `cleanup_error`, `cleanup_status=cleanup_failed`, and `human_review_required`.
- Added cancellation handling before external operations and terminal status normalization for `cancelled`, `interrupted`, `blocked`, and `cleanup_failed`.

## Review Fixes

- Runtime-owned `TargetOperationLock` now spans real preflight, injection, evidence, coordinator reasoning, and cleanup; the coordinator skips its nested action lock when runtime ownership is active.
- Coordinator mode and optional backend are validated against the request before any external operation; both real/mock mismatch directions are covered.
- Added a deadline from `RuntimeConfiguration.timeouts["experiment"]`, cancellation/deadline checkpoints around injection, evidence, coordinator execution, and recovery execution, plus coordinator runtime-control checkpoints.
- Coordinator event stores defer finalization to one runtime-owned terminal write after cleanup. The persisted report includes terminal status, cleanup data, runtime event sequence, and the same experiment id as the returned result.
- Added an injectable `ExperimentSessionStore`; every terminal path persists exactly one normalized immutable session.

## Tests

- `python -m pytest tests/test_experiment_runtime.py tests/test_experiment_session.py -q`: `24 passed`
- `python -m pytest`: `427 passed, 1 warning`
- `git diff --check`: passed

## Concerns

- Tests use deterministic fakes and do not claim live Kubernetes, Prometheus, Chaos Mesh, or model/API-key validation.
- Deadline cancellation is cooperative through the runtime-control contract and is checked by the existing synchronous coordinator before/after external stages; arbitrary third-party coordinators must honor the injected control capability to be interruptible.
- The existing CLI behavior was not modified; runtime construction and web integration remain later plan tasks.
