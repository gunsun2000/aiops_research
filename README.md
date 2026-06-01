# AIOps 4개 에이전트 Kubernetes 자동화 프로토타입

교수님이 제안하신 AIOps 구조를 로컬에서 먼저 검증하기 위한 프로토타입입니다.

1. AIOpsLab / Kind / Prometheus가 인프라와 서비스 상태를 생성합니다.
2. `AI-MCMP` 통합 관리 에이전트가 4개 전문 에이전트의 의견을 수집합니다.
3. 검증된 Kubernetes 액션만 이식 가능한 `kubectl` 명령어로 변환합니다.
4. 같은 소스코드를 로컬 mock 검증에서 연구실 Ubuntu 서버로 옮겨 실행합니다.

## 아키텍처

현재 프로토타입은 `agentops.png` 그림의 2번 AI 에이전트 레이어를 따릅니다.

- `AIMCMPCoordinator`: GroupChat Manager 역할의 최종 의사결정자입니다.
- `AIServiceHASupportAgent`: 서비스 장애 위험과 복구 필요성을 판단합니다.
- `AIApplicationManagementAgent`: 애플리케이션 배포/제어 액션을 제안합니다.
- `AISemiconductorInfraOpsAgent`: GPU/NPU 자원 여유를 모사해 인프라 적합성을 검토합니다.
- `CostOptimizationAgent`: 1차 비용 정책 안에서 액션이 안전한지 확인합니다.
- `KubernetesExecutor`: allowlist를 통과한 scale 명령만 실행합니다.

에이전트별 액션과 reward 설계는
[에이전트별 액션 및 Reward 설계](docs/agent_action_reward_policy.md)에 정리되어
있습니다.

v1에서 실행 가능한 Kubernetes 액션은 아래 하나로 제한합니다.

```bash
kubectl scale deployment <deployment> --replicas=<N> -n <namespace>
```

LLM이 만든 자유 텍스트는 직접 실행하지 않습니다. 에이전트 출력은 반드시
`ScaleAction` 구조체가 되고, allowlist 검증기를 통과한 뒤 명령어 렌더러로
변환되어야 합니다.

## 로컬 Mock 실행

처음 한 번 패키지를 editable mode로 설치합니다.

```bash
python -m pip install -e ".[dev]"
```

```bash
python -m aiops_k8s_agents.cli run \
  --mode mock \
  --namespace online-boutique \
  --service paymentservice \
  --metric cpu \
  --value 95 \
  --threshold 80 \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice
```

JSON 출력에 들어가야 하는 예상 명령어는 아래와 같습니다.

```bash
kubectl scale deployment paymentservice --replicas=3 -n online-boutique
```

## 실행 모드

- `mock`: `kubectl`을 호출하지 않고 명령어 검증과 렌더링만 수행합니다.
- `dry-run`: 로컬 Kind 클러스터에 `kubectl ... --dry-run=server`로 검증합니다.
- `real`: 설정된 kubeconfig를 대상으로 검증된 명령어를 실제 실행합니다.

deterministic policy agent에서 LLM 기반 AutoGen agent로 확장할 때는 선택 의존성을
설치합니다.

```bash
python -m pip install -e ".[autogen,dev]"
```

## AutoGen GroupChat 실행

AutoGen GroupChat은 기존 안전 실행 구조 위에 붙는 선택형 레이어입니다. AutoGen
에이전트가 `action`, `reward`, `approved`, `reason`, `parameters`를 구조화해서
반환하면, 기존 validator가 최종 `kubectl` 명령어를 검증합니다.

```bash
set OPENAI_API_KEY=<your-api-key>
aiops-k8s-agents autogen-run \
  --mode mock \
  --model gpt-4o-mini \
  --namespace online-boutique \
  --service paymentservice \
  --metric cpu \
  --value 95 \
  --threshold 80 \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice
```

`autogen-run`도 처음에는 `mock` 모드로만 검증하세요. 서버 이관 후에도 `dry-run`
확인 없이 `real` 모드로 바로 전환하지 않습니다.

## Prometheus Metric 입력 실행

실제 Prometheus 서버가 없어도 mock 응답 파일로 metric 입력 경로를 검증할 수 있습니다.

```bash
aiops-k8s-agents prometheus-run \
  --mode mock \
  --mock-response-file examples/prometheus_cpu_high_response.json \
  --query "cpu_query" \
  --metric cpu \
  --threshold 80 \
  --default-namespace online-boutique \
  --default-service paymentservice \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice
```

나중에 Prometheus가 준비되면 `--mock-response-file` 대신 `--prometheus-url`을 사용합니다.

```bash
aiops-k8s-agents prometheus-run \
  --mode mock \
  --prometheus-url http://localhost:9090 \
  --query "avg(rate(container_cpu_usage_seconds_total{service=\"paymentservice\"}[1m]))" \
  --metric cpu \
  --threshold 80 \
  --default-namespace online-boutique \
  --default-service paymentservice \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice
```

로컬 kind에 배포된 상태를 확인하려면:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\local_kind_status.ps1
```

현재 테스트는 결과 재현성을 위해 deterministic mock 동작을 사용합니다.

## 테스트

```bash
python -m pytest
```
