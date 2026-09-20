# DVT — Dashboard Metadata / Indicator Registry Handoff

**Project:** Bảng điều hành DVT  
**Purpose:** Implementation-ready handoff for Claude  
**Status:** Approved design  
**Goal:** Mọi thành phần hiển thị trên Dashboard phải được khai báo bằng metadata, có nhóm, bật/tắt, loại hiển thị, rule Python được đăng ký, và có thể kéo/thả vào vị trí cụ thể trên Dashboard.

---

## 1. Kiến trúc tổng thể

```text
DashboardIndicatorGroup
        │
        └── DashboardIndicator
                 │
                 ├── DashboardRuleRegistry
                 │
                 └── DashboardLayoutItem
                           │
                           └── DashboardLayout
```

Nguyên tắc:

- Dashboard không còn hard-code cấu trúc từng section.
- Business rule vẫn nằm ở backend Python.
- Admin chỉ chọn rule đã deploy, không upload/chạy Python tùy ý.
- Frontend render theo `DisplayType`.
- Layout tách khỏi Indicator.
- Layout có Draft / Publish / Retire.
- Giữ nguyên logic/interaction Revenue hiện tại.
- Tương thích Light/Dark theme.

---

## 2. Cây chức năng

```text
QUẢN TRỊ
└── Cấu hình Dashboard
    ├── Nhóm chỉ số
    ├── Chỉ số theo dõi Dashboard
    ├── Rule Registry
    └── Bố cục Dashboard
```

Dashboard runtime vẫn nằm ở tab `DASHBOARD`.

---

## 3. DashboardIndicatorGroup

Table:

```text
dashboard_indicator_groups
```

Fields:

```text
id
group_code
group_name
description
default_enabled
display_order
layout_mode
collapsible
is_active
created_by
created_at
updated_by
updated_at
```

Initial groups:

```text
REVENUE
ORDER_PROGRESS
QA
SIGNALS
```

Allowed `layout_mode`:

```text
GRID
STACK
CUSTOM
```

---

## 4. DashboardIndicator

Table:

```text
dashboard_indicators
```

Fields:

```text
id
indicator_code
indicator_name
group_code
description

display_type
rule_code
data_source
default_scope

drilldown_type
drilldown_target

refresh_mode
default_enabled
is_active
display_order

owner
data_freshness_requirement
config_json

created_by
created_at
updated_by
updated_at
```

Allowed scope:

```text
COMPANY
FACTORY
BOTH
```

Allowed drilldown:

```text
NONE
DRAWER
PAGE
MODAL
CUSTOM
```

Allowed refresh:

```text
REALTIME
SYNC
CACHED
ON_LOAD
```

Rules:

- `indicator_code` unique.
- `group_code` FK.
- `rule_code` phải tham chiếu Rule Registry.
- Indicator không chứa tọa độ layout.
- Disable không phải delete.

---

## 5. DashboardRuleRegistry

Table:

```text
dashboard_rule_registry
```

Fields:

```text
id
rule_code
rule_name
rule_module
rule_function
rule_version
description
input_contract
output_contract
is_active
created_by
created_at
updated_by
updated_at
```

Example:

```text
rule_code     = REVENUE_EXECUTIVE_SUMMARY
rule_module   = app.dashboard_rules.revenue
rule_function = build_revenue_summary
```

### Security bắt buộc

Không cho Admin nhập:

```text
C:\abc\xyz.py
```

Không upload Python.

Không `eval`, không dynamic import từ path tùy ý.

Backend dùng whitelist:

```python
RULE_REGISTRY = {
    "REVENUE_EXECUTIVE_SUMMARY": revenue.build_revenue_summary,
    "ORDER_PROGRESS_MATRIX": order_progress.build_summary,
    "QA_COMPARISON": qa.build_summary,
    "GOOD_NEWS": signals.build_good_news,
    "WARNING_SIGNALS": signals.build_warnings,
}
```

Database chỉ chọn `rule_code`.

---

## 6. DashboardLayout

Table:

```text
dashboard_layouts
```

Fields:

