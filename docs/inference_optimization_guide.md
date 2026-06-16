# CPU/GPU VM 기반 AI 응용 배포/제어 추론 최적화 가이드

## 목적

이 기능은 연구 개발 항목 중 다음 부분을 담당한다.

> CPU/GPU VM 기반 AI 응용 배포/제어에 특화된 추론 최적화 전략 설계

현재 구현은 실제 GPU scheduler를 대체하는 것이 아니라, **추론 워크로드를 어떤 CPU/GPU VM 후보에 배치할지 결정하는 정책 프로토타입**이다.

## 입력 구조

설정 파일:

```bash
config/inference_optimization.json
```

이 파일에는 두 가지 정보가 있다.

| 구분 | 내용 |
| --- | --- |
| `resources` | CPU VM, GPU VM 후보의 latency, throughput, 비용, 가용 replica |
| `workloads` | 추론 모델 유형, 가속기 필요 여부, VRAM 요구량, latency SLO, 최소 처리량 |

## 현재 VM 후보

| Resource | Accelerator | 용도 |
| --- | --- | --- |
| `cpu-vm-standard` | CPU | 가벼운 text-classification, embedding |
| `gpu-vm-l4` | GPU | 비용과 성능 균형형 LLM/vision inference |
| `gpu-vm-a100` | GPU | 고성능 LLM/vision inference |

## 배치 결정 방식

배치 추천은 다음 순서로 수행된다.

1. workload가 accelerator를 요구하는지 확인한다.
2. resource가 해당 model type을 지원하는지 확인한다.
3. GPU 메모리 요구량을 만족하는지 확인한다.
4. latency SLO와 최소 throughput을 만족하는지 확인한다.
5. 남은 후보에 대해 weighted score를 계산한다.

Score는 다음 요소를 사용한다.

```text
score =
  latency_weight * latency_score
+ throughput_weight * throughput_score
+ cost_weight * cost_score
+ capacity_weight * capacity_score
```

기본 가중치:

| 항목 | Weight |
| --- | --- |
| latency | 0.35 |
| throughput | 0.30 |
| cost | 0.20 |
| capacity | 0.15 |

## 실행 명령

워크로드와 리소스 목록 확인:

```bash
aiops-k8s-agents list-inference-workloads \
  --config config/inference_optimization.json
```

LLM 추론 워크로드 배치 추천:

```bash
aiops-k8s-agents recommend-inference-placement \
  --config config/inference_optimization.json \
  --workload llm-chat-inference
```

가벼운 텍스트 모델 배치 추천:

```bash
aiops-k8s-agents recommend-inference-placement \
  --config config/inference_optimization.json \
  --workload text-classifier
```

## 현재 기대 결과

| Workload | 선택 Resource | 선택 Action | 이유 |
| --- | --- | --- | --- |
| `llm-chat-inference` | `gpu-vm-l4` | `deploy_on_gpu_vm` | LLM은 GPU가 필요하며 L4가 SLO와 비용 균형을 만족 |
| `text-classifier` | `cpu-vm-standard` | `deploy_on_cpu_vm` | CPU VM으로도 SLO를 만족하여 비용 효율적 |

## 향후 확장

- 실제 Kubernetes node label과 연계
- NVIDIA device plugin 기반 GPU pod scheduling
- GPU memory usage metric 반영
- NPU 또는 AI 반도체 가속기 resource profile 추가
- Online Boutique가 아닌 실제 AI inference service 배포와 연결
