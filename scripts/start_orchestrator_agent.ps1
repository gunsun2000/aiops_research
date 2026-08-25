$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

if (-not $env:ORCHESTRATOR_BIND_ADDRESS) { $env:ORCHESTRATOR_BIND_ADDRESS = "127.0.0.1" }
if (-not $env:PORT) { $env:PORT = "18200" }

python -m orchestrator_agent.web

