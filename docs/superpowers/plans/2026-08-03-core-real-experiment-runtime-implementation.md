# Core Real Experiment Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prometheus, Chaos Mesh, Kubernetes, 4-Agent Coordinator를 안전한 하나의 실험 런타임으로 연결하고 이후 웹 Job 시스템이 호출할 안정적인 서비스 인터페이스를 제공한다.

**Architecture:** 외부 시스템별 Adapter를 작은 모듈로 분리하고 `ExperimentRuntime`이 preflight, 장애 수명주기, Agent 실행, cleanup 순서를 조정한다. 기존 `MutualSupervisionCoordinator`, `KubernetesExecutor`, `ExperimentSession`은 재사용하며 테스트에서는 주입 가능한 fake runner를 사용한다.

**Tech Stack:** Python 3.11+, dataclasses, urllib, subprocess, existing FastAPI-compatible domain objects, pytest, Kubernetes CLI, Prometheus HTTP API, Chaos Mesh CRDs

## Global Constraints

- 기존 deterministic CLI와 command contract를 유지한다.
- `mock`, `dry-run`, `real` 결과를 서로 대체 가능한 증거로 취급하지 않는다.
- real 실행은 allowlist, replica limit, operation lock, timeout, cleanup을 우회할 수 없다.
- 웹 브라우저는 Kubernetes 명령을 직접 실행하지 않는다.
- 모든 실행 단계는 하나의 `experiment_id`와 `ExperimentSession`으로 연결한다.
- Python 단위 테스트는 외부 API key와 real Kubernetes 없이 재현 가능해야 한다.
- real end-to-end 검증은 Ubuntu 연구실 서버에서만 수행한다.

---

## File Structure

### 새 파일

- `src/aiops_k8s_agents/experiment_runtime_models.py`
  - runtime request, stage, event, result의 불변 domain model
- `src/aiops_k8s_agents/real_evidence.py`
  - Prometheus metric과 Kubernetes snapshot을 결합하는 Evidence Provider
- `src/aiops_k8s_agents/chaos_adapter.py`
  - 등록된 Chaos Mesh scenario의 apply/status/delete 수명주기
- `src/aiops_k8s_agents/experiment_runtime.py`
  - preflight부터 cleanup까지 단일 실험 orchestration
- `tests/test_experiment_runtime_models.py`
- `tests/test_real_evidence.py`
- `tests/test_chaos_adapter.py`
- `tests/test_experiment_runtime.py`

### 수정 파일

- `src/aiops_k8s_agents/prometheus.py`
  - timestamp와 labels를 보존하는 일반 vector query 인터페이스 추가
- `src/aiops_k8s_agents/experiment_session.py`
  - runtime stage event를 정규화할 수 있도록 상태 vocabulary 확장
- `src/aiops_k8s_agents/control_plane_data.py`
  - scenario catalog를 runtime에서 재사용 가능한 형태로 노출
- `config/experiment_runtime.json`
  - scenario, metric query, allowlist, timeout의 기본 등록 설정
- `tests/test_prometheus_adapter.py`
- `tests/test_experiment_session.py`
- `README.md`
  - 구현된 runtime 범위와 아직 웹 미연결인 경계 설명

---

### Task 1: Runtime Domain Contracts

**Files:**
- Create: `src/aiops_k8s_agents/experiment_runtime_models.py`
- Create: `tests/test_experiment_runtime_models.py`

**Interfaces:**
- Produces: `RuntimeStage`, `RuntimeEvent`, `ExperimentRuntimeRequest`, `ExperimentRuntimeResult`
- Consumes: `ExecutionMode`, `ExecutionBackend`, `ExperimentSession`

- [ ] **Step 1: Write failing model tests**

