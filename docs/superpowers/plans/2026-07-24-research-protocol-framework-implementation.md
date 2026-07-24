# Research Protocol Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the fixed mutual-supervision workflow into a versioned, configurable research protocol framework with runtime Agent adapters, role-scoped vetoes, interchangeable consensus strategies, and reproducible experiment metadata.

**Architecture:** A `ResearchProtocolProfile` selects registered Agent adapters, review relationships, consensus strategy, action space, and experimental weights. `MutualSupervisionCoordinator` remains the safety-bounded execution orchestrator but delegates Agent behavior and consensus resolution through explicit interfaces. Every report and event stream records the canonical profile identity and hash.

**Tech Stack:** Python 3.11+, dataclasses, `typing.Protocol`, JSON configuration, SHA-256 canonical hashing, pytest, existing AutoGen integration.

## Global Constraints

- Preserve all existing deterministic CLI commands and test behavior.
- The default profile is `four-agent-role-veto-v1`.
- Default negotiation is limited to 2 rounds and 1 replan attempt.
- Consensus failure falls back to `observe_only` and requires human review.
- Python Validator remains mandatory for every strategy.
- Go Guard remains an optional independent second validation backend.
- Configuration may only reference registered implementations; it must never import arbitrary code paths from JSON.
- Web execution remains mock-only; real Kubernetes control remains CLI-gated.

---

### Task 1: Versioned Research Protocol Profile

**Files:**
- Create: `src/aiops_k8s_agents/research_protocol.py`
- Create: `config/protocol_profiles/four-agent-role-veto-v1.json`
- Create: `config/protocol_profiles/four-agent-unanimous-v1.json`
- Create: `config/protocol_profiles/four-agent-weighted-v1.json`
- Test: `tests/test_research_protocol.py`

**Interfaces:**
- Produces: `ConsensusStrategy`, `ProtocolAgentBinding`, `ResearchProtocolProfile`
- Produces: `load_research_protocol(path) -> ResearchProtocolProfile`
- Produces: `load_protocol_profiles(directory) -> dict[str, ResearchProtocolProfile]`
- Produces: `ResearchProtocolProfile.config_hash: str`

- [ ] **Step 1: Write failing profile parsing and hashing tests**

```python
def test_role_veto_profile_has_stable_hash():
    profile = load_research_protocol(
        "config/protocol_profiles/four-agent-role-veto-v1.json"
    )
    assert profile.profile_id == "four-agent-role-veto-v1"
    assert profile.consensus_strategy is ConsensusStrategy.ROLE_BASED_VETO
    assert profile.max_negotiation_rounds == 2
    assert len(profile.config_hash) == 64


def test_profile_hash_changes_when_consensus_changes(tmp_path):
    source = json.loads(
        Path("config/protocol_profiles/four-agent-role-veto-v1.json")
        .read_text(encoding="utf-8")
    )
    first = ResearchProtocolProfile.from_dict(source)
    source["consensus_strategy"] = "unanimous_veto"
    second = ResearchProtocolProfile.from_dict(source)
    assert first.config_hash != second.config_hash
```

- [ ] **Step 2: Run tests and verify the missing module failure**

Run: `python -m pytest tests/test_research_protocol.py -v`

Expected: FAIL because `aiops_k8s_agents.research_protocol` does not exist.

- [ ] **Step 3: Implement strict profile dataclasses and canonical hashing**

```python
class ConsensusStrategy(str, Enum):
    ROLE_BASED_VETO = "role_based_veto"
    UNANIMOUS_VETO = "unanimous_veto"
    WEIGHTED_MAJORITY = "weighted_majority"


@dataclass(frozen=True)
class ProtocolAgentBinding:
    name: str
    implementation_id: str
    runtime: str
    enabled: bool
    veto_scopes: tuple[str, ...]
    consensus_weight: float


@dataclass(frozen=True)
class ResearchProtocolProfile:
    profile_id: str
    version: str
    agents: tuple[ProtocolAgentBinding, ...]
    review_matrix: Mapping[str, tuple[str, ...]]
    consensus_strategy: ConsensusStrategy
    max_negotiation_rounds: int
    max_replan_attempts: int
    fallback_action: RecoveryActionKind
    action_space: tuple[RecoveryActionKind, ...]
    reward_weights: Mapping[str, float]
    experiment_tags: tuple[str, ...]
    config_hash: str

    @property
    def enabled_agents(self) -> tuple[ProtocolAgentBinding, ...]:
        return tuple(binding for binding in self.agents if binding.enabled)
```

