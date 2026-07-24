# Mutual-Supervision 4-Agent AIOps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic, configurable mutual-supervision engine in which the four AIOps agents peer-review, revise, veto, execute, and post-review bounded Kubernetes recovery actions while preserving existing coordinators and CLI behavior.

**Architecture:** Add focused protocol, policy, orchestration, and event-store modules beside the existing sequential and autonomous coordinators. The new coordinator reuses the existing evidence provider, application candidates, infrastructure/cost policies, validator, executor, and recovery monitor; it adds structured peer reviews, bounded negotiation, post-execution reviews, and research artifacts.

**Tech Stack:** Python 3.11+, dataclasses, Enum, argparse, JSON/JSONL/CSV, pytest, existing Kubernetes executor and validators.

## Global Constraints

- Keep `AIMCMPCoordinator`, `AutonomousAIOpsCoordinator`, and all existing CLI commands compatible.
- Default research profile contains HA, Application, Infrastructure, and Cost agents.
- The coordinator routes state and applies protocol rules; it does not invent an unreviewed action.
- A domain `VETO` cannot be overridden by reward.
- Negotiation is bounded to two rounds by default.
- Unknown metrics remain safe and do not trigger scale-out.
- Real mode always enforces validator, allowlist, replica bounds, and bounded actions.
- LLM free text is never executed as a shell command.
- First implementation is deterministic; AutoGen uses the same protocol in a later extension.
- Persist experiment configuration and structured events with stable run, decision, review, and action identifiers.

---

## File Structure

- Create `src/aiops_k8s_agents/mutual_supervision_models.py`
  - Structured decisions, reviews, negotiation rounds, post-execution reviews, verdicts, and serialization.
- Create `src/aiops_k8s_agents/mutual_supervision_policy.py`
  - Versioned policy loading, review matrix, round/replan bounds, and fallback behavior.
- Create `src/aiops_k8s_agents/research_event_store.py`
  - In-memory test sink and JSONL/JSON/Markdown/CSV artifact writer.
- Create `src/aiops_k8s_agents/mutual_supervision.py`
  - Deterministic peer-review, negotiation, safety execution, recovery monitoring, and post-review coordinator.
- Create `config/mutual_supervision_policy.json`
  - Default four-agent review graph and bounded protocol settings.
- Modify `src/aiops_k8s_agents/cli.py`
  - Add `mutual-supervision-run`.
- Modify `src/aiops_k8s_agents/__init__.py`
  - Export the new coordinator and public protocol types.
- Create `tests/test_mutual_supervision_models.py`
- Create `tests/test_mutual_supervision_policy.py`
- Create `tests/test_mutual_supervision.py`
- Create `tests/test_mutual_supervision_event_store.py`
- Modify `tests/test_cli.py`
- Modify `README.md`
  - Add a concise research-engine description and command link without expanding unrelated scope.

---

### Task 1: Structured Mutual-Supervision Protocol Models

**Files:**
- Create: `tests/test_mutual_supervision_models.py`
- Create: `src/aiops_k8s_agents/mutual_supervision_models.py`

**Interfaces:**
- Produces: `ReviewVerdict`, `SupervisionDecision`, `PeerReview`, `NegotiationRound`, `PostExecutionReview`, `new_trace_id(prefix: str) -> str`, and `to_serializable(value: Any) -> Any`.
- Consumes: `RecoveryAction` from `aiops_k8s_agents.models`.

- [ ] **Step 1: Write failing model tests**