```python
from aiops_k8s_agents.experiment_runtime_models import (
    ExperimentRuntimeRequest,
    RuntimeEvent,
    RuntimeStage,
)


def test_runtime_request_normalizes_mode_and_target():
    request = ExperimentRuntimeRequest(
        scenario_id="cpu-stress",
        namespace=" online-boutique ",
        deployment=" paymentservice ",
        metric="CPU",
        threshold=80.0,
        mode="dry-run",
        backend="python",
        protocol_profile="four-agent-role-veto-v1",
    )
    assert request.namespace == "online-boutique"
    assert request.deployment == "paymentservice"
    assert request.metric == "cpu"
    assert request.mode.value == "dry-run"


def test_runtime_event_serializes_monotonic_sequence():
    event = RuntimeEvent(
        experiment_id="exp-1",
        sequence=3,
        stage=RuntimeStage.COLLECTING_EVIDENCE,
        status="running",
        message="collecting registered evidence",
        created_at="2026-08-03T00:00:00+00:00",
        payload={"source": "fake"},
    )
    assert event.to_dict()["sequence"] == 3
    assert event.to_dict()["stage"] == "collecting_evidence"
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest tests/test_experiment_runtime_models.py -q`

Expected: FAIL with `ModuleNotFoundError: aiops_k8s_agents.experiment_runtime_models`.

- [ ] **Step 3: Implement the immutable runtime models**

Use these exact public types:

```python
class RuntimeStage(str, Enum):
    QUEUED = "queued"
    PREFLIGHT = "preflight"
    INJECTING_FAULT = "injecting_fault"
    COLLECTING_EVIDENCE = "collecting_evidence"
    AGENT_REASONING = "agent_reasoning"
    NEGOTIATING = "negotiating"
    VALIDATING = "validating"
    EXECUTING = "executing"
    OBSERVING_RECOVERY = "observing_recovery"
    ANALYZING = "analyzing"
    CLEANUP = "cleanup"
    COMPLETED = "completed"


@dataclass(frozen=True)
class ExperimentRuntimeRequest:
    scenario_id: str
    namespace: str
    deployment: str
    metric: str
    threshold: float
    mode: ExecutionMode
    backend: ExecutionBackend
    protocol_profile: str
    repetitions: int = 1


@dataclass(frozen=True)
class RuntimeEvent:
    experiment_id: str
    sequence: int
    stage: RuntimeStage
    status: str
    message: str
    created_at: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExperimentRuntimeResult:
    experiment_id: str
    status: str
    report: Mapping[str, Any]
    session: ExperimentSession
    events: tuple[RuntimeEvent, ...]
    cleanup: Mapping[str, Any]
```

Validation rules:

- strip `scenario_id`, namespace, deployment, metric, profile
- normalize metric with lowercase and `_`
- coerce string mode/backend through existing enums
- reject empty identifiers
- require `repetitions >= 1`
- accept only finite thresholds

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/test_experiment_runtime_models.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the domain contracts**

```bash
git add src/aiops_k8s_agents/experiment_runtime_models.py tests/test_experiment_runtime_models.py
git commit -m "feat: add experiment runtime contracts"
```

---

### Task 2: Prometheus Vector Query Contract

**Files:**
- Modify: `src/aiops_k8s_agents/prometheus.py`
- Modify: `tests/test_prometheus_adapter.py`

**Interfaces:**
- Produces: `PrometheusSample`, `PrometheusAdapter.query_vector(query: str) -> tuple[PrometheusSample, ...]`, `PrometheusAdapter.ready() -> bool`
- Consumes: existing `fetch_prometheus_query(base_url, query)`

- [ ] **Step 1: Add failing tests for labels, timestamp, and readiness**

```python
def test_query_vector_preserves_labels_timestamp_and_value():
    adapter = PrometheusAdapter(
        "http://prometheus",
        fetcher=lambda _url, _query: {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [{
                    "metric": {"namespace": "online-boutique", "pod": "payment-1"},
                    "value": [1780000000.5, "3.25"],
                }],
            },
        },
    )
    samples = adapter.query_vector("up")
    assert samples[0].labels["pod"] == "payment-1"
    assert samples[0].timestamp == 1780000000.5
    assert samples[0].value == 3.25


def test_query_vector_rejects_non_vector_result():
    adapter = PrometheusAdapter(
        "http://prometheus",
        fetcher=lambda _url, _query: {
            "status": "success",
            "data": {"resultType": "matrix", "result": []},
        },
    )
    with pytest.raises(PrometheusAdapterError, match="vector"):
        adapter.query_vector("up")
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_prometheus_adapter.py -q`

