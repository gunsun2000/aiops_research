# Learned Partition Candidate Ranker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Model Partition Orchestrator Agent가 결정론적으로 생성하고 하드 제약을 검증한 분할 후보를 관측 Reward로 학습한 Ranker로 안전하게 재정렬하고, 결과를 기존 API·CLI·플랫폼·Evaluator·Artifact 흐름에서 재현 가능하게 비교하도록 만든다.

**Architecture:** 후보 생성과 Hard Feasibility Filter는 기존 결정론적 코드가 계속 담당한다. 새 Ranker 계층은 하드 제약을 통과한 후보만 `deterministic`, `shadow`, `learned_guarded` 모드로 순위화하며, 선택 후 기존 `PartitionPlanValidator`가 독립적으로 다시 검증한다. Runtime Outcome은 기존 `PartitionPlanEvaluator`가 관측 Reward로 평가하고, 그 결과만 Dataset Builder와 Offline Ridge Trainer로 전달한다.

**Tech Stack:** Python 3.11+, dataclasses, JSON/JSONL, SHA-256 canonical hashing, optional scikit-learn Ridge Regression, FastAPI, vanilla JavaScript/CSS, pytest

**Spec:** `docs/superpowers/specs/2026-08-21-learned-partition-ranker-design.md`

## Global Constraints

- `deterministic`가 기존 API·CLI·Agent의 기본 선택 모드이며 기존 선택 결과와 의미를 유지한다.
- Learned Ranker는 `PartitionCandidate.valid is True`인 후보만 입력받고 하드 제약이나 Validator 결과를 변경할 수 없다.
- `shadow`는 AI 추천을 기록하지만 최종 후보를 변경하지 않는다.
- `learned_guarded`는 Artifact 무결성, Schema, 표본 수, 검증 지표, OOD, Confidence 조건을 모두 만족할 때만 AI 추천을 최종 후보로 사용한다.
- Guard 조건 미달은 예외가 아니라 결정론적 선택으로의 구조화된 Fallback이다.
- 기본 학습 Dataset은 `evidence_level == "observed"`인 선택 후보만 포함하며 predicted, mock, dry-run, synthetic Outcome을 섞지 않는다.
- 첫 학습 모델은 scikit-learn Ridge Regression이며 JSON 계수로 내보내고 Runtime 추론은 scikit-learn 없이 순수 Python으로 수행한다.
- Runtime은 Pickle을 로드하지 않으며 Web 요청에서 임의 Model 파일 경로를 받지 않는다.
- Scheduling Agent와 FL/SL 실행 모드 검증은 외부 범위로 유지한다.
- Recovery, AIOpsLab, AutoGen, 기존 Model Partition CLI/API의 의미와 실행 경계를 변경하지 않는다.
- 기본 Guard 기준은 관측 표본 30개, 독립 Group 5개, Hold-out MAE 0.25 이하, Spearman 0.30 이상, 선택 Confidence 0.70 이상, OOD 비율 20% 미만이다.

## File Structure

- `src/aiops_k8s_agents/partition_ranking_models.py`: 선택 모드, 후보별 순위, 최종 선택 Metadata의 직렬화 계약
- `src/aiops_k8s_agents/partition_features.py`: `partition-feature-v1`의 고정 Feature 추출과 후보 Key 생성
- `src/aiops_k8s_agents/partition_ranker_repository.py`: JSON Model Artifact의 저장, 조회, Hash 검증
- `src/aiops_k8s_agents/partition_ranking.py`: Deterministic Ranker, Learned Ranker, Guarded Selector
- `src/aiops_k8s_agents/partition_learning.py`: 관측 Dataset 생성, Group 분할, Ridge 학습, Offline 평가
- `src/aiops_k8s_agents/partition_models.py`: `PartitionExecutionPlan.selection` 선택 Metadata 연결
- `src/aiops_k8s_agents/model_partition_agent.py`: 기존 후보 생성 뒤 Ranker를 호출하는 단일 통합 지점
- `src/aiops_k8s_agents/partition_service.py`: Ranker Registry와 선택 모드를 Plan·Feedback 실행에 전달
- `src/aiops_k8s_agents/control_plane_web.py`: 선택 모드 요청과 등록 Model 상태 API
- `src/aiops_k8s_agents/cli.py`: Dataset·학습·평가 명령 및 Planning 옵션
- `ui/control_plane_static/index.html`: Selection Mode와 등록 Model 선택 UI
- `ui/control_plane_static/app.js`: Baseline과 AI 추천, Fallback, Outcome 반영 표시
- `ui/control_plane_static/styles.css`: 기존 연구 콘솔 규칙에 맞춘 비교 표와 상태 표시
- `config/model_partition_policy.json`: Learned Guard 기본 기준
- `pyproject.toml`: 학습 전용 `ml` Optional Dependency

---

### Task 1: Ranking Contract와 결정론적 Ranker 분리

**Files:**
- Create: `src/aiops_k8s_agents/partition_ranking_models.py`
- Create: `src/aiops_k8s_agents/partition_ranking.py`
- Modify: `src/aiops_k8s_agents/partition_models.py`
- Modify: `src/aiops_k8s_agents/model_partition_agent.py`
- Test: `tests/test_partition_ranking.py`
- Test: `tests/test_model_partition_agent.py`

**Interfaces:**
- Consumes: `NormalizedPartitionRequest`, `PartitionIntent`, `PartitionCandidate`
- Produces: `SelectionMode`, `CandidateRankingEntry`, `CandidateSelection`, `RankingContext`, `CandidateRanker`, `DeterministicPolicyRanker`, `GuardedCandidateSelector.select(...)`

- [ ] **Step 1: Write failing contract and compatibility tests**

