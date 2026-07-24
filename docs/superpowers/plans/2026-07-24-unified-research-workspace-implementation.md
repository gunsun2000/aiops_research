# Unified Research Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace disconnected Control Plane feature pages with one experiment workspace whose Evidence, Agent reviews, consensus, safety validation, execution, and artifacts share a single experiment session.

**Architecture:** The backend normalizes mutual-supervision reports into an immutable `ExperimentSession` and stores recent sessions in a bounded process-local registry while retaining the existing JSONL artifact store. The static frontend uses one `currentSession` state object, a five-route information architecture, a seven-stage experiment timeline, and an explicit platform API-version handshake.

**Tech Stack:** FastAPI, Pydantic, Python dataclasses, vanilla JavaScript, CSS, pytest, in-app browser/Playwright verification.

## Global Constraints

- This plan consumes the Research Protocol Framework plan and its profile APIs.
- The platform exposes mock execution only.
- Real Kubernetes execution remains CLI-gated.
- Every stage displayed for one run must use the same `experiment_id`.
- Non-2xx API responses must never render as empty successful reports.
- The UI must distinguish browser mock sessions, server real artifacts, AIOpsLab results, and full-stack results.
- Desktop and mobile layouts must not overflow or overlap.
- Existing artifact download path protections must remain intact.

---

### Task 1: Normalized Experiment Session and Session Registry

**Files:**
- Create: `src/aiops_k8s_agents/experiment_session.py`
- Create: `tests/test_experiment_session.py`

**Interfaces:**
- Produces: `ExperimentStage`, `ExperimentSession`
- Produces: `normalize_experiment_session(report) -> ExperimentSession`
- Produces: `InMemoryExperimentSessionStore`

- [ ] **Step 1: Write failing normalization tests**

```python
def test_mutual_report_normalizes_to_one_experiment_session():
    session = normalize_experiment_session(mutual_report_fixture())
    assert session.experiment_id == mutual_report_fixture()["run_id"]
    assert session.protocol_profile["profile_id"] == "four-agent-role-veto-v1"
    assert session.stages["evidence"]["status"] == "completed"
    assert session.stages["consensus"]["experiment_id"] == session.experiment_id
    assert session.stages["safety"]["experiment_id"] == session.experiment_id
    assert session.stages["result"]["experiment_id"] == session.experiment_id


def test_session_store_evicts_oldest_entry():
    store = InMemoryExperimentSessionStore(max_sessions=2)
    store.put(session("one"))
    store.put(session("two"))
    store.put(session("three"))
    assert store.get("one") is None
    assert [item.experiment_id for item in store.list()] == ["three", "two"]
```

- [ ] **Step 2: Run tests and verify missing module failure**

Run: `python -m pytest tests/test_experiment_session.py -v`

Expected: FAIL because `experiment_session.py` does not exist.

- [ ] **Step 3: Implement the immutable session model**

```python
class ExperimentStage(str, Enum):
    CONDITION = "condition"
    EVIDENCE = "evidence"
    DIAGNOSIS = "diagnosis"
    CONSENSUS = "consensus"
    SAFETY = "safety"
    EXECUTION = "execution"
    RESULT = "result"


@dataclass(frozen=True)
class ExperimentSession:
    experiment_id: str
    created_at: str
    mode: str
    status: str
    protocol_profile: Mapping[str, Any]
    condition: Mapping[str, Any]
    stages: Mapping[str, Mapping[str, Any]]
    active_agents: tuple[str, ...]
    human_review_required: bool
    artifacts: Mapping[str, str]
```

Normalize absent stages as `pending`, validation rejection as `blocked`, and
execution completion as `completed` or `failed`. Include `experiment_id` inside
every stage object to make cross-stage mismatch testable.

- [ ] **Step 4: Implement a bounded thread-safe in-memory store**

Use `RLock` and insertion order. `put`, `get`, and `list` return immutable
session objects or serialized copies. Default capacity is 50 sessions.

- [ ] **Step 5: Run session tests**

Run: `python -m pytest tests/test_experiment_session.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/aiops_k8s_agents/experiment_session.py \
  tests/test_experiment_session.py
git commit -m "feat: add normalized experiment sessions"
```

---

### Task 2: Platform Capability, Profile, and Session APIs

**Files:**
- Modify: `src/aiops_k8s_agents/control_plane_data.py`
- Modify: `src/aiops_k8s_agents/control_plane_web.py`
- Modify: `tests/test_control_plane_data.py`
- Create: `tests/test_control_plane_api.py`