Expected: FAIL because `PrometheusSample` and `query_vector` do not exist.

- [ ] **Step 3: Implement the query contract**

```python
@dataclass(frozen=True)
class PrometheusSample:
    labels: dict[str, str]
    timestamp: float
    value: float


def query_vector(self, query: str) -> tuple[PrometheusSample, ...]:
    response = (self.fetcher or fetch_prometheus_query)(self.base_url, query)
    return prometheus_result_to_samples(response)


def ready(self) -> bool:
    try:
        return bool(self.query_vector("vector(1)"))
    except (OSError, ValueError):
        return False
```

`prometheus_result_to_samples` must reject unsuccessful responses, non-vector
result types, malformed values, and non-finite values. An empty valid vector is
returned as `()`; the Evidence Provider decides whether that is an error.

- [ ] **Step 4: Run adapter tests**

Run: `python -m pytest tests/test_prometheus_adapter.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aiops_k8s_agents/prometheus.py tests/test_prometheus_adapter.py
git commit -m "feat: expose prometheus vector samples"
```

---

### Task 3: Registered Real Evidence Provider

**Files:**
- Create: `src/aiops_k8s_agents/real_evidence.py`
- Create: `tests/test_real_evidence.py`
- Create: `config/experiment_runtime.json`

**Interfaces:**
- Consumes: `PrometheusAdapter.query_vector`, `collect_kubernetes_snapshot`
- Produces: `MetricQueryDefinition`, `RuntimeConfiguration`, `load_runtime_configuration(path)`, `PrometheusKubernetesEvidenceProvider.collect(namespace, deployment)`

- [ ] **Step 1: Write failing evidence fusion tests**

```python
class FakePrometheus:
    def __init__(self, values):
        self.values = values

    def query_vector(self, query):
        metric = next(
            (name for name, registered in {
                "cpu": "registered-cpu-query"
            }.items() if registered == query),
            "",
        )
        value = self.values[metric]
        return (
            PrometheusSample(
                labels={"namespace": "online-boutique"},
                timestamp=time.time(),
                value=value,
            ),
        )


def test_real_evidence_combines_registered_metric_and_kubernetes_snapshot():
    provider = PrometheusKubernetesEvidenceProvider(
        prometheus=FakePrometheus({"cpu": 3.5}),
        metric_queries={"cpu": "registered-cpu-query"},
        requested_metric="cpu",
        kubernetes_collector=lambda **_kwargs: {
            "deployment_status": {
                "ok": True,
                "desired_replicas": 2,
                "available_replicas": 1,
            },
            "pods": {
                "ok": True,
                "items": [{"name": "p-1", "uid": "u-1", "phase": "Running", "restarts": 2}],
            },
        },
    )
    evidence = provider.collect("online-boutique", "paymentservice")
    assert evidence.metric_values == {"cpu": 3.5}
    assert evidence.desired_replicas == 2
    assert evidence.available_replicas == 1
    assert evidence.restart_count == 2
    assert evidence.source == "prometheus+kubernetes"


def test_real_evidence_rejects_unregistered_metric():
    with pytest.raises(ValueError, match="unregistered metric"):
        PrometheusKubernetesEvidenceProvider(
            prometheus=FakePrometheus({}),
            metric_queries={},
            requested_metric="arbitrary-promql",
        )
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_real_evidence.py -q`

Expected: FAIL because `real_evidence` does not exist.

- [ ] **Step 3: Add the runtime configuration**

Create `config/experiment_runtime.json` with this schema and registered defaults:

