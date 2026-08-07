# Complete 4-Agent AIOps Research Console Design

## Goal

Finish the `feat/ui-research-console-redesign` branch so the platform implements the full approved UI prompt, not only the visual shell. The five reference screenshots remain the layout target, while every displayed value must come from existing or explicitly extended backend data. No fabricated benchmark scores, experiment results, or provider states are allowed.

## Preserved architecture

The existing FastAPI control plane, SQLite experiment/AIOpsLab/comparison stores, SSE streams, experiment cancellation, Mock/Dry-run/Real boundaries, AutoGen readiness gate, Kubernetes safety gate, Python validator, Go guard, allowlists, replica bounds, Real confirmation, and artifact endpoints remain authoritative. Frontend improvements consume those contracts or extend them narrowly when a missing read-only API is required.

## Completion scope

### 1. System overview

- Keep the approved navy sidebar and four primary menus.
- Read connection state from `/api/connections`.
- Show the eight-stage recovery flow, live SSE stage, four Agent summaries, latest result and Evidence summary.
- Quick Run reuses the recovery experiment controls and safety validation.
- Loading, empty, error, retry states are explicit.

### 2. Recovery experiment

- Four recovery scenarios only: Pod Failure, CPU Saturation, Memory Saturation, Network Delay.
- Deterministic is default; AutoGen is disabled when readiness is false.
- Controller labels never mix deterministic with a model name.
- Mock, Dry-run and Real boundaries stay distinct.
- Real requires the existing explicit confirmation phrase and server gate.
- Advanced settings show only supported fields.
- Job creation, SSE progression, cancellation, Agent decisions, Evidence and safety status remain live.

### 3. AIOpsLab Benchmark

AIOpsLab remains separate from recovery and never triggers Kubernetes recovery actions.

Three functional tabs are required:

1. **벤치마크 평가**
   - Catalog from `/api/benchmarks/aiopslab`.
   - Actual runtime readiness.
   - Scenario selection, repetitions, run/cancel, progress and dynamic metrics.
   - Recent results table from persisted AIOpsLab jobs.

2. **모델 성능 비교**
   - Aggregate only actual persisted benchmark results.
   - Compare registered detector/model identifiers when two or more exist.
   - The current runtime exposes `AI-MCMP Four-Agent` as the actual detector. If only one detector has results, render that detector and a clear `비교 가능한 Detector가 1개입니다` empty-comparison state rather than inventing competitors.
   - Metrics are schema driven: Accuracy, Average TTD, Average Steps and Average Reward when present.

3. **실행 이력**
   - Read persisted jobs from `/api/benchmarks/aiopslab/jobs`.
   - Show Job ID, scenario, detector, repetitions, status, start/end time, actual metrics and detail action.
   - Filters and pagination operate on loaded persisted jobs.
   - Detail view exposes events and only actual artifacts.

The AIOpsLab API payload gains stable detector metadata (`detector_id`, `detector_label`) but no fake metrics.

### 4. Experiment results

- Tabs: experiment list, recovery strategy comparison, performance dashboard.
- Filters: period, scenario, controller, mode, result and Experiment ID.
- Filter state synchronizes to URL query parameters and survives refresh.
- Changing a filter resets page to 1; search is debounced.
- Client-side pagination is acceptable because the current API does not expose server paging; the UI must state the loaded result limit when relevant.
- Table shows Experiment ID, time, scenario, controller, mode, result, MTTR, reward and detail.
- Mock rows visibly identify synthetic data.
- Summary excludes missing MTTR/Reward from averages instead of treating them as zero.
- Donut/ring distribution includes success, failed, safe/blocked and cancelled when data exists.
- Empty state provides a filter reset action.

### 5. Experiment detail

- Header: back, experiment ID, copy ID, grouped result download, rerun.
- Rerun prefills the recovery form and never starts a Real experiment automatically.
- Six tabs: summary, timeline, Agent decisions, Evidence, logs, events.
- Active detail tab is reflected in URL query state.
- Summary includes final action, recovery status, MTTR, reward and safety status plus experiment metadata.
- Evidence table shows only metrics with actual before/after data.
- Agent tab shows decision, approval/rejection, reason and peer review without secrets.
- Log tab supports level/search controls and bounded rendering.
- Event tab shows SSE event name/time/stage/summary/payload.
- Artifact menu displays only available artifacts and reports download failures.

### 6. Shared state and data integrity

- Central formatting rules for controller, mode, status, duration and metrics.
- Missing values remain `—`, `데이터 없음`, `수집되지 않음` or equivalent; missing never becomes numeric zero.
- Chaos Mesh recovery Evidence never uses AIOpsLab provider labels.
- Synthetic/Mock results are visibly marked.
- Lifecycle status and final result status cannot produce contradictory labels.

### 7. Accessibility and responsive behavior

- Inputs have labels.
- Selectable cards use keyboard-accessible buttons and `aria-pressed`.
- Status is not conveyed by color alone.
- Error regions use `aria-live`.
- 1440px and 1920px keep the approved desktop composition; narrower widths collapse cleanly.

## Testing and verification

- Backend tests cover AIOpsLab detector metadata and persisted history payloads.
- UI contract tests cover all three AIOpsLab tabs, result URL filters/pagination, detail actions and no fabricated metrics.
- Existing unit, Go guard and CLI tests remain green.
- JavaScript syntax checks run for all UI scripts.
- CI starts the control plane on `127.0.0.1:18180` and captures system overview, recovery, all three AIOpsLab tabs, experiment results, and experiment detail at the reference desktop viewport.
- No work is considered complete until the screenshots are produced and the workflow succeeds.

## External-runtime boundary

GitHub CI cannot prove real Kubernetes/Prometheus/Chaos Mesh/OpenAI/AIOpsLab infrastructure behavior. Code paths, readiness gates, Mock-safe integration tests and server startup are verified in CI; external Real execution remains a final environment-specific validation and is reported explicitly rather than simulated.
