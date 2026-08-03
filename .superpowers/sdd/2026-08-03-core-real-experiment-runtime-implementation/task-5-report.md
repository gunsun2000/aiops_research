# Task 5 Report: Experiment Runtime Orchestration

## Commit

- Implementation commit: `b06068c` (`feat: orchestrate bounded real experiments`)
- Review-fix commit: `04e7913` (`fix: enforce experiment runtime safety invariants`)
- Review-fix 2 commit: `f5d2b66` (`fix: bound coordinator execution by registered deadline`)
- Review-fix 3 commit: `b2f4b71` (`fix: reject unsupported coordinator capabilities`)
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
- Added the required positive `experiment_seconds` production setting and validation; runtime deadlines now use this registered key rather than an optional timeout-map entry.
- Added a cancellable coordinator worker boundary that signals runtime control on expiry, joins the worker before cleanup, and prevents recovery from continuing in background after timeout.
- Replaced the worker boundary with an explicit `CoordinatorRuntimeCapabilities` contract validated before fault injection. Unsupported/non-cooperative coordinators are rejected before Chaos Mesh work; no Python thread cancellation or unbounded join is claimed or used.
- The production `MutualSupervisionCoordinator` advertises the bounded, cancellable, finite-stage-I/O, deadline-aware contract and continues to enforce runtime control at evidence and recovery boundaries.

## Tests

- `python -m pytest tests/test_experiment_runtime.py tests/test_experiment_session.py -q`: `27 passed`
- `python -m pytest tests/test_experiment_runtime.py tests/test_experiment_session.py tests/test_real_evidence.py -q`: `58 passed`
- `python -m pytest`: `430 passed, 1 warning`
- `git diff --check`: passed

## Concerns

- Tests use deterministic fakes and do not claim live Kubernetes, Prometheus, Chaos Mesh, or model/API-key validation.
- Coordinator execution is intentionally synchronous after capability validation; boundedness and cancellation are an explicit coordinator contract, not a claim that Python threads can be forcibly stopped. Unsupported coordinators are rejected before injection, while the supported coordinator checks runtime control before evidence/recovery stages.
- The existing CLI behavior was not modified; runtime construction and web integration remain later plan tasks.