```json
{
  "version": "1.0.0",
  "allowed_namespaces": ["online-boutique"],
  "allowed_deployments": ["paymentservice", "checkoutservice"],
  "min_replicas": 1,
  "max_replicas": 5,
  "timeouts": {
    "preflight_seconds": 15,
    "fault_ready_seconds": 60,
    "recovery_seconds": 120,
    "cleanup_seconds": 60
  },
  "metric_queries": {
    "cpu": "sum(rate(container_cpu_usage_seconds_total{namespace=\"{namespace}\",pod=~\"{deployment}-.*\",container!=\"\",image!=\"\"}[1m])) * 100",
    "memory": "max(container_memory_working_set_bytes{namespace=\"{namespace}\",pod=~\"{deployment}-.*\",container!=\"\",image!=\"\"})",
    "latency": "max(probe_duration_seconds{target=\"paymentservice\"})",
    "availability": "kube_deployment_status_replicas_available{namespace=\"{namespace}\",deployment=\"{deployment}\"}"
  },
  "scenarios": {
    "pod-kill": "k8s/paymentservice-pod-kill.yaml",
    "cpu-stress": "k8s/chaos/paymentservice-cpu-stress.yaml",
    "memory-stress": "k8s/chaos/checkoutservice-memory-stress.yaml",
    "network-delay": "k8s/chaos/paymentservice-network-delay.yaml"
  }
}
```

- [ ] **Step 4: Implement safe query template rendering and fusion**

`MetricQueryDefinition.render(namespace, deployment)` must reject values that
do not match the Kubernetes name rule before formatting. The provider must:

- require the requested metric in `metric_queries`
- require exactly one usable sample after aggregation
- reject samples older than `max_sample_age_seconds`
- preserve the query, timestamp, and labels in `events` as sanitized summaries
- raise `EvidenceCollectionError` when Prometheus or Kubernetes collection fails

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_real_evidence.py tests/test_prometheus_adapter.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add config/experiment_runtime.json src/aiops_k8s_agents/real_evidence.py tests/test_real_evidence.py
git commit -m "feat: fuse prometheus and kubernetes evidence"
```

---

### Task 4: Chaos Mesh Scenario Adapter

**Files:**
- Create: `src/aiops_k8s_agents/chaos_adapter.py`
- Create: `tests/test_chaos_adapter.py`

**Interfaces:**
- Consumes: scenario manifest mapping from `RuntimeConfiguration`
- Produces: `ChaosScenario`, `ChaosApplication`, `ChaosMeshAdapter.preflight()`, `ChaosMeshAdapter.inject(scenario_id)`, `ChaosMeshAdapter.cleanup(application)`

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_chaos_adapter_applies_waits_and_deletes_registered_manifest(tmp_path):
    manifest = tmp_path / "cpu.yaml"
    manifest.write_text("kind: StressChaos\n", encoding="utf-8")
    calls = []

    def runner(argv):
        calls.append(argv)
        if argv[:2] == ["kubectl", "api-resources"]:
            return 0, "stresschaos", ""
        return 0, "ok", ""

    adapter = ChaosMeshAdapter(
        scenarios={"cpu-stress": manifest},
        runner=runner,
        sleeper=lambda _seconds: None,
    )
    assert adapter.preflight().valid is True
    application = adapter.inject("cpu-stress")
    cleanup = adapter.cleanup(application)
    assert application.valid is True
    assert cleanup.valid is True
    assert ["kubectl", "apply", "-f", str(manifest)] in calls
    assert ["kubectl", "delete", "-f", str(manifest), "--ignore-not-found"] in calls


def test_chaos_adapter_rejects_unknown_scenario():
    adapter = ChaosMeshAdapter(scenarios={}, runner=lambda _argv: (0, "", ""))
    with pytest.raises(ValueError, match="unknown chaos scenario"):
        adapter.inject("disk-corruption")
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_chaos_adapter.py -q`

Expected: FAIL because `chaos_adapter` does not exist.

- [ ] **Step 3: Implement the bounded Adapter**

Use structured subprocess argv only. `preflight` must verify:

- every configured manifest resolves under the repository `k8s` directory
- `kubectl api-resources` contains the required Chaos Mesh resource types
- no configured file is missing

