$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
$SourceRoot = (Resolve-Path (Join-Path $Root "src")).Path

if ($env:PYTHONPATH) {
    $env:PYTHONPATH = @($SourceRoot, $env:PYTHONPATH) -join [IO.Path]::PathSeparator
} else {
    $env:PYTHONPATH = $SourceRoot
}

if (-not $env:ORCHESTRATOR_BIND_ADDRESS) { $env:ORCHESTRATOR_BIND_ADDRESS = "127.0.0.1" }
if (-not $env:PORT) { $env:PORT = "18200" }

python -m orchestrator_agent.web

