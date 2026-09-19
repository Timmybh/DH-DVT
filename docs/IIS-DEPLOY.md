# Triển khai lên IIS

Kiến trúc: **IIS** (HTTPS, cổng 443) → **HttpPlatformHandler** → tiến trình `uvicorn` (FastAPI). Cùng một tiến trình phục vụ
API (`/api/*`) và giao diện React (thư mục `static`). Dữ liệu cache: **PostgreSQL**. Nguồn: **SQL Server eGMF** (10.8.0.72).

## 1. Yêu cầu trên máy chủ

| Thành phần | Ghi chú |
|---|---|
| Windows Server + IIS | Bật role *Web Server (IIS)* |
| [HttpPlatformHandler 1.2](https://www.iis.net/downloads/microsoft/httpplatformhandler) | Module IIS chạy tiến trình Python |
| Python 3.12 (64-bit, cài **for all users**) | Có trong PATH của tài khoản chạy script publish |
| Node.js LTS | Chỉ cần ở máy build frontend (có thể build ở máy dev rồi copy `frontend\dist`) |
| Microsoft ODBC Driver 18 for SQL Server | Để đọc eGMF |
| PostgreSQL (>= 14) | DB `dhdvt` + role `dhdvt` (xem README) |
| Mạng | Máy chủ IIS phải truy cập được `10.8.0.72:1433` (SQL Server) và PostgreSQL |

## 2. Publish

```powershell
cd D:\Source\DH-DVT
.\deploy\publish.ps1 -Target C:\inetpub\dvt-dashboard
```

Script build frontend, copy `app/` + `static/`, sinh `web.config`, tạo virtualenv và cài thư viện. Lần đầu nó tạo
`C:\inetpub\dvt-dashboard\.env` từ `.env.example` — **mở file và điền**:

- `JWT_SECRET` — chuỗi ngẫu nhiên dài (bắt buộc đổi)
- `POSTGRES_DSN` — chuỗi kết nối Postgres thật
- `SQLSERVER_USER` / `SQLSERVER_PASSWORD` — tài khoản đọc eGMF (nên dùng tài khoản **chỉ đọc**)

Cập nhật lần sau: chạy lại script (không ghi đè `.env`); thêm `-SkipVenv` nếu chỉ đổi code.

## 3. Tạo Application Pool và Site

1. **Application Pool** `dvt-dashboard`: *.NET CLR version = No Managed Code*, Pipeline = Integrated.
   - Advanced Settings: **Start Mode = AlwaysRunning**, **Idle Time-out = 0**, *Regular Time Interval* = 0 (hoặc đặt giờ
     không trùng giờ đồng bộ). Lý do: job đồng bộ eGMF chạy nền trong tiến trình; nếu pool bị idle-stop thì lịch 05:00 không chạy.
     (Khi tiến trình khởi động lại, job tự bắt kịp lượt đã lỡ trong ngày.)
2. **Site** `dvt-dashboard`: Physical path = `C:\inetpub\dvt-dashboard`, Application pool ở trên, binding HTTPS + chứng chỉ.
   - Trang **Site → Advanced Settings → Preload Enabled = True**.
3. **Quyền thư mục**: cấp *Modify* cho `IIS AppPool\dvt-dashboard` trên `C:\inetpub\dvt-dashboard\logs`, và *Read & Execute*
   trên toàn bộ thư mục site (kể cả `.venv` — nếu Python cài ở `C:\Program Files` thì pool cũng cần đọc thư mục đó, mặc định đã có).
4. Đặt **Process Model → Identity** = `ApplicationPoolIdentity` (hoặc tài khoản dịch vụ riêng nếu Postgres dùng Windows auth).

## 4. Kiểm tra

- `https://<host>/api/health` → `{"status":"ok"}`
- Mở `https://<host>/`, đăng nhập `admin` / `Admin@123` rồi **đổi mật khẩu ngay** (Người dùng → Đặt lại mật khẩu).
- Vào **Sync Log** → *Đồng bộ eGMF ngay*, và nhập file kế hoạch SX (`.xlsb`).
- Log tiến trình: `C:\inetpub\dvt-dashboard\logs\stdout*.log`.

## 5. Bảo mật khi lên môi trường thật

- Đổi `JWT_SECRET`, đổi mật khẩu `admin` mặc định.
- Bật **Google SSO** (menu *Đăng nhập / SSO*: Client ID, domain cho phép), tạo người dùng đúng email; sau khi SSO ổn định thì tắt
  "đăng nhập nội bộ (dự phòng)". Mọi lượt đăng nhập đều nằm trong Audit.
- Chỉ mở HTTPS; SQL Server cấp tài khoản read-only cho các bảng `LCD_Truc_Quan_XiNghiep_*` và `GDXN_XiNghiep`.

## 6. Xử lý sự cố

| Triệu chứng | Nguyên nhân thường gặp |
|---|---|
| HTTP 502.3 / 500.0 khi mở site | Sai `processPath` trong `web.config`, thiếu `.venv`, hoặc tiến trình lỗi khi khởi động → xem `logs\stdout*.log` |
| Trang trắng, `/assets/*` 404 | Thiếu thư mục `static` (chạy lại publish) |
| Đồng bộ eGMF FAILED "Không kết nối được SQL Server" | Firewall/VPN từ máy IIS tới 10.8.0.72:1433; chi tiết kỹ thuật trong Sync Run |
| Đồng bộ FAILED "từ chối đăng nhập" | Sai `SQLSERVER_USER/PASSWORD` trong `.env` |
| Upload file kế hoạch lỗi 404.13 | Tăng `maxAllowedContentLength` trong `web.config` |
