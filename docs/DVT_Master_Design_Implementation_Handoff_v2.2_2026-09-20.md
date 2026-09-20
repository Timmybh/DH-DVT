# DVT — MASTER DESIGN & IMPLEMENTATION HANDOFF v2

**Project:** Bảng điều hành DVT  
**Repository reviewed:** `Timmybh/DH-DVT`  
**As-built baseline commit:** `7755ada616904954f5f446e14ef90ec414c7fcc3`  
**Revenue baseline commit:** `aac6a36a23e7b49d2b00d01b8d13a4c2ce45991f`  
**Review date:** 2026-09-20  
**Purpose:** Replace fragmented implementation assumptions with one authoritative implementation handoff that distinguishes the approved business design from the current code state.

---

# 0. How to use this document

This document has two layers:

1. **AS-BUILT** — what is actually present in the current repository.
2. **TARGET DESIGN** — the approved behavior that the implementation must converge to.

A feature is **not Done** merely because a screen exists. A capability is Done only when the required **Data Model + Backend + UI + Validation/Test** coverage is complete.

Do not remove older design documents yet. This file is the implementation control document that should be used to reconcile them.

The implementation must not regress the newly accepted Revenue presentation and interaction described in section 4.

---

# 1. Executive findings after repository review

The latest code has materially improved the Planning UI:

- Planned is now an Excel-like grid rather than Kanban cards.
- Unplanned is a grid with filters.
- Planned grouping follows `Factory -> Line -> Rows`.
- Drag/drop exists with confirmation.
- Exclusive edit session, heartbeat, draft, Undo/Redo, Recheck, Commit, Issue, Calendar and version comparison exist in partial or substantial form.
- Revenue main-dashboard interaction has been changed toward the intended executive summary model.

However, the implementation still does **not** represent the complete approved Planning design.

The biggest gaps are:

1. **No real configurable Column Configuration / Formula Definition master.**
2. **No general formula expression engine and dependency graph.**
3. Current calculation logic is hard-coded for a small number of fields.
4. Several Planning columns are only presentation references to imported Excel `grid` JSON, not first-class governed Planning values.
5. Formula behavior from the source workbook is not fully implemented/versioned.
6. `PREVIOUS_SEQUENCE` exists as a hard-coded calculation concept, not a configurable semantic reference engine.
7. Capacity Definition and Machine Capacity master capabilities are not implemented.
8. Resource reservation/release and Resource Release Schedule are not implemented.
9. Actual-to-Plan mapping, durable mapping tables, actual snapshot history, yearly retention/carry-forward are not implemented.
10. Dashboard Order Progress is still risk-oriented and does not yet match the approved On Time/Late completion structure.
11. QA executive dashboard is not implemented to the approved five-category design.
12. Auth has improved, but token revocation/session hardening remains limited.

These gaps must be treated as implementation work, not UI polish.

---

# 2. Current repository — AS-BUILT assessment

## 2.1 Planning screen

Current files include:

- `frontend/src/pages/Planning.tsx`
- `frontend/src/components/planning/PlannedGrid.tsx`
- `frontend/src/components/planning/UnplannedPanel.tsx`
- `frontend/src/components/planning/PendingDropModal.tsx`
- `frontend/src/components/planning/ValidationPanel.tsx`
- `frontend/src/lib/planColumns.ts`
- `frontend/src/lib/draft.ts`
- `app/api/planning.py`
- `app/services/planning_engine.py`
- `app/services/planning_service.py`
- `app/models/planning.py`

### What is correct and should be preserved

- Main Planning is a **grid/table**, not a Kanban.
- Planned and Unplanned are vertically separated.
- Planned supports horizontal scrolling and frozen columns.
- Rows can be grouped `Factory -> Line`.
- Sort/filter exists.
- Row selection and expandable detail exist.
- Drag/drop is part of the grid interaction.
- Unplanned supports XN/customer/season/sport/PO/style/model/search-oriented filtering.
- Known factory and Unassigned are distinguished.
- Edit Mode is exclusive.
- Draft operations are not immediately committed.
- Recheck and Commit are separate.
- Version Issue is separate from Commit.
- Calendar hierarchy Company -> XN -> Line exists.
- Multi-line notation and transfer structures exist at data/validation level.

### What is incomplete

`frontend/src/lib/planColumns.ts` currently defines visible columns, but it is **presentation metadata only**. It is not the approved business-level Column Configuration capability.

Example current behavior:

- `OFF_DAYS` is calculated directly in frontend with a helper.
- Worker/Fabric Ready/ACC Ready/SOT/etc. are read from imported `ref/grid` values.
- There is no persisted definition saying whether a column is `Manual Input`, `Select from List`, or `Calculated`.
- There is no effective-dated/versioned formula definition.
- There is no formula publication lifecycle.
- There is no formula dependency graph master.
- There is no formula preview/test UI as designed.

Therefore, the current visible grid must be retained but the calculation architecture behind it must be rebuilt/extended.

---

## 2.2 Current Planning calculation engine

`app/services/planning_engine.py` currently hard-codes calculation logic for a small set of fields.

Current calculated fields include approximately:

```text
total_day
begin_prod_date
end_prod_date
warehouse_date
```

Current known functions include:

```text
calc_total_day(quantity, capacity)
calc_begin(previous_row, calendar, factory, line)
calc_end(begin, total_day, calendar, factory, line)
```

This is useful scaffolding, but it is **not the approved generic Formula Engine**.

### Current mismatch

Approved:

```text
Column Formula Definition
    -> Dependency Template
    -> Runtime Cell Dependency
```

Current:

```text
if field == "total_day": ...
elif field == "begin_prod_date": ...
elif field == "end_prod_date": ...
```

The latter must not become the long-term architecture.

---

## 2.3 Current Working Calendar

Current code in `app/services/calendar.py` correctly implements several approved principles:

```text
Company -> XN -> Line
more-specific scope wins
WORKING / OFF / OVERTIME
NEXT_WORKING_DAY
PREVIOUS_WORKING_DAY
ADD_WORKING_DAYS
```

`OFF_DAYS` is kept separate from actual calendar OFF status.

This foundation should be preserved.

Still required later:

