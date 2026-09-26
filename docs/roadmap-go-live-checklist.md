# Roadmap V1 — Go-live Checklist

Dùng kèm [roadmap-production-runbook.md](roadmap-production-runbook.md) và [IIS-DEPLOY.md](IIS-DEPLOY.md). Đánh dấu từng mục, ghi người thực hiện + ngày.

> **Trạng thái phần mềm:** Roadmap V1 hoàn chỉnh về chức năng; **giá trị nghiệp vụ chỉ xuất hiện sau khi business nhập + duyệt executable rule và cost evidence**
> (production ban đầu có 0 rule/0 evidence ⇒ proposal `NEEDS_INPUT` / action `UNPRICED` — đúng thiết kế). Không seed rule/giá giả.

## A. Pre-deploy

- [ ] **Test/build đầy đủ** trên commit sẽ deploy: `.venv\Scripts\python.exe -m pytest` xanh; `cd frontend; npx tsc --noEmit; npm run build` xanh.
- [ ] **Backup DB toàn bộ** (runbook mục 2) — ghi tên file; chạy `scripts\roadmap_integrity_check.py` và lưu kết quả trước deploy.
- [ ] **Schema/migration**: Roadmap chỉ *thêm* bảng (tạo tự động khi khởi động); xác nhận không có thay đổi phá vỡ bảng cũ; so danh sách bảng `roadmap_*` (19 bảng) trước/sau.
- [ ] **Trạng thái đồng bộ nguồn**: xem Roadmap → *Source Data Health* (lần thử gần nhất, độ tươi, cờ stale). PARTIAL không phải stale; FAILED liên tiếp cần xử lý trước go-live.
- [ ] **Tài khoản duyệt**: ≥ 2 user *active* có quyền `roadmap.approve` (four-eyes + dự phòng); kiểm ở *Production Readiness → User có khả năng duyệt*. Không dùng chung tài khoản.
- [ ] **HTTPS/Auth**: site có binding HTTPS + chứng chỉ hợp lệ; đăng nhập bằng tài khoản thật; `ACCESS_TOKEN_EXPIRE_MINUTES` phù hợp; không còn tài khoản test/UAT (`uat9_*`, `smoke_*`).
- [ ] **Env/Secrets**: `JWT_SECRET` ngẫu nhiên dài đã đổi; `POSTGRES_DSN`/`SQLSERVER_*` đúng; tài khoản eGMF **chỉ đọc**; `.env` không nằm trong git; không in secret vào log.
- [ ] **Logging**: thư mục `{site}\logs` ghi được; xác nhận thấy dòng khởi động `dvt`; biết cách lọc `dvt.roadmap` (runbook mục 9).
- [ ] **Quyền/role**: viewer chỉ đọc; planner (manage + run) không duyệt được; approver duyệt được — thử nhanh bằng 3 tài khoản thật.

## B. Go-live (dữ liệu nghiệp vụ — do business sở hữu)

- [ ] Mở *Production Readiness* → nắm các mục `ACTION_REQUIRED` (rule LABOR/MACHINE, evidence giá máy/lao động).
- [ ] **Tạo + duyệt executable rule ban đầu** (LABOR_GAP_REQUIREMENT_V1 / MACHINE_GAP_REQUIREMENT_V1): productivity do business khai báo, đúng scope/kỳ, nguồn `IE_APPROVED_STUDY` / `TIME_MOTION_STUDY` / `APPROVED_CAPACITY_STUDY` / `CONTROLLED_PRODUCTION_TRIAL`, có sample calculation; reviewer ≠ approver.
- [ ] **Tạo + duyệt cost evidence ban đầu**: giá máy (source `SUPPLIER_QUOTATION`/`APPROVED_CONTRACT_PRICE`/`APPROVED_BUDGET_STANDARD`/`CONTROLLED_PURCHASE_HISTORY`, `price_basis` rõ), chi phí lao động (`HR_APPROVED_COST_STANDARD`/`APPROVED_BUDGET_STANDARD`, kỳ + scope khớp). *Không* dùng BROCHURE/CLAIMED/ESTIMATE/DEFAULT/PLACEHOLDER/UNVERIFIED_WEB_PRICE.
- [ ] **Chạy scenario thật đầu tiên** (kỳ đã đủ dữ liệu, ví dụ tháng gần nhất *đủ* trong Source Data Health); kiểm baseline/gap khớp số liệu nguồn; đọc cờ dữ liệu.
- [ ] **Xác minh Action Plan + Decision Package**: chọn item, coverage đúng; package bind evidence tường minh, freeze, duyệt; kiểm CAPEX/lao động đúng số học và **không** có "Total Investment"/ROI.
- [ ] **Xác minh audit**: các sự kiện `ROADMAP_*` xuất hiện trong `audit_logs` với đúng actor; history trạng thái đúng.
- [ ] **Giám sát sync**: theo dõi lần đồng bộ 05:00 các ngày đầu (PARTIAL/FAILED); báo owner nếu FAILED.
- [ ] Chạy `scripts\roadmap_integrity_check.py` sau khi có dữ liệu thật đầu tiên → `ok: true`.

## C. Post-go-live

- [ ] **24 giờ**: xem log `dvt.roadmap` (RUN_FAILED, VERIFY_FAILED, PERMISSION_DENIED); kiểm sync; hỏi người dùng đầu tiên về UX.
- [ ] **7 ngày**: review PARTIAL/FAILED của sync; **dung lượng/volume `audit_logs`**; thời gian phản hồi các trang Roadmap (không có API phổ biến > 2 s); bất thường quyền (denied lặp lại).
- [ ] Chạy lại `roadmap_integrity_check.py`; lưu backup sau go-live; lập lịch restore thử đầu tiên (runbook mục 3).
- [ ] Review quyết định business còn mở: FACTORY OUTPUT_QTY (mapping ~98%), YEAR OUTPUT_QTY, chất lượng dữ liệu doanh thu lịch sử, chính sách PARTIAL sync — *chưa thay đổi trong V1*.

## D. Quyết định business còn mở (không thay đổi bởi Task 10)

1. **FACTORY `OUTPUT_QTY`** vẫn `PARTIAL_SOURCE` (mapping PO→XN kỳ 2026-08: ~98,4% theo số lượng) — cần ngưỡng/quy tắc xử lý PO chưa map.
2. **YEAR `OUTPUT_QTY`** — chỉ tính khi nguồn phủ đủ năm dương lịch (rolling-12M/YTD là quyết định riêng).
3. **Chất lượng dữ liệu doanh thu lịch sử** (`revenue_yearly` 2024/2025, dòng ngày `0001-01-01`).
4. **Chính sách sync PARTIAL** (hiện không coi là stale).
