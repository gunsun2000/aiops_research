# Test Guide

## Complete suite

```bash
python -m pip install -e ".[dev,ui,ml]"
python -m pytest
```

## Contract smoke tests

```bash
orchestrator-agent plan-federated-coordination \
  --input config/examples/federated_coordination_fl_v04.json \
  --context config/examples/federated_coordination_context_v04.json \
  --artifact-root runs/smoke/fl

orchestrator-agent plan-federated-coordination \
  --input config/examples/federated_coordination_sl_v04.json \
  --context config/examples/federated_coordination_context_v04.json \
  --artifact-root runs/smoke/sl

orchestrator-agent plan-federated-coordination \
  --input config/examples/federated_coordination_inference_v04.json \
  --context config/examples/federated_coordination_context_v04.json \
  --artifact-root runs/smoke/inference
```

각 결과에서 다음을 확인합니다.

- `context_enrichment.status=complete`
- `plan.valid=true`
- `validation.valid=true`
- `scheduling_handoff.status=ready`
- `artifact_path`의 report가 실제로 저장됨

SL 예제는 network bandwidth가 요구조건을 만족하지 않으면 의도적으로 `blocked`일 수 있습니다. 이 경우 Validator의 오류와 human review 표시가 시험 증거입니다.