```text
id
layout_code
layout_name
scope_type
scope_value
version
status
is_default
description
created_by
created_at
published_by
published_at
retired_at
```

Statuses:

```text
DRAFT
PUBLISHED
RETIRED
```

Examples:

```text
CORPORATE_DEFAULT
FACTORY_DEFAULT
EXECUTIVE_2026
```

Rules:

- PUBLISHED immutable.
- Edit bằng cách clone/create Draft.
- Publish Draft mới rồi retire/supersede layout cũ.
- Chỉ một default Published layout cho mỗi scope phù hợp.

---

## 7. DashboardLayoutItem

Table:

```text
dashboard_layout_items
```

Fields:

```text
id
layout_id
indicator_code
section

grid_x
grid_y
width
height
order_no

is_visible
collapsed
config_override_json

created_at
updated_at
```

Sections:

```text
MAIN
RIGHT_SIDEBAR
BOTTOM
FULL_WIDTH
```

Grid chuẩn:

```text
12 columns
```

Ví dụ:

```text
Revenue:
x=0 y=0 w=8 h=4

Signals:
x=8 y=0 w=4 h=8

Order Progress:
x=0 y=4 w=4 h=3

QA:
x=4 y=4 w=4 h=3
```

---

## 8. DisplayType

Frontend phải có registry chuẩn:

```text
KPI_CARD
PROGRESS_BAR
COMPARISON_BAR
GAUGE
COUNTER
STATUS_COUNTER
LINE_CHART
BAR_CHART
STACKED_BAR
TABLE
MATRIX
TREND
SIGNAL_LIST
TEXT
CUSTOM_COMPONENT
```

Renderer factory:

```text
DisplayType
   ↓
Renderer
```

Ví dụ:

```text
KPI_CARD       -> KpiCardRenderer
COMPARISON_BAR -> ComparisonBarRenderer
MATRIX         -> MatrixRenderer
BAR_CHART      -> BarChartRenderer
SIGNAL_LIST    -> SignalListRenderer
```

`CUSTOM_COMPONENT` chỉ dùng cho widget thực sự đặc thù.

Frontend phải có component registry, ví dụ:

```text
REVENUE_EXECUTIVE_SUMMARY -> RevenueSection
ORDER_PROGRESS_MATRIX      -> OrderProgressSection
QA_COMPARISON              -> QaComparisonSection
```

---

## 9. Rule contract

Input chuẩn:

```text
DashboardContext
- current_date
- period
- scope
- factory
- user
- filters
- indicator_config
- layout_config_override
```

Example:

```json
{
  "scope": "TONG",
  "period": "MONTH",
  "date": "2026-09-20",
  "factory": null,
  "filters": {}
}
```

Output chuẩn:

```json
{
  "status": "OK",
  "value": 74.2,
  "label": "74.2%",
  "items": [],
  "drilldown": {},
  "meta": {
    "last_calculated_at": "...",
    "data_freshness": "FRESH",
    "rule_version": "1"
  }
}
```

Allowed status:

```text
OK
EMPTY
WARNING
ERROR
STALE
```

Rule lỗi không được làm crash toàn Dashboard.

---

## 10. Migrate toàn bộ nội dung Dashboard hiện tại

### Revenue

```text
IndicatorCode:
REVENUE_EXECUTIVE_SUMMARY

Group:
REVENUE

DisplayType:
CUSTOM_COMPONENT hoặc COMPARISON_BAR

RuleCode:
REVENUE_EXECUTIVE_SUMMARY

Scope:
BOTH

Drilldown:
REVENUE_DETAIL
```

Config:

```json
{
  "periodOptions": ["MONTH", "YTD"],
  "showCorporateTotal": true,
  "preserveCurrentInteraction": true
}
```

Business behavior phải giữ:

Corporate:

```text
XN1
XN2
XN3
Tổng công ty
```

Factory:

```text
Selected XN
Tổng công ty
```

Daily Plan vs Actual chỉ ở drill-down.

Không được regression style/interact Revenue hiện tại.

---

### Order Progress

Indicator:

```text
ORDER_PROGRESS_MATRIX
```

