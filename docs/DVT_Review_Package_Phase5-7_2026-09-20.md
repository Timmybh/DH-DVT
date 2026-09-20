# DVT — Gói review Phase 5–7 (2026-09-20)

Mục đích: để reviewer độc lập (GPT) soát lại phần vừa xây theo `DVT_Master_Design_Implementation_Handoff_v2.2` §23–33.
Trạng thái mã: Phase 5 + virtual lane đã commit (`94efbd0`); **Phase 6–7 chưa commit** (xem "Cách lấy diff" cuối tài liệu).
Kiểm thử: 134 test backend pass (`.venv\Scripts\python -m pytest tests -q`), `tsc --noEmit` sạch, `npm run build` OK.
**Chưa kiểm tra bằng trình duyệt** (công cụ trình duyệt của người phát triển bị treo): mọi màn hình mới chỉ được xác nhận qua build + gọi API thật; cần reviewer/QA nhìn giao diện.

## 1. Phạm vi đã làm

### Phase 5 — Actual / Mapping (đã commit)
| Hạng mục handoff §25–26, §28 | Hiện thực |
|---|---|
| Khóa nghiệp vụ ổn định | `actual_service.fingerprint` = PO + Style/CC + Khách (chuẩn hóa). Không dùng ID eGMF, không dùng số lượng. `actual_key` = PO+XN+chuyền |
| Lịch sử thực tế, không ghi đè | `ActualObservation`: mỗi lần đồng bộ chỉ ghi bản ghi MỚI hoặc THAY ĐỔI (`changes` = diff so với lần trước); `state_at(run)` dựng lại trạng thái tại lần N |
| Mapping records | `ActualMapping` (status MATCHED/REVIEW/UNMATCHED/OUT_OF_PLAN/IGNORED, method, confidence, reason, candidates, dòng KH được gán); gán tay/bỏ qua được **giữ qua các lần đồng bộ** |
| Đối soát Plan-vs-Actual | may xong và nhập kho TP là hai mốc tách biệt (§28); trễ tính theo số lượng thực tế |
| Giao diện | Kế hoạch → "Thực tế & Đối soát" (3 tab) |

Phát hiện dữ liệu thật ảnh hưởng thiết kế: phiên bản kế hoạch hiện có 2.683 dòng nhưng chỉ ~8 giá trị PO (chủ yếu "FCAST WEEK 48", "PRE SELECTION"). Vì vậy ngoài khớp theo PO còn có khớp theo Style/CC + xí nghiệp + chuyền + cửa sổ thời gian (±14 ngày). Kết quả trên 9.924 thực tế: 144 khớp, 3.037 cần xem, 2.913 không khớp, 3.830 trước kỳ kế hoạch.

### Virtual lane (đã commit) — `app/services/lanes.py`
- Dòng có nhiều chuyền (`line_assignments` 4+5) thuộc **mọi** lane tương ứng. Thứ tự: dòng "sở hữu" (primary_line) theo `sequence`; thành viên phụ đứng sau dòng neo `extra.vanchor[line]`, chưa có neo thì suy ra theo (ngày bắt đầu, sequence).
- PREVIOUS_SEQUENCE / overlap / recalc lane / Recheck / kiểm tra tài nguyên / lịch nguồn lực rảnh / dựng baseline đều theo lane ảo. Dòng nhiều chuyền lấy dòng trước có **ngày kết thúc muộn nhất** trong các lane của nó.
- Test bắt buộc: A=4+5, B=5, C=4 ⇒ prev(B@5)=A, prev(C@4)=A (`test_planning_engine.py::test_virtual_lane_multi_line_row_belongs_to_every_lane_and_previous_sequence`).

### Phase 6 — hoàn thiện Dashboard (chỉ phần còn thiếu; phần đã có từ trước được bỏ qua theo yêu cầu)
- Drill-down Dashboard → dữ liệu vận hành: số PO trong bảng drill (PO tiến độ / PO rủi ro) là liên kết sang `Thực tế & Đối soát → Lịch sử thực tế?po=…` (chỉ hiện khi có quyền `mapping.view`); trang tự tra cứu PO.
- Đã có sẵn từ trước (không làm lại): Revenue thiết kế mới, Order Progress, QA (4/5 nhóm — nhóm QC ở DB hipro chưa kết nối), Tin tốt/Cảnh báo.