`inject` records stdout/stderr and returns the application timestamp. `cleanup`
is idempotent and always uses `--ignore-not-found`. Do not parse YAML with string
replacement and do not accept an arbitrary manifest path from an HTTP request.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_chaos_adapter.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aiops_k8s_agents/chaos_adapter.py tests/test_chaos_adapter.py
git commit -m "feat: add bounded chaos mesh adapter"
```

---

### Task 5: Experiment Runtime Orchestration

**Files:**
- Create: `src/aiops_k8s_agents/experiment_runtime.py`
- Create: `tests/test_experiment_runtime.py`
- Modify: `src/aiops_k8s_agents/experiment_session.py`
- Modify: `tests/test_experiment_session.py`

**Interfaces:**
- Consumes: `ExperimentRuntimeRequest`, `ChaosMeshAdapter`, `EvidenceProvider`, `MutualSupervisionCoordinator`, `normalize_experiment_session`
- Produces: `RuntimeEventSink.emit(event)`, `ExperimentRuntime.run(request) -> ExperimentRuntimeResult`

- [ ] **Step 1: Write the failing happy-path integration test**

```python
class RecordingEventSink:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)


class FakeChaosAdapter:
    def __init__(self):
        self.calls = []

    def preflight(self):
        self.calls.append("preflight")
        return SimpleNamespace(valid=True, stderr="")

    def inject(self, scenario_id):
        self.calls.append(f"inject:{scenario_id}")
        return SimpleNamespace(
            scenario_id=scenario_id,
            valid=True,
            stderr="",
        )

    def cleanup(self, application):
        self.calls.append(f"cleanup:{application.scenario_id}")
        return {"valid": True, "stderr": ""}


class FakeCoordinator:
    def __init__(self, report):
        self.report = report

    def run(self, namespace, deployment, metric, threshold):
        return dict(self.report)


class RaisingCoordinator:
    def run(self, namespace, deployment, metric, threshold):
        raise RuntimeError("coordinator failed")


def approved_report(run_id):
    return {
        "run_id": run_id,
        "mode": "real",
        "final_status": "recovered",
        "active_agents": ["HA", "Application", "Infrastructure", "Cost"],
        "evidence": {
            "scenario": "cpu-stress",
            "namespace": "online-boutique",
            "deployment": "paymentservice",
            "metric_values": {"cpu": 95.0},
            "source": "prometheus+kubernetes",
        },
        "diagnosis": {"cause": "cpu_saturation"},
        "negotiation": {"consensus": "approved"},
        "safety_validation": {"valid": True},
        "execution_result": {"valid": True, "mode": "real"},
        "recovery_monitoring": {"recovery_success": True},
    }


def real_request():
    return ExperimentRuntimeRequest(
        scenario_id="cpu-stress",
        namespace="online-boutique",
        deployment="paymentservice",
        metric="cpu",
        threshold=80.0,
        mode="real",
        backend="python",
        protocol_profile="four-agent-role-veto-v1",
    )


def mock_request():
    return replace(real_request(), mode=ExecutionMode.MOCK)


def test_runtime_runs_fault_agent_cleanup_as_one_experiment():
    events = RecordingEventSink()
    chaos = FakeChaosAdapter()
    coordinator = FakeCoordinator(report=approved_report(run_id="exp-runtime-1"))
    runtime = ExperimentRuntime(
        configuration=runtime_configuration(),
        chaos=chaos,
        coordinator_factory=lambda _request: coordinator,
        event_sink=events,
        experiment_id_factory=lambda: "exp-runtime-1",
    )
    result = runtime.run(real_request())
    assert result.experiment_id == "exp-runtime-1"
    assert result.status == "recovered"
    assert chaos.calls == ["preflight", "inject:cpu-stress", "cleanup:cpu-stress"]
    assert [event.stage.value for event in result.events] == [
        "preflight",
        "injecting_fault",
        "collecting_evidence",
        "agent_reasoning",
        "validating",
        "executing",
        "observing_recovery",
        "cleanup",
        "completed",
    ]
