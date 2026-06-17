# 현재 연구 완료 범위와 다음 단계

이 문서는 AIOps 4-Agent 연구가 현재 어디까지 구현·실험됐는지 설명하는 기준 문서입니다.

## 1. 현재 단계의 정확한 의미

현재 연구는 단순한 아이디어나 Mock 프로토타입 단계가 아닙니다.

```text
1차: 4-Agent 시스템 설계·구현 및 서버 통합 가능성 검증
2차: 실제 장애별 Action 및 Reward 정책 정량 비교
3차: Baseline·Ablation·AutoGen real·GPU/NPU 확장
```

현재 위치는 다음과 같습니다.

```text
1차 시스템 연구: 완료
2차 정량 비교: 핵심 두 실험 완료
3차 확장 연구: 미진행
```

여기서 말하는 `1차`, `2차`, `3차`는 논문이 세 편이라는 뜻이 아니라, 연구 진행을 이해하기 쉽게 나눈 내부 단계입니다.

## 2. 구현된 전체 시스템

```text
AIOpsLab / Chaos Mesh 장애
-> Prometheus·Kubernetes 상태 관측
-> 4-Agent 운영 관점 평가
-> Coordinator의 Action 후보 비교
-> Validator 안전 검증
-> kubectl dry-run 또는 real 실행
-> 복구 상태 재관측
-> JSONL·CSV·Markdown 결과 저장
```

| 구성 요소 | 상태 | 검증 내용 |
| --- | --- | --- |
| HA Agent | 완료 | 서비스 가용성과 복구 성공 평가 |
| 응용관리 Agent | 완료 | 복구 속도와 애플리케이션 상태 평가 |
| 인프라 Agent | 완료 | Replica·노드 자원 부담 평가 |
| 비용 Agent | 완료 | Action 비용과 과잉 제어 평가 |
| AI-MCMP Coordinator | 완료 | Agent 점수 집계 및 후보 Action 순위화 |
| Action/Reward 정책 | 완료 | Balanced·HA·Cost·Infra 정책 구현 |
| Kubernetes Validator | 완료 | Allowlist와 Action 범위 안전 검증 |
| AutoGen GroupChat | 구현 완료 | LLM 대화와 구조화 응답 Mock/Dry-run 검증 |
| AIOpsLab Referee | 완료 | 허용된 AIOpsLab API 호출 검증 |
| Prometheus 연동 | 완료 | CPU·Memory·Availability·Latency 관측 |
| Chaos Mesh 연동 | 완료 | 실제 장애 4종 주입 |
| Kubernetes real 제어 | 완료 | 관찰·재시작·Scale-out 실행 |
| 결과 자동 저장·분석 | 완료 | JSONL과 Reward 비교 문서 생성 |

## 3. 코드 검증 결과

2026년 6월 15일 기준 서버에서 다음 검증을 통과했습니다.

```text
collected 92 items
92 passed
```

`pytest` 통과는 Agent, Validator, CLI, AIOpsLab Adapter, Prometheus Adapter, Recovery Runner가 정의한 규칙대로 동작한다는 코드 검증입니다. 실제 장애 성능은 아래의 real 실험 결과로 따로 판단합니다.

## 4. AIOpsLab Hotel Reservation 탐지 실험

### 실험 대상

```text
problem_id: misconfig_app_hotel_res-detection-1
namespace: test-hotel-reservation
target service: geo
fault signal: panic: no reachable servers
```

### 자동 실행 흐름

```text
AIOpsLab 문제 시작
-> get_logs로 장애 근거 수집
-> get_metrics로 상태 관측
-> 4-Agent Action/Reward 판단 기록
-> Referee 검증
-> submit("Yes")
-> AIOpsLab 평가 결과 저장
```

### 12회 반복 결과

| 지표 | 결과 |
| --- | ---: |
| 전체 실행 | 12 |
| Correct detection | 12 |
| Metric 수집 성공 | 11 |
| 평균 TTD | 4.117초 |
| 평균 Action step | 3.000 |
| 평균 최종 Reward | 3.100 |

이 실험은 AIOpsLab 공식 문제에서 장애를 자동으로 탐지하고 제출하는 경로의 검증입니다. Kubernetes 복구 Action 비교 실험과는 목적이 다릅니다.

## 5. 실제 장애별 복구 Action 실험

### 연구 질문

1. 실제 장애 종류에 따라 적합한 Kubernetes Action이 달라지는가?
2. 같은 실측 결과라도 Agent Reward 가중치에 따라 선택 Action이 달라지는가?

### 실험 행렬

| 항목 | 구성 |
| --- | --- |
| 장애 | `pod-kill`, `cpu-stress`, `memory-stress`, `network-delay` |
| Action | `observe_only`, `rollout_restart`, `scale_out` |
| Reward 정책 | `balanced`, `ha_first`, `cost_first`, `infra_first` |
| 파일럿 | 4장애 × 3Action × 1회 = 12 treatments |
| 본 실험 | 4장애 × 3Action × 3회 = 36 treatments |

### 실제 환경

```text
연구실 Ubuntu 서버
-> 개인용 kind Kubernetes
-> Online Boutique
-> Chaos Mesh
-> kube-prometheus-stack
-> Blackbox Exporter
-> AIOps 4-Agent Recovery Runner
```

### 완료 결과

| 실험 | 전체 | 유효 측정 | 복구 성공 |
| --- | ---: | ---: | ---: |
| 12회 파일럿 | 12 | 12 | 12 |
| 36회 본 실험 | 36 | 36 | 36 |

본 실험 결과 위치:

