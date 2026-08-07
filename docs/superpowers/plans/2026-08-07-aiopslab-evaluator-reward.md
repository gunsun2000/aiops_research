# AIOpsLab Evaluator Reward Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace fixed AIOpsLab action rewards with a deterministic post-run Evaluator Agent that emits both per-agent rewards and a team reward from real benchmark evidence.

**Architecture:** Keep the existing four-agent detection policy responsible only for decisions. Add a separate `AIOpsLabEvaluatorAgent` that consumes the completed AIOpsLab result plus recorded decision history, writes an `evaluation` object into each report, and drives aggregate/UI reward metrics from that persisted evaluation. No LLM or external API is required for scoring.

**Tech Stack:** Python 3.13, dataclasses, pytest, existing AIOpsLab JSON reports, existing FastAPI control-plane UI JavaScript.

## Global Constraints

- Apply the new reward behavior only to the AIOpsLab detection path.
- Keep all evaluator outputs bounded to `[-1.0, 1.0]`.
- Use actual `Detection Accuracy`, `TTD`, `steps`, recorded safety/referee status, and evidence-collection actions only.
- Do not fabricate missing measurements; missing component values contribute neutral scores.
- Incorrect final detections must never receive a positive team reward.
- Preserve `average_final_reward` for API compatibility, but redefine it as average evaluator team reward and also expose `average_team_reward` explicitly.
- Expose per-agent reward averages in persisted aggregate results.
- Do not add an OpenAI/API-key dependency for reward calculation.
- Do not change non-AIOpsLab recovery reward behavior.

---

### Task 1: Evaluator Agent Core

**Files:**
- Create: `src/aiops_k8s_agents/aiopslab_evaluator.py`
- Create: `tests/test_aiopslab_evaluator.py`

**Interfaces:**
- Consumes: completed AIOpsLab `results` mapping, decision-history list, `max_steps`, `metrics_duration_minutes`.
- Produces: `AIOpsLabEvaluation` and `AIOpsLabEvaluatorAgent.evaluate(...)`.

- [ ] **Step 1: Write failing tests** for correct vs incorrect runs, TTD/step efficiency ordering, safety penalty, bounded output, and per-agent/team reward keys.
- [ ] **Step 2: Run evaluator tests and verify RED** because the evaluator module does not exist.
- [ ] **Step 3: Implement minimal deterministic evaluator** with rubric version `evaluator-v1`, the approved weighted team score, role-specific credit assignment, clamp helpers, and concise reason text.
- [ ] **Step 4: Run evaluator tests and verify GREEN**.
- [ ] **Step 5: Commit** evaluator core and tests.

### Task 2: Run Integration and Removal of Fixed AIOpsLab Rewards

**Files:**
- Modify: `src/aiops_k8s_agents/aiopslab_detection.py`
- Modify: `scripts/server_aiopslab_auto_detection.py`
- Modify: `tests/test_aiopslab_detection.py`
- Create/Modify: `tests/test_server_aiopslab_evaluator.py`

**Interfaces:**
- Consumes: `AIOpsLabEvaluatorAgent.evaluate(...)` from Task 1.
- Produces: report-level `evaluation` object with `team_reward`, `agent_rewards`, `components`, `reason`.

- [ ] **Step 1: Write failing tests** asserting AIOpsLab decision metadata no longer contains `reward_total`/fixed reward totals and completed report construction includes evaluator output.
- [ ] **Step 2: Run focused tests and verify RED**.
- [ ] **Step 3: Set AIOpsLab execution-path `AgentDecision.reward` values to neutral `0.0` and remove `rewards`/`reward_total` from AIOpsLab decision metadata.**
- [ ] **Step 4: Invoke evaluator after `orchestrator.start_problem(...)` and serialize `evaluation` into the saved report payload.**
- [ ] **Step 5: Run focused tests and verify GREEN.**
- [ ] **Step 6: Commit** integration changes.

### Task 3: Result Parsing and Aggregate Metrics

**Files:**
- Modify: `src/aiops_k8s_agents/aiopslab_results.py`
- Modify: `src/aiops_k8s_agents/aiopslab_job_runner.py`
- Modify: `tests/test_aiopslab_results.py`
- Modify: `tests/test_aiopslab_job_runner.py`

**Interfaces:**
- Consumes: report-level `evaluation.team_reward` and `evaluation.agent_rewards`.
- Produces: run `final_reward`, `agent_rewards`, `average_team_reward`, `average_agent_rewards`, updated Markdown/CSV artifacts.

- [ ] **Step 1: Rewrite fixture reports in tests to use persisted `evaluation` data and add failing assertions for per-agent averages.**
- [ ] **Step 2: Run focused result/runner tests and verify RED.**
- [ ] **Step 3: Replace reverse-decision `reward_total` extraction with report `evaluation` extraction; add per-agent fields to records and summary.**
- [ ] **Step 4: Add `average_team_reward` and `average_agent_rewards` to job aggregate payload while retaining `average_final_reward`.**
- [ ] **Step 5: Update Markdown/CSV summary output to identify Team Reward and individual agent rewards.**
- [ ] **Step 6: Run focused tests and verify GREEN.**
- [ ] **Step 7: Commit** aggregation changes.

### Task 4: UI Reward Semantics

**Files:**
- Modify: `ui/control_plane_static/reference-ui.js`
- Modify: `ui/control_plane_static/research-console-polish.js`
- Modify: `tests/test_complete_research_console_ui.py`

**Interfaces:**
- Consumes: persisted job `average_team_reward` / backward-compatible `average_final_reward` and `average_agent_rewards`.
- Produces: UI copy `Average Team Reward` and per-agent reward display in AIOpsLab job detail without fake values.

- [ ] **Step 1: Write failing UI contract assertions** for `Average Team Reward`, persisted `average_agent_rewards`, and missing-value `—` behavior.
- [ ] **Step 2: Run UI contract tests and verify RED.**
- [ ] **Step 3: Update AIOpsLab comparison/recent-result labels and job-detail rendering to use actual evaluator fields only.**
- [ ] **Step 4: Run UI contract tests and JavaScript syntax checks; verify GREEN.**
- [ ] **Step 5: Commit** UI changes.

### Task 5: Full Verification

**Files:**
- No new production files.

**Interfaces:**
- Validates all earlier tasks together.

- [ ] **Step 1: Run full Python test suite.** Expected: all tests pass.
- [ ] **Step 2: Run `node --check ui/control_plane_static/app.js`, `reference-ui.js`, and `research-console-polish.js`.** Expected: exit 0.
- [ ] **Step 3: Verify GitHub CI/CD and UI Redesign Check on the final commit.** Expected: both successful, including browser screenshot step.
- [ ] **Step 4: Inspect final PR diff to confirm no non-AIOpsLab reward behavior changed and no fabricated metrics were added.**