Group:

```text
ORDER_PROGRESS
```

Display:

```text
MATRIX
```

Output target:

```text
                       On Time     Late
Sewing complete
FG receipt complete
```

Ưu tiên 1 widget 2x2 thay vì 4 indicator riêng.

---

### QA

Indicator:

```text
QA_COMPARISON
```

Group:

```text
QA
```

Display:

```text
BAR_CHART
```

Categories:

```text
Đầu chuyền
QC
Inline
Endline
Prefinal (Final)
```

Series:

```text
XN1
XN2
XN3
```

Metric:

```text
Total Defect Count
```

---

### Signals

Indicators:

```text
GOOD_NEWS
WARNING_SIGNALS
```

Display:

```text
SIGNAL_LIST
```

---

## 11. Bật / tắt

Hai tầng:

### Indicator master

```text
is_active
default_enabled
```

### Layout item

```text
is_visible
```

Interpretation:

- `is_active=false`: không dùng cho layout mới.
- `default_enabled`: default khi tạo layout.
- `is_visible`: hiện hay ẩn trên một layout cụ thể.

Không xóa Indicator chỉ vì không muốn hiện Dashboard.

---

## 12. Admin UI — Nhóm chỉ số

Route:

```text
/admin/dashboard/groups
```

Columns:

```text
Bật
Mã nhóm
Tên nhóm
Mô tả
Layout mode
Collapsible
Thứ tự
```

Actions:

```text
Create
Edit
Enable/Disable
Reorder
```

---

## 13. Admin UI — Chỉ số theo dõi Dashboard

Route:

```text
/admin/dashboard/indicators
```

Columns:

```text
Bật
Nhóm
Mã
Tên
Loại hiển thị
Rule
Scope
Drilldown
Source
```

Actions:

```text
Create
Edit
Duplicate
Enable/Disable
Preview
Test Rule
```

Editor sections:

```text
General
Display
Rule
Data
Drilldown
Advanced Config
```

---

## 14. Admin UI — Rule Registry

Route:

```text
/admin/dashboard/rules
```

Show:

```text
Rule Code
Rule Name
Module
Function
Version
Active
Input Contract
Output Contract
Last Test
```

Actions:

```text
Test Rule
Disable Rule
View Contract
```

Không cho upload executable code.

---

## 15. Admin UI — Layout Builder

Route:

```text
/admin/dashboard/layouts
```

Flow:

```text
Select layout
-> Clone/Create Draft
-> Edit
-> Preview
-> Publish
```

Layout:

```text
Left:
Available Indicators

Right:
Dashboard Canvas
```

Capabilities:

```text
drag indicator vào canvas
reposition
resize
move section
toggle visibility
preview Company
preview XN
preview Light
preview Dark
save draft
publish
```

---

## 16. Responsive

Desktop:

```text
dùng grid_x / grid_y / width / height
```

Tablet:

```text
wrap hợp lý, giữ ưu tiên width
```

Mobile:

```text
stack theo order_no
```

Không cần layout mobile riêng ở v1.

---

## 17. Theme

Mọi Dashboard renderer dùng semantic design tokens.

Tối thiểu:

```text
LIGHT
DARK
```

Layout Builder có:

```text
Preview Light
Preview Dark
```

Text phải tự tương phản với background theo theme/contrast logic.

Không thêm fixed color dependency mới.

---

## 18. Runtime API

Khuyến nghị v1:

```text
GET /api/dashboard/runtime
```

Params:

```text
scope
period
factory
```

Backend:

```text
resolve Published layout
resolve visible indicators
validate rules
execute rules
return positions + metadata + data
```

Response:

```json
{
  "layout": {},
  "items": [
    {
      "indicator": {},
      "position": {},
      "data": {}
    }
  ]
}
```

Sau này có thể lazy-load từng widget.

---

## 19. Cache

Indicator có thể có:

```text
refresh_mode
cache_seconds
```

Cache key tối thiểu:

```text
indicator_code
rule_version
scope
factory
period
relevant filters
```

Không cache sai scope/user permission.