```

- [ ] **Step 2: Write failing cleanup and safety tests**

```python
def test_runtime_cleans_up_fault_when_coordinator_raises():
    chaos = FakeChaosAdapter()
    runtime = runtime_with(coordinator=RaisingCoordinator(), chaos=chaos)
    result = runtime.run(real_request())
    assert result.status == "failed"
    assert "cleanup:cpu-stress" in chaos.calls
    assert result.cleanup["valid"] is True


def test_runtime_does_not_inject_fault_for_mock_mode():
    chaos = FakeChaosAdapter()
    result = runtime_with(chaos=chaos).run(mock_request())
    assert not any(call.startswith("inject:") for call in chaos.calls)
    assert result.session.mode == "mock"


def test_runtime_rejects_target_outside_allowlist_before_fault_injection():
    chaos = FakeChaosAdapter()
    result = runtime_with(chaos=chaos).run(
        replace(real_request(), deployment="not-allowed")
    )
    assert result.status == "blocked"
    assert chaos.calls == []
```

Define `runtime_configuration()` in the test with the exact allowlists
`{"online-boutique"}` and `{"paymentservice", "checkoutservice"}` and replica
bounds `1..5`. Define `runtime_with(coordinator=None, chaos=None)` to construct
`ExperimentRuntime` with that configuration, a `RecordingEventSink`, the fixed
id factory `lambda: "exp-runtime-1"`, and `FakeCoordinator(approved_report(...))`
when no coordinator is supplied.

- [ ] **Step 3: Verify RED**

Run: `python -m pytest tests/test_experiment_runtime.py -q`

Expected: FAIL because `ExperimentRuntime` does not exist.

- [ ] **Step 4: Implement the runtime state machine**

Use this constructor boundary:

```python
@dataclass
class ExperimentRuntime:
    configuration: RuntimeConfiguration
    chaos: ChaosMeshAdapter
    coordinator_factory: Callable[[ExperimentRuntimeRequest], MutualSupervisionCoordinator]
    event_sink: RuntimeEventSink
    experiment_id_factory: Callable[[], str] = default_experiment_id

    def run(self, request: ExperimentRuntimeRequest) -> ExperimentRuntimeResult:
        ...
```

Required order:

1. validate target and profile before external operations
2. emit `preflight`
3. acquire `TargetOperationLock` for real mode
4. preflight external adapters
5. inject registered fault only in real mode
6. emit Evidence and Agent stages around coordinator execution
7. preserve coordinator safety/execution/recovery report
8. cleanup in `finally`
9. attach runtime events and cleanup result to report
10. normalize one immutable `ExperimentSession`

Add `RuntimeResearchEventBridge`, implementing the existing
`ResearchEventSink.append(stream, event)` contract, to translate coordinator
streams into live runtime stages:

```python
STREAM_STAGE = {
    "evidence": RuntimeStage.COLLECTING_EVIDENCE,
    "initial_decisions": RuntimeStage.AGENT_REASONING,
    "peer_reviews": RuntimeStage.NEGOTIATING,
    "negotiation_rounds": RuntimeStage.NEGOTIATING,
    "safety_validations": RuntimeStage.VALIDATING,
    "executed_actions": RuntimeStage.EXECUTING,
    "post_execution_reviews": RuntimeStage.OBSERVING_RECOVERY,
}
```

The bridge forwards finalization to the configured artifact event store and
emits runtime events without changing the existing coordinator contract.

If cleanup fails, preserve the primary result and add `cleanup_error`; mark
`human_review_required=true`. Do not hide the initial exception.

- [ ] **Step 5: Extend ExperimentSession status normalization**

Add explicit handling for `cancelled`, `interrupted`, `blocked`, and
`cleanup_failed`. Preserve existing status behavior and existing tests.

- [ ] **Step 6: Run focused tests**

Run: `python -m pytest tests/test_experiment_runtime.py tests/test_experiment_session.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/aiops_k8s_agents/experiment_runtime.py src/aiops_k8s_agents/experiment_session.py tests/test_experiment_runtime.py tests/test_experiment_session.py
git commit -m "feat: orchestrate bounded real experiments"
```

---

### Task 6: Runtime Factory and Scenario Catalog Integration

**Files:**
- Modify: `src/aiops_k8s_agents/control_plane_data.py`
- Create: `src/aiops_k8s_agents/experiment_runtime_factory.py`
- Create: `tests/test_experiment_runtime_factory.py`
- Modify: `tests/test_control_plane_data.py`

**Interfaces:**
- Consumes: `load_runtime_configuration`, `PrometheusAdapter`, `ChaosMeshAdapter`, `MutualSupervisionCoordinator`
- Produces: `build_experiment_runtime(configuration_path, prometheus_url, event_sink)`, `runtime_scenario_catalog(configuration)`

- [ ] **Step 1: Write failing factory tests**

```python
def write_runtime_config(tmp_path):
    source = Path("config/experiment_runtime.json")
    destination = tmp_path / "experiment_runtime.json"
    destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return destination


