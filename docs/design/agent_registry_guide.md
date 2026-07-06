# AI Agent Registry Guide

Agent Registry는 4-Agent 구조의 역할, 허용 action, reward signal을 JSON으로 관리하기 위한 프로토타입입니다.

이 기능은 연구 본체에 남깁니다. 이유는 Agent별 책임과 action boundary를 명시해 4-Agent 구조를 설명하기 쉽고, 향후 Agent 제거 ablation 실험에도 사용할 수 있기 때문입니다.

## 기본 Agent

| Agent | 역할 |
| --- | --- |
| `AIServiceHASupportAgent` | 서비스 장애 진단, 가용성 판단, 복구 필요성 평가 |
| `AIApplicationManagementAgent` | Kubernetes recovery action 후보 생성 |
| `AISemiconductorInfraOpsAgent` | Kubernetes replica/deployment 안전성 검토 |
| `CostOptimizationAgent` | 비용 증가와 과잉 action 검토 |

설정 파일:

```bash
config/agent_registry.json
```

## 실행 명령

Agent 목록 확인:

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
  --name AIPolicyReviewAgent \
  --korean-name "AI policy review agent" \
  --role "Reviews recovery policy before Kubernetes actions are executed." \
  --responsibility "Check whether a recovery action candidate satisfies safety policy." \
  --action review_recovery_policy \
  --reward-signal "Positive reward when unsafe actions are rejected."
```

이미 존재하는 Agent를 수정하려면 `--overwrite`를 붙입니다.

## 연구에서의 의미

Agent Registry는 단순 설정 파일이 아니라 다음 실험의 기반입니다.

- Agent별 action space 비교
- 특정 Agent 제거 ablation 실험
- reward signal 변경 실험
- 4-Agent에서 추가 Agent 구조로 확장
- Agent action boundary를 문서화하여 안전한 자동화 구조 설명