```python
from aiops_k8s_agents.models import RecoveryAction, RecoveryActionKind
from aiops_k8s_agents.mutual_supervision_models import (
    PeerReview,
    ReviewVerdict,
    SupervisionDecision,
    to_serializable,
)


def test_peer_review_serializes_traceable_structured_revision():
    action = RecoveryAction(
        namespace="online-boutique",
        deployment="paymentservice",
        kind=RecoveryActionKind.SCALE_OUT,
        replicas=2,
        reason="cost-bounded revision",
    )
    review = PeerReview(
        review_id="review-1",
        run_id="run-1",
        round_index=1,
        reviewer="CostOptimizationAgent",
        target_agent="AIApplicationManagementAgent",
        target_decision_id="decision-1",
        verdict=ReviewVerdict.REVISE,
        reason="replica 3 exceeds cost policy",
        suggested_action=action,
        confidence=0.91,
        evidence_refs=("current_replicas", "cost_policy"),
        policy_version="mutual-v1",
    )

    payload = to_serializable(review)

    assert payload["verdict"] == "revise"
    assert payload["suggested_action"]["kind"] == "scale_out"
    assert payload["suggested_action"]["replicas"] == 2
    assert payload["evidence_refs"] == ["current_replicas", "cost_policy"]
```

- [ ] **Step 2: Run the model test and verify RED**

Run: `python -m pytest tests/test_mutual_supervision_models.py -v`

Expected: collection fails because `mutual_supervision_models` does not exist.

- [ ] **Step 3: Implement immutable protocol models and recursive serialization**

Implement:

```python
class ReviewVerdict(str, Enum):
    APPROVE = "approve"
    REVISE = "revise"
    VETO = "veto"
    ABSTAIN = "abstain"


@dataclass(frozen=True)
class SupervisionDecision:
    decision_id: str
    run_id: str
    round_index: int
    agent: str
    decision_type: str
    proposed_action: RecoveryAction | None
    approved: bool
    reason: str
    confidence: float
    evidence_refs: tuple[str, ...]
    reward: float
    policy_version: str


@dataclass(frozen=True)
class PeerReview:
    review_id: str
    run_id: str
    round_index: int
    reviewer: str
    target_agent: str
    target_decision_id: str
    verdict: ReviewVerdict
    reason: str
    suggested_action: RecoveryAction | None
    confidence: float
    evidence_refs: tuple[str, ...]
    policy_version: str
```

Add equivalent immutable `NegotiationRound` and `PostExecutionReview` models and a serializer that converts dataclasses, enum members, tuples, and nested actions to JSON-compatible values.

- [ ] **Step 4: Run model tests and verify GREEN**

Run: `python -m pytest tests/test_mutual_supervision_models.py -v`

Expected: all tests pass.

---

### Task 2: Versioned Review and Consensus Policy

**Files:**
- Create: `tests/test_mutual_supervision_policy.py`
- Create: `src/aiops_k8s_agents/mutual_supervision_policy.py`
- Create: `config/mutual_supervision_policy.json`

**Interfaces:**
- Produces: `MutualSupervisionPolicy`, `load_mutual_supervision_policy(path)`.
- `MutualSupervisionPolicy.reviewers_for(target_agent: str) -> tuple[str, ...]`.
- `MutualSupervisionPolicy` fields: `version`, `max_negotiation_rounds`, `max_replan_attempts`, `fallback_action`, `review_matrix`.

- [ ] **Step 1: Write failing policy tests**

```python
def test_default_policy_requires_three_reviews_for_application_action():
    policy = load_mutual_supervision_policy("config/mutual_supervision_policy.json")

    assert policy.version == "mutual-supervision-v1"
    assert policy.max_negotiation_rounds == 2
    assert policy.max_replan_attempts == 1
    assert policy.reviewers_for("AIApplicationManagementAgent") == (
        "AIServiceHASupportAgent",
        "AISemiconductorInfraOpsAgent",
        "CostOptimizationAgent",
    )
```

Also test rejection of zero rounds, unknown fallback actions, missing default agents, and reviewers not present in the configured registry.

- [ ] **Step 2: Run policy tests and verify RED**

Run: `python -m pytest tests/test_mutual_supervision_policy.py -v`

Expected: import failure for the missing policy module.

- [ ] **Step 3: Add the default JSON policy**

