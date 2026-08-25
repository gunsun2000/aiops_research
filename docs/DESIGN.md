# Orchestrator-Agent Design

## Responsibility

이 Agent의 책임은 상위 coordination plan을 실행 가능한 논리 분할 계획으로 변환하고, 외부 Scheduling Agent에 전달할 수 있는지 독립 검증하는 것입니다.

## Processing Core

1. **Coordination Plan Intake**: v0.4 FL, SL, distributed-inference 계약을 검증합니다.
2. **Context Resolution**: participant resource, network, model registry 정보를 versioned snapshot으로 결합합니다.
3. **Candidate Generation**: 승인된 mode와 policy에 맞는 logical partition과 execution DAG 후보를 생성합니다.
4. **Estimation**: compute, memory, communication, latency, resilience 수요를 추정합니다.
5. **Hard Feasibility Filter**: model version, memory, DAG, network, mode provenance, SLO를 검사합니다.
6. **Candidate Selection**: deterministic baseline을 기본으로 사용하고, 학습 ranker는 shadow 또는 guard 조건 내에서만 사용합니다.
7. **Artifact and Handoff**: plan version, hash, assumptions, warnings, validation, evaluation, scheduling handoff를 저장합니다.
8. **Bounded Repartition**: runtime/scheduler feedback을 받아 제한된 횟수와 후보 범위 안에서 재계획합니다.

## System Boundary

`Orchestrator-Agent`는 placement나 dispatch를 실행하지 않습니다. `scheduling_handoff.status=ready`는 외부 Scheduling Agent가 계획을 받을 수 있다는 뜻이며 실제 배치 성공을 의미하지 않습니다.

전체 설계 결정 기록은 [superpowers/specs/2026-08-25-orchestrator-agent-standalone-design.md](superpowers/specs/2026-08-25-orchestrator-agent-standalone-design.md)에 있습니다.

