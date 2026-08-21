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

## Re-review Closure: Registry Root Enumeration Boundary

- Implementation and regression-test commit: `070e543c8e8e37f6dd59d35d8c2983a08a69a0f4`
- Production files: `src/aiops_k8s_agents/partition_ranker_repository.py` and
  `src/aiops_k8s_agents/control_plane_web.py`
- Test file: `tests/test_model_partition_api.py`

`PartitionRankerRepository.collection_model_versions()` now validates and
canonicalizes the configured registry root before it enumerates any child
entries. It enumerates the validated resolved root only, rejects a
symlink/junction/reparse-point root through the existing repository boundary,
and rejects linked child directories. The control-plane collection endpoint no
longer calls `ranker_registry_root.iterdir()` directly.

The Windows-friendly regression models a registry root detected as a reparse
point while it contains an external-looking directory name. The endpoint now
returns a generic `422 invalid_model_artifact` response before collection and
does not emit the directory name in `integrity_errors` or any response field.
This test failed before the boundary change with `200` and an exposed model
version, then passed after the change.

### Verification

```text
python -m pytest tests/test_model_partition_api.py \
  tests/test_control_plane_web.py \
  tests/test_partition_ranker_repository.py -q

85 passed, 1 warning in 10.40s

python -m pytest -q

958 passed, 1 warning in 59.72s
```

The sole warning is the existing FastAPI/TestClient Starlette deprecation
warning. `python -m py_compile` for both modified production modules and
`git diff --check` also completed successfully. No push or merge was
performed.
