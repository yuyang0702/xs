# Compatible Quality Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add project-scoped draft style use, run context visibility, Skill conflict warnings, and versioned manual StoryState editing without replacing existing workflow contracts.

**Architecture:** Reuse `project.json`, run events and receipts, Skill scan results, and `StoryStateStore`. All new behavior is optional or read-only except manual edits, which use the existing candidate commit path.

**Tech Stack:** FastAPI, Pydantic, SQLite StoryState, static HTML/CSS/JavaScript, pytest.

---

### Task 1: Project style scope

- [x] Add API tests for the default and explicit scope.
- [x] Store scope in `project.json` and inject the profile only when draft use is enabled.
- [x] Add the workbench segmented control.

### Task 2: Run context summary

- [x] Summarize existing stage events and tool receipts in the run detail UI.
- [x] Exclude secrets, headers, and duplicate raw prompts.

### Task 3: Skill conflict warnings

- [x] Add a focused API regression test.
- [x] Return conservative advisory conflicts and display them without changing execution.

### Task 4: Manual StoryState revisions

- [x] Add API tests for successful and stale edits.
- [x] Commit one allowlisted section through the existing candidate path.
- [x] Add a project editor with JSON validation, diff preview, and revision display.

### Task 5: Verification

- [x] Run focused tests and JavaScript syntax validation.
- [x] Run the complete test suite, visually verify desktop/mobile, update docs, and restart safely.
