# Task 7 Fix Report: Control Plane Ranker API Hardening

## Result

- Implementation and test commit: `a7c1ec2cb556194ec5469fcda1b4e266aeb49330`
- Production file: `src/aiops_k8s_agents/control_plane_web.py`
- Test file: `tests/test_model_partition_api.py`

All findings from `task-7-review.md` are resolved.

1. A safe registered model version whose artifact fails verification now returns
   `422 invalid_model_artifact`, its safe model version, and a sanitized,
   operator-relevant integrity reason. The collection endpoint remains
   available, excludes corrupt artifacts from selectable models, and returns
   `integrity_errors` for affected registered versions without filesystem paths.
2. The ranker detail route captures decoded path segments and validates them
   before repository access. Encoded slash traversal, encoded dot traversal,
   and Windows drive/backslash tokens return `422 invalid_model_version`.
   Unknown safe tokens remain `404`; valid tokens remain `200`.
3. `artifact_signing_key`, `artifact_signing_key_file`, and
   `ranker_registry_root` are explicitly rejected in HTTP bodies with `422`.
   The request model still ignores unrelated legacy extension fields, preserving
   legacy request compatibility.
4. Tests prove the trusted Control Plane configuration supplies the artifact
   signing configuration to planning and the registry root to feedback
   replanning. No HTTP field can override either value.

## TDD Evidence

The review regressions were written before the implementation. The initial
focused API run reproduced six failures: corrupt artifacts were mislabeled,
encoded traversal returned `404`, and all three reserved HTTP fields were
silently accepted.

## Verification

```text
python -m pytest tests/test_model_partition_api.py tests/test_control_plane_web.py -q
70 passed, 1 warning in 10.32s

python -m pytest -q
957 passed, 1 warning in 60.57s
```

The warning is the existing FastAPI/TestClient `httpx` deprecation warning.
`git diff --check` and Python compilation of the modified production module
also passed.

## Boundaries

- Recovery, AIOpsLab, AutoGen, UI, CLI, and deterministic partition behavior
  were not modified.
- No push or merge was performed.
