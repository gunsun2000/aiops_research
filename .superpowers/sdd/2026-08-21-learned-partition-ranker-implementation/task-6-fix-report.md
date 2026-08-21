# Task 6 Fix Report

## Result

Implemented the Task 6 review fixes for production observed runtime outcome provenance.

- Replaced the mutable payload-SHA trust boundary with an HMAC-SHA256 authenticated manifest.
- The manifest is created in the repository transaction and binds the committed version report, runtime outcome, and optional candidate ranking, plus plan identity and version.
- Signing material is supplied only by an explicit key, key file, or the `AIOPS_PARTITION_ARTIFACT_HMAC_KEY` environment fallback. It is never serialized into an artifact, report, sidecar, history, dataset, or log.
- Observed dataset building and real-claim dataset loading independently verify the manifest. Missing keys, manifests, bad signatures, unexpected file sets, and coordinated ordinary-SHA tampering are excluded or rejected safely.
- Restricted the dataset CLI to the supported `observed` scope. Deterministic defaults, recovery, AIOpsLab, AutoGen, and `PartitionPlanValidator` behavior are unchanged.

## Tests

- `python -m pytest tests/test_partition_service.py tests/test_partition_repository.py tests/test_partition_feedback.py tests/test_model_partition_cli.py tests/test_partition_learning_dataset.py tests/test_partition_evaluator.py -q` - 120 passed.
- `python -m pytest tests/test_partition_learning_training.py tests/test_partition_ranker_repository.py tests/test_partition_ranking.py -q` - 40 passed.
- `python -m pytest -q` - 937 passed, 1 third-party FastAPI/Starlette deprecation warning.

## Self Review

- Added deterministic tests for coordinated report/runtime-outcome tampering after recomputing the ordinary payload SHA; the HMAC verifier excludes the artifact.
- Added tests for a missing signing key, transactional manifest creation, and CLI rejection of unsupported `predicted` and `synthetic` scopes.
- `git diff --check` passed before commit.

## Commits

- Implementation and tests: `6e9c5ee7381771d6579fc7e9faf84596c5a352be` (`Authenticate observed partition artifacts`).