- explicit annual calendar administration usability;
- shutdown/business exception categorization if needed;
- effective-date/version trace for calendar changes;
- calculation trace showing which calendar rule produced a date result.

---

## 2.4 Current Revenue implementation

Current implementation has moved in the correct direction and should be treated as the new baseline.

Relevant files:

- `frontend/src/components/RevenueSection.tsx`
- `frontend/src/components/RevenueDetail.tsx`
- `app/services/dashboard.py`
- `tests/test_revenue_summary.py`

Automated tests already verify:

- Corporate view: `XN1 + XN2 + XN3 + Total Company`.
- Factory view: `Selected XN + Total Company`.
- Total Company remains the corporate total, not the selected XN total.
- Month and YTD modes are distinct.

This interaction must not be reverted to the previous three-gauge + main daily chart layout.

See section 4 for authoritative Revenue UI behavior.

---

# 3. Information architecture

Top-level functional separation:

```text
Dashboard
Planning
Administration
```

Recommended Planning contextual functions:

```text
Planning
├── Operational Plan
├── Column Configuration
├── Capacity Definition
├── Machine Capacity
├── Working Calendar
├── Formula Explanation
├── Resource Release Schedule
├── Version / Compare
└── Mapping / Reconciliation (contextual or later operational screen)
```

Avoid creating many unrelated top-level menus if the functions are fundamentally Planning configuration/control.

Administration remains for:

```text
Sync Log
Users
Roles / Permissions
Audit
SSO
System-level configuration
Style / Theme Management
```

---

# 4. Dashboard — approved target

Dashboard has two perspectives:

```text
Tổng công ty
Xí nghiệp
```

The selector may offer:

```text
Tổng công ty | XN1 | XN2 | XN3
```

The Dashboard main page is an **executive summary**, not a deep analytical report.

Primary areas:

```text
Revenue
Order Progress
QA
Good News / Warning
```

Technical sync details must not dominate the executive screen.

---

# 4.1 Revenue — AUTHORITATIVE CURRENT DESIGN

This section incorporates the latest user-approved presentation and Claude implementation direction.

## Corporate perspective

Show a 100%-style achievement comparison for:

```text
XN1
XN2
XN3
Tổng công ty
```

Each row must display at least:

```text
Achievement %
Actual Revenue Value
```

The bar represents performance against 100% of the selected revenue plan.

Concept:

```text
XN1           [████████░░]  80%    Actual 8.1
XN2           [██████░░░░]  60%    Actual 6.4
XN3           [█████████░]  92%    Actual 9.3
Tổng công ty  [███████░░░]  74%    Actual 23.8
```

`Tổng công ty` is computed from all applicable enterprises, independent of which factory is selected elsewhere.

## Factory perspective

If scope = `XN2`, show only:

```text
XN2
Tổng công ty
```

Do not show XN1/XN3 in this perspective.

Purpose:

```text
Selected Factory vs Corporate Total
```

## Period

Main executive summary may support:

```text
Current Month
YTD / Lũy kế
```

Do not confuse YTD with daily trend.

## Click interaction

Clicking a Revenue row opens Revenue detail/drill-down for the selected scope.

Only inside drill-down should the user see:

```text
Plan
Actual
Remaining
Achievement %
daily trend
monthly trend as appropriate
daily Plan vs Actual chart
factory detail table
```

### Critical rule

The detailed chart:

```text
Kế hoạch vs Thực hiện theo ngày
```

must **not** appear on the main Dashboard.

It belongs inside Revenue detail after click.

---

# 4.2 Order Progress — target design

Current Dashboard progress/risk presentation is not the final approved design.

Main Order Progress must explicitly compare:

```text
On Time
Late
```

Each group has two child counters:

```text
# PO sewing complete
# PO finished-goods receipt complete
```

Concept:

```text
                    On Time       Late
Sewing complete        128          17
FG receipt complete    112          11
```

The data basis must use operational actuals:

```text
Sewing Output / SL may ra
Finished-goods receipt / SL TP đã nhập
```

Some customers are not managed for warehouse receipt; configuration must allow those customers to be excluded from the FG receipt completion requirement.

Risk alerts such as material shortage may remain in warning/drill-down areas but must not replace the approved Order Progress executive KPI.

---

# 4.3 QA — target design

QA main comparison categories:

```text
Đầu chuyền
QC
Inline
Endline
Prefinal (Final)
```

Inline, Endline and Prefinal include relevant recheck/rework inspections.

Current primary defect KPI:

```text
Total Defect Count
```

Do **not** use defective-product rate or AQL pass/fail as the main KPI in the current scope.

Reason: one inspected product can have multiple defect records/categories; unit-level defective-product grouping requires deeper traceability.

Main QA comparison:

```text
XN1 vs XN2 vs XN3
```

Click a category or factory to drill into enterprise/category detail.

Exclude:

```text
CUTTING_BTP_KiemTraChatLuong*
```

from current QA dashboard scope.

---

# 4.4 Good News / Warning

Keep the right-side two-zone concept:

```text
Good News
Warning / Critical
```

Examples:

Good:
- early production completion;
- favorable revenue progress;
- relevant operational improvement.

Warning/Critical:
- late delivery risk;
- material readiness risk;
- stale actual data;
- major mapping exceptions.

Do not allow routine technical sync status to overwhelm business signals.

---


# 4.5 Style / Theme Management — approved addition

The system must support centralized UI style/theme management.

## Minimum themes

At least two built-in themes are required:

```text
LIGHT
DARK
```

Recommended future extensibility:

```text
SYSTEM
LIGHT
DARK
CUSTOM
```

`SYSTEM` means follow the operating system/browser preference when enabled.

## Theme behavior

Theme selection applies consistently across the entire application:

```text
Dashboard
Planning
Administration
Dialogs / drawers
Tables / grids
Charts
Validation states
Warnings / alerts
Drill-down screens
```

Do not implement independent hard-coded color schemes per page.

Use a shared design-token/theme system.

Minimum semantic tokens:

```text
background
surface
surfaceElevated
textPrimary
textSecondary
textMuted
border
primary
primaryContrast
success
warning
danger
info
disabled
focus
selected
hover
```

