# Task 4 Fix Report: Observed Artifact Validation

## Scope

Fixed only the Task 4 observed-outcome dataset ingestion boundary. Trainer,
API, UI, evaluator behavior, and unrelated artifact writer behavior were not
changed.

## Root Cause

`partition_learning._training_row(...)` accepted an observed report after
checking only source and timestamp presence. It did not apply the established
`ObservedPartitionMetrics.from_dict(...)` validation contract, so malformed
timestamps and invalid transfer-byte values could become training rows.
`_read_committed_partition_report(...)` also accepted a directory containing
both `commit.json` and `pending.json`.

## TDD Evidence

1. RED: added dataset-level tests for a malformed ISO-8601 timestamp, NaN,
   negative, and fractional `total_transfer_bytes`, plus a committed-and-pending
   artifact. The focused command failed as expected: `5 failed, 9 deselected`.
2. GREEN: observed evidence now passes its metrics mapping through
   `ObservedPartitionMetrics.from_dict(...)`; committed artifacts with a
   `pending.json` marker raise a corrupt-artifact rejection.
3. The same focused command then passed: `5 passed, 9 deselected`.

## Verification

- Focused regression:
  `python -m pytest tests/test_partition_learning_dataset.py tests/test_partition_evaluator.py tests/test_partition_features.py tests/test_partition_ranking.py tests/test_partition_service.py -q`
  -> `77 passed in 3.26s`.
- Full regression: `python -m pytest -q` -> `901 passed, 1 warning in 55.04s`.
  The warning is the existing Starlette `TestClient` deprecation warning for
  `httpx`.
