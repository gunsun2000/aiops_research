# Task 4 Report: Chaos Mesh Scenario Adapter

## Commit

- Implementation commit: `ae4f8f5` (`feat: add bounded chaos mesh adapter`)
- Base commit: `e18a21c`

## Files

- `src/aiops_k8s_agents/chaos_adapter.py`
- `tests/test_chaos_adapter.py`

## Implemented

- Registered scenario manifests are resolved and constrained beneath the configured repository `k8s` root.
- `preflight()` checks manifest existence, supported Chaos Mesh kinds, and `kubectl api-resources` availability.
- `inject()` uses structured argv for `kubectl apply`, waits for `AllInjected`, records timestamps and command output, and exposes `cleanup_required` after an apply attempt.
- `cleanup()` is repeatable and always uses `kubectl delete ... --ignore-not-found`; failed deletion remains visible through `cleanup_required=True`.
- Unknown scenarios and unsafe/unregistered manifest paths are rejected without accepting request-supplied arbitrary paths.

## Tests

- `python -m pytest tests/test_chaos_adapter.py tests/test_real_evidence.py tests/test_experiment_runtime_models.py -q`: `58 passed`
- `python -m pytest -q`: `400 passed, 1 warning`
- `git diff --check`: passed

## Concerns

- Tests use deterministic fake command runners and do not claim a live Kubernetes or Chaos Mesh cluster validation.
- The adapter waits for the Chaos Mesh `AllInjected` condition; later orchestration should treat a failed wait as an invalid application while still invoking cleanup.
- The adapter intentionally does not mutate or parse manifest content beyond a conservative `kind` check; manifest policy validation remains outside this Task 4 contract.