Components should consume semantic tokens rather than fixed literal colors.

## Automatic text contrast

The system must automatically choose or validate foreground/text color so that text remains visually opposite/contrasting against its background.

Examples:

```text
dark background -> light text
light background -> dark text
```

For configurable colors, calculate contrast from the actual background color rather than relying only on the theme name.

Recommended rule:

```text
foreground = chooseContrastColor(background)
```

The implementation should use luminance/contrast-ratio logic and target WCAG-readable contrast.

Do not allow cases such as:

```text
dark navy background + dark gray text
light gray background + white text
warning yellow + low-contrast pale text
```

Charts, badges, buttons, table selections and alert states also require readable foreground colors.

## Theme persistence

Theme preference should be stored per user when authenticated.

Suggested setting:

```text
UserPreference.Theme = LIGHT | DARK | SYSTEM
```

If a user preference has not been saved:

```text
use organization/system default
```

If system default is `SYSTEM`, resolve from browser/OS preference.

A user switching theme should see the UI update immediately without logout/reload where technically practical.

## Administration

Theme management belongs under:

```text
QUẢN TRỊ
  -> Cấu hình hệ thống
     -> Giao diện / Style
```

Administration should support at least:

```text
Default Theme
Allow User Theme Override: Yes/No
Available Themes
Preview Light
Preview Dark
```

If custom enterprise branding is added later, manage it here rather than editing source code.

Possible future branding tokens:

```text
Logo
Primary Color
Accent Color
Header Background
Sidebar Background
Card Radius
Density
```

Do not expose arbitrary CSS to normal administrators.

## User-level control

If `Allow User Theme Override = Yes`, provide a theme selector in the user/header menu:

```text
Sáng
Tối
Theo hệ thống
```

Theme selection is a user preference, not an authorization role.

## Implementation guidance

Prefer CSS variables/design tokens, for example:

```css
:root[data-theme="light"] {
  --bg: ...;
  --surface: ...;
  --text-primary: ...;
}

:root[data-theme="dark"] {
  --bg: ...;
  --surface: ...;
  --text-primary: ...;
}
```

React/Tailwind components should reference semantic theme classes/variables.

Avoid large-scale patterns such as:

```text
bg-slate-900
text-white
border-slate-700
```

being independently hard-coded across every component without theme abstraction.

Existing Revenue styling and interaction that has already been accepted must be preserved while migrating it onto shared theme tokens.

## Acceptance criteria

```text
[ ] Light theme exists
[ ] Dark theme exists
[ ] User can switch themes when permitted
[ ] Theme persists for the user
[ ] Admin can choose system default theme
[ ] All three main areas follow the same theme
[ ] Revenue view/interactions are unchanged functionally
[ ] Planning grids remain readable in both themes
[ ] Tables/charts/tooltips/modals use theme tokens
[ ] Foreground text has automatic/readable contrast against configurable backgrounds
[ ] Warning/Success/Error states remain distinguishable in both themes
[ ] No major component depends exclusively on fixed light-only or dark-only colors
```


# 5. Planning screen — authoritative view

Planning is a spreadsheet-like operational planning grid.

It is **not a Kanban board**.

Layout:

```text
┌─────────────────────────────────────────────────────────────┐
│ Planned / Operational Plan                                  │
│ Grid: Factory -> Line -> Planning Rows                      │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│ Unplanned / Chưa lên KH                                     │
│ Grid + filters                                              │
└─────────────────────────────────────────────────────────────┘
```

## Planned grouping

```text
XN1
  Line 1
    Row...
    Row...
  Line 2
    Row...
XN2
...
```

Factory and Line groups must support expand/collapse.

## Grid behavior

Required:

```text
horizontal scroll
frozen key columns
column filtering
sorting
row selection
row status/risk highlighting
cell validation highlighting
expandable row detail
drag/drop in Edit Mode
```

Sorting must not redefine business sequence.

`virtualSequence` / persisted business sequence is authoritative for sequence-dependent formulas.

---

# 6. Planning columns

The planning grid must preserve the source workbook business content.

Minimum field set:

```text
FACTORY
LINE
PO_DATE
SPORT
SEASON
PO_NUMBER
STYLE_CC
MODEL_CODE
DESCRIPTION
CUSTOMER
QUANTITY
WORKER
CAPACITY
TOTAL_DAY
OFF_DAYS
FABRIC_READY
ACC_READY
NO_ISSUE
DATE_ISSUE
WORKING_DAY
SOT
TOTAL_SOT
BEGIN_PROD_DATE
END_BEGIN_DATE
OUTPUT_DATE
END_PROD_DATE
BEGIN_WAREHOUSE_IMPORT
END_WAREHOUSE_IMPORT
CHD
EHD_ETD
AHD
ON_TIME
```

The implementation may internally normalize names, but the UI/data dictionary must make the workbook mapping explicit.

### Important

A calculated field must not disappear merely because it is derived.

A source/reference field must not be permanently trapped in opaque `grid JSON` if it later becomes a governed Planning field.

Use first-class columns or governed extension fields when the value participates in:

```text
calculation
filtering
validation
audit
version comparison
mapping
business reporting
```

---

# 7. Column Configuration — MANDATORY, currently missing

Replace the idea of a programmer-only Formula Builder with a business-facing Column Configuration table.

Minimum UI:

| Planning Column | Input Type | List Source | Formula | Sample Result |
|---|---|---|---|---|
| FACTORY | Select from List | Factory | — | XN1 |
| LINE | Select from List | Production Line | — | 07 |
| QUANTITY | Manual Input | — | — | 10,000 |
| CAPACITY | Select/Calculated | Capacity Definition | — | 1,200 |
| TOTAL_DAY | Calculated | — | `QUANTITY / CAPACITY` | 8.33 |
| BEGIN_PROD_DATE | Calculated | — | `PREVIOUS_SEQUENCE.END_PROD_DATE + 1 Working Day` | 21/09/2026 |

Input types:

```text
Manual Input
Select from List
Calculated
```

`Select from List` uses business object names, not physical database table names.

Examples:

```text
Factory
Production Line
Customer
Style
Model
Season
Sport
Worker Group
Machine Group
```

Dependent selections are allowed.

Example:

