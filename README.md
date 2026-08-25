# Orchestrator-Agent

`Orchestrator-Agent`는 Federated Coordination Agent의 계획과 버전이 고정된 시스템 컨텍스트를 받아, 검증된 `PartitionExecutionPlan`을 생성하는 독립 Model Partition Orchestrator Agent입니다.

```text
Federated Coordination v0.4 / Native Request
                    +
Resource, Network, Model Context Snapshot
                    |
                    v
        Model Partition Orchestrator Agent
  Intake -> Candidate Build -> Feasibility -> Selection
                    |
                    v
       Validated PartitionExecutionPlan
                    |
                    v
        External Scheduling Agent Handoff
```

## 포함 범위

- FL 학습 계획, SL 학습 계획, 분산 추론 계획 입력
- participant/model context enrichment
- training/inference partition candidate 생성
- execution DAG와 resource/communication demand 추정
- hard feasibility validation과 deterministic selection
- 선택적 shadow/learned-guarded ranker
- plan artifact, version, lineage, feedback 저장
- bounded repartition
- CLI, FastAPI, 브라우저 연구 UI, 시험 및 예제

실제 Scheduling Agent, FL/SL/inference runtime 실행, Kubernetes 제어, 장애 복구 4-Agent, AIOpsLab, AutoGen은 이 저장소 범위가 아닙니다.

## 설치

```bash
cd Orchestrator-Agent
python -m venv .venv

# Linux/macOS
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1

python -m pip install -U pip
python -m pip install -e ".[dev,ui,ml]"
```

## 빠른 실행

### 웹 플랫폼

```bash
orchestrator-agent-api
```

브라우저: [http://127.0.0.1:18200](http://127.0.0.1:18200)

환경변수로 주소를 바꿀 수 있습니다.

```bash
export ORCHESTRATOR_BIND_ADDRESS=0.0.0.0
export PORT=18200
orchestrator-agent-api
```

### Federated Coordination 연동

```bash
orchestrator-agent plan-federated-coordination \
  --input config/examples/federated_coordination_fl_v04.json \
  --context config/examples/federated_coordination_context_v04.json \
  --artifact-root runs/model-partition/fl
```

SL과 분산 추론은 입력 파일만 변경합니다.

```bash
--input config/examples/federated_coordination_sl_v04.json
--input config/examples/federated_coordination_inference_v04.json
```

### Native partition request

```bash
orchestrator-agent plan-model-partition-v2 \
  --input config/examples/model_partition_inference_v2.json \
  --artifact-root runs/model-partition/native
```

## API

| Method | Path | Role |
| --- | --- | --- |
| `GET` | `/healthz` | service readiness |
| `GET` | `/api/examples` | FL, SL, inference examples |
| `POST` | `/api/coordination-plans` | Federated Coordination v0.4 planning |
| `POST` | `/api/plans` | native request planning |
| `GET` | `/api/strategies` | strategy catalog |
| `GET` | `/api/rankers` | registered learned rankers |
| `GET` | `/api/plans` | persisted plan artifact catalog |
| `GET` | `/api/plans/{plan_id}` | persisted plan |
| `GET` | `/api/plans/{plan_id}/download` | persisted plan JSON download |
| `GET` | `/api/plans/{plan_id}/history` | plan lineage |
| `POST` | `/api/plans/{plan_id}/feedback` | bounded repartition feedback |

Swagger UI: [http://127.0.0.1:18200/docs](http://127.0.0.1:18200/docs)

## 시험

```bash
python -m pytest
```

상세 연동 계약은 [docs/INTEGRATION.md](docs/INTEGRATION.md), 시험 범위는 [docs/TESTING.md](docs/TESTING.md), 설계 경계는 [docs/DESIGN.md](docs/DESIGN.md)를 참고하십시오.

## 중요한 경계

예제의 `source: prometheus-snapshot-example`은 Prometheus에서 수집됐다고 가정한 JSON snapshot입니다. 이 독립본은 첫 단계에서 JSON-backed context provider를 제공하며 Prometheus에 직접 접속한다고 주장하지 않습니다. 향후 Prometheus/Shared State adapter는 동일 context 계약을 구현하면 됩니다.

