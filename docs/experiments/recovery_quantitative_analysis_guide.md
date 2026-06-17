# Recovery 정량 그래프 및 통계 분석 가이드

## 목적

이 문서는 실제 Chaos Mesh recovery action 실험 결과를 기반으로 다음 지표를 정량 분석하는 절차를 정리한다.

- 평균 복구 시간
- 복구 성공률
- metric 개선도
- reward 정책별 action 선택 차이
- 발표 및 논문용 시각화 그래프

## 입력 파일

입력은 `server_recovery_action_pilot.sh`가 생성한 JSONL 파일이다.

```text
runs/recovery-action-pilot/<실험시각>/outcomes.jsonl
```

각 줄은 하나의 treatment 결과이며, 장애 시나리오, action, 복구 성공 여부, 복구 시간, metric 개선도, replica 증가량, command 수, 안전 검증 여부를 포함한다.

## 실행 명령

가장 최근 recovery action 실험 결과를 분석하려면:

```bash
LATEST=$(ls -dt runs/recovery-action-pilot/*/ | head -1)

aiops-k8s-agents summarize-recovery-statistics \
  --input "${LATEST}outcomes.jsonl" \
  --output-dir "${LATEST}statistics"
```

특정 실험 결과를 분석하려면:

```bash
aiops-k8s-agents summarize-recovery-statistics \
  --input runs/recovery-action-pilot/20260616_173903/outcomes.jsonl \
  --output-dir runs/recovery-action-pilot/20260616_173903/statistics
```

## 생성 산출물

```text
statistics/
  quantitative_summary.json
  scenario_action_statistics.csv
  policy_reward_statistics.csv
  quantitative_summary.md
  mean_recovery_seconds_by_action.svg
  mean_recovery_seconds_by_action.png
  success_rate_by_action.svg
  success_rate_by_action.png
  reward_by_policy.svg
  reward_by_policy.png
```

| 파일 | 내용 |
| --- | --- |
| `quantitative_summary.json` | 전체 정량 분석 결과 |
| `scenario_action_statistics.csv` | 장애/action별 평균 복구 시간, 성공률, metric 개선도 |
| `policy_reward_statistics.csv` | reward 정책별 action ranking |
| `quantitative_summary.md` | 발표/보고서용 요약 |
| `mean_recovery_seconds_by_action.svg` | 평균 복구 시간 그래프 |
| `mean_recovery_seconds_by_action.png` | 평균 복구 시간 발표 삽입용 PNG |
| `success_rate_by_action.svg` | 복구 성공률 그래프 |
| `success_rate_by_action.png` | 복구 성공률 발표 삽입용 PNG |
| `reward_by_policy.svg` | reward 정책별 선택 점수 그래프 |
| `reward_by_policy.png` | reward 정책별 선택 점수 발표 삽입용 PNG |

## 해석 방법

### 평균 복구 시간

`mean_recovery_seconds_by_action.svg`와 `.png`는 각 장애와 action 조합별 평균 복구 시간을 보여준다.

복구 시간이 짧을수록 빠른 대응이다. 다만 복구 시간이 짧다고 항상 좋은 action은 아니다. 예를 들어 `observe_only`가 빠르게 성공하는 경우는 Kubernetes가 자체 복구한 상황일 수 있다.

### 성공률

`success_rate_by_action.svg`와 `.png`는 각 장애와 action 조합별 복구 성공률을 보여준다.

성공률이 높고 복구 시간이 낮은 action은 강한 후보가 된다. 반대로 성공률이 높더라도 replica 증가량이나 command 수가 크면 비용/인프라 관점에서 불리할 수 있다.

### Reward 정책 차이

`reward_by_policy.svg`, `.png`, `policy_reward_statistics.csv`는 reward 정책을 바꿨을 때 action 선택이 어떻게 달라지는지 보여준다.

| 정책 | 해석 |
| --- | --- |
| `balanced` | HA, 응용관리, 인프라, 비용을 균형 있게 고려 |
| `ha_first` | 복구 성공과 가용성을 더 중요하게 평가 |
| `cost_first` | 불필요한 scale-out과 자원 증가를 강하게 억제 |
| `infra_first` | replica 증가, command 수, 자원 부담을 더 강하게 고려 |

## 연구 보고서 문장 예시

```text
본 연구는 Chaos Mesh 기반 실제 장애 실험 결과를 대상으로 장애 유형과 복구 action 조합별 평균 복구 시간, 성공률, metric 개선도, reward 정책별 action ranking을 산출하였다. 이를 통해 단일 action을 고정적으로 적용하는 방식보다, 장애 유형과 reward 정책에 따라 복구 action을 선택하는 4-Agent 기반 제어 구조가 더 세밀한 운영 판단을 제공할 수 있음을 확인하였다.
```

## 발표자료에 넣을 핵심 그림

발표자료에는 다음 3개를 추천한다.

1. `mean_recovery_seconds_by_action.png`
2. `success_rate_by_action.png`
3. `reward_by_policy.png`

이 3개만 넣어도 “빠른가”, “성공했는가”, “reward 정책에 따라 판단이 달라지는가”를 설명할 수 있다.