```python
def test_deterministic_ranker_preserves_existing_candidate_order(training_context, candidates):
    ranking = DeterministicPolicyRanker().rank(training_context, candidates)
    assert ranking.baseline_selected_candidate_key == candidate_key(
        candidates[1], training_context.strategy_version
    )
    assert ranking.final_selected_candidate_key == ranking.baseline_selected_candidate_key
    assert ranking.mode is SelectionMode.DETERMINISTIC
    assert ranking.fallback_used is False


def test_invalid_candidate_is_never_rank_eligible(training_context, candidates):
    invalid = replace(candidates[0], valid=False, rejection_reasons=("memory_exceeded",))
    ranking = DeterministicPolicyRanker().rank(training_context, (invalid, candidates[1]))
    entry = next(item for item in ranking.entries if item.candidate_key == candidate_key(
        invalid, training_context.strategy_version
    ))
    assert entry.eligible is False
    assert ranking.final_selected_candidate_key != entry.candidate_key


def test_default_agent_plan_keeps_legacy_deterministic_selection(v2_training_request, policy_path):
    plan = ModelPartitionOrchestrationAgent(
        ModelPartitionPolicy.from_path(policy_path)
    ).plan_request(v2_training_request)
    assert plan.selected_candidate is not None
    assert plan.selected_candidate.split_points == (3,)
    assert plan.selection is not None
    assert plan.selection.mode == "deterministic"
```

- [ ] **Step 2: Run tests and confirm the missing ranking contracts fail**

Run: `python -m pytest tests/test_partition_ranking.py tests/test_model_partition_agent.py -q`

Expected: FAIL because `partition_ranking_models`, `DeterministicPolicyRanker`, and `PartitionExecutionPlan.selection` do not exist.

- [ ] **Step 3: Add immutable ranking contracts with backward-compatible serialization**

```python
class SelectionMode(str, Enum):
    DETERMINISTIC = "deterministic"
    SHADOW = "shadow"
    LEARNED_GUARDED = "learned_guarded"


@dataclass(frozen=True)
class CandidateRankingEntry:
    candidate_key: str
    baseline_score: float
    predicted_reward: float | None
    prediction_confidence: float | None
    rank: int
    eligible: bool
    warnings: tuple[str, ...] = ()
    feature_contributions: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True)
class CandidateSelection:
    mode: str
    active_ranker_id: str
    active_ranker_version: str
    baseline_selected_candidate_key: str | None
    learned_selected_candidate_key: str | None
    final_selected_candidate_key: str | None
    model_version: str | None
    model_artifact_hash: str | None
    feature_schema_version: str
    entries: tuple[CandidateRankingEntry, ...]
    confidence: float
    fallback_used: bool
    fallback_reason: str | None
    rationale: tuple[str, ...]
```

Add `selection: CandidateSelection | None = None` to `PartitionExecutionPlan`, emit it from `to_dict()`, and treat a missing `selection` key as `None` in `from_dict()` so persisted legacy plans continue to load.

- [ ] **Step 4: Extract current ordering into the deterministic Ranker and inject it into the Agent**

```python
@dataclass(frozen=True)
class RankingContext:
    request: NormalizedPartitionRequest
    intent: PartitionIntent
    strategy_version: str


class CandidateRanker(Protocol):
    @abstractmethod
    def rank(
        self,
        context: RankingContext,
        candidates: Sequence[PartitionCandidate],
    ) -> CandidateSelection:
        raise NotImplementedError


class DeterministicPolicyRanker:
    ranker_id = "deterministic-policy-ranker"
    ranker_version = "1.0"
    feature_schema_version = "partition-feature-v1"

    def rank(self, context, candidates):
        ordered = sorted(
            candidates,
            key=lambda item: (not item.valid, item.score, item.split_points),
        )
        selected = next((item for item in ordered if item.valid), None)
        return selection_from_deterministic_order(context, ordered, selected)
```

Change `_plan(...)` so it receives `normalized` and `partition_intent`, builds all candidates exactly as before, invokes the selector once, resolves `final_selected_candidate_key` back to the original candidate object, and stores `selection` in the returned plan. Version the signature payload so it includes selection mode, active Ranker version, optional Model Artifact Hash, and final candidate Key. Add a regression test proving that identical input, snapshot, policy, selection mode, and Model Artifact produce an identical signature; do not assert equality with the pre-ranker signature string.

- [ ] **Step 5: Run focused compatibility tests**

Run: `python -m pytest tests/test_partition_ranking.py tests/test_model_partition_agent.py tests/test_partition_models.py -q`

Expected: PASS; the historical fixture still selects split point `(3,)` and legacy reports without `selection` still parse.

- [ ] **Step 6: Commit the deterministic Ranker integration**

```bash
git add src/aiops_k8s_agents/partition_ranking_models.py src/aiops_k8s_agents/partition_ranking.py src/aiops_k8s_agents/partition_models.py src/aiops_k8s_agents/model_partition_agent.py tests/test_partition_ranking.py tests/test_model_partition_agent.py
git commit -m "Refactor partition candidate selection behind ranker contract"
```

### Task 2: Versioned Feature Schema와 JSON Model Registry

**Files:**
- Create: `src/aiops_k8s_agents/partition_features.py`
- Create: `src/aiops_k8s_agents/partition_ranker_repository.py`
- Test: `tests/test_partition_features.py`
- Test: `tests/test_partition_ranker_repository.py`

**Interfaces:**
- Consumes: `RankingContext`, `PartitionCandidate`, canonical JSON helper
- Produces: `FEATURE_SCHEMA_VERSION`, `FEATURE_ORDER`, `candidate_key(...)`, `extract_partition_features(...)`, `PartitionRankerModelArtifact`, `PartitionRankerRepository`

- [ ] **Step 1: Write failing deterministic feature and Artifact integrity tests**

```python
def test_candidate_key_is_stable_and_excludes_plan_identity(training_context, candidate):
    first = candidate_key(candidate, training_context.strategy_version)
    second = candidate_key(candidate, training_context.strategy_version)
    assert first == second
    assert len(first) == 64


def test_feature_vector_matches_declared_order(training_context, candidate):
    vector = extract_partition_features(training_context, candidate)
    assert tuple(vector) == FEATURE_ORDER
    assert all(math.isfinite(value) for value in vector.values())
    assert vector["candidate_partition_count"] == len(candidate.partitions)


def test_repository_rejects_tampered_model_artifact(tmp_path, model_artifact):
    repository = PartitionRankerRepository(tmp_path)
    path = repository.save(model_artifact)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["intercept"] = payload["intercept"] + 0.5
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PartitionContractError, match="artifact hash"):
        repository.get(model_artifact.model_version)
```

