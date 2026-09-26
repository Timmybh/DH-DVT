# Roadmap V1 — Production Runbook (Backup / Restore / Retention / Rollback)

Phạm vi: các module Roadmap (Scenario → Run → Proposal → Action Plan → Cost Evidence → Decision Package) trên kiến trúc đã mô tả ở
[IIS-DEPLOY.md](IIS-DEPLOY.md): IIS → `uvicorn`/FastAPI → **PostgreSQL** (`dhdvt`). Tài liệu này là **runbook vận hành**, không phải script tự động;
mọi lệnh dưới đây là ví dụ — kiểm tra đường dẫn/tên máy/tài khoản trước khi chạy.

> **Nguyên tắc số 1:** dữ liệu governance của Roadmap (rule, evidence, plan, package, history, audit) là **bằng chứng** — **không DELETE/UPDATE tay để "sửa"**.
> Sai thì dùng workflow của hệ thống: `RETIRE` / `ARCHIVE` / *version mới*. Không restore đè lên production để "xóa dấu vết".

---

## 1. Bảng cần backup

| Nhóm | Bảng | Ghi chú |
|---|---|---|
| **Roadmap governance (bắt buộc)** | `roadmap_scenarios`, `roadmap_scenario_versions`, `roadmap_milestones`, `roadmap_targets`, `roadmap_technology_links`, `roadmap_runs`, `roadmap_run_target_results`, `roadmap_proposals`, `roadmap_proposal_decisions`, `roadmap_status_history` | Run + snapshot **bất biến** — không tái tạo được nếu mất (nguồn ERP đã đổi) |
| **Rule / Evidence** | `roadmap_rules`, `roadmap_executable_rules`, `roadmap_cost_evidence`, `roadmap_asset_refs` | Productivity/giá do business khai báo + duyệt |
| **Action Plan / Package** | `roadmap_action_plans`, `roadmap_action_plan_versions`, `roadmap_action_plan_items`, `roadmap_decision_packages`, `roadmap_package_bindings` | Coverage/`package_json` đóng băng + `package_fingerprint` |
| **Audit & người dùng (bắt buộc)** | `audit_logs`, `users` | `audit_logs` là **append-only** (mục 4) |
| **Master/ngữ cảnh Roadmap tham chiếu** | `machine_types`, `machine_models`, `future_technology_candidates`, `future_technology_evidence`, `factories`, `labor_standards`, `labor_standard_grade_details`, `machine_capacities` | FK/ngữ cảnh available labor/machine |
| **Nguồn đồng bộ (cache eGMF)** | `revenue_daily`, `revenue_monthly`, `revenue_yearly`, `po_pack_daily`, `po_progress`, `sync_runs` | Có thể đồng bộ lại từ eGMF nhưng **lịch sử `sync_runs`** và snapshot Run mới là bằng chứng |

**Khuyến nghị:** backup **toàn bộ DB** `dhdvt` (không chỉ bảng Roadmap) để giữ nguyên vẹn FK/sequence.

## 2. Backup PostgreSQL (ví dụ, Windows)

```powershell
# Backup định dạng custom (nén, restore chọn lọc được) — chạy bằng tài khoản có quyền đọc DB
$stamp = Get-Date -Format "yyyyMMdd_HHmm"
& "C:\Program Files\PostgreSQL\16\bin\pg_dump.exe" -h localhost -p 5432 -U dhdvt -d dhdvt -Fc -f "D:\backup\dhdvt_$stamp.dump"
# Mật khẩu: dùng biến môi trường PGPASSWORD hoặc file pgpass.conf — KHÔNG ghi mật khẩu vào script/lịch sử lệnh.
```

Chỉ bảng Roadmap + audit (bổ sung, không thay thế backup toàn DB):

```powershell
& "...\pg_dump.exe" -h localhost -U dhdvt -d dhdvt -Fc -t "roadmap_*" -t audit_logs -t users -f "D:\backup\dhdvt_roadmap_$stamp.dump"
```

Lịch đề xuất: **hằng ngày** (giữ 7) + **hằng tuần** (giữ 4) + **hằng tháng** (giữ 12) + **bắt buộc trước mỗi lần deploy** (mục 6). Lưu bản sao ở vị trí **khác máy chủ DB**;
kiểm tra định kỳ (mỗi quý) bằng quy trình restore thử ở mục 3.

