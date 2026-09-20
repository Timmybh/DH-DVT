# DVT — Bảng điều hành (Dashboard điều hành)

Dashboard cho Ban Tổng giám đốc theo dõi tình hình công ty: **Doanh thu/Thực hiện, Tiến độ thực hiện, Nhân sự, Cảnh báo**,
xem được ở góc nhìn **Tổng công ty** (cộng dồn từ đơn vị) hoặc từng **Xí nghiệp**. Backend Python (FastAPI) + PostgreSQL,
frontend React, chạy trên **IIS**. Thiết kế tham chiếu: [`docs/DVT_Planning_Core_Design_Handoff.md`](docs/DVT_Planning_Core_Design_Handoff.md) và bản chỉnh sửa [`docs/DVT_Unplanned_Design_Correction.md`](docs/DVT_Unplanned_Design_Correction.md) (Planning status, Factory assignment, Mapping status là **ba chiều độc lập**).

## Đã có (theo handoff)

| Mục handoff | Nội dung | Trạng thái |
|---|---|---|
| §28 Dashboard sidebar phải | Vùng trên "Tin tốt", vùng dưới "Cảnh báo" (WARNING cam / CRITICAL đỏ nhấp nháy), bấm để drill-down | Có |
| §21–22 Roll-up | Tổng công ty = cộng dồn XN; chọn XN1/XN2/XN3 xem riêng | Có |
| §27 Sync Log | Mỗi lần đồng bộ là 1 Sync Run (`SYNC-YYYYMMDD-NNNN`), trạng thái RUNNING/SUCCEEDED/PARTIAL/FAILED, chi tiết khớp/chưa khớp/lỗi, Trace ID, retry tạo run mới | Có |
| §34A Đăng nhập & phân quyền | Google SSO (cấu hình trong UI) + đăng nhập nội bộ dự phòng; vai trò Admin/Planner/Viewer → permission; backend tự kiểm quyền; Audit log | Có (SSO cần Client ID thật để thử) |
| Đồng bộ định kỳ | Job nền 1 lần/ngày đọc eGMF → Postgres (giờ cấu hình ở Sync Log) | Có |
| §29–30 (một phần) | Sync Run lưu số liệu theo phiên, dòng lỗi/không khớp giữ chi tiết | Một phần |
| §2.1, §14 Edit Mode | Phiên soạn thảo độc quyền: `EditSessionId` do backend cấp, chỉ 1 phiên ACTIVE (ràng buộc DB), heartbeat + hết hạn, Force Unlock (Admin), khôi phục phiên của chính mình, backend kiểm tra lại session ở mọi API ghi | Có |
| §3–7 Draft / Undo | Draft State phía frontend (thao tác + Undo/Redo 100 bước + Revert All, lưu cục bộ để khôi phục khi mất mạng/đóng tab), kéo-thả PO từ Unplanned vào Planned, di chuyển dòng, virtual sequence per chuyền | Có (chưa có Merge/Split) |
| §8–11 Công thức / Recheck | Sửa ô tính toán -> OVERRIDE ("!" cam) + Return to Auto Calculate; công thức tối thiểu `BEGIN = PREVIOUS_SEQUENCE.END + 1 ngày làm việc`; Recheck All Plan toàn kế hoạch (ERROR/WARNING/PASS) gắn với đúng DraftRevision; Commit bị chặn nếu chưa Recheck hoặc có ERROR | Có (engine công thức tổng quát + kiểm tra vòng phụ thuộc: chưa) |
| §12 Validation panel | Panel nổi Collapsed/Floating/Expanded, lọc Tất cả/Lỗi/Cảnh báo/Ghi đè, bấm để cuộn tới đúng dòng | Có |
| §15–16 Lịch làm việc | Company → XN → Chuyền, WORKING/OFF/OVERTIME, `IS_WORKING_DAY / NEXT / PREVIOUS / ADD_WORKING_DAYS`, `OFF_DAYS` half-up; màn hình quản lý + xem lịch kế thừa | Có |
| §17–18 Dồn chuyền / Chuyển chuyền | Cấu trúc thật (`line_assignments`, `transfer` + ngày hiệu lực) parse từ ký hiệu `4 + 5 + 9`, `1 ==> 2`; kiểm tra ngày hiệu lực & chuyền đích; chuỗi chỉ để hiển thị | Dữ liệu + kiểm tra (chưa có UI tạo mới) |
| §19–21 Phiên bản | Đặt tên `2026.W38.Master.v01[.f01]`, Commit bất biến, Issue tách riêng (chỉ Recheck PASS, phiên bản cũ -> SUPERSEDED), So sánh phiên bản theo 11 loại thay đổi | Có |
| Unplanned (Correction) | Panel dưới màn Planning, bộ lọc XN(All/XN1-3/Unassigned)+Quick+Customer/Season/Sport/PO/Style/Model/Free-text giữ qua Edit Session, Case A giữ XN / Case B bắt buộc chọn XN, Pending Drop Confirm/Cancel | Có |
| §22–33 (Actual sync, mapping tables, snapshot, retention, carry-forward) | Đồng bộ Actual theo XN/Line, bảng mapping, năm tài chính | **Chưa làm** |

