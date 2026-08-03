# Task 7 Report: Runtime API Boundary

## Implemented

- Added `GET /api/platform` with the `1.0` API contract, explicit mock/dry-run/real mode readiness, safety bounds, and the Phase A preflight-only boundary.
- Added `GET /api/connections` with bounded, read-only readiness probes for Kubernetes, Prometheus, Chaos Mesh, AutoGen configuration, AIOpsLab, and the artifact directory.
- Added `POST /api/experiments/validate` using `ExperimentRuntimeRequest` validation and the registered runtime configuration. It checks scenario identity, target allowlists, metric/threshold/profile registration, and real-mode prerequisites without calling runtime execution or fault injection.
- Added `create_app(...)` dependency injection for runtime factories and connection probes while preserving the existing global `app` and existing endpoints.
- Readiness responses expose stable prerequisite names and boolean states only; probe command output, URLs, credentials, and exception text are not returned.

## Verification

- TDD contract tests were written first and observed failing during collection because `create_app` and the new API boundary were absent.
- Focused control-plane/runtime suite: `29 passed`.
- Full Python suite: `445 passed, 1 warning`.
- `git diff --check`: passed.
- No Kubernetes cluster, Chaos Mesh mutation, model/API key, or experiment execution was used.

## Scope

Changed only:

- `src/aiops_k8s_agents/control_plane_web.py`
- `tests/test_control_plane_web.py`
- this report

## Review Fix

- Added the typed `RuntimePreflightResult` contract and `ExperimentRuntime.preflight(request)` path. It validates the registered request, exact scenario manifest/resource kind, and coordinator admission without acquiring a lock, calling `run`, injecting, applying, deleting, or executing an action.
- `POST /api/experiments/validate` now constructs the injected runtime for real requests and requires that request-specific preflight to pass alongside all connection prerequisites.
- `GET /api/platform` is conservative: generic readiness cannot claim real mode ready because scenario-specific preflight is request-dependent.
- Added deterministic real-mode accepted/rejected, scenario-resource rejection, factory/preflight exception secrecy, and no-mutation tests.

Review-fix verification: `11 passed` focused control-plane tests, `449 passed` full Python suite, and `git diff --check` passed. The platform capability test now uses fixed injected probes and performs no ambient kubectl/Prometheus I/O. The review note was moved to this task folder and remains untracked reviewer material.
