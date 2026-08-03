# Task 8 Report

## Scope

Task 8 only was implemented in the worktree
`C:\Users\geonhae\Documents\aiops_research\.worktrees\full-research-platform-v1-impl`.
The changes are documentation and verification records; no runtime source was
modified. The main repository and its `tmp/` content were not touched.

## Files

- `README.md`
- `docs/experiments/platform_real_runtime_guide.md`
- `task-8-report.md`

The README now describes the implemented core runtime and read-only preflight
API, preserves the existing CLI real path, and separates Plan B and Plan C.
The guide contains Ubuntu commands for environment, Prometheus, API preflight,
CLI real execution, cleanup, and failure evidence collection.

## Verification

Focused Plan A regression tests:

```text
python -m pytest tests/test_experiment_runtime_models.py tests/test_prometheus_adapter.py tests/test_real_evidence.py tests/test_chaos_adapter.py tests/test_experiment_runtime.py tests/test_experiment_runtime_factory.py tests/test_control_plane_web.py -q
126 passed, 1 warning in 1.47s
```

Full Python suite:

```text
python -m pytest
449 passed, 1 warning in 4.24s
```

Go Guard:

```text
cd go/aiops-guard
go test ./...
?   github.com/gunsun2000/aiops_research/go/aiops-guard/cmd/aiops-guard [no test files]
ok  github.com/gunsun2000/aiops_research/go/aiops-guard/internal/guard (cached)
```

Static checks:

```text
git diff --check
pass (no output)

git status --short
 M README.md
?? docs/experiments/platform_real_runtime_guide.md
?? task-8-report.md
```

## Warning

Both Python runs emitted one `StarletteDeprecationWarning` from the installed
FastAPI TestClient integration: using `httpx` with `starlette.testclient` is
deprecated and `httpx2` is recommended. It did not fail the tests.

## Commit

The documentation commit is recorded here after commit creation:

`f7b1836` (`docs: explain real experiment runtime`)

## Remaining validation boundary

The verification ran in the Windows worktree. It proves Python contracts,
mock-safe behavior, documentation consistency, and Go Guard regression tests;
mock tests are not real evidence. No real Kubernetes, Prometheus, or Chaos Mesh
validation was performed here. Real end-to-end validation remains an authorized
Ubuntu research-server activity and must include connection/readiness checks,
registered scenario preflight, actual bounded CLI execution, cleanup, and
artifact review. AutoGen web runtime and AIOpsLab Job integration remain
separate Plan C work, and persistent Job/SSE/cancellation/web-triggered real
execution remain unimplemented Plan B work.
