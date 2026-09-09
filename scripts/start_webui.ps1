$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$WebUi = Join-Path (Split-Path -Parent $ProjectRoot) "agentscope-main\examples\web_ui"
if (-not (Test-Path $WebUi)) { throw "AgentScope Web UI not found: $WebUi" }
Set-Location $WebUi
& npm run dev