Canonicalize dictionaries with sorted keys and compact separators before
calculating `sha256(canonical_json.encode("utf-8")).hexdigest()`. Reject empty
profiles, duplicate agents, unknown consensus strategies, invalid round counts,
negative weights, empty action spaces, and self-review edges.

- [ ] **Step 4: Add the three concrete profile JSON files**

The role profile must contain four enabled deterministic bindings, role-specific
veto scopes, the existing review matrix, 2 rounds, 1 replan, and
`observe_only` fallback. The unanimous and weighted profiles must differ only in
`profile_id`, `version`, `consensus_strategy`, tags, and consensus weights so
their scientific comparison is controlled.

- [ ] **Step 5: Run profile tests**

Run: `python -m pytest tests/test_research_protocol.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/aiops_k8s_agents/research_protocol.py \
  config/protocol_profiles tests/test_research_protocol.py
git commit -m "feat: add versioned research protocol profiles"
```

---

### Task 2: Runtime Agent Adapter Registry

**Files:**
- Create: `src/aiops_k8s_agents/agent_adapters.py`
- Modify: `src/aiops_k8s_agents/agent_registry.py`
- Modify: `config/agent_registry.json`
- Test: `tests/test_agent_adapters.py`
- Modify: `tests/test_agent_registry.py`

**Interfaces:**
- Consumes: `ProtocolAgentBinding`
- Produces: `AgentAdapter` protocol
- Produces: `AgentAdapterRegistry.register(implementation_id, factory)`
- Produces: `AgentAdapterRegistry.create(binding) -> AgentAdapter`
- Produces: `build_default_agent_adapter_registry()`

- [ ] **Step 1: Write failing registry tests**

```python
def test_default_adapter_registry_builds_four_agents():
    registry = build_default_agent_adapter_registry()
    profile = load_research_protocol(
        "config/protocol_profiles/four-agent-role-veto-v1.json"
    )
    adapters = [registry.create(binding) for binding in profile.enabled_agents]
    assert [adapter.name for adapter in adapters] == [
        "AIServiceHASupportAgent",
        "AIApplicationManagementAgent",
        "AISemiconductorInfraOpsAgent",
        "CostOptimizationAgent",
    ]


def test_unregistered_implementation_is_rejected():
    registry = build_default_agent_adapter_registry()
    binding = ProtocolAgentBinding(
        name="UnknownAgent",
        implementation_id="not-registered",
        runtime="deterministic",
        enabled=True,
        veto_scopes=("availability",),
        consensus_weight=1.0,
    )
    with pytest.raises(AgentRegistryError, match="unregistered implementation"):
        registry.create(binding)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_agent_adapters.py tests/test_agent_registry.py -v`

Expected: FAIL because runtime adapters are not defined.

- [ ] **Step 3: Define the adapter contract**

```python
class AgentAdapter(Protocol):
    name: str
    runtime: str

    def diagnose(
        self, evidence: EvidenceSnapshot, threshold: float
    ) -> tuple[Diagnosis, SupervisionDecision] | None: ...

    def propose(
        self, diagnosis: Diagnosis, evidence: EvidenceSnapshot
    ) -> tuple[RecoveryAction, ...]: ...

    def review(
        self,
        decision: SupervisionDecision,
        evidence: EvidenceSnapshot,
        context: ReviewContext,
    ) -> PeerReview | None: ...

    def post_review(
        self,
        action: RecoveryAction,
        assessment: RecoveryAssessment,
        evidence: EvidenceSnapshot,
    ) -> PostExecutionReview: ...
```

