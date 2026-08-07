# Bulk Experiment Result Deletion Design

## Goal

Add an `전체 삭제` action to the Experiment Results screen that permanently deletes every terminal recovery experiment result while never touching an active experiment.

## Scope

The bulk action applies only to the regular recovery experiment store (`SQLiteExperimentJobStore`). It does not delete AIOpsLab benchmark jobs or recovery-comparison jobs.

Terminal statuses eligible for deletion:

- `completed`
- `failed`
- `blocked`
- `cancelled`
- `interrupted`

Protected statuses that must remain untouched:

- `queued`
- `running`
- `cancelling`

For each eligible experiment, deletion uses the same safety rules as single-result deletion and removes:

- the experiment job row,
- related runtime events,
- validated experiment-owned artifact files.

## UX

A destructive `전체 삭제` button is placed in the upper area of the Experiment Results view, next to the results controls/heading where it is visible before the table.

Selecting it shows a strong confirmation message explaining that all completed/failed/blocked/cancelled/interrupted experiment results, events, and generated files will be permanently removed, while currently active experiments will remain.

The action is disabled when there are no terminal results to delete.

After success, the UI refreshes the experiment history, pagination, summary cards, distribution chart, synthetic-data warning, and current detail state without a full browser reload.

If the currently opened experiment detail was deleted by the bulk operation, the console returns to the Experiment Results list.

## Backend

Add a bulk endpoint:

`DELETE /api/experiments`

The endpoint must:

1. Load persisted experiment jobs from the server-side store.
2. Select only terminal jobs.
3. Reuse the same validated artifact cleanup behavior used by single deletion.
4. Never cancel, alter, or delete nonterminal jobs.
5. Return a summary such as:

```json
{
  "deleted": 7,
  "artifacts_deleted": 19,
  "protected_active": 2,
  "deleted_experiment_ids": ["exp-...", "exp-..."]
}
```

If no terminal jobs exist, return success with `deleted: 0` rather than treating it as an error.

If safe artifact cleanup fails for any selected experiment, do not report that experiment as deleted. The API returns an error rather than silently losing database provenance.

## Safety

- No client-supplied file paths are accepted.
- Artifact paths must remain inside the repository-controlled runs/artifact root.
- Active jobs are excluded server-side even if the client state is stale.
- The bulk endpoint does not call cancellation APIs.
- No DOM observers or continuous polling are introduced.

## Testing

Backend tests cover:

- multiple terminal jobs are deleted,
- their related events are deleted,
- active jobs survive unchanged,
- no-terminal case returns `deleted: 0`,
- artifact cleanup uses the same path-boundary rules as single deletion.

UI tests cover:

- `전체 삭제` appears above the results table,
- confirmation is required,
- `DELETE /api/experiments` is called,
- active-result protection is explained,
- success refreshes history/pagination/dashboard,
- the button is disabled when no terminal jobs are available,
- `MutationObserver` remains absent.