**Interfaces:**
- Produces: `GET /api/platform`
- Produces: `GET /api/protocol-profiles`
- Produces: `GET /api/protocol-profiles/{profile_id}`
- Produces: `POST /api/experiments/mock`
- Produces: `GET /api/experiments/{experiment_id}`
- Produces: `GET /api/experiments`

- [ ] **Step 1: Write failing API contract tests**

```python
def test_platform_contract_exposes_api_version(client):
    response = client.get("/api/platform")
    assert response.status_code == 200
    assert response.json() == {
        "api_version": "2026-07-24",
        "service": "aiops-control-plane",
        "execution_boundary": "mock-only",
        "capabilities": [
            "experiment-sessions",
            "protocol-profiles",
            "mutual-supervision",
            "artifact-browser",
        ],
    }


def test_mock_experiment_can_be_retrieved_by_id(client):
    created = client.post("/api/experiments/mock", json=mock_request()).json()
    fetched = client.get(
        f"/api/experiments/{created['experiment_id']}"
    ).json()
    assert fetched == created
```

- [ ] **Step 2: Run API tests and verify route failures**

Run:

```bash
python -m pytest \
  tests/test_control_plane_data.py \
  tests/test_control_plane_api.py -v
```

Expected: FAIL with 404 for the new endpoints.

- [ ] **Step 3: Add typed request and response wiring**

Extend the mock request with:

```python
protocol_profile: str = "four-agent-role-veto-v1"
scenario: str = "cpu-stress"
```

`run_experiment_mock(...)` must load the selected profile, construct the
profile-driven Coordinator, normalize the report, save it in the session store,
and return `session.to_dict()`.

- [ ] **Step 4: Add capability and profile endpoints**

The platform endpoint is a constant contract. Profile endpoints load only the
configured profile directory and return safe serialized fields. Unknown
profiles return 404; invalid profiles fail startup tests rather than being
silently omitted.

- [ ] **Step 5: Add session endpoints**

`GET /api/experiments` returns newest-first session summaries.
`GET /api/experiments/{id}` returns 404 when absent. The process-local registry
is explicitly described as UI convenience; durable evidence remains the JSONL
artifact store.

- [ ] **Step 6: Preserve old endpoints as compatibility aliases**

`/api/mutual-supervision/mock` may call the new execution function and return
the legacy report shape during one compatibility cycle. Add a deprecation
marker in metadata but do not break existing tests or CLI consumers.

- [ ] **Step 7: Run API tests**

Run:

```bash
python -m pytest \
  tests/test_control_plane_data.py \
  tests/test_control_plane_api.py \
  tests/test_control_plane_ui.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/aiops_k8s_agents/control_plane_data.py \
  src/aiops_k8s_agents/control_plane_web.py \
  tests/test_control_plane_data.py \
  tests/test_control_plane_api.py
git commit -m "feat: add unified experiment session APIs"
```

---

### Task 3: Frontend API Client and Shared Session State

**Files:**
- Create: `ui/control_plane_static/platform-api.js`
- Create: `ui/control_plane_static/experiment-state.js`
- Modify: `ui/control_plane_static/index.html`
- Modify: `ui/control_plane_static/app.js`
- Modify: `tests/test_control_plane_ui.py`

**Interfaces:**
- Produces: `window.PlatformApi`
- Produces: `window.ExperimentState`
- Consumes: platform and experiment APIs from Task 2

- [ ] **Step 1: Write failing static-contract tests**

```python
def test_ui_loads_api_and_session_modules_before_app():
    html = INDEX.read_text(encoding="utf-8")
    assert html.index("platform-api.js") < html.index("app.js")
    assert html.index("experiment-state.js") < html.index("app.js")


def test_sidebar_uses_research_work_units():
    source = APP.read_text(encoding="utf-8")
    for label in (
        "연구 개요",
        "운영 실험",
        "Agent & Policy",
        "실험 기록",
        "연구 문서",
    ):
        assert label in source
```

- [ ] **Step 2: Run UI tests and verify failure**

Run: `python -m pytest tests/test_control_plane_ui.py -v`

Expected: FAIL because the new modules and route labels do not exist.

- [ ] **Step 3: Implement a strict API client**

```javascript
async function requestJson(path, options = {}) {
  const response = await fetch(path, options);
  let payload = null;
  try {
    payload = await response.json();
  } catch (error) {
    throw new PlatformApiError(path, response.status, "invalid JSON response");
  }
  if (!response.ok) {
    throw new PlatformApiError(
      path,
      response.status,
      payload.detail || "request failed"
    );
  }
  return payload;
}
```

