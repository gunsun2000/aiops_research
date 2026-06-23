# Ops 분석 시험 및 최적 LLM 선정 가이드

## 목적

이 문서는 1차년도 개발 항목 중 **Ops 분석 시험 및 최적 LLM 선정**을 설명한다.

이 프로젝트에서 LLM 선정은 단순히 최신 모델을 고르는 작업이 아니다. AIOps 운영 자동화에 필요한 기준, 즉 장애 탐지 정확도, metric 수집 성공률, action 안전성, 반복 실행 일관성, 비용, 응답 지연을 함께 비교해 연구용 기본 모델과 보조 모델을 구분하는 과정이다.

## 설정 파일

기본 설정 파일:

```bash
config/ops_llm_benchmark.json
```

현재 후보는 다음과 같다.

| 후보 | 역할 |
| --- | --- |
| `gpt-5.5` | 4-Agent AutoGen GroupChat의 기본 추론 모델 |
| `gpt-4o-mini` | 저비용 smoke test 및 fallback 모델 |
| `codex-cross-check-agent` | 코드, 테스트, 문서 교차 검증용 코딩 에이전트 |

## 데이터 출처 명시

`config/ops_llm_benchmark.json`에는 `metadata`가 포함되어 있다.

```json
{
  "metadata": {
    "data_source": "manual_summary",
    "benchmark_run_id": "aiopslab-and-chaos-summary-20260616",
    "is_synthetic": false
  }
}
```

현재 숫자는 사용 가능한 AIOpsLab 탐지 결과, Chaos Mesh 복구 실험 결과, 프로젝트 검토 노트를 바탕으로 **수동 요약한 값**이다. 즉, 완전히 자동화된 per-model benchmark 결과는 아니며, 최종 논문용 정량 비교에서는 같은 실험 조건으로 모델별 run record를 생성해 다시 산출해야 한다.

이를 위해 보조 스크립트를 제공한다.

```bash
python scripts/build_ops_llm_benchmark_from_runs.py \
  --base-config config/ops_llm_benchmark.json \
  --input runs/some-model-run.jsonl \
  --output config/ops_llm_benchmark.generated.json
```

입력 로그에 `model`, `selected_model`, `selected_llm`, `runtime_model` 같은 필드가 있으면 후보별 성공률과 metric 성공률을 갱신한다. 표준화된 model 필드가 없으면 기존 후보 점수를 보존하고 metadata만 갱신한다.

## 평가 지표

| 지표 | 의미 |
| --- | --- |
| `accuracy` | AIOpsLab detection 문제에서 정답을 찾은 비율 |
| `metric_success` | metric 수집 및 해석 성공 비율 |
| `action_validity` | 생성된 action이 validator/guard를 통과한 비율 |
| `consistency` | 반복 실행 시 판단이 흔들리지 않는 정도 |
| `ttd` | Time To Detect. 낮을수록 좋음 |
| `cost` | 1,000회 Ops 요청 기준 추정 비용. 낮을수록 좋음 |
| `latency` | 모델 응답 지연시간. 낮을수록 좋음 |

## 선정 정책

### `quality_first`

연구 발표와 주요 실험에서 기본으로 사용하는 정책이다. 정확도, action 안전성, 판단 일관성을 우선한다.

예상 결과:

```text
selected_model = gpt-5.5
```

### `cost_first`

반복적인 사전 검증, smoke test, 비용이 중요한 보조 실행에서 사용할 수 있는 정책이다. 비용과 latency 가중치가 높다.

예상 결과:

```text
selected_model = gpt-4o-mini
```

## 실행 명령

후보와 정책 확인:

```bash
aiops-k8s-agents list-ops-llm-candidates \
  --config config/ops_llm_benchmark.json
```

품질 우선 정책으로 LLM 선정:

```bash
aiops-k8s-agents select-ops-llm \
  --config config/ops_llm_benchmark.json \
  --policy quality_first
```

비용 우선 정책으로 LLM 선정:

```bash
aiops-k8s-agents select-ops-llm \
  --config config/ops_llm_benchmark.json \
  --policy cost_first
```

## 현재 연구 해석

현재 프로젝트의 기본 LLM은 `quality_first` 정책에 따라 `gpt-5.5`로 설정되어 있다. 다만 `codex-cross-check-agent`는 runtime reasoning model이 아니라 코드 구현, 테스트, 문서 교차 검증에 사용하는 개발 보조 에이전트로 구분한다.

따라서 발표에서는 다음처럼 설명하는 것이 정확하다.

> 본 연구에서는 Ops 분석 품질을 우선하는 정책에서 `gpt-5.5`를 기본 추론 모델로 선정하고, 반복 검증에는 저비용 모델을 보조적으로 사용하며, Codex는 구현 및 교차 검증용 코딩 에이전트로 활용하였다.

## 산출물

| 산출물 | 파일 |
| --- | --- |
| LLM 운영 관리 구조 설계서 | `docs/design/ops_llm_selection_guide.md` |
| LLM 후보 및 평가 설정 | `config/ops_llm_benchmark.json` |
| LLM benchmark 재생성 보조 스크립트 | `scripts/build_ops_llm_benchmark_from_runs.py` |
| LLM 선정 CLI | `aiops-k8s-agents select-ops-llm` |
| 테스트 코드 | `tests/test_ops_llm_selection.py` |

## 최종 보고서 사용 범위 보정

현재 `config/ops_llm_benchmark.json`은 표준화된 per-model 반복 benchmark 결과가 아니라, 사용 가능한 AIOpsLab 탐지 결과와 Chaos Mesh 복구 실험 결과를 바탕으로 정리한 manual summary이다.

따라서 현재 값은 다음 목적에 사용한다.

- Ops LLM 선정 정책이 코드에 연결되는지 검증
- `quality_first`, `cost_first` 정책에 따른 모델 선택 흐름 확인
- Agent 운영 파이프라인에서 선택된 LLM 이름이 전달되는지 확인

최종 논문 또는 정량 보고서에서는 동일 조건에서 모델별 반복 실험을 다시 수행해 benchmark를 재생성해야 한다. 이 범위를 명확히 하기 위해 benchmark metadata는 다음 필드를 포함한다.

```json
{
  "is_standardized_benchmark": false,
  "measurement_level": "manual_summary_from_available_project_runs",
  "requires_regeneration_for_final_report": true
}
```

발표에서는 다음처럼 설명하는 것이 정확하다.

> 현재 Ops LLM 선정 모듈은 AIOps 운영 기준의 모델 선택 정책을 구현한 것이며, 수치는 사용 가능한 프로젝트 run을 기반으로 한 manual summary이다. 최종 정량 비교를 위해서는 모델별 동일 조건 반복 실험으로 benchmark를 재생성한다.
