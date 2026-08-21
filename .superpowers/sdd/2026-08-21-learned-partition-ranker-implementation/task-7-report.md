# Task 7 Report: Control Plane Ranker API

## Implementation

- Commit: `7095482d49014857ff1f716e89e1993ab80adca1`
- Production file: `src/aiops_k8s_agents/control_plane_web.py`
- Test file: `tests/test_model_partition_api.py`

The Model Partition Control Plane now accepts `selection_mode` and a registered
`ranker_model_version` on V2 planning requests. Legacy `round_plan` requests
ignore both fields and remain deterministic.

The Control Plane owns the ranker registry root. HTTP callers supply only a
model-version token, which is resolved through `PartitionRankerRepository`.
The following status endpoints are available:

- `GET /api/model-partition/rankers`
- `GET /api/model-partition/rankers/{model_version}`

Each response exposes model metadata, validation metrics, artifact hash, and
ordered static guard eligibility failures. Unknown models return `404`; invalid
or path-like model versions return `422`.

Artifact HMAC configuration is injected only through trusted `create_app()`
runtime arguments. HTTP request fields cannot provide a signing key or key
path. Feedback replanning receives the same server-owned registry root so that
persisted learned selections can be resolved without an HTTP path input.

## TDD Evidence

The new API tests were added before the Control Plane contract changes. The
initial focused run failed because `create_app()` did not yet accept
`ranker_registry_root` or the server-owned artifact HMAC configuration.

## Verification

```text
python -m pytest tests/test_model_partition_api.py tests/test_control_plane_web.py -q
61 passed, 1 warning in 9.75s

python -m pytest -q
948 passed, 1 warning in 59.63s
```

The warning is the existing FastAPI/TestClient `httpx` deprecation warning.

## Scope and Boundaries

- No recovery, AIOpsLab, AutoGen, static UI, or legacy deterministic API files
  were changed.
- No push or merge was performed.
- Task 8 remains responsible for exposing ranker selection and status in the
  browser UI.