```json
{
  "version": "mutual-supervision-v1",
  "max_negotiation_rounds": 2,
  "max_replan_attempts": 1,
  "fallback_action": "observe_only",
  "review_matrix": {
    "AIServiceHASupportAgent": [
      "AIApplicationManagementAgent",
      "AISemiconductorInfraOpsAgent"
    ],
    "AIApplicationManagementAgent": [
      "AIServiceHASupportAgent",
      "AISemiconductorInfraOpsAgent",
      "CostOptimizationAgent"
    ],
    "AISemiconductorInfraOpsAgent": [
      "AIApplicationManagementAgent",
      "CostOptimizationAgent"
    ],
    "CostOptimizationAgent": [
      "AIApplicationManagementAgent",
      "AISemiconductorInfraOpsAgent"
    ]
  }
}
```

- [ ] **Step 4: Implement strict policy loading**

Parse JSON into an immutable policy, validate positive round bounds, validate `fallback_action` against `RecoveryActionKind`, and verify that every target and reviewer is one of the default four registered names.

- [ ] **Step 5: Run policy tests and verify GREEN**

Run: `python -m pytest tests/test_mutual_supervision_policy.py -v`

Expected: all tests pass.

---

### Task 3: Deterministic Peer Review and Bounded Negotiation

**Files:**
- Create: `tests/test_mutual_supervision.py`
- Create: `src/aiops_k8s_agents/mutual_supervision.py`

**Interfaces:**
- Produces: `MutualSupervisionCoordinator.run(namespace: str, deployment: str, metric: str, threshold: float) -> dict[str, Any]`.
- Constructor consumes existing `CommandValidator`, `EvidenceProvider`, `RecoveryMonitor`, execution mode/backend, policy, and four existing agents.
- Internal pure functions produce HA, infrastructure, and cost `PeerReview` objects for one application proposal.

- [ ] **Step 1: Write a failing revision-and-consensus test**

```python
def test_cost_agent_revision_changes_replica_target_before_execution():
    coordinator = MutualSupervisionCoordinator(
        validator=_validator(),
        evidence_provider=FakeEvidenceProvider.cpu_saturation(
            "online-boutique", "paymentservice", 95.0
        ),
        recovery_monitor=FakeRecoveryMonitor(default_success=True),
        mode=ExecutionMode.MOCK,
        policy=_policy(max_rounds=2),
        cost_agent=CostOptimizationAgent(max_cost_safe_replicas=2),
    )

    report = coordinator.run(
        namespace="online-boutique",
        deployment="paymentservice",
        metric="cpu",
        threshold=80.0,
    )

    assert report["valid"] is True
    assert report["final_status"] == "recovered"
    assert report["selected_action"]["kind"] == "scale_out"
    assert report["selected_action"]["replicas"] == 2
    assert report["negotiation"]["round_count"] == 2
    assert any(
        review["verdict"] == "revise"
        and review["reviewer"] == "CostOptimizationAgent"
        for review in report["peer_reviews"]
    )
```

- [ ] **Step 2: Run the revision test and verify RED**

Run: `python -m pytest tests/test_mutual_supervision.py::test_cost_agent_revision_changes_replica_target_before_execution -v`

Expected: import failure for `MutualSupervisionCoordinator`.

- [ ] **Step 3: Implement minimal action-review negotiation**

Implement one proposal per round:

1. Diagnose through `AIServiceHASupportAgent`.
2. Generate application candidates.
3. Review the selected candidate through HA, infrastructure, and cost reviewers.
4. Convert a cost limit violation that has a safe lower replica target into `REVISE`.
5. Convert infrastructure capacity violation into `VETO`.
6. Apply structured revisions and repeat until approval or round exhaustion.
7. Keep reward for approved-candidate ranking only; never use it to remove a veto.

- [ ] **Step 4: Run the revision test and verify GREEN**

Run: `python -m pytest tests/test_mutual_supervision.py::test_cost_agent_revision_changes_replica_target_before_execution -v`

Expected: pass.

- [ ] **Step 5: Write failing Veto and safe-stop tests**

Test:

- infrastructure `VETO` prevents the rejected scale-out from reaching the executor;
- max-round exhaustion returns `safe_stopped`;
- unknown metric returns `no_action_required` with no candidate execution;
- every required reviewer appears in the report.

