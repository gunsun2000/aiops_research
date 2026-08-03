# Core Real Experiment Runtime Verification Guide

This guide is for the Ubuntu research-server environment. It describes the
implemented Plan A runtime boundary and the evidence that each command can
establish. Run commands from the repository root.

## 1. Environment and kubeconfig

```bash
cd ~/geonhae/aiops_research
conda activate aiops_research
python -m pip install -e ".[ui,dev]"

export PATH="$HOME/bin:$PATH"
export KUBECONFIG="${KUBECONFIG:-$HOME/geonhae/kubeconfigs/kind-geonhae-aiops.yaml}"
export PROMETHEUS_URL="${PROMETHEUS_URL:-http://127.0.0.1:9091}"

kubectl config current-context
kubectl get nodes
kubectl get pods -n online-boutique
kubectl get pods -n monitoring-full
```

Expected result: the Python commands prove environment setup only. The
`kubectl` commands prove Kubernetes connectivity and current resource state;
they are connection evidence, not an experiment result. Record the context,
node status, and pod output before any real run.

## 2. Prometheus readiness

In a separate terminal, port-forward the Prometheus service if necessary:

```bash
kubectl port-forward -n monitoring-full \
  service/kube-prometheus-stack-prometheus 9091:9090
```

Then verify the endpoint and a registered metric:

```bash
curl -fsS "$PROMETHEUS_URL/-/ready"
curl -fsSG "$PROMETHEUS_URL/api/v1/query" \
  --data-urlencode 'query=up'
```

Expected result: `/-/ready` returns HTTP success and the query returns a
Prometheus `status: success` response. This proves Prometheus readiness and
query access only; it is not evidence that a Chaos Mesh experiment recovered.

## 3. Start the current Control Plane

```bash
export PORT="${PORT:-18080}"
export AIOPS_BIND_ADDRESS="${AIOPS_BIND_ADDRESS:-127.0.0.1}"
aiops-control-plane
```

The server is available at `http://127.0.0.1:${PORT}/` and its OpenAPI page is
`http://127.0.0.1:${PORT}/api/docs`. The current web boundary is preflight-only:
there is no persistent Job, SSE stream, cancellation endpoint, or web-triggered
real execution endpoint in Plan A.

## 4. Capability and connection probes

```bash
curl -fsS "http://127.0.0.1:${PORT}/api/platform"
curl -fsS "http://127.0.0.1:${PORT}/api/connections"
```

Expected result: `/api/platform` reports `persistent_jobs: false`,
`real_runtime: true`, and `runtime_boundary: preflight_only`. The real mode is
not globally marked ready until request-specific preflight succeeds.
`/api/connections` reports `read_only: true` and individual readiness for
Kubernetes, Prometheus, Chaos Mesh, AutoGen configuration, AIOpsLab path, and
the artifact directory. These responses prove read-only capability/readiness
checks, never Kubernetes mutation or a real experiment.

## 5. Request-specific preflight

Use the registered `cpu-stress` scenario. The endpoint validates the scenario,
target, metric, threshold, protocol profile, and mode.

Save this request body once for the three mode checks:

```bash
cat > /tmp/cpu-stress-validate.json <<'JSON'
{
  "scenario_id":"cpu-stress",
  "namespace":"online-boutique",
  "deployment":"paymentservice",
  "metric":"cpu",
  "threshold":80,
  "mode":"mock",
  "backend":"python",
  "protocol_profile":"four-agent-role-veto-v1"
}
JSON
```

### Mock

```bash
curl -fsS -X POST "http://127.0.0.1:${PORT}/api/experiments/validate" \
  -H 'content-type: application/json' \
  --data-binary @/tmp/cpu-stress-validate.json
```

Expected result: HTTP success with `validated: true` and `read_only: true`.
This proves request validation for mock mode only. It does not collect external
evidence or execute an experiment.

### Dry-run

Use the same request with only the mode changed:

```bash
sed 's/"mode":"mock"/"mode":"dry-run"/' /tmp/cpu-stress-validate.json \
  | curl -fsS -X POST "http://127.0.0.1:${PORT}/api/experiments/validate" \
      -H 'content-type: application/json' --data-binary @-
```

