# Experiment Result Deletion Design

## Goal

Add a safe delete flow for persisted recovery experiment results from the Research Console.

## Scope

The delete operation applies to regular recovery experiment jobs stored in `SQLiteExperimentJobStore`. A deletion removes:

- the selected experiment job row,
- all runtime events belonging to that experiment,
- artifacts owned by that experiment under the configured experiment artifact/runs area.

AIOpsLab benchmark jobs and recovery-comparison jobs are out of scope for this first delete feature and remain unchanged.

## Safety rules

- Only terminal experiment jobs may be deleted.
- `queued`, `running`, and `cancelling` jobs cannot be deleted.
- The UI must show a confirmation dialog before sending the delete request.
- The confirmation must clearly state that the job, events, and experiment artifacts are permanently removed.
- A missing experiment returns 404.
- A non-terminal experiment returns 409 Conflict.
- Artifact deletion must stay inside the configured repository/artifact root; arbitrary paths must never be accepted from the client.
- Deleting database state and events must use the SQLite relationship already configured with `ON DELETE CASCADE`.
- If an experiment has no artifacts, deletion still succeeds.

## Backend design

### Store

Add `SQLiteExperimentJobStore.delete(experiment_id: str) -> ExperimentJob`.

Behavior:

1. Load the existing job.
2. Reject non-terminal status with `ValueError`.
3. Delete the `experiment_jobs` row in one SQLite transaction.
4. Rely on `ON DELETE CASCADE` to delete `experiment_events`.
5. Return the deleted `ExperimentJob` snapshot for API reporting.

### API

Add:

`DELETE /api/experiments/{experiment_id}`

Response on success:

```json
{
  "deleted": true,
  "experiment_id": "exp-...",
  "artifacts_deleted": 3
}
```

The server resolves artifact locations from the stored experiment result and repository-controlled artifact root. The client never submits file-system paths.

HTTP behavior:

- `200` successful deletion
- `404` experiment not found
- `409` experiment is not terminal

## Frontend design

### Experiment results list

Each result row receives a `삭제` action beside `상세`.

Selecting it opens a confirmation dialog:

> 이 실험 결과를 삭제하시겠습니까? Job, 이벤트, 생성된 결과 파일이 영구적으로 삭제됩니다.

After success:

- reload `/api/experiments?limit=100`,
- recalculate table pagination and summary metrics,
- remove the deleted row without a full browser reload,
- show a short success message.

### Experiment detail

Add a red/destructive `실험 삭제` button in the detail header.

After confirmation and successful deletion:

- return to the Experiment Results list,
- refresh result data,
- clear the deleted experiment from any current-detail state.

If the experiment is running, the delete button is disabled or the API rejection is shown as `실행 중인 실험은 삭제할 수 없습니다.`

## Error handling

- Network/API failure leaves the row visible and shows the server error.
- 409 maps to the Korean non-terminal warning.
- 404 refreshes the list because the result is already gone.
- Artifact cleanup errors must not silently report complete success. The response or error should state that database deletion succeeded but artifact cleanup needs attention only if the implementation cannot make cleanup atomic enough; preferred implementation deletes validated artifact paths before committing the database removal so a cleanup error stops the operation.

## Testing

Backend tests must verify:

- completed job deletion succeeds,
- related events are removed,
- non-terminal jobs cannot be deleted,
- missing job returns 404,
- valid experiment artifacts are deleted,
- artifact paths outside the allowed root are never removed.

UI contract/browser tests must verify:

- result rows expose delete,
- detail page exposes delete,
- confirmation is required,
- `DELETE /api/experiments/{id}` is used,
- success refreshes the result list,
- the feature does not introduce `MutationObserver` or another continuous DOM polling loop.
