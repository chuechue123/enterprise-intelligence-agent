param(
    [string]$Scope = "FinanceSalesAgent",
    [string]$ProjectRoot = (Get-Location).Path
)

& "$ProjectRoot\.venv\Scripts\python.exe" -m bizinsight.mcp.server --scope $Scope --project-root $ProjectRoot