---

## 20. Data freshness

Indicator metadata:

```text
data_freshness_requirement
```

Rule output meta:

```text
source_last_sync_at
last_calculated_at
freshness_status
```

Allowed:

```text
FRESH
STALE
UNKNOWN
```

Nếu stale, vẫn render nhưng phải có stale marker.

---

## 21. Permissions

Recommended:

```text
dashboard.view
dashboard.config_view
dashboard.config_manage
dashboard.layout_manage
dashboard.rule_test
dashboard.publish
```

ADMIN có toàn bộ config permissions.

PLANNER/VIEWER mặc định chỉ `dashboard.view`, trừ khi business yêu cầu khác.

Backend luôn enforce.

---

## 22. Audit

Events:

```text
DASHBOARD_GROUP_CREATE
DASHBOARD_GROUP_UPDATE

DASHBOARD_INDICATOR_CREATE
DASHBOARD_INDICATOR_UPDATE
DASHBOARD_INDICATOR_ENABLE
DASHBOARD_INDICATOR_DISABLE

DASHBOARD_LAYOUT_CREATE
DASHBOARD_LAYOUT_UPDATE
DASHBOARD_LAYOUT_PUBLISH
DASHBOARD_LAYOUT_RETIRE

DASHBOARD_RULE_TEST
```

Audit lưu:

```text
object
old/new config relevant
user
time
layout version
```

---

## 23. API proposal

Groups:

```text
GET    /api/admin/dashboard/groups
POST   /api/admin/dashboard/groups
PUT    /api/admin/dashboard/groups/{code}
```

Indicators:

```text
GET    /api/admin/dashboard/indicators
POST   /api/admin/dashboard/indicators
GET    /api/admin/dashboard/indicators/{code}
PUT    /api/admin/dashboard/indicators/{code}
POST   /api/admin/dashboard/indicators/{code}/preview
POST   /api/admin/dashboard/indicators/{code}/test
```

Rules:

```text
GET    /api/admin/dashboard/rules
GET    /api/admin/dashboard/rules/{code}
POST   /api/admin/dashboard/rules/{code}/test
```

Layouts:

```text
GET    /api/admin/dashboard/layouts
POST   /api/admin/dashboard/layouts
GET    /api/admin/dashboard/layouts/{id}
POST   /api/admin/dashboard/layouts/{id}/clone
PUT    /api/admin/dashboard/layouts/{id}
POST   /api/admin/dashboard/layouts/{id}/publish
POST   /api/admin/dashboard/layouts/{id}/retire
```

Runtime:

```text
GET /api/dashboard/runtime
```

---

## 24. Migration strategy

Không rewrite business logic hiện tại trước.

Thứ tự:

```text
1. Tạo metadata tables
2. Seed groups
3. Seed indicators
4. Seed default layouts giống Dashboard hiện tại
5. Wrap backend business functions thành Rule Registry
6. Tạo Renderer Factory
7. Switch Dashboard sang runtime metadata
8. Verify parity
9. Sau khi ổn mới bỏ hard-coded layout cũ
```

Backward compatibility:

- Revenue detail giữ nguyên.
- Dashboard hiện tại không được gián đoạn.
- Có thể giữ legacy fallback trong rollout đầu.
- Chỉ bỏ fallback sau khi metadata runtime ổn định.

---

## 25. Initial seed

Groups:

```text
REVENUE
ORDER_PROGRESS
QA
SIGNALS
```

Indicators:

```text
REVENUE_EXECUTIVE_SUMMARY
ORDER_PROGRESS_MATRIX
QA_COMPARISON
GOOD_NEWS
WARNING_SIGNALS
```

---

## 26. Example seed — Revenue

```json
{
  "indicator_code": "REVENUE_EXECUTIVE_SUMMARY",
  "indicator_name": "Doanh thu",
  "group_code": "REVENUE",
  "display_type": "CUSTOM_COMPONENT",
  "rule_code": "REVENUE_EXECUTIVE_SUMMARY",
  "data_source": "eGMF/PostgreSQL",
  "default_scope": "BOTH",
  "drilldown_type": "DRAWER",
  "drilldown_target": "REVENUE_DETAIL",
  "refresh_mode": "CACHED",
  "default_enabled": true,
  "is_active": true,
  "config_json": {
    "periodOptions": ["MONTH", "YTD"],
    "showCorporateTotal": true
  }
}
```