## 3. Restore validation (KHÔNG restore đè production)

Luôn restore vào **DB thử riêng**, không bao giờ `--clean` lên `dhdvt` đang chạy:

```powershell
& "...\createdb.exe" -h localhost -U postgres dhdvt_restore_check
& "...\pg_restore.exe" -h localhost -U postgres -d dhdvt_restore_check --no-owner "D:\backup\dhdvt_YYYYMMDD_HHMM.dump"
```

Checklist xác nhận backup dùng được:

1. **Đếm dòng** khớp (hoặc ≥ tại thời điểm backup) cho các bảng ở mục 1: `SELECT count(*) FROM roadmap_runs;` … so với ghi chú lúc backup.
2. **Sequence/PK** không bị lệch: `SELECT max(id) FROM roadmap_scenarios;` so với `SELECT last_value FROM roadmap_scenarios_id_seq;`.
3. **Toàn vẹn snapshot/fingerprint** (chỉ đọc) trỏ vào DB thử:
   ```powershell
   $env:POSTGRES_DSN = "postgresql+psycopg2://dhdvt:<mật khẩu>@localhost:5432/dhdvt_restore_check"
   .\.venv\Scripts\python.exe scripts\roadmap_integrity_check.py     # exit 0 = OK, 1 = có lỗi (in chi tiết JSON)
   ```
   Script kiểm: `package_fingerprint` + tái định giá từ snapshot cho mọi Decision Package đã đóng băng, và coverage đóng băng của mọi Action Plan version không còn DRAFT.
4. **Audit**: `SELECT count(*), max(at) FROM audit_logs;` không nhỏ hơn thời điểm backup; `SELECT count(*) FROM audit_logs WHERE action LIKE 'ROADMAP%';`.
5. **Ứng dụng đọc được**: trỏ một instance thử (`POSTGRES_DSN` DB thử, cổng khác) và mở trang Roadmap → *Production Readiness*, *Source Data Health*, mở 1 Decision Package đã APPROVED và so `package_fingerprint`.
6. Ghi biên bản (ngày, file backup, người thực hiện, kết quả) → xóa DB thử: `dropdb dhdvt_restore_check`.

## 4. Audit log — chính sách append-only

- `audit_logs` **không bao giờ bị xóa/sửa** bởi ứng dụng hoặc thao tác vận hành (kể cả dòng của test/UAT/smoke). Nhận diện dữ liệu test bằng `username`/prefix (`uat9_*`, `smoke_*`, `UAT9-*`), **không** xóa.
- Không cấp quyền `DELETE/UPDATE/TRUNCATE` trên `audit_logs` cho tài khoản ứng dụng ngoài mức cần thiết; tài khoản quản trị DB thao tác phải có phê duyệt và ghi biên bản.
- Lịch sử trạng thái (`roadmap_status_history`, `roadmap_proposal_decisions`) cũng **append-only**.

## 5. Retention (khuyến nghị)

| Dữ liệu | Khuyến nghị |
|---|---|
| `audit_logs`, `roadmap_status_history` | **Giữ vĩnh viễn** (hoặc theo chính sách công ty/pháp lý). Nếu phải giảm dung lượng: **archive nguyên trạng** sang kho lưu trữ bất biến (dump + hash), không xóa dòng khỏi DB khi chưa có phê duyệt bằng văn bản |
| Roadmap Run/Snapshot, Action Plan, Decision Package, Cost Evidence, Rule | Giữ vĩnh viễn — là bằng chứng quyết định (bất biến). Không hard-delete; dùng `ARCHIVED`/`RETIRED` |
| Backup DB | 7 ngày + 4 tuần + 12 tháng (điều chỉnh theo quy định); bản trước deploy giữ ≥ 30 ngày |
| Bảng nguồn cache (`revenue_*`, `po_*`) | Theo chính sách đồng bộ hiện có; không xóa lịch sử `sync_runs` |
| Log ứng dụng (`{site}\logs\stdout*`) | 30–90 ngày; giữ riêng dòng `ROADMAP_*` nếu có nhu cầu điều tra |

Theo dõi tăng trưởng: `SELECT pg_size_pretty(pg_total_relation_size('audit_logs'));` — đưa vào review 7 ngày sau go-live.