- [ ] **Step 6: Run the new tests and verify RED**

Run: `python -m pytest tests/test_mutual_supervision.py -v`

Expected: failures for missing veto, safe-stop, or trace behavior.

- [ ] **Step 7: Implement veto, fallback, and trace-complete reports**

Return reports with:

```python
{
    "command": "mutual-supervision-run",
    "valid": bool,
    "mode": str,
    "final_status": str,
    "run_id": str,
    "policy_version": str,
    "evidence": dict,
    "diagnosis": dict,
    "initial_decisions": list,
    "peer_reviews": list,
    "negotiation": {
        "round_count": int,
        "rounds": list,
        "consensus": str,
    },
    "selected_action": dict,
    "safety_validation": dict,
    "execution_result": dict,
    "post_execution_reviews": list,
    "replanning_attempts": list,
    "human_review_required": bool,
}
```

- [ ] **Step 8: Run all mutual-supervision tests and verify GREEN**

Run: `python -m pytest tests/test_mutual_supervision.py -v`

Expected: all tests pass.

---

### Task 4: Safety Execution, Recovery Replanning, and Post-Execution Review

**Files:**
- Modify: `tests/test_mutual_supervision.py`
- Modify: `src/aiops_k8s_agents/mutual_supervision.py`

**Interfaces:**
- Reuses `CommandValidator.validate_recovery_action`, `KubernetesExecutor.execute_recovery`, and `RecoveryMonitor.assess`.
- Produces role-specific `PostExecutionReview` records and bounded replanning.

- [ ] **Step 1: Write failing safety and replanning tests**

Test:

```python
def test_validation_failure_never_appears_in_executed_actions():
    coordinator = _coordinator(
        validator=CommandValidator(
            allowed_namespaces={"online-boutique"},
            allowed_deployments={"checkoutservice"},
            min_replicas=1,
            max_replicas=5,
        )
    )

    report = coordinator.run(
        "online-boutique", "paymentservice", "cpu", 80.0
    )

    assert report["valid"] is False
    assert report["execution_result"]["command"] == ""
    assert report["executed_actions"] == []
    assert report["human_review_required"] is True
```

Also test a failed first recovery that moves to a different bounded candidate and a successful action that produces four post-execution reviews.

- [ ] **Step 2: Run the safety tests and verify RED**

Run: `python -m pytest tests/test_mutual_supervision.py -v`

Expected: failures for missing validation, replanning, or post-review fields.

- [ ] **Step 3: Connect the existing safety and recovery layers**

For each consensus action:

1. Validate the structured action.
2. Execute only when validation succeeds.
3. Collect after-evidence.
4. Assess recovery.
5. Generate HA/Application/Infrastructure/Cost post-reviews.
6. Return success only when recovery assessment and mandatory post-reviews approve.
7. Otherwise exclude the failed candidate and re-enter bounded negotiation.
8. Stop with `human_review_required` after `max_replan_attempts`.

- [ ] **Step 4: Run safety and full mutual-supervision tests**

Run: `python -m pytest tests/test_mutual_supervision.py -v`

Expected: all tests pass.

---

### Task 5: Reproducible Research Event Artifacts

**Files:**
- Create: `tests/test_mutual_supervision_event_store.py`
- Create: `src/aiops_k8s_agents/research_event_store.py`
- Modify: `src/aiops_k8s_agents/mutual_supervision.py`

**Interfaces:**
- Produces: `ResearchEventSink` protocol, `InMemoryResearchEventStore`, `JsonlResearchEventStore`.
- `append(stream: str, payload: dict[str, Any]) -> None`.
- `finalize(report: dict[str, Any]) -> dict[str, str]`.

- [ ] **Step 1: Write failing artifact tests**

