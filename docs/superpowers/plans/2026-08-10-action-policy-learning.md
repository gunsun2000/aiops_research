# Action Policy Learning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional Baseline/Contextual Bandit Action Policy layer that learns from completed recovery outcomes without changing the existing 4-Agent safety-bounded execution path.

**Architecture:** The current 4-Agent Coordinator remains the decision and safety boundary. A new policy module consumes normalized recovery outcome records, produces ranked recommendations for `observe_only`, `rollout_restart`, and `scale_out`, and is used in shadow/comparison mode before any optional execution integration. Team Reward remains a post-run evaluator score; the learner never bypasses Agent review, Validator, or Kubernetes execution controls.

**Tech Stack:** Python standard library, existing JSONL/CSV artifacts, existing CLI, FastAPI control-plane API, static HTML/CSS/JavaScript UI, pytest.

## Global Constraints

- Preserve existing deterministic, AutoGen, Mock, Dry-run, and Real command paths.
- Preserve the existing four-Agent Coordinator, Python Validator, optional Go Guard, Recovery Evaluator, and experiment artifact formats.
- Default policy must remain `baseline`.
- Learned recommendations are advisory until explicitly selected and must remain subject to existing safety validation.
- No PPO, online gradient training, or direct autonomous Kubernetes execution is introduced in this change.
- Existing tests must continue to pass.

---

### Task 1: Define the policy learner contract

**Files:**
- Create: `src/aiops_k8s_agents/action_policy.py`
- Test: `tests/test_action_policy.py`

**Interfaces:**
- `PolicyMode = Literal["baseline", "learned"]`
- `PolicySample.from_record(record: Mapping[str, Any]) -> PolicySample`
- `ContextualBanditPolicy.fit(samples: Iterable[PolicySample]) -> None`
- `ContextualBanditPolicy.recommend(context: PolicyContext) -> PolicyRecommendation`
- `load_policy_samples(path: str | Path) -> list[PolicySample]`

- [ ] **Step 1: Write failing tests** for sample normalization, baseline ranking, learned ranking from observed reward, empty-data fallback, and invalid/unsafe actions being excluded.
- [ ] **Step 2: Run `pytest tests/test_action_policy.py -q`** and verify the new tests fail because the module does not exist.
- [ ] **Step 3: Implement the minimum policy learner** using context keys derived from scenario, metric, and cause. Use empirical mean observed utility per context/action with a global fallback. Keep the action set bounded to the existing three registered actions.
- [ ] **Step 4: Run the focused tests** and verify they pass.
- [ ] **Step 5: Refactor only after the focused tests are green** so normalization and ranking helpers remain independently testable.

### Task 2: Add outcome-to-policy dataset generation

**Files:**
- Modify: `src/aiops_k8s_agents/action_policy.py`
- Modify: `src/aiops_k8s_agents/cli.py`
- Test: `tests/test_action_policy.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- New CLI command: `aiops-k8s-agents build-action-policy-dataset --input <outcomes.jsonl> --output <policy_samples.jsonl>`
- New CLI command: `aiops-k8s-agents recommend-action --samples <policy_samples.jsonl> --scenario <id> --metric <name> --cause <cause> --mode {baseline,learned}`

- [ ] **Step 1: Add failing CLI tests** asserting dataset output contains normalized state/action/outcome/reward fields and recommendation output contains ranked candidates, selected action, policy mode, and training sample count.
- [ ] **Step 2: Run the focused CLI tests** and verify the commands are not registered.
- [ ] **Step 3: Add parsers for the existing recovery outcome JSONL format**, preserving `measurement_valid` filtering and rejecting unsafe or invalid samples from learned statistics.
- [ ] **Step 4: Register the two commands** beside the existing recovery statistics commands without changing existing argument behavior.
- [ ] **Step 5: Run focused CLI tests and existing recovery tests**.

### Task 3: Connect recommendations to experiment comparison without changing execution safety

**Files:**
- Modify: `src/aiops_k8s_agents/recovery_comparison_runner.py`
- Modify: `src/aiops_k8s_agents/recovery_statistics.py`
- Test: `tests/test_recovery_comparison_runner.py`
- Test: `tests/test_recovery_statistics.py`

**Interfaces:**
- Comparison request gains `policy_mode: Literal["baseline", "learned"] = "baseline"`.
- Comparison results include `policy_mode`, `recommendation`, and `baseline_vs_learned` metadata.

- [ ] **Step 1: Add failing tests** for baseline default compatibility, learned ranking metadata, and no execution when the recommendation is unsafe or unavailable.
- [ ] **Step 2: Verify the tests fail** with the current request/result schema.
- [ ] **Step 3: Add policy metadata to comparison artifacts** and keep actual Action execution delegated to the existing runner and Validator.
- [ ] **Step 4: Ensure learned mode falls back to baseline when no valid training samples exist** and records the fallback reason.
- [ ] **Step 5: Run comparison and statistics tests**.

### Task 4: Expose policy selection in the control-plane API and UI

**Files:**
- Modify: `src/aiops_k8s_agents/control_plane_web.py`
- Modify: `ui/control_plane_static/index.html`
- Modify: `ui/control_plane_static/app.js`
- Modify: `ui/control_plane_static/styles.css`
- Test: `tests/test_control_plane_web.py`
- Test: `tests/test_control_plane_ui.py`
- Test: `tests/test_complete_research_console_ui.py`

**Interfaces:**
- Experiment request gains `action_policy: Literal["baseline", "learned"] = "baseline"`.
- API responses expose `action_policy`, `policy_recommendation`, and `policy_fallback_reason` when available.

- [ ] **Step 1: Add failing API and static UI tests** for the default baseline policy, learned policy selection, and visible recommendation metadata.
- [ ] **Step 2: Verify the tests fail** because the request and UI do not expose the new field.
- [ ] **Step 3: Add an optional Action Policy selector** inside the existing advanced experiment settings; keep the main screen layout unchanged.
- [ ] **Step 4: Render learned/baseline policy provenance in experiment summaries and results**, clearly labeling recommendations as advisory until safety validation passes.
- [ ] **Step 5: Bump static asset versions and run focused UI/API tests**.

### Task 5: Document the research boundary and validate the full repository

**Files:**
- Modify: `README.md`
- Modify: `docs/experiments/recovery_quantitative_analysis_guide.md`
- Modify: `docs/design/agent_action_reward_policy.md`

- [ ] **Step 1: Document the policy modes**, dataset command, recommendation command, and Baseline versus Learned comparison.
- [ ] **Step 2: Explicitly state that this is contextual/offline policy learning, not PPO or online RL, and that all recommendations remain behind the 4-Agent safety boundary.**
- [ ] **Step 3: Run `python -m pytest` and confirm the full Python suite passes.**
- [ ] **Step 4: Run `cd go/aiops-guard && go test ./...` and confirm the Go Guard suite passes.**
- [ ] **Step 5: Run `git diff --check` and summarize changed files and execution commands.**
