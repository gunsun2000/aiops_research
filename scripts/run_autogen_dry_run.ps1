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

aiops-k8s-agents autogen-run `
  --mode dry-run `
  --namespace online-boutique `
  --service paymentservice `
  --metric cpu `
  --value 95 `
  --threshold 80 `
  --message "paymentservice CPU usage is 95 percent" `
  --allowed-namespace online-boutique `
  --allowed-deployment paymentservice `
  --save-result-dir runs
