# Task 5 Fix 2 Report: Provenance-Bound Offline Ranker Contracts

## Scope

- Limited to the offline partition-ranking dataset loader/builder, v2 ranker Artifact validation, evaluator metrics, and focused fixtures.
- Runtime Artifact loading and learned inference remain sklearn-free. No UI, API, scheduler, or runtime execution surface changed.

## Corrected Review Findings

1. Observed datasets produced through the registered builder now record builder provenance plus one source-artifact contract per row. Each contract binds the source root, committed plan/version, runtime outcome ref, and a SHA-256 hash over the committed report and sidecars. A loader re-reads the source contract, reconstructs the row, and rejects changed artifacts or a forged runtime outcome ref. Direct JSONL can be loaded for offline work only with `eligible_for_real_claims: false`; it cannot be promoted with runtime-monitor strings alone.
2. The loader parses observed timestamps as timezone-aware ISO-8601 values. Malformed values are rejected before training or evaluation.
3. Artifact v2 requires `group_count` to equal the sorted, unique training lineage hash count. Provenance now records all six learned-ranker guard thresholds, with integer and bounded numeric validation that matches their semantics.
4. Evaluation metrics always export `candidate_selection_agreement`, `learned_regret`, and both availability flags. When no lineage group has comparable candidates, values are `0.0` and availability is `0.0`.
5. The group holdout test now calls the production `group_key()` contract directly.

## TDD Evidence

- RED before implementation: malformed observed timestamps loaded; direct observed JSONL exposed no real-claim eligibility boundary; no-comparison metrics omitted learned regret keys; artifacts accepted group/provenance threshold violations; the trainer omitted two guard thresholds; a changed committed source artifact was accepted.
- Focused regression:
  - `python -m pytest tests/test_partition_learning_dataset.py tests/test_partition_learning_training.py tests/test_partition_ranker_repository.py tests/test_partition_ranking.py tests/test_partition_models.py tests/test_partition_features.py -q`
  - Result: `74 passed in 3.40s`.
- Full regression: all 76 test files ran in four contiguous batches because the terminal output window truncates long-running commands.
  - Result: `922 passed`; one existing FastAPI/Starlette `TestClient` deprecation warning in the UI/API batch.

## Boundary

The source contract verifies persisted offline evidence; it does not execute infrastructure or establish a new runtime outcome. Predicted, synthetic, direct JSONL, missing-source, tampered-source, or lineage-overlapping data remains ineligible for real deployment claims.
