# Learning Library UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize the learning library into three understandable views with compact candidates and readable Chinese artifacts.

**Architecture:** Keep existing APIs and state. Add client-side view switching, change the existing render functions to produce progressive disclosure, and update CSS around stable content widths and responsive layouts.

**Tech Stack:** FastAPI, vanilla JavaScript, HTML, CSS, pytest.

## Global Constraints

- No paid model calls in tests or verification.
- Do not change manuscripts, model bindings, stored source text, or learning authority.
- Use plain Chinese for all writer-facing labels.

---

### Task 1: Page Structure

- [ ] Add failing HTML contract tests for the three learning views.
- [ ] Add the segmented navigation and three panels.
- [ ] Move existing sections without changing their IDs or event contracts.

### Task 2: Reference Guidance

- [ ] Add a failing policy test for removal of the duplicate ordinary-reference action.
- [ ] Remove the duplicate action and add plain-language local-tool guidance.

### Task 3: Compact Mechanisms

- [ ] Add failing UI contract tests for collapsed details.
- [ ] Render summary-first mechanism cards with one expandable detail section.
- [ ] Preserve confirm/adopt/reject/release/delete behaviors.

### Task 4: Readable Artifacts

- [ ] Add failing tests for Chinese narrative labels and hidden technical data.
- [ ] Render artifact summaries in one column and collapse them by default.
- [ ] Move unknown and technical fields to a technical detail disclosure.

### Task 5: Verification

- [ ] Run focused tests and the complete suite.
- [ ] Restart only when no local or model task is active.
- [ ] Verify desktop and mobile layouts in the browser.

### Task 6: Project Application Reading Flow

- [ ] Add a failing console contract test for the application heading, separate active-rules section, collapsed review details, and nearby review actions.
- [ ] Replace the repeated `作品应用` heading with `当前作品的创作设置` and a direct explanation of what changes.
- [ ] Keep review actions visible in the summary and move the full rule list into a collapsed `查看具体规则` disclosure.
- [ ] Verify that desktop and 375 px layouts have no horizontal overflow and no longer require scrolling through every rule before acting.