- [ ] **Step 2: Run tests and confirm missing Feature and Repository APIs fail**

Run: `python -m pytest tests/test_partition_features.py tests/test_partition_ranker_repository.py -q`

Expected: FAIL with import errors for the new modules.

- [ ] **Step 3: Implement canonical candidate Key and the complete `partition-feature-v1` vector**

```python
FEATURE_SCHEMA_VERSION = "partition-feature-v1"
FEATURE_ORDER = (
    "plan_type_training",
    "plan_type_inference",
    "layer_count",
    "participant_count",
    "total_compute_units",
    "total_parameter_bytes",
    "total_activation_bytes",
    "total_working_memory_bytes",
    "device_compute_min",
    "device_compute_mean",
    "device_compute_max",
    "device_memory_min",
    "device_memory_mean",
    "device_memory_max",
    "network_bandwidth_min",
    "network_bandwidth_mean",
    "network_bandwidth_max",
    "network_latency_min",
    "network_latency_mean",
    "network_latency_max",
    "max_latency_ms",
    "max_transfer_bytes",
    "minimum_memory_headroom_ratio",
    "forecast_request_rate",
    "forecast_batch_size",
    "forecast_sequence_length",
    "forecast_uncertainty",
    "forecast_request_rate_missing",
    "forecast_batch_size_missing",
    "forecast_sequence_length_missing",
    "candidate_partition_count",
    "candidate_compute_share_min",
    "candidate_compute_share_mean",
    "candidate_compute_share_max",
    "estimated_compute_ms",
    "estimated_transfer_ms",
    "estimated_total_latency_ms",
    "estimated_step_time_ms",
    "total_transfer_bytes",
    "gradient_transfer_bytes",
    "maximum_memory_pressure",
    "maximum_load_imbalance",
    "predicted_resilience_risk",
    "baseline_score",
    "split_position_min",
    "split_position_mean",
    "split_position_max",
)


def candidate_key(candidate: PartitionCandidate, strategy_version: str) -> str:
    payload = {
        "split_points": list(candidate.split_points),
        "assignments": [
            {"partition_id": item.partition_id, "device_id": item.device_id}
            for item in candidate.partitions
        ],
        "strategy_version": strategy_version,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
```

Use fixed zeros plus matching `*_missing` indicators for absent forecasts. Reject booleans, NaN, infinity, negative byte sizes, and mismatched feature order with `PartitionContractError`.

- [ ] **Step 4: Implement canonical JSON Model Artifact and registry-only loading**

```python
@dataclass(frozen=True)
class PartitionRankerModelArtifact:
    schema_version: str
    model_type: str
    model_version: str
    feature_schema_version: str
    trained_at: str
    training_dataset_hash: str
    training_scope: str
    sample_count: int
    group_count: int
    feature_order: tuple[str, ...]
    feature_mean: tuple[float, ...]
    feature_scale: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    training_feature_ranges: dict[str, tuple[float, float]]
    validation_metrics: dict[str, float]
    confidence_policy: dict[str, float]
    artifact_hash: str


class PartitionRankerRepository:
    def save(self, artifact: PartitionRankerModelArtifact) -> Path:
        verified = artifact.with_computed_hash()
        path = self._model_path(verified.model_version)
        self._write_json_atomic(path, verified.to_dict())
        return path

    def get(self, model_version: str) -> PartitionRankerModelArtifact:
        artifact = PartitionRankerModelArtifact.from_dict(
            self._read_json(self._model_path(model_version))
        )
        artifact.verify_hash()
        return artifact

    def list(self) -> tuple[PartitionRankerModelArtifact, ...]:
        versions = sorted(path.parent.name for path in self.root.glob("*/model.json"))
        return tuple(self.get(version) for version in versions)
```

Persist each version under `<registry_root>/<model_version>/model.json`, compute the SHA-256 from canonical JSON with `artifact_hash` omitted, reject path separators in `model_version`, and verify the Hash on every load.

- [ ] **Step 5: Run Feature and Repository tests**

Run: `python -m pytest tests/test_partition_features.py tests/test_partition_ranker_repository.py -q`

Expected: PASS, including stable Hash and tamper rejection.

- [ ] **Step 6: Commit Feature schema and Model Registry**

```bash
git add src/aiops_k8s_agents/partition_features.py src/aiops_k8s_agents/partition_ranker_repository.py tests/test_partition_features.py tests/test_partition_ranker_repository.py
git commit -m "Add partition ranking features and model registry"
```

### Task 3: Pure Python Learned Ranker와 Guarded Fallback

**Files:**
- Modify: `src/aiops_k8s_agents/partition_ranking.py`
- Modify: `src/aiops_k8s_agents/model_partition_agent.py`
- Modify: `config/model_partition_policy.json`
- Test: `tests/test_partition_ranking.py`
- Test: `tests/test_model_partition_agent.py`

**Interfaces:**
- Consumes: `PartitionRankerModelArtifact`, `extract_partition_features(...)`, deterministic ranking
- Produces: `LearnedRewardRanker.predict(...)`, `GuardedCandidateSelector.select(context, candidates, mode, model_version)`

- [ ] **Step 1: Write failing shadow, guarded, OOD, and invalid-candidate tests**

```python
def test_shadow_records_learned_choice_but_keeps_baseline(training_context, candidates, eligible_artifact):
    selector = GuardedCandidateSelector(
        deterministic=DeterministicPolicyRanker(),
        learned=LearnedRewardRanker(eligible_artifact),
    )
    selection = selector.select(training_context, candidates, SelectionMode.SHADOW)
    assert selection.learned_selected_candidate_key is not None
    assert selection.final_selected_candidate_key == selection.baseline_selected_candidate_key
    assert selection.fallback_used is False


def test_guarded_mode_falls_back_when_model_has_too_few_observed_samples(
    training_context, candidates, undertrained_artifact
):
    selection = guarded_selector(undertrained_artifact).select(
        training_context, candidates, SelectionMode.LEARNED_GUARDED
    )
    assert selection.final_selected_candidate_key == selection.baseline_selected_candidate_key
    assert selection.fallback_used is True
    assert selection.fallback_reason == "insufficient_observed_samples"


def test_learned_ranker_never_receives_hard_invalid_candidate(
    training_context, valid_candidate, invalid_candidate, eligible_artifact
):
    selection = guarded_selector(eligible_artifact).select(
        training_context,
        (invalid_candidate, valid_candidate),
        SelectionMode.LEARNED_GUARDED,
    )
    invalid_key = candidate_key(invalid_candidate, training_context.strategy_version)
    invalid_entry = next(entry for entry in selection.entries if entry.candidate_key == invalid_key)
    assert invalid_entry.eligible is False
    assert invalid_entry.predicted_reward is None
```

