# GPT ↔ Claude GitHub Handoff Protocol

## Purpose

This repository uses GitHub as the audited handoff channel between GPT (analysis/specification/review) and Claude (implementation).

The handoff channel must prevent implementation drift, hidden assumptions, and silent reinterpretation of approved business rules.

## Operating model

1. GPT prepares a task specification using `docs/handoff/TASK_TEMPLATE.md`.
2. A GitHub Issue is created for the task.
3. The Issue must contain:
   - business objective;
   - approved terminology;
   - in-scope requirements;
   - explicit non-goals;
   - data model impact;
   - calculation/business rules;
   - UI/UX requirements;
   - versioning/audit rules;
   - acceptance criteria;
   - regression constraints.
4. Claude implements only what is explicitly approved in the Issue/spec.
5. If a material ambiguity is found, Claude must NOT invent a business rule. It must report the ambiguity in the Issue before implementing that part.
6. Claude should work on a dedicated branch and return:
   - files changed;
   - migrations;
   - tests added/changed;
   - known limitations;
   - commit SHA / PR.
7. GPT reviews the result against the Issue/spec.
8. Business approval is required before changing the authoritative specification.

## Source-of-truth order

When requirements conflict, use this precedence:

1. Latest approved GitHub Issue/spec for the feature.
2. `docs/DVT_Master_Review_Implementation_Spec_Latest.md`.
3. Existing approved implementation behavior.
4. Older handoff/design documents.

Claude must not use older documents to override a newer approved requirement.

## Hard rules for Claude

- Do not treat a UI mock or temporary implementation as a final business rule.
- Do not create synthetic KPI values and present them as actual data.
- Do not silently replace a business requirement with a technically easier design.
- Do not overwrite versioned historical data when a new version should be created.
- Do not auto-approve generated engineering/process data.
- Do not turn an assumption into master data without an explicit status/source.
- Do not remove audit/history merely because the current UI does not use it.
- Do not implement a new source of truth if an approved source of truth already exists.
- Do not mark a feature Done unless applicable Definition-of-Done items are covered: model, service/rule, API, permission, audit/history, UX, validation, tests, and regression review.

## Task lifecycle

Recommended Issue states/labels:

- `handoff:gpt` — specification prepared
- `status:ready-for-claude` — Claude may start
- `status:claude-working`
- `status:ready-for-review`
- `status:changes-requested`
- `status:approved`

If labels are not configured, use these exact markers in the Issue body/comments.

## Required implementation report

Claude's final Issue comment must include:

### Implementation Summary
- What was implemented.
- What was intentionally not implemented.

### Data / Migration
- Tables/columns/indexes/migrations.

### Business Rules
- Exact rules implemented.
- Any assumptions that remain temporary.

### UI
- Screens and interactions changed.

### Tests
- Tests added/updated.
- Test command and result.

### Known Gaps
- Anything not fully compliant with the approved task.

### Delivery
- Branch:
- Commit:
- PR:

## Review rule

GPT review should compare implementation to the approved task line-by-line. A feature is not accepted merely because the UI looks complete.
