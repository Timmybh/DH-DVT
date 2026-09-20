<#
  Tạo Application Pool + Website IIS cho DVT Dashboard, cấp quyền thư mục và kiểm tra /api/health.
  Chạy bằng PowerShell "Run as Administrator", SAU KHI đã chạy deploy\publish.ps1.

  Ví dụ:
    .\deploy\setup-iis.ps1 -SiteRoot C:\inetpub\dvt-dashboard -Port 8080
    .\deploy\setup-iis.ps1 -Port 443 -HostHeader dvt.congty.vn -CertThumbprint ABCDEF...   # thêm binding HTTPS
    .\deploy\setup-iis.ps1 -InstallIIS                                                    # bật luôn tính năng IIS nếu chưa có

  Script idempotent: chạy lại sẽ cập nhật cấu hình thay vì tạo trùng.
  HttpPlatformHandler phải được cài trước (https://www.iis.net/downloads/microsoft/httpplatformhandler).
#>
#Requires -RunAsAdministrator
param(
    [string]$SiteRoot = "C:\inetpub\dvt-dashboard",
    [string]$SiteName = "dvt-dashboard",
    [string]$PoolName = "dvt-dashboard",
    [int]$Port = 8080,
    [string]$HostHeader = "",
    [string]$CertThumbprint = "",
    [switch]$InstallIIS
)
$ErrorActionPreference = "Stop"

function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "LỖI: $msg" -ForegroundColor Red; exit 1 }

Step "Kiểm tra IIS"
if (-not (Get-Service W3SVC -ErrorAction SilentlyContinue)) {
    if (-not $InstallIIS) { Fail "Chưa cài IIS. Chạy lại với -InstallIIS hoặc bật tính năng 'Internet Information Services'." }
    if (Get-Command Install-WindowsFeature -ErrorAction SilentlyContinue) {
        Install-WindowsFeature Web-Server, Web-Mgmt-Console | Out-Null
    } else {
        Enable-WindowsOptionalFeature -Online -FeatureName IIS-WebServerRole, IIS-ManagementConsole -All | Out-Null
    }
}
Import-Module WebAdministration

Step "Kiểm tra HttpPlatformHandler"
$hph = Join-Path $env:windir "System32\inetsrv\httpPlatformHandler.dll"
if (-not (Test-Path $hph)) {
    Fail "Chưa cài HttpPlatformHandler v1.2 (thiếu $hph). Tải và cài từ https://www.iis.net/downloads/microsoft/httpplatformhandler rồi chạy lại."
}

Step "Kiểm tra thư mục site"
foreach ($f in @("web.config", ".venv\Scripts\python.exe", "static\index.html", "app\main.py", ".env")) {
    if (-not (Test-Path (Join-Path $SiteRoot $f))) { Fail "Thiếu $SiteRoot\$f — hãy chạy .\deploy\publish.ps1 -Target $SiteRoot trước (và điền .env)." }
}
New-Item -ItemType Directory -Force -Path (Join-Path $SiteRoot "logs") | Out-Null
$envText = Get-Content (Join-Path $SiteRoot ".env") -Raw
if ($envText -match "JWT_SECRET=change-me-in-env") { Write-Warning "JWT_SECRET trong .env vẫn là giá trị mặc định — hãy đặt chuỗi ngẫu nhiên >= 32 ký tự." }
if ($envText -match "SQLSERVER_PASSWORD=\s*(\r?\n|$)") { Write-Warning "SQLSERVER_PASSWORD trong .env đang trống — đồng bộ eGMF sẽ thất bại." }

Step "Application Pool '$PoolName'"
if (-not (Test-Path "IIS:\AppPools\$PoolName")) { New-WebAppPool -Name $PoolName | Out-Null }
$pool = "IIS:\AppPools\$PoolName"
Set-ItemProperty $pool -Name managedRuntimeVersion -Value ""            # No Managed Code
Set-ItemProperty $pool -Name managedPipelineMode -Value "Integrated"
Set-ItemProperty $pool -Name startMode -Value "AlwaysRunning"           # job đồng bộ nền cần tiến trình luôn sống
Set-ItemProperty $pool -Name processModel.idleTimeout -Value ([TimeSpan]::Zero)
Set-ItemProperty $pool -Name recycling.periodicRestart.time -Value ([TimeSpan]::Zero)
Set-ItemProperty $pool -Name processModel.identityType -Value "ApplicationPoolIdentity"

Step "Website '$SiteName' (cổng $Port)"
if (-not (Get-Website -Name $SiteName -ErrorAction SilentlyContinue)) {
    New-Website -Name $SiteName -PhysicalPath $SiteRoot -ApplicationPool $PoolName -Port $Port -HostHeader $HostHeader | Out-Null
} else {
    Set-ItemProperty "IIS:\Sites\$SiteName" -Name physicalPath -Value $SiteRoot
    Set-ItemProperty "IIS:\Sites\$SiteName" -Name applicationPool -Value $PoolName
}
Set-ItemProperty "IIS:\Sites\$SiteName" -Name applicationDefaults.preloadEnabled -Value $true

if ($CertThumbprint) {
    Step "Binding HTTPS"
    $binding = Get-WebBinding -Name $SiteName -Protocol https -ErrorAction SilentlyContinue
    if (-not $binding) { New-WebBinding -Name $SiteName -Protocol https -Port 443 -HostHeader $HostHeader -SslFlags 1 | Out-Null }
    (Get-WebBinding -Name $SiteName -Protocol https).AddSslCertificate($CertThumbprint, "My")
}

Step "Phân quyền thư mục cho IIS AppPool\$PoolName"
icacls $SiteRoot /grant "IIS AppPool\${PoolName}:(OI)(CI)RX" /T /C | Out-Null
icacls (Join-Path $SiteRoot "logs") /grant "IIS AppPool\${PoolName}:(OI)(CI)M" /T /C | Out-Null

Step "Khởi động và kiểm tra"
Restart-WebAppPool -Name $PoolName
Start-Website -Name $SiteName
$url = "http://localhost:$Port/api/health"
$ok = $false
for ($i = 0; $i -lt 20 -and -not $ok; $i++) {
    Start-Sleep -Seconds 3
    try { $ok = (Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 10).StatusCode -eq 200 } catch { }
}
if ($ok) {
    Write-Host "`nOK: $url trả về 200. Mở http://localhost:$Port/ và đăng nhập (đổi mật khẩu admin mặc định ngay)." -ForegroundColor Green
} else {
    Fail "Không gọi được $url. Xem log tiến trình: $SiteRoot\logs\stdout*.log và Event Viewer (Windows Logs > Application)."
}
