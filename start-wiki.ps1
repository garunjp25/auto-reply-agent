# start-wiki.ps1
# Launch the Wiki Explorer (and the full auto-reply service) on http://127.0.0.1:8765/wiki

$ErrorActionPreference = "Stop"
$Port = 8765
$Url = "http://127.0.0.1:$Port/wiki"

Set-Location $PSScriptRoot

# Pre-flight checks
if (-not (Test-Path ".\.env")) {
    Write-Host "ERROR: .env not found. Copy .env.example, then edit." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path ".\wiki") -or @(Get-ChildItem .\wiki -Filter *.md).Count -eq 0) {
    Write-Host "ERROR: wiki/ is empty. Run:  uv run python scripts/build_wiki.py" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path ".\data\wiki_graph.json")) {
    Write-Host "WARN: data/wiki_graph.json not found. Building it now..." -ForegroundColor Yellow
    uv run python scripts/build_wiki_graph.py
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

# Free the port if something is already bound to it
$existing = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Port $Port is in use; stopping old process(es)..." -ForegroundColor Yellow
    $existing | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 500
}

# Open the browser shortly after the server starts
Start-Job -ScriptBlock {
    param($u)
    Start-Sleep -Seconds 3
    Start-Process $u
} -ArgumentList $Url | Out-Null

Write-Host ""
Write-Host "Starting Wiki Explorer at $Url" -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop." -ForegroundColor Cyan
Write-Host ""

uv run uvicorn auto_reply.web.app:create_app --factory --host 127.0.0.1 --port $Port
