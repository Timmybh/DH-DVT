# Khảo sát eGMF (SQL Server 10.8.0.72) — nguồn cho Order Progress và QA

Ngày khảo sát: 2026-09-20 (chỉ đọc). DB có 1.076 bảng. Dưới đây là các bảng liên quan tới handoff v2.2 §4.2 (Order Progress) và §4.3 (QA).

## 1. Order Progress (On Time / Late × Sewing complete / FG receipt)

### Nguồn tốt nhất: `dbo.Report_BaoCaoMayRa` (51.755 dòng, 17/01/2026 → hôm nay)
Báo cáo "may ra" theo PO/chuyền. **Không phải bảng sự kiện mà là nhật ký snapshot** ERP chụp lại mỗi ~10 phút, nên mỗi PO có hàng trăm–nghìn dòng (10.064 tổ hợp PO+chuyền+XN, 7.725 PO).

Cột chính: `PO` (dạng `6KC34XG8F55-6211514385`), `LenhSanXuat`, `MaHang`, `KhachHang`, `TenChuyen`, `XiNghiep` (1/2/3, khớp `factories.sql_xn_id`; 296 dòng NULL),
`SoLuong` (SL đơn), `VaoChuyenSoLuong/LuyKe`, `MayRaSoLuong/MayRaLuyKe` (**sewing output**), `NhapKhoSoLuong/NhapKhoLuyKe` (**nhập kho TP**),
`NgayXuatHang`, `NgaySanXuat`, `NgaySanXuatKetThuc`, `ThoiGianTao`.

Chất lượng dữ liệu (cần lưu ý):
- `NhapKhoLuyKe` NULL ở 72,6% dòng; `NgayXuatHang` NULL ở 73,7% dòng (các dòng gần đây thường NULL).
- `MayRaLuyKe` NULL ở 4,5% dòng.
- Khoá `PO` khác kiểu `PO NUMBER` trong file Excel kế hoạch (số 10 chữ số) → chưa ghép được với Planning; cần bảng mapping (handoff §25).
- Cần lấy **snapshot mới nhất theo (PO, chuyền)**; hoàn thành = `MayRaLuyKe ≥ SoLuong` (may) / `NhapKhoLuyKe ≥ SoLuong` (nhập kho).

### Bảng khác liên quan
- `dbo.FG_PhieuNhapKho` (26.345 phiếu) + `FG_PhieuNhapKho_ChiTiet` (480.325 dòng, có `XiNghiep`, `TenChuyen`, `ProductionOrderId`, `NgayNhapKho`): nguồn sự kiện chuẩn cho **nhập kho thành phẩm**, có ngày cụ thể (dùng được để xác định "ngày nhập kho hoàn tất").
- `dbo.GDXN_ToSanXuatNgay` (14.735 dòng): sản xuất theo tổ/ngày (`TongThucHien`, `NhapKhoNgay`).
- `dbo.Planning_KeHoachSanXuat_MayXong` (31 dòng): dữ liệu kế hoạch đã may xong, quá ít để dùng.
- `dbo.Lib_CacBuocTienDoSX`: danh mục các bước tiến độ.

### Quyết định còn thiếu (cần chủ nghiệp vụ)
1. "On time" của **may xong** so với mốc nào: `NgayXuatHang`, CHD (Excel), hay END BE. DATE (kế hoạch)?
2. "On time" của **nhập kho** so với mốc nào?
3. Ngày hoàn thành thực tế lấy từ đâu: snapshot đầu tiên có `MayRaLuyKe ≥ SoLuong` (chỉ có từ 17/01/2026) hay từ bảng sự kiện?
4. Danh sách khách hàng **không quản lý nhập kho** (loại khỏi yêu cầu FG receipt).

## 2. QA (Đầu chuyền · QC · Inline · Endline · Prefinal)

Các bảng DFC (Digital Form Check) có dữ liệu đến 19/09/2026:

| Nhóm | Bảng kiểm | Bảng lỗi | Quy mô | Xí nghiệp lấy từ đâu |
|---|---|---|---|---|
| Đầu chuyền | `DFCDauChuyenKiemtrachatluong` (244), `DFC_DauChuyen_Detail` (572) | `DFCDauChuyenChitietloi` (25) | rất nhỏ | chưa thấy cột XN — cần nối qua `MasterId` |
| Inline | `DFC_InLine_SoDoChuyen_Tram_KiemTra` (1,35 triệu) | `..._KiemTra_SanPham_CTLoi` (6,7 triệu; `SLLoi`, `TypeKiem='inline'`) | rất lớn | `..._KiemTra_SanPham.XiNghiep` (tên lẫn lộn, xem dưới) |
| Endline | `DFCEndlineKiemtrachatluong` (662 nghìn), `DFC_EndLine_Detail` (21 nghìn) | `DFCEndlineChitietloi` (52 nghìn) | lớn | chưa thấy cột XN — nối qua `MasterId` |
| Prefinal / Final | `DFC_Pre_Final_Master` (14.975) | `DFCFinalChitietloiBoSung` (36 nghìn), `DFC_Final_Kiemtrachatluong` (9) | vừa | `DFC_Pre_Final_Master.FtyXN` (XN1/XN2/XN3) |
| QC (?) | chưa xác định | | | |

Lưu ý dữ liệu:
- `XiNghiep` ở Inline có nhiều dạng: `XÍ NGHIỆP MAY 1/2/3`, `XN1/2/3`, và cả `PHÒNG KỸ THUẬT - CÔNG NGHỆ`, `PHÒNG QUẢN LÝ CHẤT LƯỢNG` (kiểm tra bởi phòng ban, không thuộc XN) → cần bảng chuẩn hoá.
- Nhóm `KTCM_*`, `TTKH_*` là bản sao cấu trúc Inline cho các phòng ban khác.
- `CUTTING_BTP_KiemTraChatLuong*` đã được loại khỏi phạm vi (handoff §4.3).
- "Total Defect Count" = tổng `SLLoi` (Inline) / số dòng chi tiết lỗi (Endline, Final).

### Quyết định còn thiếu
1. "QC" trong 5 nhóm tương ứng bảng nào (có thể là kiểm tra của Phòng Quản lý chất lượng ở Inline)?
2. Endline và Đầu chuyền: nối tới xí nghiệp qua bảng nào (cần khảo sát tiếp `MasterId`)?
3. Khoảng thời gian tổng hợp trên Dashboard (tháng đang xem / hôm nay / tuần)?

## 3. Đề xuất triển khai
Đồng bộ **theo ngày** vào Postgres (cache), không truy vấn trực tiếp SQL Server khi mở Dashboard:
- `fg_receipt_daily(po_key, xn, ngay, sl)` từ `FG_PhieuNhapKho_ChiTiet`.
- `sewing_progress_snapshot` = snapshot mới nhất theo (PO, chuyền) từ `Report_BaoCaoMayRa`.
- `qa_defect_daily(xn, category, ngay, defect_count)` gom sẵn theo nhóm.
