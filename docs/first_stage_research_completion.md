# 초기 연구 검증 단계 완료 정리

이 문서는 현재 프로젝트가 어디까지 완성되었는지, 무엇을 검증했는지, 그리고 다음 확장 방향이 무엇인지 정리합니다.

## 1. 현재 단계의 의미

여기서 말하는 초기 연구 검증 단계는 최종 논문 완성본이 아니라,
제안한 4-agent AIOps 자동화 구조가 실제 Kubernetes/AIOpsLab 환경에서 작동한다는 것을 보이는 최소 완성 프로토타입입니다.

목표는 아래 흐름을 실제 코드와 서버 실험으로 확인하는 것입니다.

```text
AIOpsLab / Kubernetes 상태
-> 4-agent 판단
-> action/reward 기반 합의
-> Referee / Validator 검증
-> AIOpsLab API 또는 kubectl action 실행
-> 결과 JSON/CSV/Markdown 저장
```

## 2. 구현된 핵심 구조

| 구성 요소 | 구현 상태 | 설명 |
| --- | --- | --- |
| 4-agent 구조 | 완료 | HA, 응용관리, 인프라 운용, 비용 최적화 에이전트 구현 |
| action/reward 설계 | 완료 | 각 에이전트가 action, reward, 승인 여부, 판단 근거를 반환 |
| AI-MCMP coordinator | 완료 | 4개 에이전트 판단을 모아 최종 action을 결정 |
| Kubernetes validator | 완료 | allowlist와 replica 범위를 통과한 `kubectl scale`만 실행 |
| AIOpsLab referee | 완료 | 허용된 AIOpsLab API call만 실행 |
| AutoGen GroupChat | 완료 | OpenAI `gpt-5.5` 기본 모델 기반 4-agent structured output 경로 구현 |
| Prometheus 연동 | 완료 | Prometheus query 결과를 alert event로 변환 |
| Chaos Mesh / kind 실험 | 완료 | 개인 kind cluster에서 pod kill 및 scale 검증 |
| AIOpsLab 자동 detection | 완료 | Hotel Reservation detection 문제 자동 해결 |
| 반복 실험 요약 | 완료 | JSON report를 Markdown/CSV 결과표로 요약 |

## 3. CPU 95% synthetic alert 시나리오의 역할

CPU 95% 시나리오는 실제 AIOpsLab 장애 주입이 아니라 synthetic alert 기반 기능 검증입니다.

이 시나리오의 목적은 아래를 확인하는 것입니다.

```text
CPU 과부하 alert
-> 4-agent가 scale-out 필요성 판단
-> ScaleAction 생성
-> CommandValidator 검증
-> kubectl scale deployment 명령 생성/실행
```

따라서 이 시나리오는 연구의 최종 장애 benchmark라기보다,
Kubernetes 제어 action 생성과 안전 검증을 확인하는 기본 검증 시나리오입니다.

## 4. AIOpsLab 공식 detection 실험 결과

서버 개인 kind cluster에서 AIOpsLab Hotel Reservation detection 문제를 반복 실행했습니다.

실험 대상:

```text
problem_id: misconfig_app_hotel_res-detection-1
namespace: test-hotel-reservation
target service: geo
fault signal: panic: no reachable servers
```

4-agent 자동 실행 흐름:

```text
get_logs("test-hotel-reservation", "geo")
-> panic/no reachable servers 로그 감지
-> get_metrics("test-hotel-reservation", 10)
-> Prometheus metric export 확인
-> submit("Yes")
-> AIOpsLab 평가 수신
```

2026-06-09 서버 반복 실험 요약:

| 지표 | 결과 |
| --- | ---: |
| total_runs | 12 |
| correct_runs | 12 |
| metric_success_runs | 11 |
| average_ttd_seconds | 4.117 |
| average_steps | 3.000 |
| average_final_reward | 3.100 |

해석:

```text
AIOpsLab Hotel Reservation detection 문제를 대상으로 4-agent 자동 탐지 실험을 12회 반복 수행한 결과,
12회 모두 Correct detection으로 평가되었다.
평균 TTD는 4.117초, 평균 action step은 3.0, 평균 최종 reward는 3.10으로 측정되었다.
```

## 5. 교수님 참고 PPT에서 반영한 연구 구조

참고 PPT의 XGBoost/PPO 방식은 가져오지 않았습니다.
우리 프로젝트에 반영한 것은 아래 연구 구조입니다.

| 참고 요소 | 우리 연구 반영 |
| --- | --- |
| Detection / Localization / Analysis / Mitigation | AIOps phase model로 정리 |
| bounded action space | 각 에이전트별 허용 action 목록으로 반영 |
| Referee / Validator | AIOpsLab API referee와 Kubernetes CommandValidator로 반영 |
| reward/penalty | action별 reward metadata와 summary 지표로 반영 |
| 반복 실험 결과표 | Detection Accuracy, TTD, steps, reward, phase coverage로 정리 |

## 6. 현재 한계

현재 단계에서 아직 하지 않은 것은 아래와 같습니다.

```text
XGBoost 기반 예측 모델 학습
PPO 기반 강화학습 policy 학습
여러 AIOpsLab problem family 전체 자동 해결
상시 daemon 형태의 장기 운영
실제 공용 Kubernetes cluster의 full-scale 운영
baseline 대비 통계 비교
```

즉 현재 연구는 학습 연구가 아니라,
AIOpsLab/Kubernetes 환경에서 4-agent orchestration과 안전한 action 실행 루프를 검증한 단계입니다.

## 7. 다음 확장 방향

초기 검증 이후 확장 방향은 아래 순서가 적절합니다.

1. AIOpsLab detection 문제를 1~2개 더 추가합니다.
2. Localization / analysis / mitigation 계열 문제로 확장합니다.
3. rule-based 4-agent policy와 AutoGen LLM GroupChat 결과를 비교합니다.
4. baseline agent 또는 manual operation 대비 TTD, steps, accuracy를 비교합니다.
5. 필요하면 XGBoost나 PPO는 후속 연구로 별도 추가합니다.

## 8. 결론

현재 프로젝트는 4-agent AIOps 자동 감시/관리 프로토타입의 초기 연구 검증 단계를 완료했습니다.

핵심 성과는 아래와 같습니다.

```text
4-agent action/reward 구조 구현
Kubernetes action validator 구현
AIOpsLab referee 구현
CPU synthetic alert 기반 scale action 검증
AIOpsLab 공식 Hotel Reservation detection 문제 자동 해결
12회 반복 실험에서 12회 Correct detection 달성
반복 실험 결과표 자동 생성
```

따라서 현재 상태는 교수님께 "제안 구조가 실제로 동작한다"는 것을 보여줄 수 있는 최소 완성 연구 프로토타입입니다.
