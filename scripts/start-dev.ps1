# Khởi động backend DVT (FastAPI, cổng 8010) chạy nền; backend đã phục vụ luôn giao diện đã build (frontend\dist).
# Dev giao diện riêng: cd frontend; npm run dev (Vite, cổng 5173, proxy /api -> 8010).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root "scripts\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (-not (Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath "$root\.venv\Scripts\python.exe" `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8010" `
        -WorkingDirectory $root -WindowStyle Hidden `
        -RedirectStandardOutput "$logDir\backend.out.log" -RedirectStandardError "$logDir\backend.err.log"
    Write-Host "Đã khởi động backend: http://127.0.0.1:8010"
} else {
    Write-Host "Backend đã chạy ở cổng 8010"
}