- [ ] **Step 2: Run tests and verify learned selection is absent**

Run: `python -m pytest tests/test_partition_ranking.py tests/test_model_partition_agent.py -q`

Expected: FAIL because Learned Ranker and Guard policy checks are not implemented.

- [ ] **Step 3: Extend the policy with exact Guard defaults**

```json
"learned_ranker_guard": {
  "minimum_observed_samples": 30,
  "minimum_independent_groups": 5,
  "maximum_holdout_mae": 0.25,
  "minimum_spearman_correlation": 0.30,
  "minimum_selection_confidence": 0.70,
  "maximum_ood_feature_ratio": 0.20
}
```

Parse this block into an immutable `LearnedRankerGuardPolicy` on `ModelPartitionPolicy`. Validate all fractions in `[0, 1]`, sample/group counts as positive integers, and MAE as non-negative.

- [ ] **Step 4: Implement dependency-free Ridge inference and structured confidence**

```python
class LearnedRewardRanker:
    def predict(self, features: Mapping[str, float]) -> tuple[float, float, tuple[str, ...]]:
        normalized = [
            (features[name] - mean) / scale
            for name, mean, scale in zip(
                self.artifact.feature_order,
                self.artifact.feature_mean,
                self.artifact.feature_scale,
                strict=True,
            )
        ]
        reward = self.artifact.intercept + sum(
            coefficient * value
            for coefficient, value in zip(
                self.artifact.coefficients, normalized, strict=True
            )
        )
        reward = max(-1.0, min(1.0, reward))
        confidence, warnings = prediction_confidence(self.artifact, features)
        return reward, confidence, warnings
```

Sort learned entries by `(-predicted_reward, -prediction_confidence, baseline_score, candidate_key)`. Store the five largest absolute `coefficient * normalized_feature` values in each entry's `feature_contributions`. Count features outside their training min/max range, calculate OOD ratio, and return one of the exact fallback codes: `model_unavailable`, `artifact_hash_invalid`, `feature_schema_mismatch`, `insufficient_observed_samples`, `insufficient_independent_groups`, `holdout_mae_exceeded`, `rank_correlation_below_threshold`, `feature_distribution_shift`, `selection_confidence_below_threshold`, `learned_inference_error`.

- [ ] **Step 5: Integrate selection modes without weakening the independent Validator**

Add optional constructor arguments `selector`, `selection_mode`, and `ranker_model_version` to `ModelPartitionOrchestrationAgent`. Default to a deterministic-only selector. The agent only maps the selector's `final_selected_candidate_key` to a candidate; `partition_service.py` continues to call `PartitionPlanValidator` after the plan is returned.

- [ ] **Step 6: Run focused ranking and orchestration tests**

Run: `python -m pytest tests/test_partition_ranking.py tests/test_model_partition_agent.py tests/test_partition_validator.py -q`

Expected: PASS; shadow does not mutate selection, guarded fallback is explicit, and invalid candidates receive no prediction.

- [ ] **Step 7: Commit learned Runtime ranking**

```bash
git add src/aiops_k8s_agents/partition_ranking.py src/aiops_k8s_agents/model_partition_agent.py config/model_partition_policy.json tests/test_partition_ranking.py tests/test_model_partition_agent.py
git commit -m "Add guarded learned partition candidate ranking"
```

### Task 4: Observed Outcome Dataset Builder

**Files:**
- Create: `src/aiops_k8s_agents/partition_learning.py`
- Test: `tests/test_partition_learning_dataset.py`

**Interfaces:**
- Consumes: persisted Model Partition reports, `PartitionPlanEvaluator` output, selected candidate, feature extractor
- Produces: `PartitionRankingTrainingRow`, `PartitionRankingDatasetSummary`, `build_partition_ranking_dataset(...)`

- [ ] **Step 1: Write failing evidence-boundary and leakage tests**

```python
def test_dataset_defaults_to_observed_selected_candidates_only(tmp_path, observed_report, predicted_report):
    write_report_fixture(tmp_path / "observed", observed_report)
    write_report_fixture(tmp_path / "predicted", predicted_report)
    summary = build_partition_ranking_dataset((tmp_path,), tmp_path / "dataset.jsonl")
    rows = read_jsonl(tmp_path / "dataset.jsonl")
    assert summary.scope == "observed"
    assert summary.row_count == 1
    assert rows[0]["evidence_level"] == "observed"
    assert rows[0]["candidate_key"] == observed_report["plan"]["selection"]["final_selected_candidate_key"]


def test_dataset_does_not_copy_selected_reward_to_alternatives(tmp_path, observed_report):
    write_report_fixture(tmp_path, observed_report)
    build_partition_ranking_dataset((tmp_path,), tmp_path / "dataset.jsonl")
    rows = read_jsonl(tmp_path / "dataset.jsonl")
    assert len(rows) == 1
    assert rows[0]["candidate_key"] != candidate_key(
        PartitionCandidate.from_dict(observed_report["plan"]["alternative_candidates"][0]),
        observed_report["plan"]["strategy_version"],
    )


def test_dataset_rejects_observed_row_without_source_or_timestamp(tmp_path, observed_report):
    observed_report["evaluation"]["metrics"].pop("source")
    write_report_fixture(tmp_path, observed_report)
    summary = build_partition_ranking_dataset((tmp_path,), tmp_path / "dataset.jsonl")
    assert summary.row_count == 0
    assert summary.rejections["missing_observed_provenance"] == 1
```

