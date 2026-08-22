# Task 9 Report: Research documentation and executable boundaries

## Implemented

- Added a concise learned-ranking overview and detailed document links to `README.md`.
- Added `docs/design/model_partition_orchestrator_agent_design.md` with component ownership,
  decision authority, selection modes, reward semantics, and external Scheduler boundaries.
- Added `docs/experiments/partition_ranker_experiment_guide.md` with observed-only Dataset,
  training, evaluation, Shadow, and Learned Guarded experiment procedures.
- Updated `docs/submission/execution_code_guide.md` with the exact current CLI contracts.
- Added documentation contract tests to prevent evidence-scope and authority drift.

## Preserved boundaries

- Deterministic candidate generation and Hard Feasibility remain authoritative.
- AI ranks feasible candidates only; Shadow never changes the final selection.
- Learned Guarded requires an eligible registered observed Ridge artifact and otherwise falls back.
- `PartitionPlanValidator` remains the independent final planning safety boundary.
- The Scheduling Agent, GPU placement, and runtime execution remain external.
- Predicted, synthetic, mock, and dry-run values are not documented as Real Runtime evidence.
- The artifact HMAC key is configured through an external file without exposing secret material.

## Verification

- `python -m pytest tests/test_documentation_contracts.py -q`: 4 passed.
- All four ranker CLI `--help` commands completed successfully and matched the documented flags.
- `python -m pytest`: 966 passed with one pre-existing TestClient deprecation warning.
- `go test ./...` under `go/aiops-guard`: passed.
- Browser QA: deterministic Training plan completed through the real Control Plane API; desktop
  and 390 px mobile layouts were inspected, with no browser console errors.
