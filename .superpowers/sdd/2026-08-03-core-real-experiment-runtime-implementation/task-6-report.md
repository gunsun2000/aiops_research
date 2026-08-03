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

## Boundaries

- No Kubernetes cluster was started.
- No Chaos Mesh fault was injected.
- No Prometheus request or model/API-key call was made by the tests.
- The injected test Prometheus client is intentionally blocked by the real runtime admission path; production defaults use the bounded `PrometheusAdapter` without an injected fetcher.

## Verification

- `python -m pytest tests/test_experiment_runtime_factory.py tests/test_control_plane_data.py -q`: 18 passed
- `python -m pytest tests/test_experiment_runtime.py tests/test_experiment_session.py tests/test_experiment_runtime_factory.py tests/test_control_plane_data.py -q`: 48 passed
- `python -m pytest`: 437 passed, 1 existing Starlette/httpx deprecation warning
- `git diff --check`: passed