- [ ] **Step 2: Run tests and confirm Dataset APIs are absent**

Run: `python -m pytest tests/test_partition_learning_dataset.py -q`

Expected: FAIL because the training row and builder do not exist.

- [ ] **Step 3: Implement the versioned row and deterministic JSONL builder**

```python
@dataclass(frozen=True)
class PartitionRankingTrainingRow:
    row_id: str
    job_id: str
    plan_id: str
    plan_version: int
    candidate_key: str
    input_snapshot_hash: str
    policy_version: str
    strategy_version: str
    feature_schema_version: str
    features: dict[str, float]
    target_reward: float
    reward_components: dict[str, float]
    evidence_level: str
    evidence_source: str
    observed_at: str
    selected_by: str
    selection_probability: float | None
    runtime_outcome_ref: str


def build_partition_ranking_dataset(
    artifact_roots: Sequence[str | Path],
    output_path: str | Path,
    *,
    scope: str = "observed",
) -> PartitionRankingDatasetSummary:
    reports = tuple(iter_partition_reports(artifact_roots))
    rows, rejection_counts = collect_training_rows(reports, scope=scope)
    ordered_rows = tuple(sorted(rows, key=training_row_sort_key))
    return write_partition_ranking_dataset(
        ordered_rows,
        output_path,
        scope=scope,
        rejection_counts=rejection_counts,
        artifact_roots=artifact_roots,
    )
```

Scan committed `report.json` and `latest.json` files once by resolved path, require planned and independently validated reports, require exact selected candidate/selection Key agreement, finite observed metrics, `source`, `observed_at`, and Reward in `[-1, 1]`. Use SHA-256 of immutable lineage fields for `row_id`; sort rows by `(job_id, input_snapshot_hash, plan_id, plan_version)` before writing JSONL.

- [ ] **Step 4: Persist a Dataset manifest with provenance and selection-bias disclosure**

Write `<output>.manifest.json` containing schema version, scope, row count, rejected counts, dataset SHA-256, unique Job/Snapshot/Lineage group counts, source roots, and `selected_candidates_only: true`. For non-observed scopes require an explicit `scope` argument and label the manifest `eligible_for_real_claims: false`.

- [ ] **Step 5: Run Dataset tests**

Run: `python -m pytest tests/test_partition_learning_dataset.py -q`

Expected: PASS; predicted reports are excluded by default and no alternative receives a copied label.

- [ ] **Step 6: Commit Dataset generation**

```bash
git add src/aiops_k8s_agents/partition_learning.py tests/test_partition_learning_dataset.py
git commit -m "Build observed partition ranking datasets"
```

### Task 5: Offline Ridge Trainer와 Group-safe Evaluator

**Files:**
- Modify: `src/aiops_k8s_agents/partition_learning.py`
- Modify: `pyproject.toml`
- Test: `tests/test_partition_learning_training.py`

**Interfaces:**
- Consumes: versioned Dataset JSONL and manifest
- Produces: `train_partition_ranker(...)`, `evaluate_partition_ranker(...)`, registered JSON `PartitionRankerModelArtifact`

- [ ] **Step 1: Write failing group-split, Artifact export, and no-runtime-sklearn tests**

```python
def test_group_split_never_leaks_job_snapshot_lineage(dataset_rows):
    split = group_holdout_split(dataset_rows, test_fraction=0.2, seed=17)
    train_groups = {row.group_key for row in split.train}
    test_groups = {row.group_key for row in split.test}
    assert train_groups.isdisjoint(test_groups)


def test_training_exports_json_coefficients(tmp_path, observed_dataset_path):
    pytest.importorskip("sklearn")
    summary = train_partition_ranker(
        observed_dataset_path,
        registry_root=tmp_path / "registry",
        model_version="partition-ridge-observed-v1",
        seed=17,
    )
    payload = json.loads(summary.artifact_path.read_text(encoding="utf-8"))
    assert payload["model_type"] == "ridge_reward_regressor"
    assert payload["training_scope"] == "observed"
    assert len(payload["coefficients"]) == len(payload["feature_order"])
    assert "artifact_hash" in payload


def test_runtime_model_load_does_not_import_sklearn(tmp_path, exported_artifact, monkeypatch):
    monkeypatch.setitem(sys.modules, "sklearn", None)
    artifact = PartitionRankerRepository(tmp_path).get(exported_artifact.model_version)
    assert artifact.model_type == "ridge_reward_regressor"
```

- [ ] **Step 2: Run tests and verify trainer APIs are absent**

Run: `python -m pytest tests/test_partition_learning_training.py -q`

Expected: FAIL because group split, trainer, and evaluator are not implemented.

- [ ] **Step 3: Add the optional ML dependency without changing base installation**

```toml
ml = [
  "scikit-learn>=1.5,<2",
]
```

Import `Ridge` only inside `train_partition_ranker()`. Produce a clear `PartitionContractError("ml_dependency_missing", ...)` when the command is invoked without the optional dependency.

- [ ] **Step 4: Implement deterministic grouped training and validation**

```python
def group_key(row: PartitionRankingTrainingRow) -> str:
    return canonical_hash({
        "job_id": row.job_id,
        "input_snapshot_hash": row.input_snapshot_hash,
        "lineage_root": row.runtime_outcome_ref.split("/versions/")[0],
    })


def train_partition_ranker(
    dataset_path: str | Path,
    *,
    registry_root: str | Path,
    model_version: str,
    seed: int = 17,
    alpha: float = 1.0,
) -> PartitionRankerTrainingSummary:
    from sklearn.linear_model import Ridge
    dataset = load_partition_ranking_dataset(dataset_path)
    split = group_holdout_split(dataset.rows, test_fraction=0.2, seed=seed)
    normalizer = fit_feature_normalizer(split.train, FEATURE_ORDER)
    model = Ridge(alpha=alpha).fit(
        normalizer.transform(split.train),
        [row.target_reward for row in split.train],
    )
    artifact = export_ridge_artifact(
        model,
        normalizer,
        dataset,
        split,
        model_version=model_version,
    )
    path = PartitionRankerRepository(registry_root).save(artifact)
    return PartitionRankerTrainingSummary.from_artifact(path, artifact)
```

