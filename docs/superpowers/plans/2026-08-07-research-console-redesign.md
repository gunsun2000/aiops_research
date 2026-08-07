# AIOps Research Console Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the existing 4-Agent AIOps research console to match the approved navy/white dashboard references while preserving the existing FastAPI experiment, SSE, safety, benchmark, and comparison contracts.

**Architecture:** Keep the existing static HTML/CSS/JavaScript console and backend APIs. Replace the information architecture with four primary views (System Overview, Recovery Experiment, AIOpsLab Benchmark, Experiment Results), retain Agent/Evidence/detail subviews, and normalize controller/mode/provider/status presentation in the frontend. No backend contract changes are required unless a later verification finds a missing field that cannot be derived safely.

**Tech Stack:** Static HTML5, CSS, vanilla JavaScript, FastAPI APIs, Server-Sent Events, pytest static UI contract tests.

## Global Constraints

- Preserve existing FastAPI API contracts and Experiment Job persistence.
- Preserve SQLite Job Store, SSE streaming, cancellation, Python Validator, Go Guard, allowlists, replica limits, and Real-mode confirmation gates.
- Recovery scenarios are only Pod Failure, CPU Saturation, Memory Saturation, and Network Delay.
- AIOpsLab is a separate benchmark view, not a recovery scenario.
- AutoGen is disabled in the UI when runtime readiness is false.
- Deterministic controller never displays an AutoGen model name.
- Mock, Dry-run, and Real are always visibly distinguished.
- Do not invent metrics; absent values render as `수집되지 않음`, `결과 없음`, or `—`.
- Mock/synthetic results must be visibly labeled as non-real research evidence.
- Reference-image numeric values are visual examples only and must not be hardcoded as results.

---

### Task 1: Update UI contract tests

**Files:**
- Modify: `tests/test_control_plane_ui.py`

- [ ] Replace legacy three-view/AIOpsLab-integrated assertions with four-view separation assertions.
- [ ] Add assertions for 8-stage recovery workflow, connection status items, mode badges, controller formatting, AutoGen disable behavior, and AIOpsLab job APIs.
- [ ] Keep regression checks for experiment creation, SSE, cancellation, comparison APIs, Real confirmations, four agents, and no fake precomputed decisions.

### Task 2: Replace page information architecture

**Files:**
- Modify: `ui/control_plane_static/index.html`

- [ ] Implement persistent navy sidebar with System Overview, Recovery Experiment, AIOpsLab Benchmark, and Experiment Results.
- [ ] Add per-service connection status rows for Kubernetes, Prometheus, Chaos Mesh, AIOpsLab, and AutoGen.
- [ ] Implement System Overview with current-session summary, 8-stage closed loop, quick experiment form, 4-Agent summary, and recent result summary.
- [ ] Implement Recovery Experiment with scenario/controller/mode cards, advanced settings, live 8-stage timeline, Agent cards, Evidence band, and collapsed recent event log.
- [ ] Implement Agent and Evidence subviews.
- [ ] Implement separate AIOpsLab Benchmark controls/results/events.
- [ ] Implement Experiment Results with filters, history table, comparison area, and detail subview.

### Task 3: Implement visual system

**Files:**
- Modify: `ui/control_plane_static/styles.css`

- [ ] Define navy/blue/neutral design tokens, card surfaces, badges, tabs, tables, empty/error states, and responsive breakpoints.
- [ ] Match reference layout density at 1440px and 1920px while preserving mobile reflow.
- [ ] Make mock/synthetic warnings visually prominent without overwhelming the interface.

### Task 4: Normalize frontend behavior and data presentation

**Files:**
- Modify: `ui/control_plane_static/app.js`

- [ ] Split recovery scenarios from AIOpsLab benchmark state.
- [ ] Add four-primary-view navigation and detail subview routing.
- [ ] Preserve `/api/experiments`, experiment SSE, cancellation, restore, and Real confirmation behavior.
- [ ] Preserve AIOpsLab benchmark APIs and wire their controls on boot.
- [ ] Preserve recovery comparison APIs and SSE.
- [ ] Add consistent controller formatter and status/stage labels.
- [ ] Disable AutoGen selection/execution when runtime readiness is false.
- [ ] Render recovery evidence source by mode without leaking AIOpsLab provider labels into Chaos Mesh experiments.
- [ ] Render Agent decisions, safety results, evidence, artifacts, and experiment history from actual job data only.

### Task 5: Verify

**Files:**
- Test: `tests/test_control_plane_ui.py`

- [ ] Run `python -m pytest tests/test_control_plane_ui.py -q`.
- [ ] Run JavaScript syntax validation (`node --check ui/control_plane_static/app.js`) when Node is available.
- [ ] Re-fetch the committed files and review controller/provider/status strings for contradictory states.
- [ ] Report any runtime-only verification that requires the user's Kubernetes/Prometheus/Chaos Mesh environment.
