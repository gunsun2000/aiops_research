# Task 6 Report: Runtime Factory and Scenario Catalog Integration

## Scope

Implemented Task 6 only on branch `codex/full-research-platform-v1-impl`.

## Changes

- Added `experiment_runtime_factory.py`.
  - Loads and validates `RuntimeConfiguration`.
  - Builds the registered `CommandValidator`, Prometheus/Kubernetes evidence provider, Kubernetes recovery monitor, Chaos Mesh adapter, deterministic protocol, policy, and adapter registry.
  - Constructs `MutualSupervisionCoordinator` per request without model calls or external operations during construction.
  - Keeps injected subprocess and Prometheus functions test-only; Task 5 admission rejects the injected Prometheus client for real execution.
- Added `runtime_scenario_catalog(configuration)`.
  - Scenario ids and manifests come from the validated runtime configuration.
  - Existing presentation fields remain explicitly marked as `ui_fallback` metadata.
- Updated `control_plane_data.scenario_catalog()` to use the registered runtime catalog while preserving existing mock/demo payload compatibility.
- Added factory, catalog, compatibility, and fail-closed real-boundary tests.

## Review Fixes

- Extended validated `RuntimeConfiguration.scenarios` entries with explicit `id`, `namespace`, `deployment`, `metric`, `threshold`, and `manifest` fields.
- Updated the registered runtime JSON and catalog so configuration-only scenarios are accepted; only chart/demo presentation data uses `ui_fallback` metadata.
- Loaded the complete registered protocol profile map and resolve `ExperimentRuntimeRequest.protocol_profile` before constructing a coordinator. Unknown profiles fail closed.
- Added regressions for configuration-only scenarios, configured target overrides, registered profile selection, and unregistered profile rejection.
- Final review fix B makes factory dependency selection mode-aware:
  - `mock` uses deterministic `FakeEvidenceProvider` and `FakeRecoveryMonitor`; it never constructs or calls live Prometheus/Kubernetes evidence.
  - `dry-run` uses the same non-live evidence and recovery boundary while retaining the existing dry-run action executor behavior.
  - `real` alone constructs `PrometheusKubernetesEvidenceProvider` and `KubernetesSnapshotRecoveryMonitor`, and still delegates to Task 5 production admission unchanged.
- Added an end-to-end factory mock regression proving injected Prometheus and Kubernetes collectors are never called.

## Boundaries

- No Kubernetes cluster was started.
- No Chaos Mesh fault was injected.
- No Prometheus request or model/API-key call was made by the tests.
- The injected test Prometheus client is intentionally blocked by the real runtime admission path; production defaults use the bounded `PrometheusAdapter` without an injected fetcher.
- Mock execution is fully deterministic and no-cluster at the evidence/recovery boundary. Dry-run evidence is also deterministic; its existing action executor may perform Kubernetes server-side dry-run when a dry-run experiment is executed.

## Verification

- `python -m pytest tests/test_experiment_runtime_factory.py tests/test_experiment_runtime.py tests/test_experiment_session.py tests/test_control_plane_data.py tests/test_real_evidence.py tests/test_chaos_adapter.py -q`: 103 passed
- `python -m pytest -q`: 455 passed, 1 existing Starlette/httpx deprecation warning
- `git diff --check`: passed