Fit feature mean/scale using the training group only, replace zero scale with `1.0`, train Ridge, calculate hold-out MAE, RMSE, Spearman rank correlation, candidate-selection agreement, and baseline regret. Export coefficients, intercept, training ranges, policy thresholds, Dataset Hash, sample/group counts, and validation metrics to the repository.

- [ ] **Step 5: Implement independent offline evaluation for an existing registered model**

`evaluate_partition_ranker(dataset_path, artifact)` must use the pure Python `LearnedRewardRanker`, report metrics separately for observed/predicted/synthetic scope, and refuse to merge scopes into one real-performance figure.

- [ ] **Step 6: Run training tests with and without the optional dependency**

Run: `python -m pytest tests/test_partition_learning_training.py tests/test_partition_ranker_repository.py -q`

Expected: PASS; sklearn-dependent test skips only when the optional dependency is absent, while Artifact load and pure-Python inference always run.

- [ ] **Step 7: Commit offline training and evaluation**

```bash
git add src/aiops_k8s_agents/partition_learning.py pyproject.toml tests/test_partition_learning_training.py
git commit -m "Train and evaluate partition reward rankers"
```

### Task 6: Service, Repository, Feedback, CLI End-to-End 연결

**Files:**
- Modify: `src/aiops_k8s_agents/partition_service.py`
- Modify: `src/aiops_k8s_agents/partition_repository.py`
- Modify: `src/aiops_k8s_agents/partition_artifacts.py`
- Modify: `src/aiops_k8s_agents/cli.py`
- Test: `tests/test_partition_service.py`
- Test: `tests/test_model_partition_cli.py`
- Test: `tests/test_partition_feedback.py`

**Interfaces:**
- Consumes: Model Registry root, `selection_mode`, optional registered `ranker_model_version`
- Produces: selection-aware reports, persisted ranking sidecar, Dataset/train/evaluate CLI JSON summaries

- [ ] **Step 1: Write failing service and CLI integration tests**

```python
def test_shadow_service_persists_baseline_and_learned_ranking(
    request_payload, policy_path, artifact_root, ranker_registry
):
    report = run_partition_planning(
        request_payload,
        policy_path=policy_path,
        artifact_root=artifact_root,
        selection_mode="shadow",
        ranker_registry_root=ranker_registry,
        ranker_model_version="partition-ridge-observed-v1",
        v2_request=True,
    )
    selection = report["plan"]["selection"]
    assert selection["mode"] == "shadow"
    assert selection["final_selected_candidate_key"] == selection["baseline_selected_candidate_key"]
    assert Path(report["artifact_path"]).with_name("candidate_ranking.json").is_file()


def test_feedback_replan_preserves_selection_mode_and_exclusions(
    persisted_shadow_report, feedback_service
):
    report = feedback_service.process_feedback(
        persisted_shadow_report["plan"]["plan_id"],
        placement_rejected_feedback(persisted_shadow_report),
    )
    assert report["plan"]["selection"]["mode"] == "shadow"
    assert report["replanning"]["bounded_exclusions"]["excluded_candidate_splits"]


def test_plan_cli_accepts_registered_model_version(cli_runner, request_path, registry_path):
    payload = cli_runner(
        "plan-model-partition-v2",
        "--input", str(request_path),
        "--selection-mode", "shadow",
        "--ranker-model-version", "partition-ridge-observed-v1",
        "--ranker-registry", str(registry_path),
    )
    assert payload["plan"]["selection"]["mode"] == "shadow"
```

- [ ] **Step 2: Run tests and verify the service signatures reject ranking options**

Run: `python -m pytest tests/test_partition_service.py tests/test_model_partition_cli.py tests/test_partition_feedback.py -q`

Expected: FAIL with unexpected keyword arguments and missing CLI options.

- [ ] **Step 3: Extend service signatures and build the selector in one helper**

Add `selection_mode: str = "deterministic"`, `ranker_registry_root: str | Path | None = None`, and `ranker_model_version: str | None = None` to `run_partition_planning(...)`, then construct the Agent through this exact integration block:

```python
selector = build_candidate_selector(
    policy=policy,
    selection_mode=SelectionMode(selection_mode),
    ranker_repository=(
        None
        if ranker_registry_root is None
        else PartitionRankerRepository(ranker_registry_root)
    ),
    model_version=ranker_model_version,
)
agent = ModelPartitionOrchestrationAgent(
    policy,
    plan_id_factory=plan_id_factory,
    strategy_registry=strategy_registry,
    selector=selector,
    selection_mode=SelectionMode(selection_mode),
    ranker_model_version=ranker_model_version,
)
```

Use `build_candidate_selector(...)` for both initial plans and `PartitionFeedbackService`. In replanning, inherit mode and model version from the previous plan unless the trusted service constructor explicitly overrides them. Never accept a model filesystem path from request payloads.

- [ ] **Step 4: Persist selection metadata and ranking sidecar transactionally**

Pass `candidate_ranking.json` through the repository's existing sidecar transaction using `plan.selection.to_dict()`. Add model version, Artifact Hash, final candidate Key, and selection mode to the history entry. Keep the repository's independent validation requirement unchanged.

- [ ] **Step 5: Add research CLI commands and planning options**

```text
build-partition-ranking-dataset --artifact-root PATH --output PATH --scope observed
train-partition-ranker --dataset PATH --ranker-registry PATH --model-version VERSION --seed 17
evaluate-partition-ranker --dataset PATH --ranker-registry PATH --model-version VERSION
plan-model-partition-v2 --selection-mode deterministic|shadow|learned_guarded --ranker-registry PATH --ranker-model-version VERSION
```

Each command returns JSON with source paths, Dataset/Artifact Hash, scope, model version, metrics, guarded eligibility, and output paths. `--ranker-model-version` is required for shadow and learned guarded modes; deterministic mode rejects it only if it refers to a missing registered model that the user explicitly requested.

- [ ] **Step 6: Run service, feedback, repository, and CLI tests**

Run: `python -m pytest tests/test_partition_service.py tests/test_partition_repository.py tests/test_partition_feedback.py tests/test_model_partition_cli.py -q`

