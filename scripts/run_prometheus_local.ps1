$ErrorActionPreference = "Stop"

$kubectlDir = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages\Kubernetes.kubectl_Microsoft.Winget.Source_8wekyb3d8bbwe"
$kindDir = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages\Kubernetes.kind_Microsoft.Winget.Source_8wekyb3d8bbwe"
$dockerDir = "C:\Program Files\Docker\Docker\resources\bin"
$env:Path = "$kubectlDir;$kindDir;$dockerDir;$env:Path"

$portForward = Start-Process `
  -FilePath powershell `
  -ArgumentList "-NoProfile", "-Command", "`$env:Path = '$kubectlDir;$kindDir;$dockerDir;' + `$env:Path; kubectl port-forward -n monitoring service/prometheus 9090:9090" `
  -WindowStyle Hidden `
  -PassThru

try {
  Start-Sleep -Seconds 8
  aiops-k8s-agents prometheus-run `
    --mode mock `
    --prometheus-url http://127.0.0.1:9090 `
    --query up `
    --metric cpu `
    --threshold 0.5 `
    --default-namespace online-boutique `
    --default-service paymentservice `
    --allowed-namespace online-boutique `
    --allowed-deployment paymentservice
}
finally {
  Stop-Process -Id $portForward.Id -Force -ErrorAction SilentlyContinue
}
