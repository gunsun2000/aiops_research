# AIOps Research Docs Map

`docs/`는 제출 문서, 설계 문서, 실험 문서, 보관 문서를 역할별로 나눈다. 처음 보는 사람은 아래 순서대로 보면 된다.

## 먼저 볼 문서

| 문서 | 목적 |
| --- | --- |
| `core_submission_summary.md` | 교수님/평가자에게 보여줄 핵심 요약 |
| `submission/requirements_definition.md` | 요구사항 정의서 |
| `submission/functional_api_guide.md` | 기능/API 사용 가이드 |
| `submission/service_control_framework_mapping.md` | AI 기반 서비스 제어 및 관리 자동화 프레임워크 항목과 구현 파일/실행 명령 매핑 |
| `submission/install_and_run_guide.md` | 설치 및 실행 가이드 |
| `submission/execution_code_guide.md` | 실행 코드 설명서 |
| `submission/test_guide.md` | 시험 검증 가이드 |

## 폴더 구조

```text
docs/
  core_submission_summary.md
  README.md

  submission/     # 제출용 문서
  design/         # Agent, reward, LLM, Go guard 설계 문서
  experiments/    # AIOpsLab, Chaos Mesh, recovery action 실험 문서
  archive/        # 중간 정리, 참고 기록, 과거 보고 문서
  superpowers/    # 작업 계획 기록
```

## submission

제출 산출물로 직접 보여주기 좋은 문서다.

| 파일 | 내용 |
| --- | --- |
| `requirements_definition.md` | 요구사항 정의서 |
| `requirements_definition.docx` | Word 형식 요구사항 정의서 |
| `functional_api_guide.md` | CLI/API 기능 사용법 |
| `service_control_framework_mapping.md` | 과제 항목, 구현 모듈, 실행 코드, 현재 범위와 future work 매핑 |
| `openapi_agent_registry.yaml` | Agent 등록 관리 OpenAPI 초안 |
| `install_and_run_guide.md` | 로컬/서버 설치 및 실행 방법 |
| `execution_code_guide.md` | 교수님 요청 연구와 과제 요구별 실행 코드 설명 |
| `test_guide.md` | pytest, Go test, real experiment 검증 방법 |

## design

연구 구조와 설계 근거를 설명하는 문서다.

| 파일 | 내용 |
| --- | --- |
| `agent_registry_guide.md` | 4-Agent 등록 관리 구조 |
| `agent_action_reward_policy.md` | Agent별 action/reward 정책 |
| `go_and_llm_cross_validation.md` | Go guard와 LLM/코딩 에이전트 교차 검증 |
| `research_task_integration_design.md` | 교수님 요청 연구와 대학원/ETRI 과제 요구의 범위 구분 및 통합 설계 |
| `ops_llm_selection_guide.md` | Ops 분석 시험 및 최적 LLM 선정 |
| `inference_optimization_guide.md` | CPU/GPU VM 기반 추론 배치 추천 |
| `ai_application_deployment_strategy.md` | AI 응용 배포/제어 추론 최적화 전략 |
| `autogen_groupchat.md` | AutoGen GroupChat 구조 |

## experiments

실험 재현과 결과 해석에 필요한 문서다.

| 파일 | 내용 |
| --- | --- |
| `recovery_action_experiment_guide.md` | Chaos Mesh 장애별 recovery action 실험 |
| `recovery_quantitative_analysis_guide.md` | 평균 복구 시간, 성공률, reward 그래프 분석 |
| `service_operations_environment.md` | Agent 중심 AI 서비스 운영 통합 실험 환경과 실행 코드 |
| `full_stack_experiment_guide.md` | full-stack 실험 환경 구성 |
| `experiment_commands.md` | 전체 실험 명령어 기록 |
| `server_migration_runbook.md` | 서버 이관 및 실행 절차 |

## archive

발표 본문에는 넣지 않아도 되지만, 연구 기록으로 보관하는 문서다.

| 파일 | 내용 |
| --- | --- |
| `first_stage_research_completion.md` | 1차 연구 완료 범위 정리 |
| `llm_cross_validation_report_20260616.md` | LLM/코딩 에이전트 교차 검증 기록 |
| `prometheus_adapter.md` | Prometheus adapter 중간 설명 |
| `research_reference_integration.md` | 참고 PPT/연구자료 반영 기록 |

## 발표 준비 시 추천 순서

1. `core_submission_summary.md`
2. `submission/requirements_definition.md`
3. `design/agent_action_reward_policy.md`
4. `design/go_and_llm_cross_validation.md`
5. `experiments/recovery_action_experiment_guide.md`
6. `experiments/recovery_quantitative_analysis_guide.md`

긴 터미널 로그나 중간 시행착오는 `experiments/experiment_commands.md`와 `archive/`에만 두고, 발표 본문에는 핵심 결과와 그래프만 사용한다.
