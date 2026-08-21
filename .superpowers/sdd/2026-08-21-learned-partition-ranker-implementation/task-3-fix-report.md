# Task 3 Fix Report: Guarded Learned Artifact Eligibility and OOD Boundary

## Scope

Fixed the two Task 3 review defects only. UI, API, trainer, policy, and
artifact-repository behavior were not expanded.

## Root Cause

- `GuardedCandidateSelector._learned_availability(...)` verified the requested
  model version, feature schema, and artifact hash, but did not restrict a
  `learned_guarded` final selection to the deployment artifact contract:
  `model_type == "ridge_reward_regressor"` and
  `training_scope == "observed"`.
- The selected-candidate OOD guard used a strict `>` comparison, so an OOD
  fraction exactly equal to `maximum_ood_feature_ratio` was accepted rather
  than treated as a distribution-shift fallback.

## Fix

- Reject a learned artifact whose model type is not `ridge_reward_regressor` or
  whose training scope is not `observed` as `model_unavailable`. In
  `learned_guarded`, this deterministically retains the baseline final
  candidate with `fallback_used=True`.
- Changed the OOD guard comparison from `>` to `>=`, so the configured 0.20
  boundary is severe and uses `feature_distribution_shift`.
- Preserved the existing shadow contract: it may record a learned selection,
  but its final selection remains the deterministic baseline.

## TDD Evidence

1. RED: `python -m pytest tests/test_partition_ranking.py -q -k "non_deployment_artifact or ood_policy_boundary"`
   failed in all three parameterized cases. Non-deployment artifacts selected a
   learned candidate and an OOD ratio of exactly 0.20 did not fall back.
2. GREEN: after the minimal selector changes,
   `python -m pytest tests/test_partition_ranking.py -q -k "non_deployment_artifact or ood_policy_boundary or shadow_records_learned_choice_but_keeps_baseline"`
   passed with `4 passed, 6 deselected`.

The OOD boundary test injects an exact ratio of 0.20 because the immutable
47-feature production schema cannot represent exactly one fifth of features;
it exercises the real guarded final-selection branch and its deterministic
fallback result.

## Verification

- Focused regression:
  `python -m pytest tests/test_partition_ranking.py tests/test_model_partition_agent.py tests/test_partition_validator.py -q`
  -> `44 passed in 0.32s`.
- Full regression: `python -m pytest -q` -> `887 passed, 1 warning in 53.95s`.
  The warning is the existing Starlette `TestClient` deprecation warning for
  `httpx`.
