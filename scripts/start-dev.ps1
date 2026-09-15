# Khoi dong backend (FastAPI) + frontend (Vite) cho DH-DVT, chay nen (khong hien cua so).
# Duoc goi tu dong khi dang nhap Windows qua Task Scheduler (task "DH-DVT AutoStart").

$ErrorActionPreference = "Stop"

$root = "D:\Source\DH-DVT"
$logDir = Join-Path $root "scripts\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Test-PortListening($port) {
    return (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) -ne $null
}

# Backend (port 8010)
if (-not (Test-PortListening 8010)) {
    Start-Process -FilePath "$root\.venv\Scripts\python.exe" `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8010" `
        -WorkingDirectory $root `
        -WindowStyle Hidden `
        -RedirectStandardOutput "$logDir\backend.out.log" `
        -RedirectStandardError "$logDir\backend.err.log"
}

# Frontend (port 5173)
if (-not (Test-PortListening 5173)) {
    Start-Process -FilePath "D:\Program Files\nodejs\node.exe" `
        -ArgumentList "D:\Program Files\nodejs\node_modules\npm\bin\npx-cli.js", "vite", "--port", "5173", "--host", "127.0.0.1" `
        -WorkingDirectory "$root\frontend" `
        -WindowStyle Hidden `
        -RedirectStandardOutput "$logDir\frontend.out.log" `
        -RedirectStandardError "$logDir\frontend.err.log"
}