Implement focused deterministic adapters that wrap the existing HA,
Application, Infrastructure, and Cost classes. Unsupported capabilities return
`None`; they must not be silently simulated by another Agent.

- [ ] **Step 4: Implement safe factory registration**

```python
@dataclass
class AgentAdapterRegistry:
    factories: dict[str, Callable[[ProtocolAgentBinding], AgentAdapter]]

    def register(self, implementation_id, factory):
        if implementation_id in self.factories:
            raise AgentRegistryError(f"duplicate implementation: {implementation_id}")
        self.factories[implementation_id] = factory

    def create(self, binding):
        try:
            factory = self.factories[binding.implementation_id]
        except KeyError as exc:
            raise AgentRegistryError(
                f"unregistered implementation: {binding.implementation_id}"
            ) from exc
        return factory(binding)
```

Do not load modules or evaluate code from configuration values.

- [ ] **Step 5: Extend Agent Registry metadata**

Add `implementation_id`, `supported_runtimes`, and `capabilities` to
`AgentProfile`. Update `config/agent_registry.json` for the four default
implementations while preserving existing bounded actions and reward signals.

- [ ] **Step 6: Run adapter and registry tests**

Run: `python -m pytest tests/test_agent_adapters.py tests/test_agent_registry.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/aiops_k8s_agents/agent_adapters.py \
  src/aiops_k8s_agents/agent_registry.py config/agent_registry.json \
  tests/test_agent_adapters.py tests/test_agent_registry.py
git commit -m "feat: add runtime agent adapter registry"
```

---

### Task 3: Interchangeable Consensus Strategies

**Files:**
- Create: `src/aiops_k8s_agents/consensus.py`
- Test: `tests/test_consensus.py`

**Interfaces:**
- Consumes: `ResearchProtocolProfile`, `PeerReview`, `ProtocolAgentBinding`
- Produces: `ConsensusOutcome`
- Produces: `ConsensusResolver.resolve(reviews, profile, decision_scope) -> ConsensusOutcome`

- [ ] **Step 1: Write controlled comparison tests**

```python
def test_role_veto_blocks_only_reviewers_with_matching_scope():
    outcome = resolver.resolve(
        reviews=(
            review("Cost", ReviewVerdict.VETO, scope="budget"),
            review("Infra", ReviewVerdict.APPROVE, scope="capacity"),
        ),
        profile=role_profile,
        decision_scope="capacity",
    )
    assert outcome.approved
    assert outcome.non_blocking_objections == ("Cost",)


def test_unanimous_veto_blocks_on_any_veto():
    outcome = resolver.resolve(reviews, unanimous_profile, "capacity")
    assert not outcome.approved
    assert outcome.blocking_vetoes == ("Cost",)


def test_weighted_majority_uses_enabled_agent_weights():
    outcome = resolver.resolve(weighted_reviews, weighted_profile, "capacity")
    assert outcome.score == pytest.approx(0.75)
    assert outcome.approved
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_consensus.py -v`

Expected: FAIL because `ConsensusResolver` does not exist.

- [ ] **Step 3: Implement a pure deterministic resolver**

```python
@dataclass(frozen=True)
class ConsensusOutcome:
    approved: bool
    strategy: str
    score: float
    blocking_vetoes: tuple[str, ...]
    non_blocking_objections: tuple[str, ...]
    revisions: tuple[PeerReview, ...]
    reason: str
```

The resolver must not execute actions or mutate reviews. `role_based_veto`
matches review scope against the binding's veto scopes. `unanimous_veto`
blocks on any veto. `weighted_majority` calculates approve weight divided by
participating weight with a default threshold of `0.5`; abstentions do not add
approve weight. Every strategy must preserve revisions for the next round.

- [ ] **Step 4: Run consensus tests**

Run: `python -m pytest tests/test_consensus.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aiops_k8s_agents/consensus.py tests/test_consensus.py
git commit -m "feat: add configurable consensus strategies"
```

