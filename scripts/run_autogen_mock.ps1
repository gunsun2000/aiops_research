$ErrorActionPreference = "Stop"

if (-not $env:OPENAI_API_KEY) {
  throw "OPENAI_API_KEY is missing. Run: `$env:OPENAI_API_KEY='sk-...'"
}

aiops-k8s-agents autogen-run `
  --mode mock `
  --namespace online-boutique `
  --service paymentservice `
  --metric cpu `
  --value 95 `
  --threshold 80 `
  --message "paymentservice CPU usage is 95 percent" `
  --allowed-namespace online-boutique `
  --allowed-deployment paymentservice `
  --save-result-dir runs