Expected: PASS; feedback never revives excluded candidates and persisted reports include ranking provenance.

- [ ] **Step 7: Commit the end-to-end backend connection**

```bash
git add src/aiops_k8s_agents/partition_service.py src/aiops_k8s_agents/partition_repository.py src/aiops_k8s_agents/partition_artifacts.py src/aiops_k8s_agents/cli.py tests/test_partition_service.py tests/test_model_partition_cli.py tests/test_partition_feedback.py
git commit -m "Connect partition rankers to services and CLI"
```

### Task 7: Control Plane API와 Model 상태 조회

**Files:**
- Modify: `src/aiops_k8s_agents/control_plane_web.py`
- Test: `tests/test_model_partition_api.py`

**Interfaces:**
- Consumes: server-owned Ranker Registry and service selection options
- Produces: expanded `POST /api/model-partition/plans`, `GET /api/model-partition/rankers`, `GET /api/model-partition/rankers/{model_version}`

- [ ] **Step 1: Write failing request validation and registry status tests**

```python
def test_plan_api_accepts_shadow_mode_with_registered_model(client, v2_request):
    response = client.post(
        "/api/model-partition/plans",
        json={
            "request": v2_request,
            "selection_mode": "shadow",
            "ranker_model_version": "partition-ridge-observed-v1",
        },
    )
    assert response.status_code == 200
    assert response.json()["plan"]["selection"]["mode"] == "shadow"


def test_ranker_status_explains_guarded_ineligibility(client):
    response = client.get("/api/model-partition/rankers/undertrained-v1")
    assert response.status_code == 200
    payload = response.json()
    assert payload["guarded_eligible"] is False
    assert "insufficient_observed_samples" in payload["guard_failures"]


def test_plan_api_rejects_model_file_path(client, v2_request):
    response = client.post(
        "/api/model-partition/plans",
        json={
            "request": v2_request,
            "selection_mode": "shadow",
            "ranker_model_version": "../../model.json",
        },
    )
    assert response.status_code == 422
```

- [ ] **Step 2: Run API tests and confirm missing request fields/routes**

Run: `python -m pytest tests/test_model_partition_api.py -q`

Expected: FAIL because ranker routes and request fields do not exist.

- [ ] **Step 3: Extend API contracts and Runtime state**

```python
class ModelPartitionPlanRequest(BaseModel):
    round_plan: dict[str, Any] | None = None
    v2_request: dict[str, Any] | None = Field(default=None, alias="request")
    observed: dict[str, Any] | None = None
    previous_plan: dict[str, Any] | None = None
    failure: dict[str, Any] | None = None
    replan_attempt: int = 1
    selection_mode: Literal["deterministic", "shadow", "learned_guarded"] = "deterministic"
    ranker_model_version: str | None = None
```

Add a server-configured `ranker_registry_root` to `RuntimeApiState`; default it under the repository's runtime Artifact area. Resolve only `ranker_model_version` through `PartitionRankerRepository`.

- [ ] **Step 4: Add explicit Model eligibility responses**

`GET /api/model-partition/rankers` returns `{models: [...]}`. Each model item includes version, feature schema, training scope, sample/group count, validation metrics, Artifact Hash, `guarded_eligible`, and ordered `guard_failures`. `GET /api/model-partition/rankers/{model_version}` returns 404 for an unknown version and 422 for an invalid version token.

- [ ] **Step 5: Run API tests including legacy requests**

Run: `python -m pytest tests/test_model_partition_api.py tests/test_control_plane_web.py -q`

Expected: PASS; existing request bodies without selection fields remain deterministic.

- [ ] **Step 6: Commit Control Plane integration**

```bash
git add src/aiops_k8s_agents/control_plane_web.py tests/test_model_partition_api.py
git commit -m "Expose partition ranker modes and status API"
```

### Task 8: Platform UI의 Baseline 대 AI 추천 비교

**Files:**
- Modify: `ui/control_plane_static/index.html`
- Modify: `ui/control_plane_static/app.js`
- Modify: `ui/control_plane_static/styles.css`
- Test: `tests/test_control_plane_ui.py`

**Interfaces:**
- Consumes: ranker status API and `plan.selection`
- Produces: selection-mode controls, model eligibility display, candidate comparison, fallback and feedback provenance

- [ ] **Step 1: Write failing static UI contract tests**

```python
def test_partition_workspace_exposes_selection_mode_and_registered_model_controls(index_html):
    assert 'id="partition-selection-mode"' in index_html
    assert 'id="partition-ranker-model"' in index_html
    assert 'id="partition-ranker-status"' in index_html


def test_partition_workspace_labels_baseline_ai_and_final_selection(app_script):
    assert "Baseline 선택" in app_script
    assert "AI 추천" in app_script
    assert "최종 선택" in app_script
    assert "주요 Feature 기여도" in app_script
    assert "Shadow 추천은 실행 후보를 변경하지 않습니다" in app_script
    assert "/api/model-partition/rankers" in app_script
```

- [ ] **Step 2: Run UI tests and confirm missing controls**

Run: `python -m pytest tests/test_control_plane_ui.py -q`

Expected: FAIL because ranking controls and comparison labels are absent.

- [ ] **Step 3: Add concise selection controls to Plan Intake**

Add a segmented mode control for `Deterministic`, `Shadow`, `Learned Guarded`, a registered Model selector, and a compact eligibility line. Disable `Learned Guarded` when no eligible registered model exists and show the first structured guard failure rather than a generic error.

- [ ] **Step 4: Render candidate comparison without replacing the current four-stage workspace**

```javascript
function partitionRankingSummary(selection) {
  return `
    <div class="partition-ranking-summary">
      ${rankingDecision("Baseline 선택", selection.baseline_selected_candidate_key)}
      ${rankingDecision("AI 추천", selection.learned_selected_candidate_key || "없음")}
      ${rankingDecision("최종 선택", selection.final_selected_candidate_key)}
    </div>
  `;
}
```

For every candidate show Baseline Score and Predicted Reward in separate columns. Mark invalid candidates `Hard Constraint 제외`; never show them as AI-ranked. Show `연구용 합성 모델` when training scope is not observed. In shadow mode display the exact message `Shadow 추천은 실행 후보를 변경하지 않습니다`.