Expose `platform()`, `profiles()`, `runMockExperiment(payload)`,
`experiment(id)`, and `experiments()` under `window.PlatformApi`.

- [ ] **Step 4: Implement shared session state**

```javascript
const state = {
  platform: null,
  profiles: [],
  currentSession: null,
  experimentHistory: [],
  latestServerRun: null,
  request: { running: false, error: null },
};
```

Expose getters, immutable shallow updates, subscription, and
`setCurrentSession`. Remove `mockResult` and `mutualResult` as independent
sources of truth.

- [ ] **Step 5: Implement the API-version handshake**

The UI expects `api_version === "2026-07-24"`. If `/api/platform` is missing,
returns non-2xx, or reports another version, show a full-width
`서버 재시작 필요` notice with exact restart commands. Disable experiment
execution until the contract matches.

- [ ] **Step 6: Replace the seven-route navigation**

Use:

```javascript
const ROUTES = [
  { key: "overview", hash: "#/overview", label: "연구 개요" },
  { key: "workspace", hash: "#/workspace", label: "운영 실험" },
  { key: "agents", hash: "#/agents", label: "Agent & Policy" },
  { key: "records", hash: "#/records", label: "실험 기록" },
  { key: "documents", hash: "#/documents", label: "연구 문서" },
];
```

Redirect old hashes to the closest new route so saved URLs do not render blank
screens.

- [ ] **Step 7: Run static UI tests**

Run: `python -m pytest tests/test_control_plane_ui.py -v`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add ui/control_plane_static/platform-api.js \
  ui/control_plane_static/experiment-state.js \
  ui/control_plane_static/index.html \
  ui/control_plane_static/app.js \
  tests/test_control_plane_ui.py
git commit -m "refactor: share experiment state across control plane"
```

---

### Task 4: Unified Operating Experiment Workspace

**Files:**
- Modify: `ui/control_plane_static/app.js`
- Modify: `ui/control_plane_static/styles.css`
- Modify: `tests/test_control_plane_ui.py`

**Interfaces:**
- Consumes: `ExperimentState.currentSession`
- Produces: seven-stage workspace rendered from one session

- [ ] **Step 1: Write failing workspace structure tests**

```python
def test_workspace_contains_seven_connected_stages():
    source = APP.read_text(encoding="utf-8")
    for stage in (
        "조건 설정",
        "Evidence",
        "Agent 진단",
        "상호검토·합의",
        "안전 검증",
        "실행·복구 관찰",
        "결과·산출물",
    ):
        assert stage in source


def test_workspace_uses_current_session_only():
    source = APP.read_text(encoding="utf-8")
    assert "currentSession" in source
    assert "mockResult" not in source
    assert "mutualResult" not in source
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_control_plane_ui.py -v`

Expected: FAIL because old disconnected views still exist.

- [ ] **Step 3: Build the experiment header and stage navigator**

Display experiment ID, profile ID/version, mode, target, current status, and
human-review state. The stage navigator reads `session.stages`; completed,
blocked, failed, and pending are visually distinct and do not resize when
status changes.

- [ ] **Step 4: Build the connected decision timeline**

Render in order:

1. Evidence snapshot
2. HA diagnosis
3. Application proposal
4. peer reviews with scope and verdict
5. negotiation rounds and revisions
6. safety validation
7. execution result
8. post-execution reviews

Every timeline row displays the common experiment ID through context, not as
repeated decorative text.

- [ ] **Step 5: Build the execution context rail**

Show selected Action, bounded command, Validator backend, recovery state,
artifact links, profile hash, and active Agents. On narrow screens this rail
moves below the timeline; it must not become a nested card.

- [ ] **Step 6: Wire the run form**

The form selects scenario, protocol profile, metric, value, threshold,
namespace, deployment, and validation backend. Submit once to
`POST /api/experiments/mock`; store the returned session and render all stages.
Running state must show elapsed time and disable duplicate submissions.

- [ ] **Step 7: Replace disconnected page CSS**

Use full-width bands and a restrained research-tool palette. Avoid card nesting.
Set stable grid tracks, minimum column widths, and stage dimensions. At
`max-width: 900px`, collapse to one column and preserve readable labels.

- [ ] **Step 8: Run UI tests**

Run: `python -m pytest tests/test_control_plane_ui.py -v`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add ui/control_plane_static/app.js \
  ui/control_plane_static/styles.css \
  tests/test_control_plane_ui.py
git commit -m "feat: add unified operating experiment workspace"
```

---

### Task 5: Agent & Policy and Unified Experiment Records

