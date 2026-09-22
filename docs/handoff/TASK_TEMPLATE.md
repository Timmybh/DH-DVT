# Task: <short name>

## 0. Status

- Handoff owner: GPT
- Implementation owner: Claude
- Status: READY_FOR_CLAUDE
- Repository: Timmybh/DH-DVT
- Baseline commit: <commit SHA>
- Related master spec: `docs/DVT_Master_Review_Implementation_Spec_Latest.md`

---

## 1. Business objective

Describe the business problem in plain language.

---

## 2. Approved terminology

List exact business terms that must be used consistently.

Example:

- `Current Process`
- `Optimized Current Technology`
- `Future Technology`

Do not rename approved terms without business approval.

---

## 3. Scope

### In scope

- ...

### Out of scope / Non-goals

- ...

---

## 4. Existing behavior to preserve

- ...

---

## 5. Business rules

Number every rule.

### BR-001
...

### BR-002
...

For each temporary assumption, explicitly mark:

`TEMPORARY ASSUMPTION — NOT MASTER DATA`

---

## 6. Data model

Specify new/changed entities, key fields, relationships, statuses, source-of-truth, effective dating, versioning, and audit requirements.

---

## 7. Calculation / decision logic

Define formulas, dependency order, optimization objective, constraints, fallback behavior, and evidence required for every calculated recommendation.

Do not use unexplained constants.

---

## 8. Versioning and history

Define:
- what creates a new version;
- what is immutable;
- what can be edited;
- how prior versions remain explainable;
- which source snapshot/version is bound to each calculation.

---

## 9. Workflow and approval

Define Draft / Simulated / Reviewed / Approved / Retired or other applicable statuses.

Auto-generated records must not become Approved without the required business approval.

---

## 10. UI/UX

Specify:
- navigation location;
- screen structure;
- filters;
- actions;
- dialogs;
- drill-down;
- evidence/explanation view;
- empty/error/stale states.

---

## 11. Permissions

List view/manage/approve/publish permissions and server-side enforcement.

---

## 12. Audit

Define the actions that must produce immutable audit/history records.

---

## 13. API

List endpoints or capability contracts. Claude may choose implementation details only where they do not change the business contract.

---

## 14. Validation

List business validations and error behavior.

---

## 15. Acceptance criteria

Use testable statements.

### AC-001
Given ...
When ...
Then ...

### AC-002
...

---

## 16. Regression constraints

List existing Planning/Dashboard/Resource/Actual behaviors that must not break.

---

## 17. Claude implementation instructions

1. Read this task and the master spec before coding.
2. Do not infer new business rules.
3. If a material ambiguity exists, report it in the Issue instead of inventing behavior.
4. Implement on a dedicated branch.
5. Add/update backend tests for business rules.
6. Do not call temporary/demo/calculated data “actual”.
7. Return a structured implementation report using `docs/handoff/HANDOFF_PROTOCOL.md`.
