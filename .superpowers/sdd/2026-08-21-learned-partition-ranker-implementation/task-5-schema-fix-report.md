# Task 5 Schema Fix Report

## Scope

- Added one exported `VALIDATION_METRIC_KEYS` contract containing the exact 13 keys emitted by the offline Ridge trainer.
- Artifact parsing and object validation now reject missing or extra validation-metric keys and continue to reject non-numeric or non-finite values.
- Updated all ranker test artifacts that construct `PartitionRankerModelArtifact` instances.
- No runtime outcome provenance, service, API, CLI, or UI changes were made.

## TDD Evidence

- RED: added `test_artifact_rejects_incomplete_validation_metrics` with `validation_metrics={"mae": 0.1}`. The focused test failed because the prior numeric-map validator did not raise.
- GREEN: added the exact-key validator and reran the same test: `1 passed`.
- The training regression asserts the serialized trainer output has exactly the exported key set.

## Verification

- Focused: `python -m pytest tests/test_partition_ranker_repository.py tests/test_partition_ranking.py tests/test_partition_learning_training.py -q` -> `40 passed in 1.76s`.
- Full Python suite: `python -m pytest -q` -> `923 passed, 1 warning in 57.09s`.
- `git diff --check` passed.

## Files Changed

- `src/aiops_k8s_agents/partition_ranker_repository.py`
- `tests/test_partition_learning_training.py`
- `tests/test_partition_ranker_repository.py`
- `tests/test_partition_ranking.py`

## Commit

- Implementation: `6619e1b7013cbc034b0f4cdee4f1fc9e081ae996` (`Fix learned ranker validation metric schema`)

## Concerns

- The full suite retains one pre-existing Starlette/httpx deprecation warning from `fastapi.testclient`; it is unrelated to this fix.