```python
def test_jsonl_event_store_writes_traceable_research_artifacts(tmp_path):
    store = JsonlResearchEventStore(
        root_dir=tmp_path,
        experiment_id="experiment-1",
    )
    store.append("peer_reviews", {"run_id": "run-1", "review_id": "review-1"})
    paths = store.finalize(
        {
            "run_id": "run-1",
            "valid": True,
            "final_status": "recovered",
            "peer_reviews": [{"verdict": "approve"}],
            "negotiation": {"round_count": 1},
        }
    )

    assert Path(paths["peer_reviews"]).exists()
    assert Path(paths["final_report_json"]).exists()
    assert Path(paths["final_report_md"]).exists()
    assert Path(paths["statistics_csv"]).exists()
```

- [ ] **Step 2: Run event-store tests and verify RED**

Run: `python -m pytest tests/test_mutual_supervision_event_store.py -v`

Expected: import failure for the missing event-store module.

- [ ] **Step 3: Implement append-only JSONL and final reports**

Use UTF-8 JSON Lines for event streams. Write:

- `experiment_config.json`
- `evidence.jsonl`
- `initial_decisions.jsonl`
- `peer_reviews.jsonl`
- `negotiation_rounds.jsonl`
- `safety_validations.jsonl`
- `executed_actions.jsonl`
- `post_execution_reviews.jsonl`
- `final_report.json`
- `final_report.md`
- `statistics.csv`

The Markdown and CSV summary include consensus status, round count, review counts by verdict, selected action, recovery result, human review, and policy version.

- [ ] **Step 4: Run event-store tests and verify GREEN**

Run: `python -m pytest tests/test_mutual_supervision_event_store.py -v`

Expected: all tests pass.

---

### Task 6: CLI, Public Exports, and Research Documentation

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `src/aiops_k8s_agents/cli.py`
- Modify: `src/aiops_k8s_agents/__init__.py`
- Modify: `README.md`

**Interfaces:**
- Adds CLI command `aiops-k8s-agents mutual-supervision-run`.
- Uses default policy `config/mutual_supervision_policy.json`.
- Persists runs below `runs/mutual-supervision` unless `--no-save` is supplied.

- [ ] **Step 1: Write failing CLI tests**

```python
def test_cli_mutual_supervision_run_emits_peer_reviews_and_artifacts(tmp_path, capsys):
    exit_code = main(
        [
            "mutual-supervision-run",
            "--mode", "mock",
            "--namespace", "online-boutique",
            "--deployment", "paymentservice",
            "--metric", "cpu",
            "--threshold", "80",
            "--evidence-value", "95",
            "--allowed-namespace", "online-boutique",
            "--allowed-deployment", "paymentservice",
            "--output-dir", str(tmp_path),
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["command"] == "mutual-supervision-run"
    assert output["negotiation"]["consensus"] == "approved"
    assert len(output["peer_reviews"]) >= 3
    assert Path(output["artifacts"]["final_report_json"]).exists()
```

- [ ] **Step 2: Run the CLI test and verify RED**

Run: `python -m pytest tests/test_cli.py::test_cli_mutual_supervision_run_emits_peer_reviews_and_artifacts -v`

Expected: argparse rejects the unknown command.

- [ ] **Step 3: Add parser, CLI factory, exports, and concise README usage**

Add arguments parallel to `autonomous-run`:

- `--mode`
- `--guard-backend`
- `--evidence-source`
- `--namespace`
- `--deployment`
- `--metric`
- `--threshold`
- `--evidence-value`
- `--desired-replicas`
- `--available-replicas`
- `--restart-count`
- `--allowed-namespace`
- `--allowed-deployment`
- `--min-replicas`
- `--max-replicas`
- `--policy`
- `--output-dir`
- `--no-save`

Export `MutualSupervisionCoordinator`, `ReviewVerdict`, and `PeerReview` from the package root. Add one README section linking to the design and showing a safe mock command.

- [ ] **Step 4: Run CLI and focused tests**

Run:

```powershell
python -m pytest tests/test_cli.py tests/test_mutual_supervision_models.py tests/test_mutual_supervision_policy.py tests/test_mutual_supervision.py tests/test_mutual_supervision_event_store.py -v
```

