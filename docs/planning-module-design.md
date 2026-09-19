# Module Lập kế hoạch sản xuất — thiết kế (draft)

> **Ghi chú (2026-09-20):** Tài liệu này là bản phân tích sơ bộ ban đầu. Thiết kế chính thức được duyệt nằm ở
> `docs/DVT_Planning_Core_Design_Handoff.md` — khi mâu thuẫn, ưu tiên handoff. Phần "Dữ liệu doanh thu trong SQL Server"
> và "Phân tích file Excel kế hoạch" bên dưới vẫn còn giá trị tham khảo.

Trạng thái: **Đang chờ người dùng chốt 3 câu hỏi ở cuối file** trước khi code.

## Bối cảnh

Dashboard điều hành DH-DVT ban đầu chỉ có 5 chỉ số sidebar generic (SX/Đóng gói/Giao hàng/QA/Vướng mắc). Người dùng
mô tả lại tầm nhìn thật: dashboard cho Ban Tổng giám đốc theo dõi 4 nhóm — **Doanh thu/Thực hiện, Tiến độ thực hiện,
Tình hình Nhân sự, Tình hình cảnh báo** — cộng thêm module **Lập kế hoạch** (nhiều phiên bản, phiên bản chính thức
hiện tại/tương lai, thao tác kéo-thả dòng để xếp lịch — phần kéo-thả để làm sau).

Đã kết nối được SQL Server nguồn thật: `10.8.0.72` / database `eGMF` (SQL Authentication, xem `.env` —
`SQLSERVER_HOST/PORT/DB/USER/PASSWORD`, không commit `.env` vào git). Database có 1075 bảng (hệ thống ERP nội bộ,
nhiều bảng tiền tố `Bravo_`, `GDXN_`, `LCD_`, `OMM_`, `Planning_`...).

## Dữ liệu doanh thu đã dò được trong SQL Server (dùng ngay được)

| Bảng | Nội dung | Trạng thái |
|---|---|---|
| `GDXN_XiNghiep` | 3 xí nghiệp (XN1/XN2/XN3), id 4/5/6 | ✅ Sẵn sàng |
| `LCD_Truc_Quan_XiNghiep_DoanhThu_Ngay` | Doanh thu Kế hoạch/Thực hiện/Còn lại theo **ngày**, theo xí nghiệp | ✅ Sẵn sàng — tên bảng gợi ý đã có sẵn hệ thống LCD/dashboard tại xưởng dùng bảng này |
| `GDXN_TongQuanRow1_KPI` | KPI dạng `TieuDe`/`GiaTri`/`NgayUpdate` theo xí nghiệp — hiện chỉ có các KPI doanh thu (KẾ HOẠCH/THỰC HIỆN/CÒN LẠI × THÁNG/NĂM) | ✅ Sẵn sàng, đúng format key-value cho gauge |
| `DFC_EndLine_KiemDongGoi` | QC đóng gói, có `KetQua` (đạt/không đạt) | 🟡 Có thể tính tỷ lệ đạt, chưa xác nhận công thức |
| `Lib_GiaoHangThanhPham` | Phiếu giao hàng, có `TrangThai` | 🟡 Có thể đếm theo trạng thái, chưa xác nhận công thức |
| `Lib_CacBuocTienDoSX` | Chỉ là danh mục bước tiến độ (lookup), không phải dữ liệu thực tế | ❌ Chưa đủ |
| QA, Vướng mắc | Chưa tìm ra bảng rõ ràng | ❌ Chưa xác định |

## Phân tích file Excel kế hoạch SX thật

Nguồn: `D:\1. Workplace\Đồng Tiến\Tài liệu - Yêu cầu\KH-SX\01 Thang-12 (01.12.2025) XN CHỐT.xlsb`
(đọc bằng `pyxlsb`, đã cài trong `.venv` của project).

Vòng đời 1 đơn hàng (PO) qua 4 sheet chính:

```
PO MỚI (209 dòng, chưa xếp lịch)
   └──schedule──▶ KẾ HOẠCH (18,618 dòng, đã xếp Xí nghiệp + Chuyền + khung thời gian — bản "CHỐT")
                    └──may xong──▶ PO MAY XONG (1,031 dòng)
                                     └──xuất──▶ ĐÃ XUẤT (39,396 dòng, lịch sử)
```

