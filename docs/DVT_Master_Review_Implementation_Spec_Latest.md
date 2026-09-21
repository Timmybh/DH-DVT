# DVT — Master Review & Implementation Specification
**Project:** Bảng điều hành DVT  
**Repository:** `Timmybh/DH-DVT`  
**Purpose:** Consolidated authoritative review + implementation specification  
**Status:** Latest approved baseline

---

# 0. Mục tiêu tài liệu

Tài liệu này hợp nhất:

- Review implementation hiện tại.
- Các design đã được business chốt.
- Các correction mới nhất.
- SO architecture final.
- Những phần phải làm ngay.
- Những phần tạm hoãn sau UAT.

Claude chỉ cần dùng tài liệu này làm baseline triển khai.

Không dùng các handoff/design cũ nếu có nội dung mâu thuẫn với tài liệu này.

---

# 1. Nguyên tắc Definition of Done

Không được coi feature là Done chỉ vì UI đã có.

Một feature chỉ được coi là hoàn tất khi phần áp dụng có đủ:

- Data Model / Migration
- Backend Rule / Service
- API
- Permission
- Audit / History
- Frontend UX
- Validation
- Backend Test
- Không regression Planning hiện tại

---

# 2. Trạng thái review tổng thể

Các phần hiện tại đã đi đúng hướng và phải giữ:

- Planning grid kiểu Excel.
- Planned upper / Unplanned lower.
- Drag/drop hai chiều.
- Pending Drop → Confirm / Cancel.
- Edit Session.
- Draft.
- Undo / Redo.
- Recheck tách khỏi Commit.
- Planning Version.
- Virtual lane cho multi-line.
- Capacity/Resource foundation.
- Actual History theo sync run.
- Calendar Company → XN → Line.
- Snapshot.
- Lifecycle / carry-forward / archive foundation.
- Security / monitoring / theme foundation.

Các phần cần sửa hoặc hoàn thiện:

1. Productivity Grade + Labor composition.
2. Machine Management.
3. Admin menu visibility.
4. Dashboard Layout Designer.
5. Unplanned multi-select / batch assign.
6. Clone Unplanned Row.
7. Mapping redesign theo SO.
8. SO Transfer / Allocation.
9. OFF DAYS runtime/import/override.
10. Calendar governance Active/Inactive only.
11. QA scope correction.
12. source_key chưa migrate vội.

---

# 3. Priorities

## P1 — Làm ngay

1. Productivity Grade Master 1–10.
2. Labor Standard theo cơ cấu nhiều Grade.
3. Machine Management redesign.
4. Admin menu visibility correction.
5. Dashboard Layout Designer kiểu SharePoint Page.
6. Unplanned multi-select / batch assign.
7. Clone Unplanned Row.
8. SO architecture.
9. Mapping redesign theo SO.
10. SO Transfer / Actual Allocation.
11. OFF DAYS calculation/import/override.
12. Calendar no-delete governance.
13. QA scope: ẩn QC + Đầu chuyền.

## Deferred until after UAT

1. Rà Order Progress bằng dữ liệu thật.
2. Frontend automated regression suite lớn.
3. Monitoring thresholds configurable.
4. Application-level archive encryption.
5. Re-enable / hoàn thiện QA QC + Đầu chuyền.
6. source_key migration.
7. Carry-forward NO_ACTUAL business policy review.

---

# 4. Productivity Grade Master

`Productivity Grade` là Master Data độc lập.

Không nối với HR Performance Evaluation ở phase hiện tại.

Flow:

```text
Productivity Grade
        ↓
Labor Grade Composition
        ↓
Weighted Productivity Factor
        ↓
Effective Labor Equivalent
        ↓
Capacity / Planning
```

Seed mặc định:

| Grade | Code | Factor |
|---:|---|---:|
| 1 | PG01 | 50% |
| 2 | PG02 | 55% |
| 3 | PG03 | 60% |
| 4 | PG04 | 65% |
| 5 | PG05 | 70% |
| 6 | PG06 | 75% |
| 7 | PG07 | 80% |
| 8 | PG08 | 85% |
| 9 | PG09 | 90% |
| 10 | PG10 | 100% |