**Files:**
- Modify: `ui/control_plane_static/app.js`
- Modify: `ui/control_plane_static/styles.css`
- Modify: `src/aiops_k8s_agents/control_plane_data.py`
- Modify: `tests/test_control_plane_data.py`
- Modify: `tests/test_control_plane_ui.py`

**Interfaces:**
- Consumes: protocol profiles and session history APIs
- Produces: profile comparison, current-session evidence, server artifact archive

- [ ] **Step 1: Write failing policy and records tests**

```python
def test_agent_policy_view_exposes_consensus_profiles():
    source = APP.read_text(encoding="utf-8")
    assert "role_based_veto" in source
    assert "unanimous_veto" in source
    assert "weighted_majority" in source


def test_records_distinguish_mock_and_real_sources():
    records = build_experiment_records(...)
    assert {item["source"] for item in records} >= {
        "platform-mock",
        "server-recovery-run",
    }
```

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```bash
python -m pytest \
  tests/test_control_plane_data.py \
  tests/test_control_plane_ui.py -v
```

Expected: FAIL because unified records and policy comparison are absent.

- [ ] **Step 3: Implement Agent & Policy view**

Show active Agents, runtime, capabilities, veto scopes, review edges,
consensus strategy, rounds, fallback, Action space, reward weights, version,
and hash. Compare profiles by fields rather than marketing copy.

- [ ] **Step 4: Implement unified records view**

List the in-process current session first, followed by durable server runs.
Each item displays source, mode, profile, scenario, timestamp, success,
recovery time when available, and artifact links. Never merge mock and real
statistics into one unlabeled aggregate.

- [ ] **Step 5: Preserve research documents**

Keep DOCX documents and architecture image in the `연구 문서` route. Update
links only when filenames or source paths changed; do not duplicate document
descriptions in the experiment workspace.

- [ ] **Step 6: Run focused tests**

Run:

```bash
python -m pytest \
  tests/test_control_plane_data.py \
  tests/test_control_plane_ui.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add ui/control_plane_static/app.js \
  ui/control_plane_static/styles.css \
  src/aiops_k8s_agents/control_plane_data.py \
  tests/test_control_plane_data.py \
  tests/test_control_plane_ui.py
git commit -m "feat: unify protocol and experiment record views"
```

---

### Task 6: Browser Verification, Documentation, and Final Regression

**Files:**
- Modify: `README.md`
- Modify: `docs/submission/control_plane_ui_guide.md`
- Modify: `docs/submission/execution_code_guide.md`

**Interfaces:**
- Verifies all outputs from Tasks 1-5

- [ ] **Step 1: Run the complete automated suite**

Run: `python -m pytest`

Expected: all tests pass.

- [ ] **Step 2: Run Go Guard tests**

Run: `cd go/aiops-guard && go test ./...`

Expected: Go Guard package passes.

- [ ] **Step 3: Start a fresh Control Plane process**

Stop the previous process before testing because FastAPI route tables are loaded
at process startup.

Run:

```bash
conda activate aiops_research
python -m pip install -e ".[ui,dev]"
aiops-control-plane
```

Expected: `/api/platform` returns `api_version: 2026-07-24`.

- [ ] **Step 4: Verify the desktop workflow**

At `http://127.0.0.1:18080/#/workspace`:

- run one mock experiment;
- verify all seven stages use one experiment ID;
- verify profile ID/hash and active Agents;
- verify peer reviews, consensus, safety, execution, and post-review;
- navigate to Agent & Policy and Records, then return;
- verify the current session remains selected;
- verify no console errors.

- [ ] **Step 5: Verify responsive layout**

Check desktop and a 390×844 viewport. Verify no horizontal overflow, clipped
buttons, overlapping timeline labels, or context rail occlusion.

- [ ] **Step 6: Verify stale-server messaging**

Test the frontend against a server missing `/api/platform` or with a mismatched
version fixture. Verify the UI shows `서버 재시작 필요`, the restart command,
and disables execution.

- [ ] **Step 7: Update documentation**

Document the five routes, single-session flow, profile selection, mock/real
boundary, server restart requirement after backend updates, and paths to
durable experiment evidence.

- [ ] **Step 8: Run final checks**

Run:

```bash
python -m compileall -q src
git diff --check
python -m pytest
cd go/aiops-guard && go test ./...
```

Expected: all commands pass.

- [ ] **Step 9: Commit**

```bash
git add README.md \
  docs/submission/control_plane_ui_guide.md \
  docs/submission/execution_code_guide.md
git commit -m "docs: explain unified research workspace"
```

