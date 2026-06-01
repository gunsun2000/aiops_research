# Prometheus Metric Adapter

이 adapter는 Prometheus `/api/v1/query` 응답을 현재 프로토타입의 `AlertEvent`로
변환합니다. 실제 Prometheus가 없어도 mock JSON 응답으로 먼저 검증할 수 있습니다.

## 변환 흐름

```text
Prometheus /api/v1/query response
-> PrometheusMetricConfig
-> AlertEvent(namespace/service/metric/value/threshold/message)
-> AI-MCMP Coordinator
-> 4개 agent action/reward 합의
-> kubectl scale 명령어 검증
```

## Mock 응답 실행

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

## 실제 Prometheus 실행

로컬 kind에서 가벼운 Prometheus API만 검증하려면 아래 manifest를 적용합니다.

```bash
kubectl apply -f k8s/minimal-prometheus.yaml
kubectl rollout status deployment/prometheus -n monitoring --timeout=120s
kubectl port-forward -n monitoring service/prometheus 9090:9090
```

다른 터미널에서 Prometheus API 기반 입력을 실행합니다.

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

서버에서는 반드시 `mock -> dry-run -> real` 순서로 전환합니다.