Không hard-code factor trong calculation engine.

Master tối thiểu:

```text
ProductivityGrade
- id
- grade
- code
- name
- productivity_factor
- effective_from
- effective_to
- status
- note
- audit fields
```

Rule:

- Grade 1..10.
- factor > 0.
- Grade cao không thấp factor hơn Grade thấp.
- không hard delete.
- Active / Inactive.
- factor thay đổi phải effective-dated.

---

# 5. Labor Standard theo nhiều Grade

Không gán một Grade duy nhất cho cả tổ/chuyền.

Ví dụ business:

```text
Total Labor = 40

30 người Grade 8
10 người Grade 7
```

Kết quả:

```text
Effective Labor Equivalent
= 30 × 0.85 + 10 × 0.80
= 33.5
```

```text
Weighted Productivity Factor
= 33.5 / 40
= 83.75%
```

Data model:

```text
LaborStandard
- id
- factory_code
- line / labor_group
- total_labor
- effective_from
- effective_to
- status
- note
- audit fields
```

Child:

```text
LaborStandardGradeDetail
- id
- labor_standard_id
- productivity_grade_id
- headcount
```

Validation:

```text
SUM(headcount) = total_labor
```

UI phải hiển thị:

| Grade | Factor | Headcount | Effective Equivalent |
|---:|---:|---:|---:|
| 8 | 85% | 30 | 25.5 |
| 7 | 80% | 10 | 8.0 |
| **Total** | **83.75%** | **40** | **33.5** |

Giữ riêng:

```text
Standard Labor
Weighted Productivity Factor
Effective Labor Equivalent
```

Không overwrite Standard Labor.

---

# 6. Machine Management redesign

Phải tách 3 business object.

## 6.1 Machine Master

```text
MachineMaster / MachineType
- code
- name
- model
- machine_group
- process
- operation
- compatible_style
- compatible_model
- compatible_product_family
- nominal_speed
- nominal_output
- default_efficiency_or_oee
- setup_changeover
- bottleneck_capability
- effective_from
- effective_to
- status
- source
- note
```

## 6.2 Machine Allocation by Factory-Line

```text
MachineAllocation
- factory_code
- line
- machine_type/model
- quantity
- available_quantity
- maintenance_quantity
- down_quantity
- planned_downtime
- efficiency / OEE
- effective_from
- effective_to
- status
- note
```

## 6.3 Machine Requirement

```text
MachineRequirement
- style_cc
- model_code
- product_family
- process / operation
- machine_type/model
- required_quantity
- source = QTCN / MANUAL
```

UI:

```text
Năng suất & nguồn lực
  └─ Máy móc
      ├─ Danh mục máy
      ├─ Phân bổ máy theo XN/Chuyền
      └─ Yêu cầu máy theo mã hàng/quy trình
```

---

# 7. Admin menu visibility

Hiện `sync.view` làm Viewer thấy menu Quản trị.

Phải sửa.

Rule:

- VIEWER không thấy Quản trị chỉ vì `sync.view`.
- PLANNER không thấy Quản trị chỉ vì `sync.view`.
- Menu Quản trị chỉ hiện nếu user có admin/governance permission thật.

Ví dụ:

```text
admin.*
dashboard.config_*
dashboard.layout_manage
dashboard.publish
audit.view
monitoring.view
lifecycle.manage
theme.manage
snapshot.view
```

Ẩn menu chỉ là UX.

Backend API vẫn enforce permission server-side.

---

# 8. Dashboard Layout Designer

Vị trí:

```text
Quản trị
→ Cấu hình Dashboard
→ Bố cục
```

Mặc định `View Mode`.

Có nút:

```text
Edit Mode
```

Khi vào Edit Mode:

- Add Section.
- Chọn preset column layout.
- Add Widget.
- Drag/drop widget.
- Move widget sang column khác.
- Move section.
- Resize bằng preset.
- Hide/Show.
- Duplicate.
- Property panel bên phải.
- Save Draft.
- Cancel.
- Preview.
- Publish.

Section presets:

