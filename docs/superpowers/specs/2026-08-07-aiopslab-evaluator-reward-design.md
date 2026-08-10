# AIOpsLab Evaluator-Based Reward Design

## Goal

Replace fixed decision-time reward totals with post-run Evaluator Agents that assign per-agent rewards and a team reward from objective experiment evidence.

## Scope

This document originally specified the AIOpsLab detection benchmark path. The same report-level contract is now also used by the Chaos Mesh/Kubernetes recovery path through `RecoveryEvaluatorAgent`; each path keeps its own evidence rubric and official metrics.

## Architecture

The existing four agents continue to make detection decisions. They do not assign meaningful rewards during execution. After AIOpsLab returns the benchmark result, an independent `AIOpsLabEvaluatorAgent` evaluates the completed run. After a Chaos Mesh recovery runtime completes, `RecoveryEvaluatorAgent` evaluates the final recovery report before persistence.

Flow:

`4-Agent Decision -> AIOpsLab Environment -> Objective Result/Evidence -> Evaluator Agent -> Per-Agent Rewards + Team Reward -> Report/Aggregate/UI`

The Evaluator Agent never changes Kubernetes state and never changes the four-agent decision before submission.

## Evaluation Inputs

The evaluator consumes only evidence already produced by the run:

- AIOpsLab `Detection Accuracy` (`Correct` or `Incorrect`)
- AIOpsLab `TTD`
- AIOpsLab `steps`
- configured `max_steps`
- configured metrics-duration budget
- whether all recorded decisions passed the bounded-action/referee safety checks
- whether the run collected both logs and metrics before submission
- the four-agent decision history for audit/rationale

Missing values remain missing and are not silently replaced with fabricated measurements.

## Reward Rubric

All evaluator outputs are bounded to `[-1.0, 1.0]`.

Objective component scores:

- `correctness`: `+1` for `Correct`, `-1` for `Incorrect`, `0` when unavailable
- `ttd_efficiency`: normalized from actual TTD against the configured metrics-duration budget
- `step_efficiency`: normalized from actual steps against configured `max_steps`
- `efficiency`: mean of available TTD and step efficiency scores
- `safety`: `+1` when every recorded decision is valid and referee-approved, otherwise `-1`; `0` if no decisions exist
- `evidence_quality`: based on whether both required evidence stages (`get_logs`, `get_metrics`) occurred before submission

Team reward:

`team_reward = 0.65 * correctness + 0.15 * efficiency + 0.10 * safety + 0.10 * evidence_quality`

The correctness weight is intentionally dominant so an incorrect final detection cannot receive a positive team reward merely by being fast or cheap.

Per-agent role scores:

- HA Agent: correctness
- Application Agent: `0.60 * correctness + 0.40 * evidence_quality`
- Infra Agent: safety
- Cost Agent: efficiency

Each per-agent reward combines the shared team outcome with role-specific credit:

`agent_reward = 0.70 * team_reward + 0.30 * role_score`

This provides credit assignment without returning to fixed rewards attached to action names.

## Report Contract

Each saved AIOpsLab report gains an `evaluation` object:

- `evaluator`: `AIOpsLabEvaluatorAgent`
- `rubric_version`: `evaluator-v1`
- `team_reward`
- `agent_rewards` keyed by the four existing agent names
- `components` containing correctness, efficiency, safety, evidence quality and normalized sub-scores
- `reason` containing a concise evidence-based explanation

The decision metadata no longer exposes a meaningful `reward_total` for AIOpsLab execution. Existing `AgentDecision.reward` values in this path are neutral (`0.0`) until post-run evaluation.

## Aggregation

`aiopslab_results.py` reads `evaluation.team_reward` as the run's `final_reward`.

Aggregate output includes:

- `average_final_reward` for backward API compatibility; its meaning becomes average team reward
- `average_team_reward` as an explicit alias
- `average_agent_rewards` for each of the four agents

The Markdown/CSV summary is updated to include team reward and per-agent reward fields.

## UI

The AIOpsLab UI continues to use actual persisted job results only.

- `Average Reward` copy becomes `Average Team Reward` where practical.
- Job detail displays Team Reward and the four per-agent rewards when evaluation data exists.
- Missing evaluation data is shown as `—`, never zero-filled.

## Error Handling

The evaluator is deterministic and local so AIOpsLab does not become dependent on an OpenAI API key. If benchmark evidence is missing, the corresponding component score is neutral rather than fabricated. Invalid or unsafe recorded actions are penalized through the safety component.

## Testing

Tests must verify:

- fixed AIOpsLab action rewards are no longer used to calculate final reward
- correct runs score higher than otherwise identical incorrect runs
- incorrect runs cannot receive a positive team reward
- safety failures reduce reward
- faster/fewer-step correct runs score higher than slower/more-step correct runs
- all rewards stay within `[-1, 1]`
- report serialization includes both team and per-agent rewards
- aggregation averages team and per-agent rewards correctly
- UI uses the persisted evaluator fields and does not fabricate values

## Recovery evaluator extension

Recovery reports use the same bounded team/per-agent contract, but score only recorded recovery evidence:

- outcome, efficiency, safety, and evidence quality are the authoritative components
- `team_reward = 0.65 * outcome + 0.15 * efficiency + 0.10 * safety + 0.10 * evidence_quality`
- missing metrics and cost evidence remain missing; they are never fabricated
- legacy `agent_contributions[*].reward` values remain diagnostic compatibility data and are not summed as the final reward
- the UI uses `evaluation.team_reward` and `evaluation.agent_rewards`; missing evaluation data is shown as `—`

## Non-Goals

- No online RL policy update or LLM-as-a-judge dependency is added.
