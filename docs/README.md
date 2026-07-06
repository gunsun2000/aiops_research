# AIOps Research Docs Map

이 폴더는 대학원 연구 본체인 **4-Agent 기반 Kubernetes 장애 감시/복구 자동화**를 설명하는 문서만 중심으로 정리합니다.

## 먼저 볼 문서

| 문서 | 목적 |
| --- | --- |
| `core_submission_summary.md` | 현재 연구 범위와 완료 상태 요약 |
| `submission/requirements_definition.md` | 요구사항 정의 |
| `submission/install_and_run_guide.md` | 설치와 실행 절차 |
| `submission/execution_code_guide.md` | 주요 실행 명령어 |
| `submission/test_guide.md` | 시험 및 검증 절차 |

## 폴더 구조

```text
docs/
  core_submission_summary.md
  README.md

  submission/     # 연구 재현과 시험 검증 문서
  design/         # Agent, reward, AutoGen 설계 문서
  experiments/    # AIOpsLab, Chaos Mesh, recovery action 실험 문서
  archive/        # 중간 정리와 참고 기록
  superpowers/    # 작업 계획 기록
```

## submission

| 파일 | 내용 |
| --- | --- |
| `requirements_definition.md` | 연구 본체 요구사항 정의 |
| `requirements_definition.docx` | Word 형식 요구사항 정의서 |
| `install_and_run_guide.md` | 로컬/서버 설치 및 실행 방법 |
| `execution_code_guide.md` | 실험 실행 코드와 의미 |
| `test_guide.md` | pytest, Go test, real experiment 검증 방법 |

## design

| 파일 | 내용 |
| --- | --- |
| `agent_registry_guide.md` | 4-Agent 등록 관리 구조 |
| `agent_action_reward_policy.md` | Agent별 action/reward 정책 |
| `autogen_groupchat.md` | AutoGen GroupChat 구조 |

## experiments

| 파일 | 내용 |
| --- | --- |
| `recovery_action_experiment_guide.md` | Chaos Mesh 장애별 recovery action 실험 |
| `recovery_quantitative_analysis_guide.md` | 복구 시간, 성공률, reward 그래프 분석 |
| `full_stack_experiment_guide.md` | full-stack 실험 환경 구성 |
| `experiment_commands.md` | 전체 실험 명령 기록 |
| `server_migration_runbook.md` | 서버 이관 및 실행 절차 |

## archive

| 파일 | 내용 |
| --- | --- |
| `first_stage_research_completion.md` | 1차 연구 완료 범위 정리 |
| `prometheus_adapter.md` | Prometheus adapter 중간 설명 |
| `research_reference_integration.md` | 참고 PPT/연구 자료 반영 기록 |

## 발표 준비 추천 순서

1. `core_submission_summary.md`
2. `submission/requirements_definition.md`
3. `design/agent_action_reward_policy.md`
4. `experiments/recovery_action_experiment_guide.md`
5. `experiments/recovery_quantitative_analysis_guide.md`

긴 실행 로그와 시행착오는 `experiments/experiment_commands.md`와 `archive/`에 두고, 발표 본문에는 핵심 구조, 실험 결과, 정량 그래프만 사용하는 것을 권장합니다.
