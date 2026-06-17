# Ops 분석 시험 및 최적 LLM 선정 가이드

## 목적

이 문서는 1차년도 개발 항목 중 다음 부분의 산출물이다.

> Ops 분석 시험 및 최적 LLM 선정

LLM 선정은 단순히 최신 모델을 고르는 것이 아니라, AIOps 운영 자동화에 필요한 기준으로 후보 모델을 비교하고, 연구 목적에 맞는 기본 모델과 보조 모델을 구분하는 과정이다.

## 평가 대상

설정 파일:

```bash
config/ops_llm_benchmark.json
```

현재 비교 대상은 다음 3종이다.

| 모델 | 역할 |
| --- | --- |
| `gpt-5.5` | 4-Agent AutoGen GroupChat의 기본 추론 모델 |
| `gpt-4o-mini` | 저비용 반복 smoke test 및 보조 실행 모델 |
| `codex-cross-check-agent` | 코드, 테스트, 문서 교차 검증용 코딩 에이전트 |

## 평가 지표

| 지표 | 의미 |
| --- | --- |
| `accuracy` | AIOpsLab detection 문제에서 정답 탐지 비율 |
| `metric_success` | metric 수집 및 해석 성공 비율 |
| `action_validity` | 생성된 action이 validator/guard를 통과한 비율 |
| `consistency` | 반복 실행 시 판단이 흔들리지 않는 정도 |
| `ttd` | Time To Detect. 낮을수록 좋음 |
| `cost` | 1,000회 Ops 요청 기준 추정 비용. 낮을수록 좋음 |
| `latency` | 모델 응답 지연시간. 낮을수록 좋음 |

## 선정 정책

### quality_first

논문 및 발표에서 기본으로 사용할 정책이다. 정확도, action 안전성, 판단 일관성을 우선한다.

기대 결과:

```text
selected_model = gpt-5.5
```

### cost_first

반복적인 사전 검증이나 비핵심 테스트에서 사용할 수 있는 정책이다. 비용과 응답 지연을 우선한다.

기대 결과:

```text
selected_model = gpt-4o-mini
```

## 실행 명령

후보 모델과 정책 확인:

```bash
aiops-k8s-agents list-ops-llm-candidates \
  --config config/ops_llm_benchmark.json
```

품질 우선 정책으로 최적 LLM 선정:

```bash
aiops-k8s-agents select-ops-llm \
  --config config/ops_llm_benchmark.json \
  --policy quality_first
```

비용 우선 정책으로 최적 LLM 선정:

```bash
aiops-k8s-agents select-ops-llm \
  --config config/ops_llm_benchmark.json \
  --policy cost_first
```

## 현재 결론

현재 연구의 기본 LLM은 `gpt-5.5`로 둔다. 이유는 `quality_first` 정책에서 Ops 탐지 정확도, action 안전성, 판단 일관성이 가장 높기 때문이다.

다만 반복 실험 비용을 줄이기 위한 보조 모델로 `gpt-4o-mini`를 유지하고, 코드 및 문서 교차 검증에는 `codex-cross-check-agent`를 사용한다.

## 산출물 대응

| 산출물 | 파일 |
| --- | --- |
| LLM 운영 관리 구조 설계서 | `docs/design/ops_llm_selection_guide.md` |
| LLM 후보 및 평가 설정 | `config/ops_llm_benchmark.json` |
| LLM 선정 CLI | `aiops-k8s-agents select-ops-llm` |
| 테스트 코드 | `tests/test_ops_llm_selection.py` |