Sheet phụ:
- **LAO ĐỘNG** (187 dòng): số công nhân có mặt theo Xí nghiệp/Tổ → nguồn cho "Tình hình Nhân sự"
- **NGÀY NGHỈ TRONG NĂM**: lịch nghỉ lễ, dùng tính ngày làm việc thực tế
- **Sheet1**: data dictionary — giải thích ý nghĩa/công thức từng cột (rất hữu ích, xem file gốc nếu cần tra lại)

### Ý nghĩa cột chính trong sheet KẾ HOẠCH (đọc từ dictionary trong file)

| Cột | Ý nghĩa | Công thức |
|---|---|---|
| FAC/XN, LINE | Xí nghiệp, Chuyền | input |
| CAPACITY | Năng suất chuyền/ngày (LEAN+CI đo đạc) | input |
| TOTAL DAY | Số ngày hoàn thành | QUANTITY / CAPACITY |
| OFF DAYS | Ngày nghỉ trong tuần | TOTAL_DAY / 7 |
| FABRIC READY / ACC READY | Ngày vải/phụ liệu sẵn sàng vào chuyền | input |
| BEGINING P. DATE | Ngày vào chuyền | phụ thuộc tồn kho BTP + thời gian gia công |
| END BE. DATE | Ngày may xong | Begin + TOTAL DAY + OFF DAYS |
| W.HOUSE | Ngày nhập kho TP | Output date + 1 |
| CHD | Ngày khách hàng yêu cầu xuất | confirm với khách |
| EHD/CHD | Chênh lệch ngày dự kiến vs CHD | dùng đánh giá ON TIME / ADVANCE / trễ |

→ Đây là **hệ thống lập lịch sản xuất theo PO kiểu Gantt**: mỗi dòng = 1 PO gán vào 1 Xí nghiệp + 1 Chuyền, timeline
tự tính từ ngày nguyên liệu sẵn sàng → vào chuyền → ra chuyền → nhập kho → giao hàng, so với ngày khách yêu cầu (CHD)
để biết sớm/trễ. **"Kéo thả dòng" (làm sau) = kéo PO giữa các chuyền/khung ngày để tái lập lịch.**

## Schema Postgres đề xuất (chưa code)

```
plan_versions       (id, name, status: DRAFT|CURRENT|FUTURE, effective_month, created_by, created_at)
production_lines    (id, factory_id, line_code, daily_capacity)
purchase_orders     (id, po_number, style_cc, model_code, description, customer,
                      sport, season, quantity, destination, fob_price, ...)
po_schedule         (id, plan_version_id, po_id, line_id,
                      fabric_ready, acc_ready, begin_prod_date, end_prod_date,
                      warehouse_date, chd, ehd_etd, ahd, status: ON_TIME|ADVANCE|DELAY, note)
labor_headcount     (id, factory_id, to_code /* tổ */, headcount, report_date)
```

- **Versioning**: mỗi lần "chốt" kế hoạch tháng → 1 row mới trong `plan_versions` (giống file `.xlsb` này = 1
  snapshot "01 Thang-12... XN CHỐT"). Cột `status` phân biệt phiên bản đang áp dụng (CURRENT) vs đang soạn cho
  tháng sau (FUTURE/DRAFT).
- **Kéo-thả** sẽ sửa `po_schedule.line_id` + `begin_prod_date` — để sau.
- **LAO ĐỘNG** → bảng `labor_headcount`, nạp cho nhóm "Tình hình Nhân sự".

## Câu hỏi cần người dùng chốt trước khi code tiếp

1. **Nguồn import kế hoạch**: từ file Excel `.xlsb` này (upload thủ công, giống tính năng "Đồng bộ Excel" đã có
   trong tab Đồng bộ dữ liệu), hay từ bảng SQL Server `Planning_KeHoachSanXuatThang` trong `eGMF` (hiện đang
   **rỗng — 0 dòng**, có thể vì chưa ai đẩy dữ liệu vào đó)?
2. **"Vướng mắc/cảnh báo"** trên dashboard — có phải lấy từ các PO có `EHD/CHD` âm (trễ so với khách) hoặc cột
   `NOTE` có ghi vấn đề (VD "chưa có vải", "check với SPL") không? Nếu đúng thì đã có nguồn, không cần mock nữa.
3. **Phạm vi đợt này**: chỉ **hiển thị** kế hoạch (đọc dữ liệu lên xem dạng bảng/Gantt, chưa cho sửa) hay cần làm
   luôn **chỉnh sửa + tạo version mới** (chuẩn bị nền cho kéo-thả sau)?
