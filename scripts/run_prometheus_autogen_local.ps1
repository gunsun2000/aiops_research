$ErrorActionPreference = "Stop"

if (-not $env:OPENAI_API_KEY) {
  throw "OPENAI_API_KEY is missing. Run: `$env:OPENAI_API_KEY='sk-...'"
}

$kubectlDir = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages\Kubernetes.kubectl_Microsoft.Winget.Source_8wekyb3d8bbwe"
$kindDir = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages\Kubernetes.kind_Microsoft.Winget.Source_8wekyb3d8bbwe"
$dockerDir = "C:\Program Files\Docker\Docker\resources\bin"
$env:Path = "$kubectlDir;$kindDir;$dockerDir;$env:Path"

$containerName = "aiops-local-control-plane"
$containerExists = docker ps -a --filter "name=^/$containerName$" --format "{{.Names}}"
if (-not $containerExists) {
  throw "kind control-plane container '$containerName' was not found. Create or recreate the aiops-local kind cluster first."
}

$isRunning = docker inspect -f "{{.State.Running}}" $containerName
if ($isRunning -ne "true") {
  Write-Host "Starting stopped kind control-plane container: $containerName"
  docker start $containerName | Out-Host
}

kind export kubeconfig --name aiops-local | Out-Host
kubectl wait --for=condition=Ready node/aiops-local-control-plane --timeout=120s

$portForward = Start-Process `
  -FilePath powershell `
  -ArgumentList "-NoProfile", "-Command", "`$env:Path = '$kubectlDir;$kindDir;$dockerDir;' + `$env:Path; kubectl port-forward -n monitoring service/prometheus 9090:9090" `
  -WindowStyle Hidden `
  -PassThru

try {
  Start-Sleep -Seconds 8
  aiops-k8s-agents autogen-prometheus-run `
    --mode dry-run `
    --prometheus-url http://127.0.0.1:9090 `
    --query up `
    --metric cpu `
    --threshold 0.5 `
    --default-namespace online-boutique `
    --default-service paymentservice `
    --allowed-namespace online-boutique `
    --allowed-deployment paymentservice `
    --save-result-dir runs
}
finally {
  Stop-Process -Id $portForward.Id -Force -ErrorAction SilentlyContinue
}
