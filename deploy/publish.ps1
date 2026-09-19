<#
  Đóng gói và copy ứng dụng vào thư mục site IIS.

  Cách dùng (PowerShell, chạy trong thư mục dự án):
    .\deploy\publish.ps1 -Target C:\inetpub\dvt-dashboard
  Tùy chọn:
    -SkipFrontendBuild   dùng frontend/dist đã build sẵn
    -SkipVenv            không tạo/cập nhật virtualenv (khi chỉ đổi code)
  Script KHÔNG ghi đè .env đã có ở thư mục đích.
#>
param(
    [string]$Target = "C:\inetpub\dvt-dashboard",
    [switch]$SkipFrontendBuild,
    [switch]$SkipVenv
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Write-Host "Nguồn: $root`nĐích : $Target"

if (-not $SkipFrontendBuild) {
    Write-Host "== Build frontend"
    Push-Location "$root\frontend"
    npm install --no-audit --no-fund
    npm run build
    Pop-Location
}
if (-not (Test-Path "$root\frontend\dist\index.html")) { throw "Thiếu frontend\dist\index.html - hãy build frontend" }

Write-Host "== Copy mã nguồn"
New-Item -ItemType Directory -Force -Path $Target, "$Target\logs" | Out-Null
robocopy "$root\app" "$Target\app" /MIR /XD __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS | Out-Null
robocopy "$root\frontend\dist" "$Target\static" /MIR /NFL /NDL /NJH /NJS | Out-Null
Copy-Item "$root\requirements.txt" "$Target\requirements.txt" -Force
if (-not (Test-Path "$Target\.env")) {
    Copy-Item "$root\.env.example" "$Target\.env"
    Write-Warning "Đã tạo $Target\.env từ .env.example - HÃY ĐIỀN thông tin thật (JWT_SECRET, POSTGRES_DSN, SQLSERVER_*)"
}

(Get-Content "$root\deploy\web.config.template" -Raw -Encoding UTF8).Replace("{{SITE_ROOT}}", $Target) |
    Set-Content "$Target\web.config" -Encoding UTF8

if (-not $SkipVenv) {
    Write-Host "== Virtualenv + dependencies"
    if (-not (Test-Path "$Target\.venv\Scripts\python.exe")) { python -m venv "$Target\.venv" }
    & "$Target\.venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
    & "$Target\.venv\Scripts\python.exe" -m pip install --quiet -r "$Target\requirements.txt"
}

Write-Host "`nXong. Các bước tiếp theo xem docs\IIS-DEPLOY.md (tạo site/app pool, cấp quyền, điền .env)."