Expected: all tests pass.

---

### Task 7: Control Plane Mutual-Supervision Workspace

**Files:**
- Modify: `src/aiops_k8s_agents/control_plane_data.py`
- Modify: `src/aiops_k8s_agents/control_plane_web.py`
- Modify: `ui/control_plane_static/app.js`
- Modify: `ui/control_plane_static/styles.css`
- Modify: `tests/test_control_plane_data.py`
- Modify: `tests/test_control_plane_ui.py`

**Interfaces:**
- Adds mock-only endpoint `POST /api/mutual-supervision/mock`.
- Adds independent sidebar route `#/supervision`.
- Displays initial decisions, peer reviews, negotiation rounds, safety execution,
  and post-execution reviews without extending the dashboard page.

- [ ] **Step 1: Write failing backend and route tests**

Test that the platform mock API uses the real deterministic
`MutualSupervisionCoordinator`, returns at least three peer reviews and four
post-execution reviews, and that the UI defines the independent supervision
route and timeline renderers.

- [ ] **Step 2: Verify RED**

Run:

```powershell
python -m pytest tests/test_control_plane_data.py tests/test_control_plane_ui.py -v
```

Expected: failures for the missing API function and supervision route.

- [ ] **Step 3: Implement the mock API and separate workspace**

Keep real execution CLI-gated. Reuse the existing form state and render:

1. initial Agent decisions;
2. peer review verdicts;
3. negotiation rounds and revisions;
4. safety validation and bounded command;
5. four role-specific post-execution reviews.

- [ ] **Step 4: Run platform tests and browser verification**

Run platform tests, start `aiops-control-plane`, and inspect desktop and mobile
viewports with the supervision route selected.

---

### Task 8: Full Regression and Verification

**Files:**
- Verify all files changed in Tasks 1-6.

**Interfaces:**
- No new interfaces.

- [ ] **Step 1: Run formatting-neutral diff checks**

Run: `git diff --check`

Expected: no whitespace errors.

- [ ] **Step 2: Run the complete Python suite**

Run: `python -m pytest`

Expected: all existing 140 tests plus new tests pass.

- [ ] **Step 3: Run a real CLI smoke test in mock mode**

Run:

```powershell
aiops-k8s-agents mutual-supervision-run `
  --mode mock `
  --namespace online-boutique `
  --deployment paymentservice `
  --metric cpu `
  --threshold 80 `
  --evidence-value 95 `
  --allowed-namespace online-boutique `
  --allowed-deployment paymentservice `
  --no-save
```

Expected:

- `command` equals `mutual-supervision-run`
- `valid` equals `true`
- `peer_reviews` contains HA, infrastructure, and cost reviews
- `negotiation.consensus` equals `approved`
- `execution_result.mode` equals `mock`

- [ ] **Step 4: Review scope and compatibility**

Confirm:

- existing sequential and autonomous modules were not removed;
- no arbitrary command execution was added;
- no `real` safety bypass exists;
- AutoGen was not falsely reported as implemented in this first milestone;
- untracked user files such as `tmp/` remain untouched.

- [ ] **Step 5: Commit the implementation**

```powershell
git add config/mutual_supervision_policy.json `
  src/aiops_k8s_agents/mutual_supervision_models.py `
  src/aiops_k8s_agents/mutual_supervision_policy.py `
  src/aiops_k8s_agents/research_event_store.py `
  src/aiops_k8s_agents/mutual_supervision.py `
  src/aiops_k8s_agents/cli.py `
  src/aiops_k8s_agents/__init__.py `
  tests/test_mutual_supervision_models.py `
  tests/test_mutual_supervision_policy.py `
  tests/test_mutual_supervision.py `
  tests/test_mutual_supervision_event_store.py `
  tests/test_cli.py `
  README.md `
  docs/superpowers/plans/2026-07-24-mutual-supervision-aiops-implementation.md

git commit -m "feat: add mutual-supervision 4-agent research engine"
```