```text
FACTORY = XN1
-> LINE list only includes lines belonging to XN1
```

Metadata such as version/effective dates should exist but should not clutter the primary business UI.

---

# 8. Formula Definition architecture — MANDATORY

The current hard-coded `if field == ...` model is insufficient.

Target:

```text
Column Definition
    |
    +-- InputType
    +-- FormulaDefinitionId
    +-- Effective Version
             |
             v
Formula Definition
    |
    +-- expression
    +-- result type
    +-- references
    +-- calendar dependency
    +-- rounding policy
    +-- status
             |
             v
Dependency Template
             |
             v
Runtime Calculation
```

Minimum lifecycle:

```text
Draft
Validate
Preview/Test
Publish
Retire/Supersede
```

Validation before Publish:

```text
syntax validation
field/reference validation
type validation
circular dependency detection
sample calculation
```

A published formula version must be immutable.

Historical Planning Versions must retain the formula version used for their calculations.

---


# 8.1 Formula Definition Version 1 — canonical workbook values

The first published formula version must not contain only the expression. It must also retain the **approved canonical workbook reference values** used to verify the formula.

Purpose:

```text
Formula definition
+ canonical input set
+ canonical expected result
= executable business specification
```

The canonical values become part of the acceptance baseline for that formula version.

Minimum Formula Definition fields:

```text
FormulaCode
PlanningColumn
Version
Status
Expression
ResultType
RoundingPolicy
CalendarPolicy
ReferenceType
Scope
SourceColumn
EffectiveFrom
EffectiveTo
BusinessDescription
SourceDocument
SourceSheet
SourceCellOrColumn
CanonicalInputs
CanonicalExpectedResult
Tolerance
VerifiedBy
VerifiedAt
VerificationNote
```

Recommended storage for the canonical case:

```json
{
  "inputs": {
    "QUANTITY": 925,
    "CAPACITY": 1000
  },
  "expected": {
    "TOTAL_DAY": 0.925
  }
}
```

Another example after workbook verification:

```json
{
  "inputs": {
    "TOTAL_DAY": 0.925
  },
  "expected": {
    "OFF_DAYS": 0.1321428571
  },
  "display_expected": 0.132
}
```

The values above are examples only until the workbook source/formula has been verified. Once verified, replace them with the approved workbook-derived canonical values and publish them as Version 1.

## Version 1 rule

Before a formula is published as `v1`:

```text
1. Extract or confirm the workbook formula.
2. Select representative real workbook rows.
3. Store canonical inputs.
4. Store workbook expected outputs.
5. Run the new engine.
6. Compare Engine Result vs Canonical Expected Result.
7. Publish only when the comparison passes the accepted tolerance.
```

Do not publish a formula version based only on a developer-written expression.

## Canonical test cases

A Formula Version may store more than one canonical case.

Recommended minimum:

```text
normal case
boundary case
zero/null case
rounding threshold case
calendar/off-day case (for date formulas)
override case where relevant
PREVIOUS_SEQUENCE case where relevant
```

Example structure:

```text
FormulaDefinition
  v1
    CanonicalCase #1
    CanonicalCase #2
    CanonicalCase #3
```

Each case stores:

```text
InputSnapshot
ExpectedResult
ExpectedDisplayValue
Tolerance
SourceRowReference
Comment
```

These cases must automatically become backend tests.

## Initial formulas targeted for Version 1

Create Version 1 definitions for:

```text
TOTAL_DAY
OFF_DAYS
BEGIN_PROD_DATE
END_PROD_DATE / workbook END BE. DATE equivalent
ON_TIME
```

### TOTAL_DAY v1

Current workbook evidence indicates the raw value must be preserved:

```text
TOTAL_DAY_RAW = QUANTITY / CAPACITY
```

Do not round the stored raw result unless the verified workbook formula proves otherwise.

If a separate integer scheduling duration is needed, create a separate derived value such as:

```text
SCHEDULE_DURATION_DAY = CEILING(TOTAL_DAY_RAW)
```

Do not overwrite `TOTAL_DAY_RAW`.

### OFF_DAYS v1

Current workbook evidence shows a real example approximately:

```text
TOTAL_DAY = 0.925
OFF_DAYS ≈ 0.132
```

which is consistent with:

```text
OFF_DAYS_RAW = TOTAL_DAY_RAW / 7
```

Therefore the old assumption “round TOTAL_DAY first, then divide by 7” must **not** be published as v1 unless the workbook formula later proves it.

The exact precision/display rounding must be taken from the workbook and stored in:

```text
RoundingPolicy
CanonicalExpectedResult
```

### BEGIN_PROD_DATE v1

Do not publish until the actual workbook formula is extracted/confirmed.

The formula definition must preserve any workbook-specific constants such as:

```text
+1/9
+1
```

if they are truly part of the source formula.

Store the original workbook formula text alongside the normalized system expression.

### END_PROD_DATE / END BE. DATE v1

Do not publish until the workbook formula is verified.

If the workbook adds fractional day values directly, preserve that behavior in the canonical test and do not force an integer-day scheduling simplification into the workbook-equivalent field.

If the system requires a separate operational scheduling date, define a separate derived formula rather than altering the workbook-equivalent formula.

### ON_TIME v1

Candidate workbook rule currently approved for verification:

```text
IFERROR(
    IF((EHD/ETD - CHD) > 4.9,
       "DELAY",
       IF((EHD/ETD - CHD) < -4,
          "ADVANCE",
          "ON TIME"
       )
    ),
    ""
)
```

Before publishing v1, confirm the exact source columns and workbook formula.

Canonical cases must include at least:

```text
difference > 4.9       -> DELAY
difference = 4.9       -> ON TIME
difference < -4        -> ADVANCE
difference = -4        -> ON TIME
missing/invalid input  -> ""
```

## Formula Version immutability

After v1 is Published:

- expression cannot be edited in place;
- canonical expected values cannot be overwritten;
- correction creates `v2`;
- historical Planning Versions continue to reference the formula version originally used.

This prevents a future formula change from silently changing the meaning of historical plans.


# 9. Formula rules

## 9.1 TOTAL_DAY

Business rule:

```text
TOTAL_DAY = QUANTITY / CAPACITY
```

