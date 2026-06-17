# CPU/GPU VM 기반 AI 응용 배포/제어 추론 최적화 전략 설계서

## 목적

이 문서는 1차년도 개발 항목 중 다음 부분의 산출물이다.

> CPU/GPU VM 기반 AI 응용 배포/제어에 특화된 추론 최적화 전략 설계

현재 구현은 실제 모델 서버를 GPU VM에 상시 운영하는 단계가 아니라, AI 응용을 어느 VM 자원에 배치하고 어떤 Kubernetes 제어 정책으로 운영할지 결정하는 프로토타입이다.

## 입력 데이터

설정 파일:

```bash
config/inference_optimization.json
```

입력은 두 가지로 나뉜다.

| 구분 | 내용 |
| --- | --- |
| `resources` | CPU VM, GPU VM 후보군의 성능, 비용, 용량, node selector |
| `workloads` | AI 응용 workload의 모델 종류, VRAM 요구량, latency SLO, throughput 요구량 |

## 현재 자원 후보

| Resource | Accelerator | 용도 |
| --- | --- | --- |
| `cpu-vm-standard` | CPU | text-classification, embedding 등 경량 AI 응용 |
| `gpu-vm-l4` | GPU | 비용과 성능 균형형 LLM/vision 추론 |
| `gpu-vm-a100` | GPU | 고성능 LLM/vision 추론 |

## 배포/제어 전략

전략은 다음 순서로 결정된다.

1. workload가 accelerator를 요구하는지 확인한다.
2. resource가 해당 model type을 지원하는지 확인한다.
3. GPU memory 요구량을 만족하는지 확인한다.
4. latency SLO와 최소 throughput을 만족하는지 확인한다.
5. latency, throughput, cost, capacity 가중 점수를 계산한다.
6. 가장 높은 점수의 VM 자원을 선택한다.
7. 선택 결과를 Kubernetes 배포/제어 계획으로 변환한다.

## 현재 기본 결과

| Workload | 선택 Resource | Action | 의미 |
| --- | --- | --- | --- |
| `llm-chat-inference` | `gpu-vm-l4` | `deploy_on_gpu_vm` | LLM 추론은 GPU가 필요하며 L4가 비용과 SLO 균형을 만족 |
| `text-classifier` | `cpu-vm-standard` | `deploy_on_cpu_vm` | CPU VM만으로 SLO를 만족하므로 비용 효율적 |

## 실행 명령

자원과 workload 목록 확인:

```bash
aiops-k8s-agents list-inference-workloads \
  --config config/inference_optimization.json
```

배치 추천:

```bash
aiops-k8s-agents recommend-inference-placement \
  --config config/inference_optimization.json \
  --workload llm-chat-inference
```

Kubernetes 배포/제어 계획 생성:

```bash
aiops-k8s-agents plan-inference-deployment \
  --config config/inference_optimization.json \
  --workload llm-chat-inference
```

## 배포 계획 출력 항목

| 필드 | 의미 |
| --- | --- |
| `selected_resource` | 선택된 CPU/GPU VM 후보 |
| `deployment_plan.kubernetes.namespace` | 배포 대상 namespace |
| `deployment_plan.kubernetes.deployment` | 생성 또는 제어할 Deployment 이름 |
| `deployment_plan.kubernetes.node_selector` | CPU/GPU VM 배치 조건 |
| `deployment_plan.kubernetes.resources` | CPU, memory, GPU resource request/limit |
| `deployment_plan.control_actions` | 배포, scale, latency monitoring, rollback 제어 action |

## 연구적 의미

이 전략은 4-Agent 구조에서 `AIApplicationManagementAgent`와 `AISemiconductorInfraOpsAgent`가 함께 판단해야 하는 영역이다.

- 응용관리 Agent는 어떤 AI 응용을 배포하고 제어할지 결정한다.
- 인프라 Agent는 CPU/GPU VM 자원이 해당 배포를 수용할 수 있는지 판단한다.
- 비용 Agent는 고성능 GPU 사용이 필요한지, 더 저렴한 CPU/GPU 후보로 충분한지 검증한다.
- HA Agent는 배포 후 latency, throughput, availability가 SLO를 만족하는지 감시한다.

## 산출물 대응

| 산출물 | 파일 |
| --- | --- |
| AI 응용 배포·제어 추론 최적화 전략 설계서 | `docs/design/ai_application_deployment_strategy.md` |
| CPU/GPU VM 자원 및 workload 설정 | `config/inference_optimization.json` |
| 배치 추천 CLI | `aiops-k8s-agents recommend-inference-placement` |
| 배포/제어 계획 CLI | `aiops-k8s-agents plan-inference-deployment` |
| 테스트 코드 | `tests/test_inference_optimizer.py`, `tests/test_cli.py` |