---

### Task 4: Profile-Driven Mutual Supervision Coordinator

**Files:**
- Modify: `src/aiops_k8s_agents/mutual_supervision.py`
- Modify: `src/aiops_k8s_agents/mutual_supervision_models.py`
- Modify: `src/aiops_k8s_agents/research_event_store.py`
- Modify: `src/aiops_k8s_agents/__init__.py`
- Modify: `tests/test_mutual_supervision.py`
- Modify: `tests/test_mutual_supervision_event_store.py`

**Interfaces:**
- Consumes: `ResearchProtocolProfile`, `AgentAdapterRegistry`, `ConsensusResolver`
- Produces: reports containing `protocol_profile` and `agent_contributions`

- [ ] **Step 1: Write failing profile-driven coordinator tests**

```python
def test_coordinator_report_records_profile_identity():
    report = coordinator_for("four-agent-role-veto-v1").run(...)
    assert report["protocol_profile"] == {
        "profile_id": "four-agent-role-veto-v1",
        "version": "1.0.0",
        "config_hash": profile.config_hash,
    }


def test_disabled_cost_agent_is_not_called_or_recorded():
    report = coordinator_for("role-veto-without-cost").run(...)
    reviewers = {item["reviewer"] for item in report["peer_reviews"]}
    assert "CostOptimizationAgent" not in reviewers
    assert report["active_agents"] == [
        "AIServiceHASupportAgent",
        "AIApplicationManagementAgent",
        "AISemiconductorInfraOpsAgent",
    ]
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `python -m pytest tests/test_mutual_supervision.py -v`

Expected: FAIL because the Coordinator does not accept a protocol profile.

- [ ] **Step 3: Replace fixed Agent fields with adapter collections**

```python
@dataclass
class MutualSupervisionCoordinator:
    executor: CommandExecutor
    evidence_provider: EvidenceProvider
    recovery_monitor: RecoveryMonitor
    protocol: ResearchProtocolProfile
    adapter_registry: AgentAdapterRegistry
    consensus_resolver: ConsensusResolver = field(default_factory=ConsensusResolver)
    event_store: ResearchEventSink | None = None

    def __post_init__(self):
        self.adapters = {
            binding.name: self.adapter_registry.create(binding)
            for binding in self.protocol.enabled_agents
        }
```

Find capabilities explicitly: exactly one enabled adapter must support
diagnosis and exactly one must support Action proposal in the default profile.
Review and post-review phases iterate configured edges and enabled adapters.
Missing required capabilities produce safe failure before execution.

- [ ] **Step 4: Delegate round resolution**

Replace Coordinator-specific veto aggregation with
`ConsensusResolver.resolve(...)`. Apply revisions only when the selected
strategy returns revisions. Stop after `max_negotiation_rounds`; use the
configured fallback and require human review.

- [ ] **Step 5: Add contribution accounting**

Record per-Agent counts and outcomes:

```python
{
    "AIServiceHASupportAgent": {
        "decisions": 1,
        "approvals": 1,
        "revisions": 0,
        "vetoes": 0,
        "post_reviews": 1,
        "reward": 0.90,
    }
}
```

Contribution is descriptive experiment evidence, not a learned credit
assignment algorithm.

- [ ] **Step 6: Persist profile and contribution metadata**

Add `protocol_profiles.jsonl` and `agent_contributions.jsonl` streams or embed
the immutable profile snapshot in `experiment_config.json`. Ensure
`final_report.json`, Markdown, and statistics CSV include profile ID, version,
hash, strategy, and active Agent list.

- [ ] **Step 7: Run coordinator and event-store tests**

Run:

```bash
python -m pytest \
  tests/test_mutual_supervision.py \
  tests/test_mutual_supervision_event_store.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/aiops_k8s_agents/mutual_supervision.py \
  src/aiops_k8s_agents/mutual_supervision_models.py \
  src/aiops_k8s_agents/research_event_store.py \
  src/aiops_k8s_agents/__init__.py \
  tests/test_mutual_supervision.py \
  tests/test_mutual_supervision_event_store.py
