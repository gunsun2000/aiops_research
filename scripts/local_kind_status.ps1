$ErrorActionPreference = "Stop"

$kubectlDir = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages\Kubernetes.kubectl_Microsoft.Winget.Source_8wekyb3d8bbwe"
$kindDir = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages\Kubernetes.kind_Microsoft.Winget.Source_8wekyb3d8bbwe"
$helmDir = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages\Helm.Helm_Microsoft.Winget.Source_8wekyb3d8bbwe\windows-amd64"
$dockerDir = "C:\Program Files\Docker\Docker\resources\bin"
$env:Path = "$kubectlDir;$kindDir;$helmDir;$dockerDir;$env:Path"

Write-Host "== Tool Versions =="
docker --version
kubectl version --client
kind version
helm version

Write-Host "`n== Kubernetes Nodes =="
kubectl get nodes -o wide

Write-Host "`n== Online Boutique =="
kubectl get pods -n online-boutique
kubectl get deployment paymentservice -n online-boutique

Write-Host "`n== Chaos Mesh =="
kubectl get pods -n chaos-mesh

Write-Host "`n== Minimal Prometheus =="
kubectl get pods -n monitoring
