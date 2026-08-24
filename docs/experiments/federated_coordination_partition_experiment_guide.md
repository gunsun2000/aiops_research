# Federated Coordination v0.4 - Model Partition 연동·시험 가이드

## 1. 실험 목적

Federated Coordination Agent가 승인한 FL, SL, 분산 추론 계획을 Model Partition
Orchestrator가 변경 없이 수용하고, versioned participant/model context와 결합해
검증된 `PartitionExecutionPlan`으로 변환하는지 확인한다.

이 시험은 Scheduling, placement, GPU 할당, 학습·추론 runtime 실행을 검증하지 않는다.

## 2. 입력과 출력

| 입력 | 소유 구성요소 | 핵심 내용 |
| --- | --- | --- |
| Coordination Plan 0.4 | Federated Coordination Agent | 승인 mode, participant, strategy/policy |
| Participant Context | Prometheus snapshot provider | device capacity, memory, network link |
| Model Context | Model Registry provider | 승인 모델 버전, block 구조, memory profile |
| 출력 | Model Partition Orchestrator | partition, execution DAG, resource demand, validation, Scheduling handoff |

예제 파일:

- `config/examples/federated_coordination_fl_v04.json`
- `config/examples/federated_coordination_sl_v04.json`
- `config/examples/federated_coordination_inference_v04.json`
- `config/examples/federated_coordination_context_v04.json`

마지막 context는 UI와 계약 시험을 위한 정적 예제다. 실제 Prometheus 측정 결과로
해석하거나 논문 성능 근거로 사용하지 않는다.

## 3. 실행

```bash
cd ~/geonhae/aiops_research
conda activate aiops_research
python -m pip install -e ".[ui]"

export AIOPS_FEDERATED_CONTEXT_PATH="$PWD/config/examples/federated_coordination_context_v04.json"
bash scripts/start_research_console.sh restart
```

FL 계획:

```bash
curl -sS -X POST http://127.0.0.1:18180/api/model-partition/coordination-plan \
  -H 'Content-Type: application/json' \
  --data-binary @config/examples/federated_coordination_fl_v04.json \
  | python -m json.tool
```

SL과 분산 추론은 파일명만 각각 `sl`, `inference`로 바꿔 실행한다. 웹에서는
`AI Workload Orchestration`에서 Input Source를 선택하고 `계획 생성`을 누른다.

## 4. 정상 판정

| 계획 | 예상 전략 | 정상 조건 |
| --- | --- | --- |
| FL | `federated-full-model-v1` | 각 participant의 full-model partition과 aggregation graph 존재 |
| SL | `training-partition-v1` | split boundary, forward/backward communication, validation 존재 |
| PARTITIONED | `inference-partition-v1` | split boundary, forward-only graph, latency/resource estimate 존재 |

공통 판정:

- `status=planned`
- `context_enrichment.status=complete`
- upstream payload와 `round_plan_id` 보존
- `validation.valid=true`
- `scheduling_handoff`와 artifact path 존재

## 5. 안전 실패 시험

participant ID, 모델 버전 또는 network link를 context에서 제거하고 다시 실행한다.
SL/PARTITIONED에서 bandwidth evidence가 없을 때 다음처럼 종료되어야 한다.

- HTTP `422`
- `status=blocked`
- 누락 context를 설명하는 error code/message
- 임의 fallback mode 또는 실행 계획을 생성하지 않음

이 동작은 upstream 계획과 관측 Context가 불일치할 때 잘못된 분할 계획을 Scheduling
Agent로 넘기지 않는 fail-closed 경계다.