```text
100%
50/50
66/34
34/66
33/33/33
25/25/25/25
```

Không resize pixel tự do phase này.

Widget Catalog:

```text
Revenue
Order Progress
QA
Labor
Planning Status
Alerts
KPI Card
Trend Chart
Comparison Chart
Table
Text / Heading
```

Data model đề xuất:

```text
DashboardLayout
DashboardSection
DashboardColumn
DashboardWidgetInstance
```

Layout version:

```text
DRAFT
PUBLISHED
SUPERSEDED
```

Permission:

```text
dashboard.view
dashboard.config_view
dashboard.layout_manage
dashboard.publish
```

---

# 9. Unplanned Batch Assign

Bổ sung multi-select.

Flow:

```text
Chọn nhiều dòng
→ Đưa vào kế hoạch
→ Chọn XN
→ Chọn tổ/chuyền
→ Chọn vị trí chèn
→ Confirm
```

Rule:

- trong Edit Mode.
- cùng Draft transaction.
- Undo được cả batch.
- Recheck lại sequence/calendar/resource.
- không silently gán các dòng conflict XN.
- giữ thứ tự chọn / thứ tự hiển thị.

---

# 10. Clone Unplanned Row

Bổ sung `Nhân bản`.

Clone tạo business row mới.

Copy business fields phù hợp:

```text
Customer
PO / Note
Style/CC
Model
Description
Sport
Season
Factory nếu phù hợp
Manual Input fields
```

Không copy identity cũ.

Không copy calculated outputs:

```text
TOTAL_DAY
OFF_DAYS_CALCULATED
BEGIN_PROD_DATE
END_PROD_DATE
```

Clone xong vẫn ở Unplanned.

---

# 11. SO Architecture — FINAL

SO là durable business identity xuyên suốt.

Không phụ thuộc PO.

Không phụ thuộc XN trong mã SO.

## 11.1 SO Number Format

Format chính thức:

```text
SO/YY/NNNNNN
```

Ví dụ:

```text
SO/26/000001
SO/26/000002
SO/26/000003
```

Sang năm:

```text
SO/27/000001
```

Rule:

- sequence 6 chữ số.
- reset theo năm.
- globally unique.
- readonly.
- immutable.
- auto-generated.
- không user edit.

Bỏ hoàn toàn:

```text
M1 / M2 / M3
```

---

# 12. Thời điểm tạo SO

SO phải có ngay từ Unplanned.

Flow:

```text
Create / Import Unplanned business item
        ↓
Generate SO
```

Không cần đợi kéo lên Planned.

Nếu dữ liệu import chưa đủ điều kiện thành business item hợp lệ thì đưa validation/error queue trước khi cấp SO.

Không cấp lại SO mỗi lần import lại cùng business item đã được nhận diện.

---

# 13. SO trên Unplanned và Planned

Cả Unplanned và Planned đều có `SO Number`.

UI:

- mặc định ẩn.
- user bật qua Column Chooser.
- readonly.
- search/filter.
- copy.
- không inline edit.

SO Number không đủ để user nhận diện.

Phải có SO Description + metadata.

---

# 14. SO Header / Description

SO tối thiểu có:

```text
SO Number
SO Description
Customer
Style/CC
Model
Season
Sport
Planned Quantity
Origin Factory
Current Execution Factory
Production Window
Current PO
Temp PO
Status
Note
CreatedAt
CreatedBy
```

Ví dụ:

```text
SO/26/000125
NIKE Pegasus / A100 / FW26

Customer: NIKE
Style/CC: A100
Model: PEGASUS
Season: FW26
Qty: 12,000
Current Factory: XN2
Current PO: PO_TEMP_009
Note: FCAST WEEK 42
```

`SO Description` cho business chỉnh mô tả.

`SO Number` không được sửa.

---

# 15. SO vs Planning Row

Phân biệt:

```text
SO = identity cấp business order / demand lineage
row_uid = identity cấp Planning Row
```

Một SO có thể có nhiều Planning Row.

Ví dụ:

```text
SO/26/000125
├─ R001 = 6,000
├─ R002 = 2,000
└─ R003 = 2,000
```

