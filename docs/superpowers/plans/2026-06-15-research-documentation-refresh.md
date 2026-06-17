# Research Documentation Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update the project documentation so the completed AIOpsLab and 36-treatment real Kubernetes experiments are immediately understandable and reproducible.

**Architecture:** Keep `README.md` as a short project map, use `first_stage_research_completion.md` as the authoritative status report, use `recovery_action_experiment_guide.md` for method and results, and keep `experiment_commands.md` as the command reference. Clearly separate deterministic real experiments from AutoGen GroupChat experiments.

**Tech Stack:** Markdown, Python/pytest verification, Git link and command validation.

---

### Task 1: Simplify the project entry point

**Files:**
- Modify: `README.md`

- [x] Replace the long historical narrative with the research goal, architecture, completed experiments, current limitations, and links to detailed documents.
- [x] Move CPU 95% to an optional smoke-test note rather than presenting it as a research result.

### Task 2: Update the research completion report

**Files:**
- Modify: `docs/archive/first_stage_research_completion.md`

- [x] Add the AIOpsLab 12-run detection result.
- [x] Add the 12-treatment pilot and 36-treatment real recovery results.
- [x] Mark reward-policy comparison and fault-specific action selection as completed.
- [x] Separate remaining AutoGen-real, baseline, ablation, and statistical-analysis work.

### Task 3: Complete the recovery experiment guide

**Files:**
- Modify: `docs/experiments/recovery_action_experiment_guide.md`

- [x] Record the verified Prometheus blackbox latency query and the final commands.
- [x] Add the 36-run selected-action table for all four reward policies.
- [x] Explain the interpretation and limitations without claiming AutoGen selected these actions.

### Task 4: Put current server commands first

**Files:**
- Modify: `docs/experiments/experiment_commands.md`

- [x] Add a top-level quick-start section for environment setup, Prometheus readiness, 12-run pilot, 36-run experiment, and result inspection.
- [x] Keep older local/mock commands as reference material below the current real-experiment workflow.

### Task 5: Verify documentation

**Files:**
- Verify: `README.md`
- Verify: `docs/archive/first_stage_research_completion.md`
- Verify: `docs/experiments/recovery_action_experiment_guide.md`
- Verify: `docs/experiments/experiment_commands.md`

- [x] Run `python -m pytest` and confirm all tests pass.
- [x] Search the updated documents for the expected `36/36`, AutoGen boundary, and result paths.
- [x] Run `git diff --check` and inspect the final diff.
