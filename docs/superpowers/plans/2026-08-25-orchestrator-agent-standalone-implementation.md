# Orchestrator-Agent Standalone Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Package every Model Partition Orchestrator capability as an independent, transferable project named `Orchestrator-Agent`.

**Architecture:** A Python package accepts Federated Coordination v0.4 or native partition requests, enriches them with versioned context, deterministically builds and validates training or inference partition candidates, persists the selected `PartitionExecutionPlan`, and processes bounded repartition feedback. A thin CLI and FastAPI/browser layer expose the same service without importing the recovery-oriented 4-Agent AIOps framework.

**Tech Stack:** Python 3.11+, dataclasses, JSON artifacts, FastAPI/Uvicorn, optional scikit-learn ranker, pytest, vanilla HTML/CSS/JavaScript.

---

### Task 1: Establish the standalone package boundary

**Files:**
- Create: `pyproject.toml`
- Create: `src/orchestrator_agent/__init__.py`
- Create: `tests/test_standalone_boundary.py`

1. Add a failing boundary test for package imports, public contracts, and forbidden recovery dependencies.
2. Run the boundary test and confirm it fails before the package exists.
3. Create packaging metadata and the minimal public package.
4. Run the boundary test and confirm the initial package contract passes.

### Task 2: Extract the complete orchestration engine

**Files:**
- Create: `src/orchestrator_agent/federated_coordination_adapter.py`
- Create: `src/orchestrator_agent/model_partition_agent.py`
- Create: `src/orchestrator_agent/partition_*.py`
- Create: `config/model_partition_policy.json`
- Create: `config/examples/*.json`
- Create: `tests/test_*partition*.py`
- Create: `tests/test_federated_coordination_*.py`

1. Copy the latest integrated partition tests and change imports to `orchestrator_agent`.
2. Run the extracted tests and confirm imports fail.
3. Copy all partition modules, rewrite only package-local imports, and retain their deterministic contracts.
4. Copy the policy and FL/SL/distributed-inference examples.
5. Run all engine tests and fix only standalone-boundary defects.

### Task 3: Add independent CLI and HTTP API

**Files:**
- Create: `src/orchestrator_agent/cli.py`
- Create: `src/orchestrator_agent/web.py`
- Create: `tests/test_cli.py`
- Create: `tests/test_api.py`

1. Add failing tests for planning from native and Federated Coordination inputs.
2. Implement CLI commands for plan, replan, feedback, dataset, train, and evaluate.
3. Add failing tests for health, examples, planning, strategy, history, and feedback routes.
4. Implement a standalone FastAPI application backed by the same orchestration service.
5. Verify CLI and API return the same plan contract.

### Task 4: Build a focused research UI

**Files:**
- Create: `ui/index.html`
- Create: `ui/styles.css`
- Create: `ui/app.js`
- Create: `tests/test_ui_contract.py`

1. Add a failing static contract test for the three-stage workflow.
2. Implement input/context, orchestration decision, and scheduling-handoff panels.
3. Show human-readable summaries first and raw JSON only in expandable details.
4. Connect examples and plan generation to the standalone API.

### Task 5: Add handoff documentation and VS Code tasks

**Files:**
- Create: `README.md`
- Create: `docs/INTEGRATION.md`
- Create: `docs/TESTING.md`
- Create: `.vscode/tasks.json`
- Create: `.gitignore`

1. Document the exact accepted inputs and `PartitionExecutionPlan` output.
2. Document installation, CLI, API, UI, test, and external Scheduling Agent handoff.
3. State the first-release boundary: JSON context provider, no direct Prometheus claim, no runtime execution.
4. Add one-command VS Code tasks for installation, tests, and local API.

### Task 6: Verify and finish the independent repository

1. Run `python -m pytest`.
2. Install editable extras and run representative FL, SL, and inference CLI examples.
3. Start the API, verify `/healthz`, API planning, and the browser UI.
4. Search for forbidden recovery/AutoGen/AIOpsLab/Chaos Mesh dependencies.
5. Commit the feature branch, merge it into standalone `master`, and open the folder in a new VS Code window.