Split row không tạo SO mới nếu vẫn là cùng business demand.

Nếu merge các row thuộc nhiều SO khác nhau, không được ép mất lineage.

Phải giữ allocation theo từng SO.

---

# 16. PO chỉ là External Identity / Alias

PO không phải durable identity.

SO có thể có nhiều external identity:

```text
PlanningSOExternalIdentity
- planning_so_id
- source_system
- identity_type
- identity_value
- valid_from
- valid_to
- status
- reason
```

Types:

```text
PLAN_NOTE
TEMP_PO
ERP_PO
CUSTOMER_PO
PREVIOUS_PO
```

PO đổi không đổi SO.

---

# 17. Mapping redesign theo SO

Current Mapping đang quá phụ thuộc PO.

Target flow:

```text
1. Có SO trực tiếp
   → Exact Map

2. Không có SO trực tiếp nhưng PO alias đã biết
   → Exact Map về SO

3. Có borrowing/allocation relation
   → Map theo allocation

4. Không exact
   → Candidate SO

5. Candidate chưa chắc chắn
   → Needs Confirmation

6. User chọn SO
   → Manual Mapping
   → Remember relation
```

Người dùng chọn SO trước, không bắt buộc chọn Planning Row ngay.

---

# 18. Candidate SO UX

Không chỉ hiện số SO.

Candidate phải hiển thị:

```text
SO Number
Description
Customer
Style/CC
Model
Owner / Current Factory
Planned Qty
Production Window
Current PO / Temp PO
```

Ví dụ:

```text
SO/26/000125
NIKE Pegasus / A100 / FW26
NIKE · XN1 · 12,000 pcs · 15/10–28/10
PO hiện tại: PO_TEMP_009
```

Hiển thị reason:

```text
Strong candidate

✓ Same Style
✓ Same Customer
✓ Same XN
✓ Same Line
△ Actual date +3 days
```

Không show confidence giả kiểu:

```text
63%
78%
```

UI dùng:

```text
Exact
Strong candidate
Possible candidate
Needs confirmation
```

---

# 19. Actual identity

Current:

```text
actual_key = PO | XN | LINE
```

cần review.

Actual nên có internal stable identity:

```text
actual_uid
```

và source snapshot:

```text
source_system
source_ref
po
style
customer
factory
line
qty
sewn_qty
fg_qty
dates
```

eGMF internal ID chỉ là auxiliary technical reference.

Không phá migration vội trong một bước.

---

# 20. Actual ↔ SO / Planning Link

Không chỉ giữ một:

```text
mapped_row_uid
```

Cần relation/allocation model.

Đề xuất:

```text
ActualPlanningLink
- id
- actual_uid
- planning_so_id
- planning_row_uid nullable
- allocation_qty nullable
- allocation_type
- mapping_status
- mapping_basis
- confirmed_by
- confirmed_at
- note
```

Hỗ trợ:

```text
1 Actual → nhiều Planning Row
n Actual → 1 SO / Planning Row
```

---

# 21. PO đổi

Ví dụ:

```text
SO/26/000125
PO_TEMP_001
↓
PO123456
```

SO không đổi.

PO cũ thành historical alias.

Actual theo PO cũ hoặc mới đều quay về cùng SO.

---

# 22. Plan chưa có PO

Plan tổng có thể chỉ có:

```text
FCAST WEEK 48
PRE SELECTION
Customer
Style
Model
Quantity
```

vẫn có SO.

Khi ERP sinh Temp PO:

```text
SO
→ TEMP_PO alias
```

Không tạo identity mới.

---

# 23. PO Borrowing

Mượn PO là nghiệp vụ riêng.

Ví dụ:

```text
Actual PO B = 5,000

3,000 → SO B
2,000 → SO A
```

Phải hỗ trợ allocation.

Validation:

```text
SUM(allocation_qty) <= actual_qty
```

Types:

```text
NORMAL
BORROWED_PO
MANUAL_TRANSFER
```

Không bắt Actual PO trùng Planning PO.

---

# 24. SO Transfer — MUST KEEP

Dù SO Number không còn XN, vẫn phải giữ SO Transfer Ledger.

