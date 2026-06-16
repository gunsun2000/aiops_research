# AI Agent 등록 관리 프로토타입 가이드

## 목적

Agent 등록 관리는 4-Agent 구조를 코드에 고정하지 않고, JSON 설정으로 역할, action, reward signal을 관리하기 위한 프로토타입이다.

이 기능은 다음 연구 요구사항에 대응한다.

- AI 에이전트 등록 관리 프로토타입 개발
- Agent별 action 범위 명시
- Agent별 reward signal 명시
- 향후 Agent 추가 및 제거 실험의 기반 제공

## 기본 Agent

현재 기본 registry에는 4개 Agent가 등록되어 있다.

| Agent | 역할 |
| --- | --- |
| `AIServiceHASupportAgent` | 서비스 장애 진단, 가용성 판단, 자율 복구 필요성 평가 |
| `AIApplicationManagementAgent` | 응용 배포, Kubernetes 제어 action 선택, 복구 절차 관리 |
| `AISemiconductorInfraOpsAgent` | CPU/GPU/NPU 자원 수용성 판단, 인프라 제약 검증 |
| `CostOptimizationAgent` | 자원 사용량, replica 증가, VM 비용 정책 검증 |

설정 파일:

```bash
config/agent_registry.json
```

## 실행 명령

등록된 Agent 목록 확인:

```bash
aiops-k8s-agents list-agents \
  --registry config/agent_registry.json
```

특정 Agent 확인:

```bash
aiops-k8s-agents show-agent \
  --registry config/agent_registry.json \
  --agent AIApplicationManagementAgent
```

Agent action 허용 여부 확인:

```bash
aiops-k8s-agents validate-agent-action \
  --registry config/agent_registry.json \
  --agent AIApplicationManagementAgent \
  --action app_scale_deployment
```

새 Agent 등록 예시:

```bash
aiops-k8s-agents register-agent \
  --registry config/agent_registry.json \
  --name AIInferenceOptimizationAgent \
  --korean-name "AI 추론 최적화 에이전트" \
  --role "CPU/GPU VM 기반 추론 배치 최적화" \
  --responsibility "latency SLO와 비용 제약을 기준으로 추론 VM 후보를 평가한다." \
  --action select_inference_vm \
  --reward-signal "SLO를 만족하면서 비용을 줄이면 양의 reward"
```

이미 존재하는 Agent를 수정하려면 `--overwrite`를 붙인다.

## 연구적 의미

Agent registry는 단순한 설정 파일이 아니라, 다음 실험을 가능하게 하는 기반이다.

- Agent별 action space 비교
- 특정 Agent 제거 ablation 실험
- reward signal 변경 실험
- 4-Agent에서 5-Agent 이상으로 확장
- API 서버 기반 Agent 관리 기능으로 확장