---

## 27. Definition of Done

Không được đánh Done nếu mới có UI.

Checklist:

```text
[ ] DashboardIndicatorGroup
[ ] DashboardIndicator
[ ] DashboardRuleRegistry
[ ] DashboardLayout
[ ] DashboardLayoutItem
[ ] migration/upgrade path
[ ] seed toàn bộ component hiện tại
[ ] enable/disable
[ ] DisplayType registry
[ ] Rule Registry execution
[ ] runtime metadata API
[ ] drag/drop layout
[ ] resize
[ ] Draft/Publish layout
[ ] Corporate layout
[ ] Factory layout
[ ] Revenue không regression
[ ] Order Progress metadata-backed
[ ] QA metadata-backed
[ ] Signals metadata-backed
[ ] Light/Dark compatible
[ ] permissions backend
[ ] audit
[ ] backend tests
[ ] frontend tests
[ ] no arbitrary Python execution
[ ] Published layout immutable
```

---

## 28. Automated tests

Backend:

```text
create indicator
invalid rule rejected
inactive rule rejected
unsupported DisplayType rejected
disabled indicator excluded
correct scope layout resolved
Published layout immutable
Draft editable
Publish supersedes old default
registered rule executes
rule exception isolated
stale status propagates
permissions enforced
```

Revenue regression:

```text
scope=TONG
-> XN1/XN2/XN3/Total

scope=XN2
-> XN2/Total

click Revenue
-> Revenue Detail opens
```

Layout:

```text
move Revenue in Draft
-> current Published runtime unchanged

Publish Draft
-> runtime uses new position
```

Theme:

```text
same layout renders Light/Dark
text remains readable
```

Frontend minimum:

```text
indicator list load
toggle
drag
resize
save draft
publish confirmation
renderer factory
unknown DisplayType fallback
rule error state
Revenue drilldown
Light/Dark preview
```

---

## 29. Implementation phases

### Phase A — Metadata foundation

```text
DB models
migration
permissions
groups
indicators
Rule Registry
seed
```

### Phase B — Runtime

```text
layout resolver
rule execution
output contract
renderer factory
```

### Phase C — Migrate current Dashboard

```text
Revenue
Order Progress
QA
Signals
```

### Phase D — Admin config

```text
Groups
Indicators
Rule Registry view/test
```

### Phase E — Layout Builder

```text
drag/drop
resize
preview
Draft/Publish
```

### Phase F — Hardening

```text
audit
cache
freshness
frontend tests
theme compatibility
```

---

## 30. Implementation constraints

1. Không rewrite business calculation chỉ để fit metadata.
2. Wrap rule đang đúng trước.
3. Không arbitrary Python execution.
4. Không upload Python từ Admin.
5. Không lưu position trong Indicator master.
6. Disable không phải delete.
7. Draft layout không hiển thị cho user thường.
8. Không regression Revenue.
9. Không hard-code group trong Dashboard frontend.
10. Không tạo component riêng cho mọi KPI nếu DisplayType generic đủ dùng.
11. `CUSTOM_COMPONENT` chỉ cho widget thực sự đặc thù.
12. Tất cả thành phần hiển thị trên Dashboard cuối cùng phải xuất phát từ metadata.

---

## 31. Expected result

Sau khi hoàn thành, thêm một chỉ số Dashboard mới sẽ theo flow:

```text
1. Viết/register backend Rule nếu cần.
2. Tạo Indicator metadata.
3. Chọn DisplayType.
4. Chọn scope/drilldown/config.
5. Add vào Draft Layout.
6. Drag/resize đến vị trí mong muốn.
7. Preview.
8. Publish.
```

Không cần sửa cấu trúc trang Dashboard chính cho các indicator thông thường đã được DisplayType hỗ trợ.