Planning scheduling rule:

```text
rounded scheduling days = CEILING(TOTAL_DAY)
```

If:

```text
QUANTITY > 0
```

then minimum scheduled duration:

```text
1 day
```

Do not lose the raw/precision value if it is useful for explanation, but scheduling uses the approved whole-day rule.

---

# 9.2 OFF_DAYS

This is a workbook business formula and is **not** the same as non-working days resolved from Working Calendar.

Use rounded TOTAL_DAY as the business input where required by the workbook logic.

Base rule:

```text
OFF_DAYS = TOTAL_DAY / 7
```

Rounding:

```text
fraction < 0.5 -> down
fraction >= 0.5 -> up
```

Examples:

```text
3 / 7 = 0.43 -> 0
4 / 7 = 0.57 -> 1
8 / 7 = 1.14 -> 1
11 / 7 = 1.57 -> 2
```

Do not merge this concept with actual holiday/Sunday resolution.

---

# 9.3 PREVIOUS_SEQUENCE

Never reference the physical previous rendered row.

Semantic reference:

```text
ReferenceType = PREVIOUS_SEQUENCE
Scope = SAME_LINE
SourceColumn = END_PROD_DATE
```

Example:

```text
BEGIN_PROD_DATE =
PREVIOUS_SEQUENCE.END_PROD_DATE + 1 Working Day
```

`PREVIOUS_SEQUENCE` means the previous production sequence in the relevant business lane.

Sorting/filtering the UI does not change it.

After drag/drop or move to another line, the runtime sequence must be rebuilt and all affected semantic dependencies recalculated.

---

# 9.4 BEGIN / END date formulas

The exact source workbook formulas must be captured from the workbook data dictionary / Sheet1 and stored as versioned Formula Definitions.

Known approved constraints:

- `END BE. DATE` uses rounded TOTAL_DAY behavior.
- `BEGINING P. DATE` must preserve workbook-specific constants/adjustments including the approved `+1/9` and fixed `+1` behavior where applicable.
- Calendar-sensitive date movement must use Working Calendar functions rather than raw calendar-day addition when the workbook/business rule specifies Working Day.

Do not “simplify” legacy constants without business confirmation.

Formula Explanation must show the original business rule and the normalized system expression.

---

# 9.5 ON_TIME

Preserve the workbook business rule:

```text
IFERROR(
    IF((EHD/ETD - CHD) > 4.9,
       "DELAY",
       IF((EHD/ETD - CHD) < -4,
          "ADVANCE",
          "ON TIME"
       )
    ),
    ""
)
```

This formula must be versioned and explainable.

Do not replace it with a different threshold merely because another Dashboard risk rule exists.

Planning `ON_TIME` and Dashboard delivery-risk logic may be related but are not automatically the same business rule.

---

# 9.6 Formula Explanation

Users must be able to inspect each calculated column:

```text
Business definition
Formula
Formula version
Input fields
Semantic references
Calendar effects
Rounding
Example inputs
Example result
Input type vs calculated type
Effective date/version history
```

This is essential for acceptance because Planning currently comes from a business-owned workbook.

---

# 10. Dependency Engine — MANDATORY

Example:

```text
TOTAL_DAY
depends on:
  QUANTITY
  CAPACITY
```

Cross-row:

```text
BEGIN_PROD_DATE
depends on:
  PREVIOUS_SEQUENCE.END_PROD_DATE
  Working Calendar
```

Architecture:

```text
Published Formula
-> Dependency Template
-> Runtime dependency resolution
-> affected-cell recalculation
```

Do not persist every physical cell relationship in advance.

Requirements:

- detect circular formula dependencies before publish;
- runtime loop guard for dynamic references;
- recalculate only downstream affected values during editing when practical;
- full Recheck recomputes all relevant formulas;
- stale calculations based on an older `SequenceRevision` must be discarded.

---

# 11. Calculated value override

Calculated cells may be manually overridden only in controlled Edit Mode.

Cell state:

```text
CalculatedValue
OverrideValue
EffectiveValue
ValueSource
```

Rule:

```text
if ValueSource == OVERRIDE:
    EffectiveValue = OverrideValue
else:
    EffectiveValue = CalculatedValue
```

All downstream formulas use `EffectiveValue`.

UI:

```text
orange border/highlight
!
tooltip showing auto value vs override value
Return to Auto Calculate
```

Audit:

```text
who
when
column
old calculated value
override value
reason if required
formula version
```

If inputs later change and auto result differs, do not silently destroy the override.

---

# 12. Recheck All Plan

Recheck is not a cosmetic validation action.

It is the authoritative full-plan calculation and validation gate.

Minimum sequence:

```text
Resolve Column/Formula versions
Rebuild business sequence
Resolve PREVIOUS_SEQUENCE
Recalculate formulas
Resolve Working Calendar
Validate date logic
Validate line availability
Validate capacity
Validate transfer
Validate override state
Validate mapping-relevant references
Generate issues
Generate CalculationTraceId
```

Levels:

```text
PASS
WARNING
ERROR
```

Commit rules:

```text
ERROR -> blocked
WARNING -> only if approved by business rule
PASS -> allowed
```

Recheck result must bind to:

```text
EditSessionId
DraftRevision
SequenceRevision
FormulaVersionSet
CalculationTraceId
```

Any edit after Recheck invalidates the prior result.

Commit must revalidate server-side; current code already does this and should retain it.

---

# 13. Working Calendar

Hierarchy:

```text
Company
-> Xí nghiệp
-> Production Line
```

Priority:

```text
Line > XN > Company
```

Statuses:

```text
WORKING
OFF
OVERTIME
```

Company configuration must support:

```text
weekly non-working days
annual holidays/date OFF
overtime/extra working day
shutdown/exception where required
```

The default must include at least Sunday OFF, but configuration is business-owned.

Minimum functions:

```text
IS_WORKING_DAY(Date, Scope)
NEXT_WORKING_DAY(Date, Scope)
PREVIOUS_WORKING_DAY(Date, Scope)
ADD_WORKING_DAYS(Date, N, Scope)
```

`+1 Working Day` skips resolved OFF days.