Expected result: HTTP success with `validated: true`. This proves dry-run
request admission; it does not apply a Chaos Mesh manifest or change a cluster.
The body was saved in the preceding step so the mode-only substitutions are
repeatable.

### Real

```bash
sed 's/"mode":"mock"/"mode":"real"/' /tmp/cpu-stress-validate.json \
  | curl -fsS -X POST "http://127.0.0.1:${PORT}/api/experiments/validate" \
      -H 'content-type: application/json' --data-binary @-
```

Expected result on a prepared Ubuntu server: HTTP success, `validated: true`,
and a valid scenario-specific `preflight` result. The preflight is read-only:
it checks registered manifest/resource prerequisites and readiness, but does not
acquire the operation lock, inject Chaos Mesh, execute an Action, or perform
cleanup. A missing prerequisite should produce HTTP 400 with the missing names;
that is a preflight failure, not evidence of an unsuccessful real experiment.

## 6. Existing CLI real experiment path

The supported real execution path remains the existing CLI/matrix runner, not a
web request. First set the required network-delay query for the deployed
telemetry:

```bash
export NETWORK_LATENCY_QUERY='max(probe_duration_seconds{target="paymentservice"})'
GUARD_BACKEND=go \
MODE=real \
REPETITIONS=1 \
PROMETHEUS_URL="$PROMETHEUS_URL" \
NETWORK_LATENCY_QUERY="$NETWORK_LATENCY_QUERY" \
bash scripts/server_recovery_action_pilot.sh
```

Expected result for a genuine real run: the command records bounded action
outcomes under `runs/recovery-action-pilot/<run-id>/`, including stdout/stderr,
measurements, recovery status, and cleanup-related evidence. This is the first
command in this guide that can produce real experiment evidence, and only when
run against the intended Ubuntu Kubernetes/Prometheus/Chaos Mesh environment.
The output must not be relabeled as real evidence when the mode is changed to
`mock` or `dry-run`.

## 7. Cleanup and failure evidence

Always retain the run directory before cleanup. For a registered scenario whose
manifest was applied, cleanup uses the same manifest and ignores an already
deleted resource:

```bash
RUN_DIR="$(ls -dt runs/recovery-action-pilot/* | head -1)"
find "$RUN_DIR" -maxdepth 3 -type f -print
kubectl delete -f k8s/chaos/paymentservice-cpu-stress.yaml \
  --ignore-not-found
kubectl get pods -n online-boutique -o wide
kubectl get events -n online-boutique --sort-by=.lastTimestamp | tail -50
```

Expected result: the registered fault resource is absent or reports
`NotFound`/ignored, and the run artifacts remain available for review. This
proves cleanup and post-run state collection, not recovery by itself.

On failure, collect bounded diagnostics without deleting the evidence:

```bash
kubectl get deployment paymentservice -n online-boutique -o yaml \
  > "$RUN_DIR/paymentservice-deployment.yaml"
kubectl get pods -n online-boutique -l app=paymentservice -o wide \
  > "$RUN_DIR/paymentservice-pods.txt"
kubectl describe deployment paymentservice -n online-boutique \
  > "$RUN_DIR/paymentservice-describe.txt"
kubectl logs -n online-boutique -l app=paymentservice \
  --all-containers --tail=200 > "$RUN_DIR/paymentservice-logs.txt" || true
cp config/experiment_runtime.json "$RUN_DIR/experiment_runtime.json"
```

Record the exact mode, scenario, namespace, deployment, Prometheus URL, current
Kubernetes context, and whether cleanup completed. A failed preflight, a failed
fault injection, a failed recovery observation, and a failed cleanup are
different outcomes and must remain distinct in the report.

## 8. Explicit exclusions

Python and Go regression tests use deterministic or injected fakes where stated;
they are not real-cluster evidence. AutoGen model execution and AIOpsLab
benchmark Jobs are separate runtimes and are not implied by the core runtime or
its preflight API. Persistent Jobs, SSE, cancellation, and web-triggered real
execution require Plan B implementation before they can be documented as
available.
