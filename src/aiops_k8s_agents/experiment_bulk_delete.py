from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Request

from aiops_k8s_agents.control_plane_web import (
    RuntimeApiState,
    _experiment_artifact_paths,
    router,
)


@router.delete("/api/experiments")
def api_bulk_delete_experiments(request: Request) -> dict[str, object]:
    """Delete every terminal recovery experiment in one HTTP request.

    Active jobs are never cancelled or mutated. Artifact paths are resolved from
    persisted job results and validated by the same helper used by single-result
    deletion before any database row is removed.
    """
    state: RuntimeApiState = request.app.state.runtime_api
    jobs = state.job_store.list(limit=1_000_000)
    terminal_jobs = [job for job in jobs if job.status.terminal]
    protected_active = len(jobs) - len(terminal_jobs)

    if not terminal_jobs:
        return {
            "deleted": 0,
            "artifacts_deleted": 0,
            "protected_active": protected_active,
            "deleted_experiment_ids": [],
        }

    artifacts_by_experiment: list[tuple[str, tuple[Path, ...]]] = []
    try:
        for job in terminal_jobs:
            artifacts_by_experiment.append(
                (job.experiment_id, _experiment_artifact_paths(state, job))
            )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # Validate file types before deleting any artifact so a malformed artifact
    # entry cannot leave a partially deleted batch merely because it is a
    # directory or another unsupported path type.
    for _experiment_id, artifacts in artifacts_by_experiment:
        for path in artifacts:
            if not path.exists() and not path.is_symlink():
                continue
            if not path.is_file() and not path.is_symlink():
                raise HTTPException(
                    status_code=409,
                    detail="experiment artifact is not a file",
                )

    artifacts_deleted = 0
    for _experiment_id, artifacts in artifacts_by_experiment:
        for path in artifacts:
            if not path.exists() and not path.is_symlink():
                continue
            try:
                path.unlink()
            except OSError as exc:
                raise HTTPException(
                    status_code=409,
                    detail="experiment artifact could not be deleted",
                ) from exc
            artifacts_deleted += 1

    deleted_ids: list[str] = []
    for job in terminal_jobs:
        try:
            state.job_store.delete(job.experiment_id)
        except KeyError:
            # Another request may already have deleted the same terminal row.
            continue
        except ValueError as exc:
            # Status is re-checked by the store, protecting a row whose state
            # changed unexpectedly between list and delete.
            raise HTTPException(
                status_code=409,
                detail="experiment is not terminal",
            ) from exc
        deleted_ids.append(job.experiment_id)

    return {
        "deleted": len(deleted_ids),
        "artifacts_deleted": artifacts_deleted,
        "protected_active": protected_active,
        "deleted_experiment_ids": deleted_ids,
    }