### Phase 7 — vòng đời năm / hardening
1. **Kết chuyển cuối năm** (`app/services/lifecycle.py`, bảng `year_carry_forwards` + `year_carry_forward_items`): mọi dòng của phiên bản tham chiếu chưa nhập kho đủ TP → mục kết chuyển với số lượng còn lại; kiểm tra bắt buộc (đối chiếu số dòng, khoảng số lượng còn lại, tổng, trùng lặp, giữ trạng thái chuyển chuyền…) → `VALIDATED`/`FAILED`; "Áp dụng" tạo phiên bản đầu năm sau (`{năm+1}.W01.Master.vNN`, `row_uid` giữ nguyên, `extra.carry_forward`).
2. **Lưu trữ theo năm**: chỉ khi kết chuyển của năm đó `VALIDATED/APPLIED` và năm < năm hiện tại; xuất từng bảng ra `archive/<năm>/*.jsonl.gz` + `manifest.json`, **đọc lại đối chiếu số dòng + SHA-256 trước khi xóa**, xóa trong một giao dịch (lỗi → rollback), gõ xác nhận `ARCHIVE <năm>`. **Phục hồi** kiểm SHA-256 từng tệp; tệp bị sửa → từ chối, không phục hồi dở. Giữ lại: phiên bản ISSUED tham chiếu, phiên bản có mapping/kết chuyển tham chiếu tới, quan sát thực tế mới nhất của từng khóa. Không bao giờ lưu trữ Master data.
3. **Phân vùng/giữ dữ liệu theo năm**: phân vùng *logic* (tệp lưu trữ + bảng nóng), `retention_online_years` (mặc định 2) đánh dấu năm "quá hạn giữ online". Không dùng partition của PostgreSQL.
4. **Hardening đăng nhập/phiên**: khóa tạm tài khoản sau 5 lần sai (15 phút, 429), `token_version` (đăng xuất/đổi quyền/khóa/đặt lại mật khẩu ⇒ token cũ mất hiệu lực), header bảo mật (nosniff, X-Frame-Options DENY, Referrer-Policy, Permissions-Policy, `Cache-Control: no-store` cho `/api`).
5. **Quản lý Style/Theme tập trung**: bảng `theme_settings` (token màu thương hiệu/trạng thái/dải biểu đồ, có version + audit, validate `#RRGGBB`), `GET /api/theme` công khai, `PUT/reset` cần `theme.manage`; frontend `theme/palette.ts` + `ThemeContext` áp CSS variables; công tắc Sáng/Tối theo từng người dùng (localStorage). Đã chuyển các màu trạng thái rải rác ở Gauge/Progress/HR/QA sang palette.
6. **Giám sát vận hành**: `GET /api/admin/monitoring` + trang Quản trị → Giám sát: DB (ping/dung lượng), đồng bộ (độ mới, thất bại 24h), lịch nền, độ mới dữ liệu, bảo mật đăng nhập, dung lượng lưu trữ, cảnh báo suy ra.

Quyền mới: `lifecycle.manage`, `monitoring.view`, `theme.manage` (ADMIN). `mapping.manage` được cấp thêm cho PLANNER.

## 2. File chính để đọc
Backend: `app/services/{actual_service,lanes,lifecycle,monitoring,theme,auth_guard}.py`, `app/api/{actual,lifecycle,monitoring,theme,auth,deps}.py`, `app/models/{actual,lifecycle,theme}.py`, `app/services/planning_engine.py` (recheck/reindex theo lane ảo), `app/services/resource_service.py`.
Frontend: `pages/planning/Actual.tsx`, `pages/admin/{Lifecycle,Monitoring,Theme}.tsx`, `theme/*`, `lib/lanes.ts`, `lib/quickCheck.ts`, `components/{Navbar,DrillDrawer,SubTabs}.tsx`.
Test: `tests/test_{actual,lifecycle,auth_guard,theme_monitoring,planning_engine,resources}.py`.

## 3. Đã xác minh trên dữ liệu/DB thật
- Đồng bộ eGMF thật: 9.924 quan sát; lần đồng bộ thứ 2 không ghi thêm dòng nào (delta).
- Recheck phiên bản W38 (2.683 dòng) theo lane ảo: 0 lỗi, 1.104 cảnh báo, 389 ms.
- API Phase 7 trên DB thật (tài khoản thử, đã dọn): monitoring OK; theme PUT hợp lệ + từ chối `javascript:alert(1)` (422); kết chuyển năm 2026 → VALIDATED (2.636 mục, 47 đã đóng), dry-run lưu trữ năm hiện hành bị từ chối (409); xác nhận sai bị từ chối (422); token bị thu hồi sau đăng xuất (401); 5 lần sai ⇒ 429 dù nhập đúng mật khẩu.
- **Chưa** chạy lưu trữ/áp dụng kết chuyển thật trên DB (chỉ test tự động bằng SQLite).

