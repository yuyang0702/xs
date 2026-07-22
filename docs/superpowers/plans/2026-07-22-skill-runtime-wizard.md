# Skill-driven Story Wizard and Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace minimal project creation with a resumable Skill-driven wizard, strict locks, a controlled file-proposal runtime, Story CLI validation, and migration for existing projects.

**Architecture:** A `WizardService` discovers initialization Skills, validates/caches their form schemas, persists answers, and creates a canonical Story Skills project after confirmation. A separate `SkillRuntime` exposes only schema-validated project tools, accumulates file proposals, enforces per-Skill path contracts and locks, applies changes under a snapshot, and invokes a whitelisted Story CLI adapter. Existing workflows consume the same canonical project files and remain the only writers of chapter manuscripts.

**Tech Stack:** Python 3.11, Pydantic 2, FastAPI, SQLite, vanilla JavaScript/CSS, existing provider adapters and Story CLI executable Skill.

---

### Task 1: Persist Wizard, Locks, Executions, and Proposals

**Files:**
- Modify: `src/novel_flywheel/db.py`
- Test: `tests/test_db.py`

- [ ] Write failing tests for wizard autosave/resume, lock persistence, runtime execution state, proposal records, and change requests.
- [ ] Run `pytest tests/test_db.py -q` and confirm missing APIs fail.
- [ ] Add SQLite tables and focused `Database` methods using JSON columns for schemas/answers and immutable lock revisions.
- [ ] Run `pytest tests/test_db.py -q` and confirm PASS.

### Task 2: Discover and Cache Skill Form Schemas

**Files:**
- Create: `src/novel_flywheel/wizard.py`
- Modify: `src/novel_flywheel/skills.py`
- Test: `tests/test_wizard.py`

- [ ] Write failing tests for core form availability, known Story Skill sections, optional sidecar schemas, generated-schema validation, cache reuse, and content-hash invalidation.
- [ ] Run `pytest tests/test_wizard.py -q` and confirm missing service failure.
- [ ] Implement typed form schemas, built-in safe questions, optional `forms/project.json`, cache paths keyed by Skill hash, and a generator callback with deterministic fallback.
- [ ] Run `pytest tests/test_wizard.py -q` and confirm PASS.

### Task 3: Build Resumable Wizard and Canonical Project

**Files:**
- Modify: `src/novel_flywheel/wizard.py`
- Modify: `src/novel_flywheel/projects.py`
- Create: `src/novel_flywheel/api/wizards.py`
- Modify: `src/novel_flywheel/app.py`
- Test: `tests/test_wizard.py`
- Create: `tests/api/test_wizards.py`

- [ ] Write failing tests for create/resume, per-field policies, required-field validation, final confirmation, locks file, enriched `story.md`, and all canonical registries.
- [ ] Run focused tests and confirm RED.
- [ ] Implement wizard APIs and `ProjectStore.create_from_wizard`; write answer provenance and `continuity/locks.json`, and keep legacy `POST /api/projects` compatible.
- [ ] Run focused tests and confirm PASS.

### Task 4: Implement Controlled Skill Runtime and Story CLI

**Files:**
- Create: `src/novel_flywheel/skill_runtime.py`
- Modify: `src/novel_flywheel/api/skills.py`
- Test: `tests/test_skill_runtime.py`
- Modify: `tests/api/test_skills.py`

- [ ] Write failing tests for bounded tool definitions, project-contained paths, per-Skill path allowlists, proposal accumulation, strict lock conflicts, atomic apply/rollback, and Story CLI command whitelist.
- [ ] Run focused tests and confirm RED.
- [ ] Implement `SkillContract`, `SkillRuntimeToolbox`, `StoryCli`, proposal validation/application, execution receipts, and API endpoints for run/proposal/change-request state.
- [ ] Run focused tests and confirm PASS.

### Task 5: Migrate Existing Projects

**Files:**
- Create: `src/novel_flywheel/migration.py`
- Modify: `src/novel_flywheel/api/projects.py`
- Test: `tests/test_migration.py`
- Modify: `tests/api/test_projects.py`

- [ ] Write failing tests for dry-run reports, outline/canon mapping, ambiguous fact review, chapter preservation, standard registries, reindex hook, and rollback.
- [ ] Run focused tests and confirm RED.
- [ ] Implement snapshot-protected migration with a retained report and no silent deletion.
- [ ] Run focused tests and confirm PASS.

### Task 6: Replace the Project Form with the Skill Wizard

**Files:**
- Modify: `src/novel_flywheel/static/index.html`
- Modify: `src/novel_flywheel/static/app.js`
- Modify: `src/novel_flywheel/static/app.css`
- Modify: `tests/test_console.py`

- [ ] Add failing console assertions for step navigation, autosave target, three-state policy controls, Skill source labels, confirmation summary, and migration controls.
- [ ] Run `pytest tests/test_console.py -q` and confirm RED.
- [ ] Implement the responsive stepper, dynamic field renderer, autosave, resume, confirmation, locks display, and execution/migration status views.
- [ ] Run `pytest tests/test_console.py -q` and confirm PASS.

### Task 7: Integrate, Document, and Verify

**Files:**
- Modify: `README.md`
- Modify: `tests/test_workflows.py` when canonical-path compatibility needs coverage.

- [ ] Run `python -m compileall -q src`.
- [ ] Run `pytest -q` and fix regressions.
- [ ] Run `git diff --check`.
- [ ] Start/restart the local console and verify health, wizard creation, autosave, confirmation, and standard files.
- [ ] Verify the wizard at 1440x900 and 390x844 with DOM overflow checks and screenshots.
- [ ] Commit implementation and documentation.