def fake_prometheus_fetcher(_url, _query):
    return {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [{"metric": {}, "value": [1780000000.0, "1"]}],
        },
    }


def test_runtime_factory_builds_real_dependencies_from_registered_config(tmp_path):
    configuration_path = write_runtime_config(tmp_path)
    runtime = build_experiment_runtime(
        configuration_path=configuration_path,
        prometheus_url="http://127.0.0.1:9091",
        event_sink=RecordingEventSink(),
        subprocess_runner=lambda _argv: (0, "{}", ""),
        prometheus_fetcher=fake_prometheus_fetcher,
    )
    assert runtime.configuration.version == "1.0.0"
    assert runtime.chaos.scenario_ids == (
        "cpu-stress",
        "memory-stress",
        "network-delay",
        "pod-kill",
    )
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_experiment_runtime_factory.py -q`

Expected: FAIL because the factory does not exist.

- [ ] **Step 3: Implement dependency construction**

The factory must accept injectable runners for tests, but production defaults
must use existing subprocess and Prometheus fetcher functions. It must build:

- one immutable runtime configuration
- one `CommandValidator` from allowlists and replica bounds
- registered Evidence Provider factory for the requested metric
- `KubernetesSnapshotRecoveryMonitor`
- protocol loaded from `config/protocol_profiles/<profile>.json`
- deterministic or registered AutoGen Adapter Registry without executing a model call during construction

- [ ] **Step 4: Replace duplicate UI scenario metadata**

Make `scenario_catalog()` derive ids, target, metric, threshold, and manifest
from `RuntimeConfiguration`. Retain chart/demo fields only as explicitly marked
UI fallback metadata. Existing mock scenario output must remain compatible.

- [ ] **Step 5: Run focused tests**

Run: `python -m pytest tests/test_experiment_runtime_factory.py tests/test_control_plane_data.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/aiops_k8s_agents/experiment_runtime_factory.py src/aiops_k8s_agents/control_plane_data.py tests/test_experiment_runtime_factory.py tests/test_control_plane_data.py
git commit -m "feat: build registered experiment runtimes"
```

---

### Task 7: Runtime API Boundary Without Background Jobs

**Files:**
- Modify: `src/aiops_k8s_agents/control_plane_web.py`
- Modify: `tests/test_control_plane_web.py`

**Interfaces:**
- Consumes: `ExperimentRuntimeRequest`, runtime factory
- Produces: `GET /api/platform`, `GET /api/connections`, `POST /api/experiments/validate`

- [ ] **Step 1: Write failing API contract tests**

```python
def test_platform_capabilities_describe_current_runtime_boundary():
    response = client.get("/api/platform")
    assert response.status_code == 200
    payload = response.json()
    assert payload["api_version"] == "1.0"
    assert payload["capabilities"]["persistent_jobs"] is False
    assert payload["capabilities"]["real_runtime"] is True


