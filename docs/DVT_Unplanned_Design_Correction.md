# Unplanned / Chưa lên KH — Design Correction

Bổ sung cho `DVT_Planning_Core_Design_Handoff.md`. Khi mâu thuẫn, ưu tiên tài liệu này cho phần Unplanned.

## 0. Nguyên tắc nền: ba chiều ĐỘC LẬP

**Planning status**, **Factory assignment** và **Mapping status** là ba chiều riêng biệt. Không gộp chúng thành một phân loại
"unmatched/unplanned".

| Chiều | Giá trị | Ý nghĩa |
|---|---|---|
| Planning status | `UNPLANNED` (Chưa lên KH) · `PLANNED` | Đã được đặt vào kế hoạch vận hành/chuyền hay chưa |
| Factory assignment | `KNOWN` (đã biết XN) · `UNASSIGNED` (chưa xác định XN) | Dòng đã có XN hợp lệ hay chưa |
| Mapping status | `OK` · `WARNING` | Dữ liệu nguồn có vấn đề cần rà soát không (FAC/XN lạ, thiếu XN trên dòng đã xếp KH...) |

Hệ quả: một PO `UNPLANNED` + `UNASSIGNED` là trạng thái **hợp lệ** (mapping vẫn `OK`), không phải "chưa khớp".

Đã hiện thực trong code: `app/services/rules.py::assess_factory`, cột `plan_rows.planning_status / factory_assignment /
mapping_status / mapping_note / fac_raw`, `tests/test_rules.py::test_three_dimensions_are_independent`.

## 1. Vị trí trong màn hình Planning

Planning chia 2 vùng làm việc theo chiều dọc: trên = **Planned / Operational Plan**, dưới = **Unplanned / Chưa lên KH**.
Unplanned là pool làm việc **trong cùng màn hình Planning**, không phải trang riêng.

## 2. Quy tắc nghiệp vụ

Unplanned **không** có nghĩa "chưa biết XN". Hai tình huống khác nhau:

- **A. Đã biết XN** (VD PO123, XN2, chưa gán chuyền) → thuộc pool Unplanned của XN2.
- **B. Chưa biết XN** (VD PO456, XN = null) → thuộc **Unassigned / Chưa xác định XN**.

Logic: `Unplanned → XN1 | XN2 | XN3 | Unassigned`. UI ưu tiên **một grid Unplanned có bộ lọc**, không bắt buộc 4 panel.

## 3. Bộ lọc riêng của panel Unplanned (ngay trên grid)

Factory/XN, Customer, Season, Sport, PO Number, Style/CC, Model Code, Free-text Search.

- Factory/XN: All · XN1 · XN2 · XN3 · Unassigned
- Quick filter: All · Factory Known · Unassigned
  - *Factory Known* = đã có XN nhưng chưa đặt vào kế hoạch vận hành/chuyền
  - *Unassigned* = chưa xác định XN

Bộ lọc phải **giữ nguyên trong suốt Edit Session** (VD chọn XN2 + Season SS2026, kéo nhiều dòng sang Planned — filter không reset).

## 4. Kéo từ Unplanned sang Planned

- **Case A — đã biết XN:** giữ nguyên XN; user chọn Line/vị trí đích → tạo Draft New Row → gán `virtualSequence` →
  Pending Drop → Confirm/Cancel. Không bắt chọn lại XN.
- **Case B — Unassigned:** bắt buộc chọn XN trước, rồi chọn/đặt Line; chỉ khi đó mới cho Confirm. Cancel → trả về Unassigned.

## 5. Frontend draft

Kéo từ Unplanned **không ghi DB**. Frontend tạo draft row tạm: `tempRowId, sourceId, factoryId, lineId, virtualSequence,
status = DRAFT_NEW`; item nguồn vẫn truy vết được. Chỉ ghi khi: Edit → Recheck All Plan → PASS → Commit.

## 6. PO MỚI

**Không** giả định mọi `PO MỚI` chưa có XN: PO MỚI + XN đã biết → Unplanned của XN đó; PO MỚI + XN chưa biết → Unassigned.
(File kế hoạch 01 Thang-12 hiện có 196 PO MỚI, tất cả đều chưa có XN — đó là *dữ liệu*, không phải quy tắc mặc định.)

## 7. Import / mapping

- Giữ nguyên giá trị FAC/XN gốc (`fac_raw`).
- FAC/XN hợp lệ và map được → `KNOWN`. Thiếu/không nhận diện → `UNASSIGNED`; có phải Mapping Warning hay không tùy ngữ nghĩa
  nguồn: dòng đã xếp KH mà thiếu XN, hoặc FAC/XN lạ (VD `DPC`) → `WARNING`; PO chưa lên KH và chưa có XN → `OK`.
- Không phân loại toàn bộ Unplanned là unmatched.

## 8. Tiêu chí nghiệm thu

- Unplanned ở nửa dưới màn hình Planning; item đã biết XN vẫn gắn với XN; item chưa biết XN hiện ở Unassigned.
- Panel có filter cục bộ; filter XN hỗ trợ All/XN1/XN2/XN3/Unassigned; quick filter All/Factory Known/Unassigned; filter giữ qua Edit Session.
- Kéo item đã biết XN giữ nguyên XN; kéo Unassigned bắt buộc chọn XN trước khi Confirm.
- Kéo/thả dùng Draft State + virtualSequence, không ghi DB.
- PO MỚI không mặc định bị coi là chưa biết XN.
- Ba chiều Planning status / Factory assignment / Mapping status luôn tách biệt.

## 9. Trạng thái hiện thực

| Hạng mục | Trạng thái |
|---|---|
| Ba chiều dữ liệu + import + dashboard (đếm "Chưa lên KH: x đã biết XN · y chưa xác định XN", cảnh báo mapping riêng, drill-down UNPLANNED/UNASSIGNED/MAPPING) | Đã có |
| Panel Unplanned trong màn hình Planning, filter, kéo-thả, Draft State, Confirm/Cancel | Chưa làm (thuộc Planning Core) |
