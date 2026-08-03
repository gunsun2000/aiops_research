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
`http://127.0.0.1:${PORT}/api/docs`. The web runtime now provides persistent
background Jobs, event replay and live SSE, cooperative cancellation, and a
gated `mock`, `dry-run`, or `real` execution request. The default SQLite file is
`runs/control-plane/experiment-jobs.sqlite3`.

## 4. Capability and connection probes

```bash
curl -fsS "http://127.0.0.1:${PORT}/api/platform"
curl -fsS "http://127.0.0.1:${PORT}/api/connections"
```

Expected result: `/api/platform` reports `persistent_jobs: true`,
`real_runtime: true`, and `runtime_boundary: persistent_bounded_jobs`. The real mode is
not globally marked ready until request-specific preflight succeeds.
`/api/connections` reports `read_only: true` and individual readiness for
Kubernetes, Prometheus, Chaos Mesh, AutoGen configuration, AIOpsLab path, and
the artifact directory. Only Kubernetes, Prometheus, Chaos Mesh, and the artifact
directory are required by the deterministic real Job. AutoGen and AIOpsLab are
reported for visibility but are not prerequisites for this runtime. These probe
responses are read-only and never prove Kubernetes mutation or a real experiment.

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

## 6. Persistent web Job execution

Create a mock Job:

```bash
jq '. + {"repetitions":1,"real_confirmation":""}' \
  /tmp/cpu-stress-validate.json \
  | curl -fsS -X POST "http://127.0.0.1:${PORT}/api/experiments" \
      -H 'content-type: application/json' --data-binary @-
```

The response is HTTP 202 and contains an `experiment_id`. Use that id to query
the persistent Job, replay/live-stream its events, or request cancellation:

```bash
EXPERIMENT_ID="<response experiment_id>"
curl -fsS "http://127.0.0.1:${PORT}/api/experiments/${EXPERIMENT_ID}"
curl -N "http://127.0.0.1:${PORT}/api/experiments/${EXPERIMENT_ID}/events"
curl -fsS -X POST \
  "http://127.0.0.1:${PORT}/api/experiments/${EXPERIMENT_ID}/cancel"
```

Cancellation is cooperative and cleanup remains mandatory. On server startup,
stale nonterminal Jobs become `interrupted`; they are not blindly resumed.

For a real web Job, start the server with `CONFIRM_REAL_RUN=YES`, change the mode
to `real`, and include the exact body field below:

```json
"real_confirmation": "EXECUTE REAL EXPERIMENT"
```

This authorization does not bypass request-specific preflight, the target lock,
allowlists, replica bounds, validation, recovery monitoring, or cleanup.

## 7. Existing CLI real experiment path

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

The matrix runner uses `config/recovery_action_experiments.json`. Preserve that
exact configuration with the run before investigating failures:

```bash
RUN_DIR="$(ls -dt runs/recovery-action-pilot/* | head -1)"
cp config/recovery_action_experiments.json \
  "$RUN_DIR/recovery_action_experiments.json"
```

## 8. Cleanup and failure evidence

Always retain the run directory before cleanup. Inspect every matrix record with
`cleanup_valid=false`; do not assume the failed treatment was CPU stress. The
following commands look up each failed record's registered scenario in the
matrix configuration, delete that scenario's manifest, reset its deployment to
the configured baseline replicas, and wait for rollout:

Prerequisite for this cleanup block: install `jq` and verify it is available:

```bash
command -v jq
jq --version
# If absent on Ubuntu: sudo apt-get update && sudo apt-get install -y jq
```

```bash
RUN_DIR="$(ls -dt runs/recovery-action-pilot/* | head -1)"
CONFIG="$RUN_DIR/recovery_action_experiments.json"
OUTCOMES="$RUN_DIR/outcomes.jsonl"
jq -c 'select(.cleanup_valid == false)' "$OUTCOMES" \
  > "$RUN_DIR/cleanup-failures.jsonl"

while IFS= read -r record; do
  scenario="$(jq -r '.scenario' <<<"$record")"
  IFS=$'\t' read -r manifest namespace deployment < <(
    jq -r --arg id "$scenario" \
      '.scenarios[] | select(.id == $id) |
       [.chaos_manifest, .namespace, .deployment] | @tsv' "$CONFIG"
  )
  if [[ -z "${manifest:-}" || -z "${namespace:-}" || -z "${deployment:-}" ]]; then
    echo "No registered cleanup target for scenario: $scenario" >&2
    exit 1
  fi
  kubectl delete -f "$manifest" --ignore-not-found
  kubectl scale deployment "$deployment" \
    --replicas="$(jq -r '.baseline_replicas' "$CONFIG")" -n "$namespace"
  kubectl rollout status "deployment/${deployment}" -n "$namespace" \
    --timeout="$(jq -r '.recovery_timeout_seconds' "$CONFIG")s"
  kubectl get deployment "$deployment" -n "$namespace" -o wide
done < "$RUN_DIR/cleanup-failures.jsonl"

find "$RUN_DIR" -maxdepth 3 -type f -print
kubectl get events -n online-boutique --sort-by=.lastTimestamp | tail -50
```

Expected result: every `cleanup_valid=false` record is visited, its manifest is
absent or reports `NotFound`/ignored, and its deployment is reset to the matrix
configuration's `baseline_replicas` and reaches rollout-ready status. The saved
`recovery_action_experiments.json` is the configuration actually used to select
all four scenarios: pod-kill/paymentservice, cpu-stress/paymentservice,
memory-stress/checkoutservice, and network-delay/paymentservice. This proves
cleanup and post-run state collection, not recovery by itself.

On failure, collect bounded diagnostics for every failed scenario without
deleting the evidence:

```bash
while IFS= read -r record; do
  scenario="$(jq -r '.scenario' <<<"$record")"
  IFS=$'\t' read -r _manifest namespace deployment < <(
    jq -r --arg id "$scenario" \
      '.scenarios[] | select(.id == $id) |
       [.chaos_manifest, .namespace, .deployment] | @tsv' "$CONFIG"
  )
  kubectl get deployment "$deployment" -n "$namespace" -o yaml \
    > "$RUN_DIR/${scenario}-deployment.yaml"
  kubectl get pods -n "$namespace" -l "app=${deployment}" -o wide \
    > "$RUN_DIR/${scenario}-pods.txt"
  kubectl describe deployment "$deployment" -n "$namespace" \
    > "$RUN_DIR/${scenario}-describe.txt"
  kubectl logs -n "$namespace" -l "app=${deployment}" \
    --all-containers --tail=200 > "$RUN_DIR/${scenario}-logs.txt" || true
done < "$RUN_DIR/cleanup-failures.jsonl"
cp config/recovery_action_experiments.json \
  "$RUN_DIR/recovery_action_experiments.json"
```

Record the exact mode, scenario, namespace, deployment, Prometheus URL, current
Kubernetes context, and whether cleanup completed. A failed preflight, a failed
fault injection, a failed recovery observation, and a failed cleanup are
different outcomes and must remain distinct in the report.

## 9. Explicit exclusions

Python and Go regression tests use deterministic or injected fakes where stated;
they are not real-cluster evidence. AutoGen model execution and AIOpsLab
benchmark Jobs are separate runtimes and are not implied by the core runtime or
its web Job API. Persistent Jobs, SSE, cancellation, and the gated deterministic
web execution path are implemented. AutoGen GroupChat web execution and
AIOpsLab benchmark Jobs remain future integrations.
