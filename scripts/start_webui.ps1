$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$WorkbenchUrl = "http://127.0.0.1:8000/"
$HealthUrl = "http://127.0.0.1:8000/bizinsight/health"

if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python virtual environment not found: $PythonPath"
}

function Test-BizInsightService {
    try {
        $null = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 2
        return $true
    }
    catch {
        return $false
    }
}

if (-not (Test-BizInsightService)) {
    $BackendProcess = Start-Process `
        -FilePath $PythonPath `
        -ArgumentList "-m", "uvicorn", "bizinsight.service:app", "--host", "127.0.0.1", "--port", "8000" `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -PassThru

    $Ready = $false
    foreach ($Attempt in 1..30) {
        Start-Sleep -Milliseconds 500
        if (Test-BizInsightService) {
            $Ready = $true
            break
        }
        if ($BackendProcess.HasExited) {
            break
        }
    }
    if (-not $Ready) {
        throw "BizInsight service did not become ready. Run scripts\start_backend.ps1 to inspect startup logs."
    }
    Write-Host "BizInsight backend started (PID $($BackendProcess.Id))."
}
else {
    Write-Host "BizInsight backend is already running."
}

Write-Host "Opening $WorkbenchUrl"
Start-Process $WorkbenchUrl