Không cho sửa Factory trực tiếp rồi mất lịch sử.

Data model:

```text
SOTransfer
- id
- so_id
- from_factory
- to_factory
- transfer_quantity
- transfer_date
- reason
- status
- confirmed_by
- confirmed_at
- note
```

---

# 25. Partial Transfer

Ví dụ:

```text
SO/26/000125
Total Qty = 10,000

XN1 đã sản xuất = 4,000
Transfer XN1 → XN2 = 6,000
```

Sau transfer:

```text
XN1
Original / allocated: 10,000
Actual produced:      4,000
Transferred out:      6,000

XN2
Transferred in:       6,000
Actual produced:      ...
```

Không mất sản lượng XN1.

---

# 26. Multiple Factory Execution

Một SO có thể đồng thời chạy nhiều XN.

Data model:

```text
SOExecutionAllocation
- id
- so_id
- factory_code
- allocated_qty
- effective_from
- effective_to
- status
```

Ví dụ:

```text
SO/26/000125
Total = 20,000

XN1 = 8,000
XN2 = 7,000
XN3 = 5,000
```

---

# 27. SO identity và Factory tách biệt

Phân biệt:

```text
SO Number
= business identity ổn định

Origin Factory
= nơi bắt đầu nếu cần trace

Current Execution Factory
= XN đang thực hiện

SO Execution Allocation
= quantity theo XN

SO Transfer Ledger
= lịch sử chuyển
```

Không overwrite lịch sử.

---

# 28. Actual Mapping sau Transfer

Actual phải truy được:

```text
SO + Execution Factory + Line
```

Ví dụ:

```text
SO/26/000125

XN1 Actual = 4,000
XN2 Actual = 6,000
```

Tổng SO = 10,000 nhưng vẫn drill-down theo XN.

---

# 29. Mapping UI

Đề xuất kiểu reconciliation.

Bên trái:

```text
Actual chưa xử lý
PO ERP
Style
XN
Line
Qty
May ra
Nhập kho
Last Seen
```

Bên phải:

```text
Candidate SO
SO Number
Description
Customer
Style
Model
Factory
Planned Qty
Production Window
Current PO/Temp PO
Reason suggested
```

Actions:

```text
Link toàn bộ
Allocate quantity
Split
Mark PO Alias
Mark Borrowed PO
Exclude
Change Mapping
Unmap
```

Không dùng rule:

```text
Chỉ gán được cùng PO
```

---

# 30. Mapping status

UI business-friendly:

```text
Automatically linked
Needs confirmation
Manually linked
Not linked
Excluded
```

`OUT_OF_PLAN` nên là reason/classification.

Manual change phải lưu:

```text
Old Mapping
New Mapping
Reason
Changed By
Changed At
```

Không overwrite history.

---

# 31. OFF DAYS — runtime mới

Nếu không có imported/manual override:

```text
TOTAL_DAY_RAW = QUANTITY / CAPACITY
```

`TOTAL_DAY_ROUNDED` theo planning duration rule hiện hành.

Sau đó:

```text
OFF_DAYS_CALCULATED
= số ngày Non-working Day phát sinh trong khoảng lịch
  cần để hoàn thành TOTAL_DAY_ROUNDED working days
```

Calendar hierarchy:

```text
Line
> XN
> Company
```

OFF gồm:

```text
Nghỉ hàng tuần
Nghỉ Tết
Nghỉ lễ khác
Nghỉ khác
Ngoại lệ = OFF
```

Không tính OFF:

```text
Tăng ca
Ngoại lệ = WORKING
```

---

# 32. OFF DAYS import từ Excel

Business final:

> Import Excel thì lấy nguyên OFF DAYS của Excel. Không half-up lại.

Ví dụ:

```text
Excel OFF DAYS = 2.4
```

Import:

```text
off_days_override = 2.4
off_days_override_source = EXCEL_IMPORT
off_days_effective = 2.4
```

Không tự làm tròn.

Không check legacy half-up rule ở bước import.

Half-up chỉ còn documentation legacy nếu cần.

---

# 33. OFF DAYS Manual Override

User được override.

