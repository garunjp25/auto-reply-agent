# start.ps1 — Launch the auto-reply agent + wiki explorer locally
# Opens http://127.0.0.1:8765 in your browser (links to both /wiki and /agent/queue)

$ErrorActionPreference = "Stop"
$Port = 8765
$RootUrl  = "http://127.0.0.1:$Port"
$WikiUrl  = "$RootUrl/wiki"
$AgentUrl = "$RootUrl/agent/queue"

Set-Location $PSScriptRoot

Write-Host ""
Write-Host "─────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host "  auto-reply agent — local launcher" -ForegroundColor Cyan
Write-Host "─────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host ""

# ── Pre-flight: .env ──────────────────────────────────────────────
if (-not (Test-Path ".\.env")) {
    Write-Host "ERROR: .env not found." -ForegroundColor Red
    Write-Host "  Copy .env.example → .env and fill in your keys." -ForegroundColor Yellow
    exit 1
}

# ── Pre-flight: wiki docs ─────────────────────────────────────────
if (-not (Test-Path ".\wiki") -or @(Get-ChildItem .\wiki -Filter *.md -ErrorAction SilentlyContinue).Count -eq 0) {
    Write-Host "WARN: wiki/ is empty. Building product docs now (~\$0.25)..." -ForegroundColor Yellow
    uv run python scripts/build_wiki.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: wiki build failed. Check your ANTHROPIC_API_KEY and LUMENX_ADMIN_TOKEN." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

# ── Pre-flight: wiki graph ────────────────────────────────────────
if (-not (Test-Path ".\data\wiki_graph.json")) {
    Write-Host "WARN: data/wiki_graph.json not found. Building graph now (~\$0.12)..." -ForegroundColor Yellow
    uv run python scripts/build_wiki_graph.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: graph build failed." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

# ── Free port if busy ─────────────────────────────────────────────
$existing = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Port $Port is in use — stopping old process(es)..." -ForegroundColor Yellow
    $existing | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 600
}

# ── Open browser after brief delay ───────────────────────────────
Start-Job -ScriptBlock {
    param($u)
    Start-Sleep -Seconds 3
    Start-Process $u
} -ArgumentList $RootUrl | Out-Null

# ── Print URLs ────────────────────────────────────────────────────
Write-Host "  🚀  $RootUrl           ← landing page" -ForegroundColor Green
Write-Host "  📚  $WikiUrl     ← knowledge graph + Q&A" -ForegroundColor Green
Write-Host "  🗂   $AgentUrl   ← review queue (needs password)" -ForegroundColor Green
Write-Host ""
Write-Host "  Press Ctrl+C to stop." -ForegroundColor DarkGray
Write-Host ""

uv run uvicorn auto_reply.web.app:create_app --factory --host 127.0.0.1 --port $Port
