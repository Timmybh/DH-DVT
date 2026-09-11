# DH-DVT — Dashboard điều hành

Dashboard điều hành cho giám đốc: theo dõi tiến độ SX, đóng gói, giao hàng, QA,
vướng mắc; đồ thị kế hoạch vs thực hiện của 3 xí nghiệp và tổng công ty; 10
chỉ số gauge cấu hình được qua màn hình "Cấu hình KPI".

Dữ liệu nguồn nằm trên SQL Server (giống traceabilityportal). Một job ETL
(thủ công hoặc lịch hàng ngày) đọc, tính toán và cache sang Postgres để
dashboard truy vấn nhanh.

## Kiến trúc

```
app/            Backend FastAPI
  api/          auth, users (admin), dashboard, etl
  core/         config, JWT/security
  db/           SQLAlchemy session (Postgres)
  models/       User, Factory, KpiConfig, GaugeMetric, PlanProgress,
                IndicatorStatus, IssueItem, ImportJob, ImportJobConfig
  schemas/      Pydantic request/response
  services/
    etl.py      Đồng bộ SQL Server -> Postgres (mock khi chưa có SQLSERVER_*)
    seed.py     Seed database (xí nghiệp, KPI mặc định, tài khoản admin)

frontend/       React + Vite + Tailwind (SPA)
  src/pages/          Login, Dashboard
  src/pages/admin/    Users, ImportJob
  src/components/     Sidebar (chỉ số Xanh/Đỏ), PlanChart, Gauge, KpiConfigModal
```

## Cài đặt backend

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
```

Tạo file `.env` từ `.env.example`. Database Postgres cache (`dhdvt`) tạo bằng:

```powershell
$env:PGBIN = "D:\Program Files\PostgreSQL\18\bin"
& "$env:PGBIN\psql.exe" -U postgres -h localhost -c "CREATE ROLE dhdvt LOGIN PASSWORD 'dhdvt';"
& "$env:PGBIN\psql.exe" -U postgres -h localhost -c "CREATE DATABASE dhdvt OWNER dhdvt;"
```

Chạy backend (tự tạo bảng + seed dữ liệu mặc định khi khởi động):

```bash
uvicorn app.main:app --reload --port 8010
```

Tài khoản mặc định sau khi seed: `admin` / `Admin@123`.

Khi có thông tin kết nối SQL Server thật, điền `SQLSERVER_*` trong `.env` và
thay query mẫu trong `app/services/etl.py` (`run_sync`) bằng query thật theo
schema traceabilityportal.

## Cài đặt frontend

```bash
cd frontend
npm install
npm run dev
```

Mặc định chạy ở `http://localhost:5173`, proxy `/api` sang backend ở
`http://127.0.0.1:8010` (chỉnh trong `frontend/vite.config.ts` nếu đổi port).

## Chạy test

```bash
pytest
```