- [ ] **Step 5: Render final authority and feedback provenance in Handoff**

Show final selector, fallback status/reason, model version/hash abbreviation, independent Validator result, predicted Reward, observed Reward, and `Dataset 반영: 포함/제외 + 이유`. Keep the existing `Scheduling Agent (External)` boundary visible.

- [ ] **Step 6: Run UI tests and browser smoke checks**

Run: `python -m pytest tests/test_control_plane_ui.py tests/test_model_partition_api.py -q`

Run the local console, open the Model Partition workspace, load the training sample, and verify deterministic, shadow, and guarded-fallback layouts at 1440×900 and 390×844. Confirm no horizontal overflow, no overlapping controls, and readable fallback text.

- [ ] **Step 7: Commit the platform comparison experience**

```bash
git add ui/control_plane_static/index.html ui/control_plane_static/app.js ui/control_plane_static/styles.css tests/test_control_plane_ui.py
git commit -m "Show guarded partition ranking in research console"
```

### Task 9: Documentation, Reproducible Experiment Commands, and Full Verification

**Files:**
- Modify: `README.md`
- Create: `docs/experiments/partition_ranker_experiment_guide.md`
- Modify: `docs/submission/execution_code_guide.md`
- Create: `docs/design/model_partition_orchestrator_agent_design.md`
- Test: `tests/test_documentation_contracts.py`

**Interfaces:**
- Consumes: completed CLI/API/UI behavior
- Produces: reproducible deterministic-vs-shadow-vs-guarded experiment sequence and exact research boundaries

- [ ] **Step 1: Write failing documentation contract tests**

```python
def test_ranker_docs_keep_scheduler_and_learning_scope_explicit():
    repo_root = Path(__file__).resolve().parents[1]
    guide = (repo_root / "docs/experiments/partition_ranker_experiment_guide.md").read_text(
        encoding="utf-8"
    )
    assert "Scheduling Agent는 외부 구성요소" in guide
    assert "observed" in guide
    assert "predicted·mock·dry-run 결과는 Real Runtime 성능 근거로 사용하지 않는다" in guide
    assert "--selection-mode shadow" in guide
    assert "--selection-mode learned_guarded" in guide
```

- [ ] **Step 2: Run the documentation test and verify the guide is absent**

Run: `python -m pytest tests/test_documentation_contracts.py -q`

Expected: FAIL because the new experiment guide does not exist.

- [ ] **Step 3: Document the exact research workflow and boundary**

The guide must provide these executable stages with real paths replaced only by shell variables:

```bash
aiops-k8s-agents build-partition-ranking-dataset \
  --artifact-root "$PARTITION_ARTIFACT_ROOT" \
  --output "$PARTITION_DATASET" \
  --scope observed

python -m pip install -e ".[ml]"

aiops-k8s-agents train-partition-ranker \
  --dataset "$PARTITION_DATASET" \
  --ranker-registry "$PARTITION_RANKER_REGISTRY" \
  --model-version partition-ridge-observed-v1 \
  --seed 17

aiops-k8s-agents plan-model-partition-v2 \
  --input config/examples/model_partition_training_v2.json \
  --selection-mode shadow \
  --ranker-registry "$PARTITION_RANKER_REGISTRY" \
  --ranker-model-version partition-ridge-observed-v1
```

Explain that the Model Partition Orchestrator owns candidate ranking, while Dataset Builder, Trainer, Evaluator, and Model Registry are supporting research components. State that Scheduling remains external and Ranker output is a `PartitionExecutionPlan`, not a runtime schedule.

- [ ] **Step 4: Run all Python tests**

Run: `python -m pytest`

Expected: all tests PASS with no regression in Recovery, AIOpsLab, AutoGen, Control Plane, or legacy Model Partition paths.

- [ ] **Step 5: Run Go tests when the repository still contains the optional Guard module**

Run: `if (Test-Path go/aiops-guard/go.mod) { Push-Location go/aiops-guard; go test ./...; Pop-Location }`

Expected: PASS when the module exists; otherwise the command exits without altering Python validation.

- [ ] **Step 6: Verify CLI help and a deterministic smoke run**

Run: `aiops-k8s-agents plan-model-partition-v2 --help`

Expected: help lists `--selection-mode`, `--ranker-registry`, and `--ranker-model-version`.

Run: `aiops-k8s-agents plan-model-partition-v2 --input config/examples/model_partition_training_v2.json --selection-mode deterministic`

Expected: planned report, independent validation PASS, selection mode `deterministic`, and Scheduling handoff `ready`.

- [ ] **Step 7: Check plan and documentation for misleading claims**

Run: `rg -n "완전 자율|실제 스케줄링 완료|Mock.*Real" README.md docs/experiments/partition_ranker_experiment_guide.md docs/design/model_partition_orchestrator_agent_design.md`

Expected: no unfinished placeholders and no claim that predicted/mock data proves Real Runtime performance or that this component implements Scheduling.

- [ ] **Step 8: Commit docs and final verification contracts**

```bash
git add README.md docs/experiments/partition_ranker_experiment_guide.md docs/submission/execution_code_guide.md docs/design/model_partition_orchestrator_agent_design.md tests/test_documentation_contracts.py
git commit -m "Document learned partition ranking experiments"
```

## Completion Evidence

- Existing deterministic Model Partition fixtures select the same candidate as before.
- Shadow mode records AI predictions but cannot change the final candidate.
- Learned Guarded mode uses AI selection only when all policy gates pass; every fallback has a stable reason code.
- Invalid candidates are never sent to the learned model and the independent Validator remains authoritative.
- Default Dataset contains only observed, provenance-complete, selected-candidate Outcomes.
- Model Artifact is canonical JSON with verified SHA-256 and pure-Python Runtime inference.
- Feedback replanning preserves prior exclusions and selection provenance.
- CLI, API, and UI expose the same selection modes and registered model versions.
- UI distinguishes Baseline Score, Predicted Reward, Evaluator Reward, observed evidence, and external Scheduling.
- Full Python tests and the optional Go Guard test suite pass.
