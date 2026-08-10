# AutoGen GroupChat 연결 설계

## 목적

이 문서는 4-Agent AIOps 구조에서 AutoGen GroupChat을 어떻게 사용하는지 설명한다.

중요한 점은 현재 AutoGen 경로가 **완전 자율 장시간 토론 시스템**이 아니라는 것이다. 현재 구현은 연구 프로토타입 단계의 **제한된 구조화 multi-agent 판단 경로**이다. 각 Agent는 정해진 역할에 따라 structured output을 반환하고, 최종 Kubernetes 실행은 반드시 validator와 guard를 통과해야 한다.

## 전체 흐름

```text
AlertEvent
-> AutoGen RoundRobinGroupChat
-> AgentDecision(action/reward/approved/reason/parameters)
-> Application Agent decision 추출
-> ScaleAction
-> CommandValidator
-> KubernetesExecutor
```

LLM이 작성한 자유 텍스트나 shell command는 직접 실행하지 않는다. 실행 가능한 명령은 구조화된 action으로 변환된 뒤 allowlist, Kubernetes 이름 규칙, replica 범위 검증을 통과해야 한다.

## 참여 Agent

| Agent | 역할 |
| --- | --- |
| `AIServiceHASupportAgent` | 장애 심각도, 가용성 위험, 복구 필요성 판단 |
| `AIApplicationManagementAgent` | 응용 관점의 복구 action 제안 |
| `AISemiconductorInfraOpsAgent` | Kubernetes replica 안전성과 인프라 수용 가능성 검토 |
| `CostOptimizationAgent` | 비용 증가와 과잉 대응 여부 검토 |

## Structured Output

각 AutoGen Agent는 다음 형태를 반환해야 한다.

```json
{
  "agent": "AIApplicationManagementAgent",
  "action": "app_scale_deployment",
  "reward": 0.85,
  "approved": true,
  "reason": "CPU saturation requires bounded scale-out.",
  "parameters": {
    "namespace": "online-boutique",
    "deployment": "paymentservice",
    "replicas": "3"
  }
}
```

현재 schema는 `namespace`, `deployment`, `replicas` 필드를 요구한다. `replicas`는 scale-out action에서만 실제 의미를 갖지만, schema 안정성을 위해 문자열 필드로 유지한다.

## 현재 한계

현재 AutoGen 연결은 다음 범위까지 지원한다.

- 4개 Agent가 순서대로 structured decision을 생성
- Agent별 `action`, `approved`, `reward`, `reason` transcript 확인
- Application Agent의 `app_scale_deployment`를 `ScaleAction`으로 변환
- validator와 executor를 통한 mock/dry-run/real 실행 가능

아직 제한적인 부분은 다음과 같다.

- 장시간 자유 토론, 반박, 재합의 루프는 제한적
- AutoGen real 경로의 action space는 scale-out 중심
- rollout restart, observe only 같은 recovery action은 deterministic coordinator 경로에서 더 안정적으로 지원
- 최종 논문 실험에서는 AutoGen multi-round real execution을 별도 확장 실험으로 분리하는 것이 적절

## 실행 방법

```bash
python -m pip install -e ".[autogen,dev]"
export OPENAI_API_KEY=<your-api-key>

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

The repository pins `autogen-core`, `autogen-agentchat`, and
`autogen-ext[openai]` to `0.7.5` so the GroupChat runtime is reproducible.
`gpt-5.5` is the selected OpenAI model, not an AutoGen package version; the
runtime supplies explicit `model_info` for this model because AutoGen does not
list the project model alias as a built-in model.

대화 요약을 보려면 `--show-transcript`를 추가한다.

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

## 안전 장치

- AutoGen은 action 판단을 생성하지만 `kubectl`을 직접 실행하지 않는다.
- 최종 action은 반드시 구조화된 모델(`ScaleAction`)로 변환된다.
- `CommandValidator`가 namespace, deployment, replica 범위, 명령 템플릿을 검증한다.
- `Go Guard`를 사용하면 Python validator 이후 Go 기반 독립 검증을 한 번 더 수행한다.
- validator를 통과하지 못한 action은 Kubernetes에 전달되지 않는다.
