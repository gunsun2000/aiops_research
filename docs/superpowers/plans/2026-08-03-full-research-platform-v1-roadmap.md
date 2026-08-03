# Full Research Platform v1 Implementation Roadmap

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement each linked plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 4-Agent 연구 엔진과 real 실험 도구를 영속적이고 실시간으로 관찰 가능한 웹 연구 플랫폼으로 통합한다.

**Architecture:** 구현은 다섯 개의 독립적인 하위 계획으로 나눈다. 각 계획은 앞 단계의 공개 인터페이스만 사용하며, 완료 시 독립적으로 테스트 가능한 소프트웨어를 제공한다.

**Tech Stack:** Python 3.11+, FastAPI, standard-library SQLite, Server-Sent Events, existing JavaScript/CSS UI, pytest, Kubernetes CLI, Prometheus HTTP API, Chaos Mesh, AutoGen, AIOpsLab

## Global Constraints

- 기존 deterministic CLI와 command contract를 유지한다.
- `mock`, `dry-run`, `real` 결과를 서로 대체 가능한 증거로 취급하지 않는다.
- real 실행은 allowlist, replica limit, operation lock, timeout, cleanup을 우회할 수 없다.
- 웹 브라우저는 Kubernetes 명령을 직접 실행하지 않는다.
- 모든 실행 단계는 하나의 `experiment_id`와 `ExperimentSession`으로 연결한다.
- AutoGen은 선택 가능한 Controller이며 핵심 real 복구 실험의 필수 의존성이 아니다.
- AIOpsLab은 Chaos Mesh 복구 실험과 구분되는 별도 benchmark Job이다.
- Python 단위 테스트는 외부 API key와 real Kubernetes 없이 재현 가능해야 한다.
- real end-to-end 검증은 Ubuntu 연구실 서버에서만 수행한다.

---

## 하위 계획

### Plan A. Core Real Experiment Runtime

문서: `docs/superpowers/plans/2026-08-03-core-real-experiment-runtime-implementation.md`

완료 결과:

- 등록된 Prometheus query와 Kubernetes snapshot을 결합한 Evidence Provider
- 등록된 Chaos Mesh 시나리오의 apply/status/delete Adapter
- preflight, fault lifecycle, 4-Agent 실행, cleanup을 묶는 단일 runtime service
- mock/dry-run/real 경계와 단계별 runtime event
- 외부 시스템 없이 동작하는 deterministic 통합 테스트

### Plan B. Persistent Job and Live Web Control

완료 결과:

- SQLite experiment/job/event/artifact store
- background Job runner와 취소
- SSE event replay와 재연결
- experiment 생성, 조회, 목록, 취소 API
- 현재 UI를 API 기반 실시간 실험 화면으로 전환

### Plan C. Optional Research Runtimes

완료 결과:

- AutoGen model preflight와 GroupChat runtime 연결
- deterministic/AutoGen provenance 표시
- AIOpsLab benchmark Adapter와 Job type
- AutoGen과 AIOpsLab의 구체적인 상태 표시

### Plan D. Comparison and Quantitative Results

완료 결과:

- treatment matrix runner
- comparison id 아래 독립 experiment 연결
- recovery statistics와 reward ranking 자동 생성
- JSONL, CSV, PNG, Markdown artifact API와 결과 화면

### Plan E. Recovery, E2E, and Research Release

완료 결과:

- 서버 재시작 시 interrupted Job 복원 및 cleanup
- adapter 단절, timeout, 취소, cleanup 실패 처리
- 브라우저 E2E와 API contract 테스트
- Ubuntu real 4-scenario end-to-end 검증 절차
- README와 운영·시험 가이드 최신화

## 통합 순서

```text
Plan A Core Runtime
  -> Plan B Persistent Job/Web
  -> Plan C AutoGen/AIOpsLab
  -> Plan D Comparison/Analysis
  -> Plan E Recovery/E2E/Release
```

각 하위 계획은 별도 검토와 커밋 단위로 진행한다. Plan A의 공개 인터페이스가
확정되기 전에는 Plan B의 API와 UI를 구현하지 않는다.