Ví dụ:

```text
Calculated = 2
Manual = 3
Effective = 3
```

Grid:

```text
3 !
```

Tooltip:

```text
OFF DAYS đã override
Calculated: 2
Applied: 3
Source: MANUAL
```

Phải giữ:

```text
off_days_calculated
off_days_override
off_days_override_source
off_days_effective
override_reason
override_by
override_at
```

Sources:

```text
EXCEL_IMPORT
MANUAL
```

Logic:

```text
Nếu override tồn tại:
    effective = override
Ngược lại:
    effective = calculated
```

Calendar thay đổi vẫn recalc calculated.

Không tự xóa override.

Chỉ `Reset to Calculated` mới bỏ override.

Manual override bắt buộc Reason.

---

# 34. Calendar governance

Calendar Day Type:

- không delete.
- Active / Inactive.

Calendar Rule:

- không delete.
- Active / Inactive.

Inactive:

- không tham gia current resolution.
- vẫn giữ history/audit.
- vẫn giải thích được Planning Version cũ.

UI đổi Delete thành:

```text
Ngưng áp dụng
```

Maintenance:

```text
Nghỉ khác
Note = Bảo trì
```

---

# 35. QA scope hiện tại

Tạm ẩn và không tính:

```text
QC
Đầu chuyền
```

Current active:

```text
Inline
Endline
Prefinal (Final)
```

Không cảnh báo thiếu dữ liệu 2 nhóm deferred.

Không xóa code/source.

---

# 36. Order Progress

Status:

```text
DEFERRED UNTIL POST-UAT
```

Chỉ sửa lỗi blocking UAT.

---

# 37. Frontend automated tests

Không ưu tiên suite lớn trước UAT.

Hiện bắt buộc:

```text
TypeScript compile
Build pass
Backend tests pass
```

Backend tests cho business rule mới phải viết ngay.

Sau UAT mới mở rộng Playwright/Vitest regression.

---

# 38. Archive / Backup / Encryption

Current:

- archive
- restore
- SHA256

giữ nguyên.

IT phải backup archive directory.

Không build custom backup system.

Không yêu cầu app-level encryption phase này.

---

# 39. Monitoring thresholds

Giữ default hiện tại nếu không blocking UAT.

Configurable Monitoring Settings để phase sau.

---

# 40. source_key

Current:

```text
PO | Style | Model | Customer | Quantity
```

Quantity mutable nên không lý tưởng.

Nhưng không migrate vội.

SO sẽ dần thay vai trò business identity.

Status:

```text
SOURCE_KEY_STABILITY = REVIEW REQUIRED
MIGRATION = NOT YET APPROVED
```

---

# 41. Carry-forward known gap

Current carry-forward có thể giữ derived dates cũ sau khi quantity thay đổi.

Target future:

```text
Carry Forward
→ Create next-year row
→ Preserve lineage
→ Set remaining quantity
→ Recalculate derived fields
→ Recheck
```

Không ưu tiên hơn P1 nếu không blocking UAT.

---

# 42. Preserve existing Planning behavior

Không regression:

- Excel-like grid.
- Planned / Unplanned split.
- Unplanned filters.
- Known XN / Unassigned.
- drag both directions.
- Confirm / Cancel.
- Edit Session.
- Draft.
- Undo / Redo.
- Recheck.
- Commit.
- Versioning.
- Virtual lane.
- multi-line.
- Actual history.
- Calendar hierarchy.
- Resource foundation.
- Snapshot.
- Lifecycle/archive.

---

# 43. Acceptance Criteria — Productivity / Labor

1. Grade 1–10 seeded.
2. Grade Active/Inactive.
3. No hard delete.
4. Effective date validation.
5. Labor supports multiple Grade.
6. SUM(headcount) = total_labor.
7. 30 Grade8 + 10 Grade7 = 33.5.
8. Weighted factor = 83.75%.
9. Backend tests.
10. Resource engine dùng được kết quả.

---

# 44. Acceptance Criteria — Machine

1. Machine Master riêng.
2. Machine Allocation riêng.
3. Machine Requirement riêng.
4. UI tách 3 phần.
5. Không regression resource check.
6. Permission đúng.
7. Effective history giữ được.