git commit -m "refactor: drive mutual supervision from research profiles"
```

---

### Task 5: CLI Profile Selection and AutoGen Runtime Boundary

**Files:**
- Modify: `src/aiops_k8s_agents/cli.py`
- Modify: `src/aiops_k8s_agents/autogen_groupchat.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_autogen_groupchat.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `mutual-supervision-run --protocol-profile <id>`
- Produces: `list-protocol-profiles`
- Produces: explicit runtime metadata and safe unavailable-runtime errors

- [ ] **Step 1: Write failing CLI tests**

```python
def test_mutual_supervision_cli_selects_protocol_profile(capsys):
    exit_code = main([
        "mutual-supervision-run",
        "--mode", "mock",
        "--protocol-profile", "four-agent-unanimous-v1",
        *default_alert_args(),
    ])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["protocol_profile"]["profile_id"] == (
        "four-agent-unanimous-v1"
    )


def test_autogen_runtime_without_client_returns_safe_failure(capsys):
    exit_code = main([... "--protocol-profile", "four-agent-autogen-v1"])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["final_status"] == "runtime_unavailable"
    assert payload["human_review_required"] is True
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_cli.py tests/test_autogen_groupchat.py -v`

Expected: FAIL because profile selection is not exposed.

- [ ] **Step 3: Add profile discovery and selection**

Load profiles only from the configured profile directory. Reject path
traversal and unknown IDs. Add `list-protocol-profiles` JSON output with profile
ID, version, strategy, active Agents, runtimes, and hash.

- [ ] **Step 4: Add the AutoGen adapter boundary**

Register `autogen-round-robin` only when a model client/provider has been
explicitly supplied. Reuse `AutoGenRoundRobinDecisionProvider` for structured
decisions and transcript capture. Convert only schema-valid outputs into
`SupervisionDecision` or `PeerReview`; malformed output becomes abstention and
never bypasses validation.

The implementation must report runtime selection even when tests use a fake
provider:

```python
metadata["agent_runtimes"] = {
    binding.name: binding.runtime for binding in profile.enabled_agents
}
```

- [ ] **Step 5: Run CLI and AutoGen tests**

Run: `python -m pytest tests/test_cli.py tests/test_autogen_groupchat.py -v`

Expected: PASS without requiring a real API key.

- [ ] **Step 6: Update README commands**

Document profile listing, role-veto mock execution, AutoGen prerequisites, and
the distinction between runtime support and completed real experiments.

- [ ] **Step 7: Commit**

```bash
git add src/aiops_k8s_agents/cli.py \
  src/aiops_k8s_agents/autogen_groupchat.py \
  tests/test_cli.py tests/test_autogen_groupchat.py README.md
git commit -m "feat: expose research protocol profiles in CLI"
```

---

### Task 6: Protocol Framework Regression Verification

**Files:**
- Modify: `docs/design/agent_action_reward_policy.md`
- Modify: `docs/submission/test_guide.md`

**Interfaces:**
- Verifies all outputs from Tasks 1-5

- [ ] **Step 1: Run the complete Python suite**

Run: `python -m pytest`

Expected: all tests pass.

- [ ] **Step 2: Run Go Guard tests**

Run: `cd go/aiops-guard && go test ./...`

Expected: `ok github.com/gunsun2000/aiops_research/go/aiops-guard/internal/guard`.

- [ ] **Step 3: Run deterministic profile comparison smoke tests**

Run the same mock condition with role-veto, unanimous, and weighted profiles.
Verify each result contains a distinct profile ID/hash and a common bounded
Validator result.

- [ ] **Step 4: Update policy and test documentation**

Document the default veto scopes, consensus strategy semantics, profile hash,
Agent adapter registration boundary, and reproducibility fields.

- [ ] **Step 5: Commit**

```bash
git add docs/design/agent_action_reward_policy.md \
  docs/submission/test_guide.md
git commit -m "docs: describe configurable research protocols"
```
