# Task 8 Report: Baseline and Learned Ranker UI

## Implementation

- Commit: `b8167a8`
- UI files: `ui/control_plane_static/index.html`, `app.js`, `styles.css`
- Test file: `tests/test_control_plane_ui.py`

The existing four-stage Model Partition workspace now exposes three candidate
selection modes: deterministic, shadow, and learned guarded. Registered models
are loaded exclusively from the Control Plane ranker registry API. Guarded mode
is disabled when no model satisfies server-derived eligibility checks.

Planning results show baseline selection, learned recommendation, final
selection, candidate baseline scores, predicted rewards, hard-constraint
exclusions, feature contributions, model provenance, and guarded fallback
reasons. Shadow mode explicitly preserves the deterministic final candidate.

Observed reward and dataset inclusion remain post-runtime evidence. The browser
does not calculate model predictions and does not receive artifact signing
material.

## Verification

```text
python -m pytest tests/test_control_plane_ui.py -q
34 passed

python -m pytest tests/test_model_partition_api.py tests/test_control_plane_web.py tests/test_control_plane_ui.py -q
105 passed, 1 pre-existing deprecation warning
```

`node --check` was unavailable because Node.js is not installed in the current
Windows environment. Browser-level verification is part of the final Task 9
verification pass.