---

# 45. Acceptance Criteria — Admin Menu

1. VIEWER không thấy Quản trị chỉ vì sync.view.
2. PLANNER không thấy Quản trị chỉ vì sync.view.
3. Admin/governance permission thật mới hiện menu.
4. Backend route/API vẫn chặn đúng.

---

# 46. Acceptance Criteria — Dashboard Layout

1. Có tab Bố cục.
2. View Mode mặc định.
3. Có Edit Mode.
4. Add Section.
5. Preset column.
6. Add Widget.
7. Drag/drop.
8. Move Section.
9. Resize preset.
10. Property panel.
11. Save Draft.
12. Cancel restore.
13. Preview.
14. Publish.
15. Version DRAFT/PUBLISHED/SUPERSEDED.
16. Corporate / Factory layout riêng.
17. Permission layout_manage / publish.

---

# 47. Acceptance Criteria — Unplanned

## Batch Assign
1. Multi-select.
2. Assign XN/Line.
3. Confirm batch.
4. Same Draft transaction.
5. Undo batch.
6. Recheck.
7. XN conflict handled.

## Clone
1. New business row.
2. clone lineage.
3. no copy calculated outputs.
4. remains Unplanned.
5. original unchanged.

---

# 48. Acceptance Criteria — SO

1. Format `SO/YY/NNNNNN`.
2. 6-digit sequence.
3. reset per year.
4. globally unique.
5. no M1/M2/M3.
6. generated at Unplanned stage.
7. readonly.
8. immutable.
9. available on Unplanned + Planned.
10. hidden by default but user can show.
11. SO Description exists.
12. PO change does not change SO.
13. Factory transfer does not change SO.
14. Split row does not change SO.
15. Merge across SO preserves multi-SO lineage.

---

# 49. Acceptance Criteria — Mapping

1. Exact SO auto-map.
2. Known PO alias auto-map.
3. No exact → Candidate SO.
4. Candidate shows full business description.
5. No fake confidence %.
6. User can select SO.
7. Manual mapping remembered.
8. Mapping audit.
9. Change Mapping.
10. Unmap.
11. PO change preserves mapping.
12. Temp PO preserves SO.
13. PO borrowing supports allocation.
14. Many-to-many capable model.
15. No “same PO only” restriction.
16. Actual History preserved.

---

# 50. Acceptance Criteria — SO Transfer

1. SO Number unchanged.
2. Origin/Owner history retained.
3. Transfer Ledger exists.
4. Partial transfer.
5. Multiple XN execution supported.
6. Source XN actual preserved.
7. No overwrite history.
8. Audit full.
9. Actual can aggregate by SO and drill down by XN.

---

# 51. Acceptance Criteria — OFF DAYS

1. Runtime uses Working Calendar when no override.
2. Excel import keeps exact value.
3. No half-up on import.
4. source = EXCEL_IMPORT.
5. Manual override allowed.
6. Manual override shows `!`.
7. Calculated + Override + Effective retained.
8. Manual override requires Reason.
9. Calendar changes recalc Calculated.
10. Override remains until reset.
11. Reset to Calculated exists.
12. Backend test for decimal Excel OFF DAYS.
13. Backend test for Manual Override.
14. Backend test for calendar-calculated OFF DAYS.

---

# 52. Final architecture principle

Ưu tiên:

```text
Stable Business Identity
Explicit Lineage
SO-based Mapping
Non-destructive History
Effective Dating
Audit
Explainable Calculation
User Confirmation for uncertain mapping
```

Tránh:

```text
PO as permanent identity
Factory encoded into SO Number
hard delete
silent remap
fake confidence %
one-to-one-only mapping
overwrite transfer history
recalculate imported Excel values without intent
```

SO phải trở thành trục xuyên suốt cho:

```text
Unplanned
→ Planned
→ Temp PO
→ ERP PO
→ PO change
→ Borrowed PO
→ Split / Merge
→ Transfer XN
→ Actual Mapping
```

`row_uid` tiếp tục là identity ổn định ở cấp Planning Row.
