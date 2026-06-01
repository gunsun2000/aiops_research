$ErrorActionPreference = "Stop"

$kubectlDir = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages\Kubernetes.kubectl_Microsoft.Winget.Source_8wekyb3d8bbwe"
$kindDir = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages\Kubernetes.kind_Microsoft.Winget.Source_8wekyb3d8bbwe"
$dockerDir = "C:\Program Files\Docker\Docker\resources\bin"
$env:Path = "$kubectlDir;$kindDir;$dockerDir;$env:Path"

aiops-k8s-agents run `
  --mode dry-run `
  --namespace online-boutique `
  --service paymentservice `
  --metric cpu `
  --value 95 `
  --threshold 80 `
  --allowed-namespace online-boutique `
  --allowed-deployment paymentservice