## Nguồn dữ liệu

- **Doanh thu XN** (kế hoạch/thực hiện/còn lại theo ngày-tháng-năm): SQL Server eGMF, bảng `LCD_Truc_Quan_XiNghiep_DoanhThu_Ngay/Thang/Nam`
  + `GDXN_XiNghiep` — chính là màn hình ERP "DOANH THU XÍ NGHIỆP". Dữ liệu do người dùng khai báo tay nên dòng sai định dạng
  (VD `Nam='1'`) được ghi vào Sync Run là *chưa khớp* để sửa tại nguồn.
- **Tiến độ (PO) & Nhân sự**: nhập file Excel kế hoạch SX (`.xlsb/.xlsx`, sheet KẾ HOẠCH / PO MỚI / PO MAY XONG / ĐÃ XUẤT / LAO ĐỘNG)
  ở màn hình Sync Log. Quy tắc PO: `EHD/CHD ≤ -1 ngày` = nguy cơ trễ; ghi chú "chưa có vải/phụ liệu" = thiếu NPL; `ADVANCE` = sớm.
- Nếu chưa nối được SQL Server, có thể nạp **doanh thu MẪU** (`scripts\seed_demo_revenue.py`); dashboard hiện banner cảnh báo và số mẫu
  tự bị xóa khi đồng bộ eGMF thành công.

## Chạy trên máy dev

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
copy .env.example .env      # điền SQLSERVER_USER / SQLSERVER_PASSWORD, POSTGRES_DSN
# DB Postgres (1 lần): CREATE ROLE dhdvt LOGIN PASSWORD 'dhdvt'; CREATE DATABASE dhdvt OWNER dhdvt;
cd frontend; npm install; npm run build; cd ..
.\scripts\start-dev.ps1     # http://127.0.0.1:8010
```

Tài khoản mặc định (tạo khi khởi động lần đầu): `admin` / `Admin@123` — hệ thống **bắt buộc đổi mật khẩu** ở lần đăng nhập đầu. Đổi schema lớn khi dev:
`.venv\Scripts\python.exe scripts\reset_db.py --yes` (xóa toàn bộ cache Postgres).

Dev giao diện riêng: `cd frontend; npm run dev` (Vite :5173, proxy `/api` → :8010). Test: `.venv\Scripts\python.exe -m pytest`.

## Triển khai IIS

`.\deploy\publish.ps1 -Target C:\inetpub\dvt-dashboard` rồi làm theo [`docs/IIS-DEPLOY.md`](docs/IIS-DEPLOY.md).

## Cấu trúc

```
app/api        auth, admin (users/SSO/audit), sync, dashboard, planning
app/core       config, security, permissions (role -> permission)
app/models     core (User, Factory, SsoConfig, SyncConfig, AuditLog) · data (SyncRun, Revenue*, PlanRow, LaborHeadcount)
app/services   planning_engine (draft/recheck/compare), planning_service (phiên, phiên bản, unplanned), calendar, sso, egmf (đồng bộ SQL Server), plan_import (Excel), dashboard (tổng hợp), signals (tin tốt/cảnh báo), scheduler, rules
frontend/src   pages (Dashboard, Planning, Versions, SyncLog, SyncDetail, ChangePassword, admin/*), components (Revenue/Progress/Hr sections, SignalsSidebar, DrillDrawer)
deploy/        web.config.template, publish.ps1, setup-iis.ps1
```