An OVERTIME exception at a more specific scope can make a broader OFF day working.

---

# 14. Capacity Definition — MANDATORY, currently absent

Capacity cannot remain just a number imported from Excel or manually keyed.

Create a governed Capacity Definition master.

Minimum dimensions:

```text
Factory
Line / Line Group
Style / CC
Model Code
Process / Product Family
Worker Count
Working Day Minutes
Standard Capacity (pcs/day)
Effective From
Effective To
Source / Owner (IE / LEAN / CI)
Status
Version
Notes
```

Resolution:

```text
most specific valid active definition
-> fallback rules if defined
-> manual override only with audit
```

Planning must show where Capacity came from.

Example:

```text
Capacity 1,250 pcs/day
Source: IE Capacity Definition v12
Effective: 01/09/2026
```

---

# 15. Machine Capacity — MANDATORY, currently absent

Machine constraints are first-class Planning constraints.

Minimum model:

```text
Machine Type / Model
Machine Group
Process / Operation
Compatible Style
Compatible Model
Compatible Product Family
Nominal Speed / Output
Efficiency / OEE factor
Setup / Changeover
Planned Downtime
Maintenance Status
Machine Quantity
Bottleneck indicator
Line impact
Effective dates
```

Planning must be able to detect a plan that is labor-feasible but machine-infeasible.

---

# 16. Worker / labor model

Planning must not treat Worker only as display data imported from the source workbook.

Target capabilities:

```text
required worker
available worker
line/team assignment
effective date
temporary movement if needed
labor reservation
labor release
```

Capacity Definition and Labor availability must remain distinguishable.

---

# 17. Multi-line assignment

Presentation:

```text
7 + 8 + 4
```

means concurrent production.

Do not use the display string as core data.

Persist structured line assignments.

Total capacity:

```text
Capacity(Line 7)
+ Capacity(Line 8)
+ Capacity(Line 4)
```

But line-level detail remains available for:

```text
actual tracking
capacity contribution
resource reservation
resource release
mapping
```

---

# 18. Line transfer

Presentation:

```text
2 ==> 1
```

Target data:

```text
FromLine
ToLine
TransferEffectiveDate
PlannedRemainingQty
TransferStatus
```

Suggested statuses:

```text
PLANNED
EFFECTIVE
CANCELLED
```

Transfer changes future capacity and sequence relationships from its effective date.

Do not automatically rewrite planning dates without validation/recheck.

---

# 19. Drag/drop interaction

Supported structural actions:

```text
move earlier/later in same line
move between lines
move between factories if permitted
Unplanned -> Planned
Planned -> Unplanned
```

Every meaningful drop:

```text
Pending Drop
-> Confirm
or
-> Cancel
```

Cancel restores exact original state.

A confirmed drop in Edit Mode changes Draft State only.

After structural change:

```text
rebuild virtual sequence
increment SequenceRevision
invalidate stale formula results
recalculate affected dependencies
mark plan Needs Recheck
```

---

# 20. Unplanned panel

Unplanned is a grid, not a card list.

Required distinction:

```text
Known Factory
Unassigned Factory
```

Filters:

```text
Factory/XN:
  All
  XN1
  XN2
  XN3
  Unassigned

Customer
Season
Sport
PO
Style/CC
Model
Free-text search
```

Filters should remain stable during the Edit Session.

Case behavior:

### Known Factory

When dragged to Planned:

- retain known factory by default;
- user chooses/validates destination line.

### Unassigned

When dragged to Planned:

- destination Factory/XN must be explicitly selected/resolved;
- do not silently infer without a governed rule.

Planning status, Factory assignment and Mapping status remain independent dimensions.

---

# 21. Draft / Undo / Redo / Offline

Preserve:

```text
OriginalState
CurrentDraftState
UndoStack
RedoStack
DraftRevision
SequenceRevision
EditSessionId
ValidationState
```

Support:

```text
Ctrl+Z
Ctrl+Y
Ctrl+Shift+Z
Revert All
```

Offline behavior:

```text
Keep local Draft
Keep Undo/Redo
Disable Recheck
Disable Commit
```

Persistent browser recovery should use IndexedDB or equivalent robust local storage for draft recovery.

Never auto-write an offline draft after session expiry.

Reacquire session, restore, Recheck, then Commit.

---

# 22. Versioning / Issue

Keep immutable committed Planning Versions.

Flow:

```text
Edit Draft
-> Recheck
-> Commit immutable version
-> separate Issue action
```

A committed version is not automatically operationally issued.

Every Version should retain:

```text
version code
parent/base
created by
created at
formula version set
calendar version/snapshot reference
row count
Recheck result
CalculationTraceId
note
status
```

Issue:

- only eligible Recheck state;
- previous issued plan becomes superseded according to policy;
- audit who issued and when.

---

# 23. Resource reservation & release — MANDATORY, currently absent

Planning must create explicit resource reservations where capacity is consumed.

Two key concepts:

```text
Labor Reservation / Labor Release
Machine Reservation / Machine Release
```

When a planned operation ends or no longer needs the resource, reserved capacity becomes available again.

Resource release must be derived from Planning, not manually duplicated.

---

# 24. Resource Release Schedule

Weekly view.

Columns:

```text
Date
  Labor
  Machine
```

Rows:

```text
XN group
  Line child
```

Example:

```text
              Mon          Tue          Wed
           Labor Mach   Labor Mach   Labor Mach
XN1
  Line 1      12    3      5    1      0    2
  Line 2       8    0      7    2      3    0
XN2
  ...
```

XN supports collapse/expand.

This view answers:

```text
When will labor capacity be released?
When will machine capacity be released?
Which line/factory receives capacity headroom?
```

---

# 25. Actual integration and mapping — MANDATORY, currently largely absent

eGMF internal IDs must never be treated as durable cross-system business identity.

Use a stable composite business identity / fingerprint.

Retain source internal IDs only as auxiliary references.

Mapping record should preserve:

```text
SourceSystem
SourceId (auxiliary)
StableBusinessKey / Fingerprint
PO
Style/CC
Model
Customer
Factory
Line
relevant dates/attributes
source snapshot
mapping status
mapping confidence/reason
mapped Planning object/version
created/reconciled timestamps
```

