# 연구실 서버 이관 Runbook

이 문서는 로컬 AIOps 프로토타입을 연구실 고성능 Ubuntu 서버로 옮기는 절차를
정리합니다. 핵심 목표는 로컬에서 검증한 `kubectl` 명령어가 서버에서도 같은
형태로 동작하게 만드는 것입니다.

## 1. 로컬 Mock 단계

같은 CPU 과부하 시나리오가 매번 같은 안전 명령어를 만들 때까지 `mock` 모드에서
통합 관리 에이전트를 실행합니다.

```bash
python -m pip install -e ".[dev]"
python -m pytest
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

출력 명령어는 반드시 아래와 같아야 합니다.

```bash
kubectl scale deployment paymentservice --replicas=3 -n online-boutique
```

## 2. 로컬 Kind Dry-Run 단계

WSL2, Docker, `kubectl`, `kind` 설치 후 작은 검증용 클러스터를 만듭니다. 이 단계는
전체 AIOpsLab 배포가 아니라 명령어 호환성만 확인하는 가벼운 환경입니다.

```bash
kind create cluster --name aiops-local
kubectl create namespace online-boutique
kubectl create deployment paymentservice \
  --image=nginx:1.27 \
  -n online-boutique
```

같은 시나리오를 `dry-run` 모드로 실행합니다.

```bash
python -m aiops_k8s_agents.cli run \
  --mode dry-run \
  --namespace online-boutique \
  --service paymentservice \
  --metric cpu \
  --value 95 \
  --threshold 80 \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice
```

사용자에게 보이는 명령어는 mock 모드와 동일합니다. executor는 Kubernetes API 검증을
위해서만 내부 실행 argv에 `--dry-run=server`를 붙입니다.

## 3. 연구실 Ubuntu 서버 단계

연구실 서버에서 아래 절차를 수행합니다.

```bash
git clone <repo-url> aiops_research
cd aiops_research
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

서버의 kubeconfig를 연결합니다.

```bash
export KUBECONFIG=/path/to/lab/kubeconfig
kubectl get nodes
kubectl get deployments -n online-boutique
```

실제 클러스터에도 먼저 `dry-run`을 실행합니다.

```bash
python -m aiops_k8s_agents.cli run \
  --mode dry-run \
  --namespace online-boutique \
  --service paymentservice \
  --metric cpu \
  --value 95 \
  --threshold 80 \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice
```

dry-run 출력과 allowlist를 확인한 뒤에만 `real` 모드로 전환합니다.

```bash
python -m aiops_k8s_agents.cli run \
  --mode real \
  --namespace online-boutique \
  --service paymentservice \
  --metric cpu \
  --value 95 \
  --threshold 80 \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice
```

## 4. AutoGen GroupChat 단계

LLM 기반 4-agent GroupChat을 사용할 때는 AutoGen 선택 의존성을 설치합니다.

```bash
python -m pip install -e ".[autogen,dev]"
export OPENAI_API_KEY=<your-api-key>
```

먼저 서버에서도 `mock` 모드로 AutoGen 판단 결과와 reward를 확인합니다.

```bash
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

그 다음 `dry-run`, 마지막으로 `real` 순서로 전환합니다.

## 5. Prometheus Metric 연결 단계

Prometheus가 준비되기 전에는 mock 응답 파일로 metric 입력 경로를 검증합니다.

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

Prometheus가 준비되면 URL 기반으로 전환합니다.

로컬 kind에서 가벼운 Prometheus API만 먼저 확인하려면:

```bash
kubectl apply -f k8s/minimal-prometheus.yaml
kubectl rollout status deployment/prometheus -n monitoring --timeout=120s
kubectl port-forward -n monitoring service/prometheus 9090:9090
```

```bash
aiops-k8s-agents prometheus-run \
  --mode mock \
  --prometheus-url http://localhost:9090 \
  --query "up{job=\"prometheus\"}" \
  --metric cpu \
  --threshold 0.5 \
  --default-namespace online-boutique \
  --default-service paymentservice \
  --allowed-namespace online-boutique \
  --allowed-deployment paymentservice
```

## 6. Chaos Mesh 장애 주입 단계

로컬 kind에서 Chaos Mesh 설치가 끝났다면 `paymentservice` pod 하나를 kill하는 안전한
실험으로 복구 루프를 확인할 수 있습니다.

```bash
kubectl apply -f k8s/paymentservice-pod-kill.yaml
kubectl get podchaos -n online-boutique
kubectl rollout status deployment/paymentservice -n online-boutique --timeout=180s
```

실험 후 정리:

```bash
kubectl delete -f k8s/paymentservice-pod-kill.yaml
```

## 안전 규칙

- `mock`과 `dry-run`이 모두 통과하기 전까지 `real` 모드는 사용하지 않습니다.
- 새 namespace나 deployment는 실험 범위에 포함되는지 확인한 뒤 allowlist에 추가합니다.
- v1에서는 `kubectl scale deployment` 이외의 명령으로 확장하지 않습니다.
- 각 실행의 JSON 출력을 실험 증거로 저장합니다.
