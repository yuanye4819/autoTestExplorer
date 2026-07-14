# AI Web Explorer - Startup Script
# Encoding: UTF-8 with BOM
$ErrorActionPreference = "Continue"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectDir

Clear-Host
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  AI Web Exploration & Testing System" -ForegroundColor White
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Check Python
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "[ERROR] Python not found! Install Python 3.10+ first" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "[OK] Python $((python --version 2>&1) -replace 'Python ','')" -ForegroundColor Green

# Install dependencies
Write-Host "[*] Checking dependencies..." -ForegroundColor Gray
pip install -r requirements.txt -q 2>$null
if ($LASTEXITCODE -ne 0) {
    pip install fastapi uvicorn pydantic pydantic-settings playwright websockets aiofiles httpx -q 2>$null
}
Write-Host "[OK] Dependencies ready" -ForegroundColor Green

# Check Playwright browser
Write-Host "[*] Checking Playwright browser..." -ForegroundColor Gray
$checkCmd = 'from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(); b.close(); p.stop()'
python -c $checkCmd 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] Installing Chromium browser (first time ~150MB download)..." -ForegroundColor Yellow
    python -m playwright install chromium
}
Write-Host "[OK] Browser ready" -ForegroundColor Green

# Start
Write-Host ""
Write-Host "============================================" -ForegroundColor DarkCyan
Write-Host "  Starting server..." -ForegroundColor White
Write-Host ""
Write-Host "  Open: " -NoNewline
Write-Host "http://127.0.0.1:8000" -ForegroundColor Yellow
Write-Host "  Press Ctrl+C to stop" -ForegroundColor Gray
Write-Host "============================================" -ForegroundColor DarkCyan
Write-Host ""

Start-Process "http://127.0.0.1:8000"

python -m uvicorn main:app --host 0.0.0.0 --port 8000

Read-Host "`nServer stopped. Press Enter to close"