If eGMF IDs change after migration/rebuild/reimport, the system must be able to rematch.

---

# 26. Planning vs Actual synchronization

Actual history must not overwrite the previous actual state.

Each synchronization run must preserve its own snapshot/history.

Concept:

```text
SyncRun
  -> ActualSnapshot / ActualObservation
  -> Mapping result
  -> Exceptions
```

The system must support:

```text
what was actual at run N?
what changed between run N and run N+1?
when did quantity/date/status change?
```

Never keep only “latest actual” if historical operational evolution is needed.

---

# 27. Data retention by year

Master/reference data stays online.

Do not archive Master simply because it is old.

Transactional/history scope managed by year:

```text
Planning
Actual
Snapshots
Mapping/operational histories where appropriate
```

Before archiving prior year, perform year-end carry-forward.

Carry forward at least:

```text
open/incomplete planning items
remaining quantities
active transfer/mapping state
required opening state/balances
objects needed to continue tracking
```

Archive only after carry-forward validation succeeds.

---

# 28. Production completion baseline

Planning/Actual reconciliation must support completion states based on real operational quantities, not merely planned end date.

At minimum retain distinction between:

```text
sewing completion
finished-goods receipt completion
```

This is also required by Dashboard Order Progress.

---

# 29. Security & Authentication

Current security direction is generally sound:

```text
Google verifies identity
DVT controls authorization
```

## User provisioning

Admin must create/provision the DVT user before access.

Google sign-in must not auto-create a DVT user merely because the email domain is allowed.

Google SSO flow:

```text
Google verified identity
-> verified email
-> allowed domain
-> DVT user exists
-> DVT user active
-> role/permissions resolved by DVT
-> DVT JWT/session
```

Google must never assign:

```text
ADMIN
PLANNER
VIEWER
```

Roles are DVT-controlled.

## Local fallback

Local login is emergency/fallback.

For SSO-only users, do not require a meaningful local password in the final model.

Recommended authentication method field:

```text
SSO_ONLY
LOCAL_AND_SSO
LOCAL_ONLY
```

## Bootstrap admin

Current code still seeds:

```text
admin / Admin@123
```

and forces password change.

This is better than before, but production should migrate toward:

```text
environment/bootstrap setup
random initial secret
one-time activation
or controlled break-glass account
```

Production must fail startup or raise a blocking deployment check if `JWT_SECRET` is still default/weak.

## JWT/session hardening backlog

Current browser token is still bearer-token based.

Future hardening should consider:

```text
HttpOnly Secure SameSite cookie
server-side session / token version
logout revocation
password-reset revocation
jti/session audit
```

Do not implement this in a way that breaks SSO without migration/testing.

---

# 30. Feature Coverage Matrix

Legend:

```text
DONE      implementation reasonably covers approved scope
PARTIAL   useful implementation exists but target design is incomplete
MISSING   not implemented to target design
```

| Capability | Data Model | Backend | UI | Tests | Overall |
|---|---|---|---|---|---|
| Planned Excel-like Grid | DONE | DONE | DONE | PARTIAL | DONE |
| Unplanned Grid + Filters | DONE | DONE | DONE | PARTIAL | DONE |
| Factory -> Line grouping | DONE | DONE | DONE | PARTIAL | DONE |
| Drag/drop Pending Confirm | PARTIAL | DONE | DONE | PARTIAL | PARTIAL |
| Exclusive Edit Session | DONE | DONE | DONE | DONE | DONE |
| Draft / Undo / Redo | PARTIAL | PARTIAL | DONE | PARTIAL | PARTIAL |
| Version / Commit / Issue | DONE | DONE | DONE | DONE | DONE |
| Working Calendar | DONE | DONE | DONE | DONE | DONE |
| Multi-line Structure | PARTIAL | PARTIAL | display only/partial | PARTIAL | PARTIAL |
| Line Transfer | PARTIAL | PARTIAL | creation UX missing | PARTIAL | PARTIAL |
| Calculated Override | PARTIAL | PARTIAL | PARTIAL | PARTIAL | PARTIAL |
| Column Configuration | MISSING | MISSING | MISSING | MISSING | MISSING |
| Formula Definition Master | MISSING | MISSING | MISSING | MISSING | MISSING |
| Generic Formula Engine | MISSING | MISSING | MISSING | MISSING | MISSING |
| Dependency Graph | MISSING | MISSING | MISSING | MISSING | MISSING |
| PREVIOUS_SEQUENCE framework | MISSING | PARTIAL hard-coded | PARTIAL | PARTIAL | PARTIAL |
| Formula Explanation | MISSING | MISSING | MISSING | MISSING | MISSING |
| Workbook Formula Coverage | MISSING/PARTIAL | PARTIAL | PARTIAL | MISSING | PARTIAL |
| Capacity Definition | MISSING | MISSING | MISSING | MISSING | MISSING |
| Machine Capacity | MISSING | MISSING | MISSING | MISSING | MISSING |
| Labor Reservation/Release | MISSING | MISSING | MISSING | MISSING | MISSING |
| Machine Reservation/Release | MISSING | MISSING | MISSING | MISSING | MISSING |
| Resource Release Schedule | MISSING | MISSING | MISSING | MISSING | MISSING |
| Actual Mapping | MISSING | MISSING | MISSING | MISSING | MISSING |
| Actual Snapshot History | MISSING | MISSING | MISSING | MISSING | MISSING |
| Year Carry-forward | MISSING | MISSING | MISSING | MISSING | MISSING |
| Revenue Executive Summary | DONE | DONE | DONE | DONE | DONE |
| Revenue Drill-down | DONE/PARTIAL | DONE | DONE | PARTIAL | DONE/PARTIAL |
| Order Progress target KPI | PARTIAL | PARTIAL | MISSING target view | MISSING | PARTIAL |
| QA target Dashboard | MISSING | MISSING/PARTIAL source research | MISSING | MISSING | MISSING |
| Auth pre-provisioned SSO | DONE | DONE | DONE | DONE | DONE |
| Forced default password change | DONE | DONE | DONE | DONE | DONE |
| Token revocation/session hardening | MISSING | MISSING | N/A | MISSING | BACKLOG |