def test_validate_experiment_rejects_real_target_outside_allowlist():
    response = client.post(
        "/api/experiments/validate",
        json={
            "scenario_id": "cpu-stress",
            "namespace": "default",
            "deployment": "unknown",
            "metric": "cpu",
            "threshold": 80,
            "mode": "real",
            "backend": "python",
            "protocol_profile": "four-agent-role-veto-v1",
        },
    )
    assert response.status_code == 400
    assert "allowlist" in response.json()["detail"]
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_control_plane_web.py -q`

Expected: FAIL with 404 for the new endpoints.

- [ ] **Step 3: Implement capability and validation endpoints**

`GET /api/connections` performs bounded readiness checks and returns individual
states for Kubernetes, Prometheus, Chaos Mesh, AutoGen configuration, AIOpsLab
path, and artifact directory. It does not start experiments.

`POST /api/experiments/validate` validates the request and runs preflight only.
It never injects Chaos or changes Kubernetes. Return `validated=true` plus the
resolved scenario, target, mode, controller, and safety bounds.

Do not expose a synchronous real execution endpoint in this phase. Plan B owns
the persistent background Job API.

- [ ] **Step 4: Run API tests**

Run: `python -m pytest tests/test_control_plane_web.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aiops_k8s_agents/control_plane_web.py tests/test_control_plane_web.py
git commit -m "feat: expose experiment runtime preflight api"
```

---

### Task 8: Regression Verification and Runtime Documentation

**Files:**
- Modify: `README.md`
- Create: `docs/experiments/platform_real_runtime_guide.md`

**Interfaces:**
- Documents: exact mock/dry-run/real boundaries and the Phase A/Phase B boundary

- [ ] **Step 1: Update README status without overstating web execution**

The README must state:

- core real runtime service and preflight API are implemented
- existing CLI real experiments remain supported
- persistent background Job, SSE, cancellation, and web-triggered real execution belong to Plan B
- AutoGen web runtime and AIOpsLab Job belong to Plan C
- Windows tests do not constitute real Kubernetes validation

- [ ] **Step 2: Add the Ubuntu runtime verification guide**

Document commands for:

1. environment and kubeconfig verification
2. Prometheus readiness
3. `/api/platform` and `/api/connections`
4. `/api/experiments/validate` for mock, dry-run, real
5. existing CLI real experiment execution
6. cleanup and failure evidence collection

Every expected result must identify whether it proves mock, preflight, dry-run,
or real behavior.

- [ ] **Step 3: Run focused and full Python tests**

Run:

```bash
python -m pytest tests/test_experiment_runtime_models.py tests/test_prometheus_adapter.py tests/test_real_evidence.py tests/test_chaos_adapter.py tests/test_experiment_runtime.py tests/test_experiment_runtime_factory.py tests/test_control_plane_web.py -q
python -m pytest
```

Expected: all tests PASS.

- [ ] **Step 4: Run Go Guard regression tests**

Run:

```bash
cd go/aiops-guard
go test ./...
```

Expected: PASS. If Go is unavailable on Windows, record that fact and run this
command in the Ubuntu `aiops_research` environment before merging.

- [ ] **Step 5: Run static repository checks**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; only intentionally changed files are present.

- [ ] **Step 6: Commit documentation**

```bash
git add README.md docs/experiments/platform_real_runtime_guide.md
git commit -m "docs: explain real experiment runtime"
```

## Plan A Acceptance Criteria

- `ExperimentRuntime` executes one bounded experiment lifecycle through injected Adapters.
- real mode always applies cleanup and operation locking.
- mock mode never applies Chaos Mesh or changes Kubernetes.
- Prometheus data includes timestamp and labels and rejects stale or malformed evidence.
- arbitrary metrics, manifests, namespaces, deployments, and Actions are rejected.
- runtime events preserve one `experiment_id` and normalize to one `ExperimentSession`.
- FastAPI exposes capability, connection, and preflight validation only.
- existing CLI and UI mock endpoints remain compatible.
- full Python tests pass.
- Go Guard tests pass in an environment where Go is available.
