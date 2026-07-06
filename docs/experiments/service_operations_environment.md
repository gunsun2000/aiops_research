# Agent 중심 AI 서비스 운영 통합 실험 환경 및 실행 코드

> 보관 문서: 현재 대학원 연구 본체는 4-Agent 기반 Kubernetes 장애 감시/복구 실험이다. 이 문서는 Ops LLM 선정, CPU/GPU VM 배치, AI 서비스 deployment manifest를 묶은 별도 과제 성격의 확장 runbook이다.

이 문서는 `run-service-operations` 통합 파이프라인을 서버에서 재현하기 위한 환경 설정, 실행 명령, 성공 기준을 정리한 runbook입니다.

## 1. 실험 목적

현재 프로젝트는 다음 기능을 하나의 Agent 중심 운영 흐름으로 연결합니다.

```text
Ops LLM 선정
-> CPU/GPU VM 기반 AI 응용 배치 추천
-> Kubernetes Deployment manifest 생성
-> 응용관리 / 인프라 / 비용 Agent 검토
-> Python Validator + Go Guard 실행 준비
-> Kubernetes server-side dry-run 검증
```

이 실험은 실제 Pod를 생성하기 전 단계에서 AI 서비스 배포 계획이 Kubernetes API 서버 검증을 통과하는지 확인합니다.

## 2. 서버 환경 준비

연구실 서버에서 실행합니다.

```bash
cd ~/geonhae/aiops_research
conda activate aiops_research

git pull origin master
python -m pip install -e ".[dev,autogen]"

export PATH="$HOME/bin:$PATH"
export KUBECONFIG="$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml"

kubectl config current-context
kubectl get nodes
```

정상 기준:

```text
current-context = kind-geonhae-aiops
node status = Ready
```

## 3. 기본 검증

Python 테스트:

```bash
cd ~/geonhae/aiops_research
python -m pytest
```

정상 기준:

```text
127 passed
```

Go guard 테스트:

```bash
cd ~/geonhae/aiops_research/go/aiops-guard
go test ./...
```

정상 기준:

```text
ok github.com/gunsun2000/aiops_research/go/aiops-guard/internal/guard
```

## 4. Mock 모드 통합 실행

Mock 모드는 실제 Kubernetes API를 호출하지 않고 전체 판단 흐름과 manifest 생성을 확인합니다.

```bash
cd ~/geonhae/aiops_research
conda activate aiops_research

aiops-k8s-agents run-service-operations \
  --llm-policy quality_first \
  --workload llm-chat-inference \
  --namespace online-boutique \
  --deployment paymentservice \
  --mode mock \
  --guard-backend go
```

확인할 핵심 출력:

```json
{
  "valid": true,
  "selected_llm": "gpt-5.5",
  "autogen_runtime_model": "gpt-5.5",
  "selected_resource": "gpu-vm-l4",
  "deployment_manifest": {
    "kind": "Deployment"
  },
  "deployment_dry_run": {
    "mode": "mock",
    "valid": true
  },
  "recovery_pipeline_ready": true,
  "guard_backend": "go"
}
```

## 5. Kubernetes dry-run 실행

Dry-run은 Kubernetes API 서버에 manifest를 보내지만 실제 Pod는 만들지 않습니다.

먼저 AI inference namespace를 준비합니다.

```bash
cd ~/geonhae/aiops_research
conda activate aiops_research

export PATH="$HOME/bin:$PATH"
export KUBECONFIG="$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml"

kubectl create namespace ai-inference --dry-run=client -o yaml | kubectl apply -f -
kubectl get namespace ai-inference
```

그 다음 통합 파이프라인을 dry-run으로 실행합니다.

```bash
aiops-k8s-agents run-service-operations \
  --llm-policy quality_first \
  --workload llm-chat-inference \
  --namespace online-boutique \
  --deployment paymentservice \
  --mode dry-run \
  --guard-backend go
```

정상 기준:

```json
{
  "valid": true,
  "deployment_dry_run": {
    "command": "kubectl apply -f - --dry-run=server",
    "mode": "dry-run",
    "valid": true,
    "stdout": "deployment.apps/llm-chat-inference created (server dry run)"
  },
  "recovery_pipeline_ready": true
}
```

## 6. 장애 입력까지 포함한 통합 실행

배포 준비뿐 아니라 4-Agent 복구 판단까지 함께 확인하려면 장애 입력을 추가합니다.

```bash
aiops-k8s-agents run-service-operations \
  --llm-policy quality_first \
  --workload llm-chat-inference \
  --namespace online-boutique \
  --deployment paymentservice \
  --metric cpu \
  --value 95 \
  --threshold 80 \
  --message "paymentservice CPU usage is high" \
  --mode mock \
  --guard-backend go
```

이 명령은 다음을 함께 확인합니다.

```text
AI 서비스 배포 준비
4-Agent 장애 복구 판단
ScaleAction 생성
Python Validator + Go Guard 실행 준비
```

## 7. 현재 완료 범위

완료된 범위:

```text
Ops LLM 선정 결과가 AutoGen runtime model로 연결됨
CPU/GPU VM 배치 결과가 Infrastructure Agent 판단에 반영됨
AI 서비스 Deployment manifest 생성
Kubernetes server-side dry-run 검증 통과
Go Guard 기반 실행 경로 연결
```

후속 단계:

```text
실제 AI inference Pod 배포
실제 LLM serving container 이미지 운영
GPU device plugin과 node label 기반 실제 GPU scheduling
Go Echo HTTP API 서버와 Swagger UI
```

## 8. 실제 Pod 배포를 아직 하지 않은 이유

현재 통합 파이프라인은 안전한 dry-run 검증까지 완료한 상태입니다. 실제 Pod 배포는 다음 조건이 필요합니다.

```text
실제 사용 가능한 AI inference container image
GPU device plugin 구성
GPU node label 구성
실제 모델 serving 포트와 health check
리소스 점유에 대한 서버 운영 허가
```

따라서 1차 연구에서는 manifest 생성과 Kubernetes API 검증까지 완료하고, 실제 배포는 후속 단계로 분리합니다.