## 6. Pre-deploy backup

Trước **mỗi** lần `publish.ps1`: (1) backup toàn DB (mục 2), ghi tên file vào ticket deploy; (2) chạy `scripts\roadmap_integrity_check.py` trên DB hiện tại và lưu kết quả;
(3) ghi lại số dòng các bảng governance (mục 1) để so sánh sau deploy.

## 7. Rollback

**Ứng dụng (code):** publish lại phiên bản trước bằng `deploy\publish.ps1` (bản build/tag trước đó); `.env` không bị ghi đè.
Schema của Roadmap chỉ **thêm bảng mới** (không `ALTER`/`DROP` bảng cũ) nên chạy lại bản ứng dụng cũ trên DB mới **không làm hỏng dữ liệu** (bảng thừa bị bỏ qua).

**Dữ liệu (DB) — nguyên tắc:**
1. **Không rollback/xóa business history tùy tiện.** Không `DELETE`/`TRUNCATE`/`DROP` bảng `roadmap_*`, `audit_logs`, `users` trên production để “quay lại”.
2. Dữ liệu nhập sai → dùng workflow: `RETIRE` evidence/rule (kèm lý do), `ARCHIVE` plan/package/scenario (kèm lý do), tạo **version mới**. Package đã đóng băng không đổi; evidence retire sau freeze chỉ hiện cảnh báo.
3. Chỉ restore DB khi mất/hỏng dữ liệu: restore vào **DB mới**, chạy checklist mục 3, so sánh với production hiện tại; việc **cut-over** (đổi `POSTGRES_DSN`) cần phê duyệt của owner nghiệp vụ + IT, ghi biên bản. Dữ liệu phát sinh sau thời điểm backup phải được đối soát và nhập lại theo workflow (không ghi đè audit).
4. `scripts\reset_db.py` **chỉ dành cho dev** — tuyệt đối không chạy trên production (xóa toàn bộ bảng).

## 8. Trách nhiệm (Disaster Recovery)

| Vai trò | Trách nhiệm |
|---|---|
| **Owner nghiệp vụ Roadmap** | Xác nhận dữ liệu rule/evidence; phê duyệt quyết định restore/cut-over; xác nhận sau restore rằng Decision Package/Action Plan trọng yếu đúng |
| **DBA / IT vận hành** | Lịch backup, lưu trữ ngoài máy chủ, restore thử hằng quý, bảo vệ `audit_logs`, quyền DB |
| **Dev/bảo trì ứng dụng** | Publish/rollback ứng dụng, chạy `roadmap_integrity_check.py`, điều tra lỗi theo log `dvt.roadmap` (mục 9) |
| **Approver (≥ 2 người)** | Duyệt rule/evidence/plan/package; không tự duyệt nội dung mình đã đưa vào review (four-eyes) |

## 9. Quan sát vận hành (logging tối thiểu)

Logger `dvt.roadmap` (stdout của tiến trình `uvicorn`, IIS: `{site}\logs\stdout*`). Các sự kiện cần theo dõi/cảnh báo:

| Sự kiện | Ý nghĩa |
|---|---|
| `ROADMAP_RUN_FAILED` (kèm stack trace) | Run lỗi ngoài dự kiến (5xx) — điều tra ngay |
| `ROADMAP_RUN_SOURCE_WARNINGS ... flags=` | Run chạy với cờ chất lượng nguồn (PARTIAL_SOURCE_COVERAGE, SOURCE_STALE_OR_LAST_SYNC_FAILED, INVALID_SOURCE_DATE …) |
| `ROADMAP_ACTION_PLAN_VERIFY_FAILED trace=…` / `ROADMAP_PACKAGE_VERIFY_FAILED trace=…` | Snapshot/fingerprint không khớp khi duyệt — có `trace` cũng nằm trong thông báo 409 gửi người dùng; chạy `roadmap_integrity_check.py` |
| `ROADMAP_PERMISSION_DENIED user=… need=roadmap.approve` | Người dùng không đủ quyền cố duyệt/retire/archive — theo dõi bất thường |

Audit nghiệp vụ nằm ở bảng `audit_logs` (action `ROADMAP_*`) — bền vững hơn log tệp. Trạng thái nguồn và checklist: giao diện Roadmap → **Source Data Health**, **Production Readiness**.