---

# 31. Implementation order

Do not continue by adding isolated UI features.

Use this dependency order.

## Phase 1 — Planning semantic foundation

1. Planning Column Registry
2. Column Configuration model/API/UI
3. Formula Definition model
4. Formula parser/expression model
5. dependency extraction
6. circular dependency validator
7. formula version publish lifecycle
8. Formula Explanation UI

## Phase 2 — Calculation runtime

1. generic runtime formula evaluator
2. semantic references
3. `PREVIOUS_SEQUENCE`
4. Working Calendar function integration
5. rounding policies
6. Calculated/Override/Effective value model
7. calculation trace
8. full Recheck integration

## Phase 3 — Business capacity

1. Capacity Definition
2. capacity resolution
3. Worker/labor availability
4. Machine Capacity
5. bottleneck validation
6. capacity exceptions

## Phase 4 — Operational Planning interaction

1. drag/drop recalculation
2. multi-line creation UI
3. line transfer UI
4. Merge/Split if required
5. resource reservation
6. Resource Release Schedule

## Phase 5 — Actual / Mapping

1. stable business fingerprint
2. mapping records
3. eGMF actual sync
4. actual snapshot history
5. mapping exception/reconciliation UI
6. plan-vs-actual tracking

## Phase 6 — Dashboard completion

1. preserve Revenue new design
2. implement approved Order Progress
3. implement QA five-category comparison
4. link drill-down to operational data
5. tune Good News/Warnings

## Phase 7 — Year lifecycle / hardening

1. carry-forward
2. archive
3. annual partition/retention
4. auth/session hardening
5. centralized Style / Theme Management
6. operational monitoring

---

# 32. Definition of Done — global

A feature cannot be marked Done based on frontend appearance.

For every feature, verify:

```text
[ ] Business rule documented
[ ] Data model exists
[ ] migration/upgrade path exists
[ ] API exists
[ ] backend validation exists
[ ] permissions exist
[ ] audit exists where required
[ ] UI exists
[ ] empty/loading/error states exist
[ ] unit tests exist
[ ] integration/business tests exist
[ ] version/history behavior is defined
[ ] failure/recovery behavior is defined
[ ] no regression of approved interactions
```

For Formula-related features additionally:

```text
[ ] formula version stored
[ ] dependencies extracted
[ ] circular dependency prevented
[ ] sample preview works
[ ] runtime calculation works
[ ] override works
[ ] Return to Auto works
[ ] downstream values use EffectiveValue
[ ] sequence changes recalculate correctly
[ ] calendar changes are handled
[ ] Recheck validates full plan
[ ] calculation trace is available
```

For Revenue additionally:

```text
[ ] Corporate view shows XN1/XN2/XN3/Total
[ ] Factory view shows Selected XN + Total
[ ] main screen uses 100%-style achievement comparison
[ ] actual revenue value shown
[ ] daily detailed chart absent from main dashboard
[ ] click opens detailed plan/actual analysis
```

---

# 33. Acceptance tests that must exist

## Formula

```text
QUANTITY change
-> TOTAL_DAY recalculates
-> downstream end dates recalculate
-> next row BEGIN recalculates through PREVIOUS_SEQUENCE
```

```text
CAPACITY change
-> TOTAL_DAY changes
-> OFF_DAYS changes if threshold crossed
-> schedule changes
```

```text
drag row A after row C
-> SequenceRevision increments
-> previous/next dependencies resolve to new business sequence
-> stale calculation response rejected
```

```text
override END_PROD_DATE
-> ValueSource=OVERRIDE
-> EffectiveValue uses override
-> next row uses overridden date
-> Return to Auto restores calculated chain
```

```text
Sunday OFF + Monday DATE_OFF
-> +1 Working Day from Saturday resolves Tuesday
```

## Revenue

```text
scope=TONG
-> rows XN1, XN2, XN3, Total
```

```text
scope=XN2
-> rows XN2, Total only
```

```text
main Dashboard
-> no daily Plan vs Actual chart
```

```text
click XN2 Revenue
-> detail for XN2
-> plan/actual/detail chart available
```

## Order Progress

```text
PO sewing complete on time
-> increments On Time / Sewing Complete
```

```text
PO sewing complete late
-> increments Late / Sewing Complete
```

```text
customer excluded from FG receipt tracking
-> no false incomplete FG receipt warning
```

## QA

```text
multiple defect records on one inspected unit
-> Total Defect Count counts defect occurrences
```

```text
CUTTING_BTP source
-> excluded from current QA main dashboard
```

---

# 34. Rules for Claude / implementation agent

1. Read this document before implementing Planning/Dashboard changes.
2. Do not infer that a feature is complete because a component already exists.
3. Do not replace spreadsheet-like Planning with Kanban/cards.
4. Do not hide business columns to make the UI visually simpler.
5. Do not hard-code new formulas directly into UI components.
6. Do not add a formula to `planning_engine.py` without determining whether it belongs in the Formula Definition architecture.
7. Do not use visual row order as `PREVIOUS_SEQUENCE`.
8. Do not use eGMF internal ID as the durable cross-system business key.
9. Do not overwrite prior Actual sync state if history is required.
10. Do not revert the Revenue executive-summary interaction.
11. Do not put detailed daily Revenue chart back on the main Dashboard.
12. Do not mark a feature Done until the Feature Coverage Matrix and Definition of Done are updated based on actual code and tests.

---

# 35. Immediate next implementation task

The next major task should **not** be further Planning visual styling.

Implement the semantic foundation:

```text
Column Configuration
+
Formula Definition
+
Dependency Engine
+
Formula Explanation
```

Then migrate current hard-coded calculations into that framework incrementally.

Suggested first formulas to migrate and publish as Version 1 with canonical workbook cases:

```text
TOTAL_DAY
OFF_DAYS
BEGIN_PROD_DATE
END_PROD_DATE
ON_TIME
```

Each v1 Formula Definition must store the verified workbook input/output examples used as its canonical acceptance baseline.

After these are working with dependency/recheck/versioning, continue with the remaining workbook columns.

This will prevent the current pattern where the screen appears functionally complete while the core planning logic remains implicit, hard-coded, or absent.
