# 교수님 참고 PPT 반영 항목

이 문서는 교수님이 참고하라고 주신 AIOps 발표자료에서 우리 연구에 흡수한 요소를 정리합니다.

## 우리 연구에 반영한 핵심

| PPT 참고 요소 | 우리 프로젝트 반영 |
| --- | --- |
| AIOpsLab 단계 구조 | `detection -> localization -> analysis -> mitigation` phase model 추가 |
| Multi-agent 역할 분담 | 기존 4-agent를 연구 프로파일로 명시 |
| bounded action space | 각 에이전트가 낼 수 있는 action 목록을 코드로 고정 |
| Referee/validator | AIOpsLab API call과 Kubernetes 명령을 실행 전에 검증 |
| reward/penalty | 각 action의 reward signal을 명시하고 결과 JSON에 기록 |
| 반복 실험 결과표 | Detection Accuracy, TTD, steps, reward, phase coverage를 요약 |

## 4-agent 연구 프로파일

| 에이전트 | 주요 역할 | 대표 action | reward 기준 |
| --- | --- | --- | --- |
| AI서비스 HA 지원 | 장애 탐지, 예측, 자율복구 | `ha_collect_logs`, `ha_anomaly_detected`, `ha_scale_out_required` | 빠른 장애 탐지와 불필요한 복구 억제 |
| AI응용관리 자동화 | 자동 배포, 제어, 서비스 수준 최적화 | `app_collect_metrics`, `app_scale_deployment`, `app_submit_detection_result` | 올바른 application action 제안 |
| AI반도체 인프라 운용 | 자원 추천, 인프라 상태 추론 | `infra_capacity_approved`, `infra_dependency_failure_detected` | 용량 초과 차단과 자원 가능성 판단 |
| 비용 최적화 지원 | 자원사용량, 비용 정책 감시 | `cost_budget_approved`, `cost_budget_rejected` | 비용 한도 내 복구와 과잉 scale-out 차단 |

## AIOpsLab phase model

| Phase | 의미 | 현재 구현 |
| --- | --- | --- |
| Detection | 장애 여부 판단 | `get_logs`, `submit("Yes/No")` |
| Localization | 장애 위치 추정 | 로그 기반 의존성 장애 판단 metadata |
| Analysis | 원인 분석 | `get_metrics` 기반 Prometheus metric 수집 |
| Mitigation | 완화 및 복구 | Kubernetes `scale deployment` validator와 real 실행 |

현재 AIOpsLab 공식 문제는 detection 문제이므로 detection과 analysis가 가장 많이 사용됩니다.
CPU 95% Kubernetes 실험은 mitigation 단계까지 연결됩니다.

## 코드 반영 위치

- `src/aiops_k8s_agents/research_framework.py`: phase, agent profile, bounded action, referee 정의
- `src/aiops_k8s_agents/aiopslab_detection.py`: AIOpsLab action metadata에 phase/referee/bounded action 기록
- `src/aiops_k8s_agents/aiopslab_results.py`: 반복 실험 요약표에 phase coverage 추가
- `tests/test_research_framework.py`: 연구 프레임워크 검증 테스트

## 발표자료에 쓰기 좋은 한 줄

본 연구는 참고 PPT의 Multi-Agent AIOps 구조를 Kubernetes/AIOpsLab 환경에 맞게 재구성하여,
4개 전문 에이전트가 bounded action space 안에서 action/reward를 제안하고,
Referee validator가 안전성을 검증한 뒤 AIOpsLab 및 Kubernetes 제어 명령으로 연결하는 구조로 설계되었다.