```text
runs/recovery-action-pilot/20260615_123017/outcomes.jsonl
runs/recovery-action-pilot/20260615_123017/analysis/reward_policy_comparison.json
runs/recovery-action-pilot/20260615_123017/analysis/reward_policy_comparison.csv
runs/recovery-action-pilot/20260615_123017/analysis/reward_policy_comparison.md
```

## 6. Reward 정책별 선택 결과

| 정책 | CPU stress | Memory stress | Network delay | Pod kill |
| --- | --- | --- | --- | --- |
| Balanced | `observe_only` | `rollout_restart` | `rollout_restart` | `observe_only` |
| HA 우선 | `observe_only` | `rollout_restart` | `rollout_restart` | `observe_only` |
| 비용 우선 | `observe_only` | `observe_only` | `observe_only` | `observe_only` |
| 인프라 우선 | `observe_only` | `rollout_restart` | `rollout_restart` | `observe_only` |

### 해석

- `pod-kill`: Kubernetes가 새 Pod를 자동 생성하므로 추가 Action보다 관찰이 높은 점수를 받았습니다.
- `cpu-stress`: 60초 후 장애가 종료되는 조건에서는 Scale-out 비용보다 관찰의 효율이 높았습니다.
- `memory-stress`: Balanced·HA·Infra 정책에서 애플리케이션 상태 개선이 큰 `rollout_restart`가 선택됐습니다.
- `network-delay`: Balanced·HA·Infra 정책은 응용 복구 점수를 반영해 `rollout_restart`를 선택했습니다.
- `cost_first`: 추가 명령과 Replica 증가 비용을 강하게 반영해 모든 장애에서 `observe_only`를 선택했습니다.

이는 미리 지정한 정답을 출력한 것이 아니라, 실제 측정 결과에 정책 가중치를 적용하여 얻은 결과입니다.

## 7. 완료된 연구 항목

| 연구 항목 | 상태 |
| --- | --- |
| 역할 기반 4-Agent 구조 | 완료 |
| Agent별 Action과 Reward 설계 | 완료 |
| Validator 기반 안전 실행 | 완료 |
| AIOpsLab 자동 탐지 | 완료 |
| Chaos Mesh 실제 장애 4종 | 완료 |
| Full Prometheus Metric 관측 | 완료 |
| Kubernetes real Action 3종 | 완료 |
| 12회 파일럿 | 완료 |
| 36회 본 실험 | 완료 |
| 장애별 최적 Action 비교 | 완료 |
| Reward 값 변화에 따른 선택 비교 | 완료 |

## 8. 아직 완료되지 않은 항목

| 연구 항목 | 필요한 이유 |
| --- | --- |
| 평균·표준편차·신뢰구간·그래프 | 반복 결과의 변동성과 재현성 제시 |
| Single-Agent baseline | 4-Agent 구조의 효과 비교 |
| Agent 제거 Ablation | HA·응용·인프라·비용 Agent 각각의 기여 확인 |
| AutoGen GroupChat real Action 선택 | LLM 대화가 실제 장애에서 Action을 결정하는 성능 비교 |
| 더 긴 장애와 부하 강도 변화 | 현재 60초 장애 조건 밖의 일반화 확인 |
| SLO·MTTR·자원 비용 상세 분석 | 운영 관점의 정량적 효과 설명 |
| GPU/NPU 실제 스케줄링 | AI 반도체 인프라 Agent 역할 확장 |

## 9. AutoGen에 대한 정확한 현재 상태

AutoGen 기반 4-Agent GroupChat은 구현돼 있으며, OpenAI API를 통한 대화와 구조화된 Agent 응답을 Mock 및 Kubernetes Dry-run 경로에서 확인했습니다.

그러나 12회·36회 실제 장애별 Action 비교는 재현성을 확보하기 위해 deterministic Recovery Runner로 수행했습니다.

```text
구현된 AutoGen 경로:
Prometheus 입력 -> AutoGen 4-Agent 대화 -> 구조화 Action -> Validator -> Mock/Dry-run

이번 36회 real 경로:
Chaos Mesh 장애 -> Prometheus 실측 -> bounded Action 실행 -> Reward 정책 비교
```

따라서 발표에서 “36회 실험을 AutoGen이 직접 제어했다”고 표현하면 안 됩니다. 정확한 표현은 다음과 같습니다.

> 실제 Kubernetes 장애·복구 실험으로 Action과 Reward 정책을 검증했으며, AutoGen GroupChat의 real 제어 비교는 후속 실험으로 남아 있다.

## 10. CPU 95% 시나리오의 현재 역할

CPU 95% 입력은 실제 장애 실험이 아니라 다음 기능을 빠르게 확인하는 선택적 Smoke Test입니다.

```text
구조화 Alert 입력
-> 4-Agent 판단
-> ScaleAction 생성
-> Validator 검증
-> kubectl 명령 렌더링
```

현재 논문·발표의 주요 결과는 CPU 95%가 아니라 AIOpsLab 반복 탐지와 Chaos Mesh 36회 real 실험입니다.

## 11. 결론

현재 연구는 다음 주장을 실제 서버 결과로 뒷받침합니다.

> 역할이 분리된 4-Agent 운영 평가 구조와 안전한 Kubernetes Action 실행 파이프라인을 구현했으며, AIOpsLab 자동 탐지와 Chaos Mesh 기반 실제 장애 36회 실험을 통해 시스템 통합 가능성, 장애별 Action 차이, Reward 정책에 따른 선택 변화를 확인하였다.

다음 연구의 우선순위는 통계 분석과 시각화, Single-Agent 비교, Agent 제거 Ablation, AutoGen real Action 선택 순서입니다.
