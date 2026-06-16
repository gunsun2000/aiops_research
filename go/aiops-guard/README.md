# aiops-guard

`aiops-guard` is the Go safety gate for the AIOps 4-Agent project.

The Python layer still performs observation, agent scoring, reward comparison, and experiment orchestration. The Go layer receives a structured action request, validates it against a strict policy, renders the allowed `kubectl` command, and then runs it only in the selected mode.

## Why Go is used here

- Final Kubernetes actions should be deterministic and small enough to audit.
- The guard is independent from the Python/LLM agent layer.
- The same JSON contract can be cross-checked by another coding agent or LLM reviewer.

## Request example

```json
{
  "mode": "mock",
  "namespace": "online-boutique",
  "deployment": "paymentservice",
  "action": "scale_out",
  "replicas": 3,
  "allowed_namespaces": ["online-boutique"],
  "allowed_deployments": ["paymentservice", "checkoutservice"],
  "min_replicas": 1,
  "max_replicas": 5
}
```

## Run

```bash
cd go/aiops-guard
go test ./...
go run ./cmd/aiops-guard --input ../../examples/go_guard_scale_action.json
```

`mock` mode validates and renders a command without running `kubectl`.

`dry-run` mode appends `--dry-run=server` to mutating commands.

`real` mode runs the validated command with the current `KUBECONFIG`.
