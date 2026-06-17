# AutoGen GroupChat 연결 설계

이 문서는 현재 프로토타입에 추가된 AutoGen GroupChat 레이어를 설명합니다.

## 왜 AutoGen을 별도 레이어로 붙이는가

AutoGen은 에이전트들의 reasoning과 토론을 담당합니다. 하지만 최종 실행 안전성은
기존 `CommandValidator`와 `KubernetesExecutor`가 담당합니다. 즉 LLM이 만든 자유
텍스트를 바로 실행하지 않고, 반드시 구조화된 결정으로 변환한 뒤 검증합니다.

```text
AutoGen RoundRobinGroupChat
-> AgentDecision(action/reward/approved/reason/parameters)
-> ScaleAction
-> CommandValidator
-> KubernetesExecutor
```

## GroupChat 참여 에이전트

- `AIServiceHASupportAgent`: HA 복구 필요성 판단
- `AIApplicationManagementAgent`: Kubernetes 응용 제어 액션 생성
- `AISemiconductorInfraOpsAgent`: GPU/NPU 자원 관점 검토
- `CostOptimizationAgent`: 비용 정책 검토

AutoGen에서는 위 4개 에이전트를 `AssistantAgent`로 만들고,
`RoundRobinGroupChat`이 한 번씩 발화하도록 구성합니다.

## Structured Output

각 AutoGen 에이전트는 아래 필드를 반환해야 합니다.

```json
{
  "agent": "AIApplicationManagementAgent",
  "action": "app_scale_deployment",
  "reward": 0.85,
  "approved": true,
  "reason": "CPU saturation 완화를 위해 deployment scale-out을 제안합니다.",
  "parameters": {
    "namespace": "online-boutique",
    "deployment": "paymentservice",
    "replicas": 3
  }
}
```

현재 structured output schema에서는 4개 에이전트 모두 `parameters`에
`namespace`, `deployment`, `replicas`를 포함합니다. 최종 `ScaleAction` 생성에는
응용관리 에이전트의 `parameters`가 사용되고, 나머지 에이전트의 값은 판단 로그와
형식 안정성 검증에 사용됩니다.

## 실행 방법

```bash
python -m pip install -e ".[autogen,dev]"
set OPENAI_API_KEY=<your-api-key>
aiops-k8s-agents autogen-run \
  --mode mock \
  --model gpt-5.5 \
  --namespace online-boutique \
  --service paymentservice \
  --metric cpu \
  --value 95 \
  --threshold 80 \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice
```

4개 에이전트가 어떤 판단을 냈는지 눈으로 확인하려면 `--show-transcript`를
추가합니다. 출력 JSON의 `metadata.transcript`에 에이전트별
`action/approved/reward/reason` 요약이 들어갑니다.

```bash
aiops-k8s-agents autogen-run \
  --mode mock \
  --show-transcript \
  --namespace online-boutique \
  --service paymentservice \
  --metric cpu \
  --value 95 \
  --threshold 80 \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice
```

Linux/Ubuntu 서버에서는 API 키 설정을 아래처럼 합니다.

```bash
export OPENAI_API_KEY=<your-api-key>
```

## 안전 원칙

- AutoGen은 판단을 생성하지만 직접 `kubectl`을 실행하지 않습니다.
- 최종 액션은 반드시 `ScaleAction`으로 변환됩니다.
- `CommandValidator`가 namespace, deployment, replica 범위, 명령 템플릿을 검증합니다.
- `mock -> dry-run -> real` 순서를 지키며 서버에서 바로 `real` 모드로 가지 않습니다.