## 4. Hạn chế & rủi ro đã biết (reviewer nên soi kỹ)
1. **Kế hoạch không có PO thật** ⇒ Plan-vs-Actual mới khớp 144/2.683 dòng; số lượng thực tế của nhiều PO cùng mã hàng bị *cộng vào một dòng dự báo* (xấp xỉ, không phải đối chiếu 1-1).
2. **Kết chuyển**: mục "chưa có thực tế" (2.600/2.636 trên dữ liệu hiện tại) đi kèm kiểm tra không chặn `NO_ACTUAL_ITEMS`; sau khi áp dụng, ngày bắt đầu/kết thúc giữ nguyên nhưng `quantity`/`total_day` đã đổi ⇒ Recheck sẽ báo CALC_MISMATCH cần recalc. Chưa có bước tự tính lại ngày.
3. **Lưu trữ**: xóa cứng khỏi bảng nóng sau khi xuất; phục hồi giữ nguyên `id`. Chưa có sao lưu ngoài thư mục `archive/` (cần đưa vào quy trình backup của IIS/máy chủ). Chưa lưu trữ `po_pack_daily`, doanh thu, Audit (cố ý: dashboard/kiểm toán còn dùng). Tệp lưu trữ **không mã hóa**.
4. **Token revocation** dùng một `token_version` mỗi người dùng ⇒ đăng xuất ở một thiết bị làm mất hiệu lực **mọi** phiên của người đó. Khóa tài khoản chỉ áp cho đăng nhập nội bộ theo tài khoản (chưa giới hạn theo IP; tài khoản không tồn tại không bị đếm). Không có CSP (cần script Google SSO). JWT vẫn lưu ở phía trình duyệt như trước.
5. **Theme**: chế độ Sáng chưa được xem bằng mắt; phần lớn màu vẫn là lớp Tailwind tĩnh, chỉ màu thương hiệu (`bg-brand`…) và bảng màu trạng thái/biểu đồ đi qua token. `GET /api/theme` công khai (chỉ mã màu).
6. **Virtual lane**: dòng đang *chuyển chuyền* chỉ tính chuyền hiện tại (chuyền đích chưa vào lane); vị trí thành viên phụ do neo/ngày quyết định, chưa có giao diện sắp xếp lại; phiên bản đã commit trước đó chưa có neo (tự suy ra theo ngày).
7. `source_key` của dòng phiên bản kế hoạch vẫn chứa số lượng (fingerprint ổn định mới nằm ở phần Actual, chưa migrate).
8. Giám sát: ngưỡng cảnh báo (`sync_stale_hours`, `plan_stale_days`, 20 lần đăng nhập sai/24h, 1.000 mapping chờ) là mức tự chọn.
9. Frontend chưa có test tự động; nhóm QC của QA chưa kết nối (DB hipro).

## 5. Câu hỏi gợi ý cho reviewer
1. Quy tắc "còn lại = kế hoạch − nhập kho TP" và việc đưa cả dòng NO_ACTUAL vào kết chuyển có hợp lý cho nghiệp vụ cuối năm không? Nên tách "đóng" (hủy dự báo) và "chuyển" (lập lại)?
2. Thứ tự xóa / phục hồi trong `archive_year` / `restore_year` có còn khe hở về toàn vẹn (FK, id trùng khi phục hồi vào bảng đã có dữ liệu mới, `sync_run_id` mồ côi trong `actual_observations` còn giữ)?
3. `previous_sequence` lấy dòng trước có `end_prod_date` muộn nhất — có đúng ngữ nghĩa workbook cho dòng nhiều chuyền không? Vòng phụ thuộc chéo giữa các lane khi recalc có cần sắp xếp topo?
4. Khóa tài khoản theo tài khoản có thể bị lợi dụng để khóa người khác (DoS) — nên thêm giới hạn theo IP / độ trễ lũy tiến?
5. Việc `GET /api/theme` không cần đăng nhập và `Cache-Control: no-store` cho toàn `/api` có gây vấn đề hiệu năng/bảo mật nào?
6. Ngưỡng và cách khớp Style + cửa sổ thời gian (±14 ngày, độ tin cậy 0,6) có gây nhận diện sai (false match) khi cùng mã hàng chạy ở nhiều chuyền/tuần không?

## 6. Cách lấy diff / chạy
```bash
git diff 94efbd0 --stat                 # Phase 6–7 chưa commit (cộng thêm các file mới chưa track: git status --short)
git diff 617f949 94efbd0 --stat         # Phase 3–5 + virtual lane đã commit
.venv\Scripts\python -m pytest tests -q
cd frontend && npx tsc --noEmit && npm run build
```
