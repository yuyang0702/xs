# Short Causal Chain Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add a short-story whole-story causal chain that augments the existing outline, learning library, draft context, and final review without replacing current workflow behavior.

**Architecture:** Implement one deterministic module for range/check/compact/extract behavior, persist chains through the existing project learning artifact table, and thread compact summaries into existing prompts. Reuse current learning nodes and creative blueprint instead of adding tables.

**Tech Stack:** Python 3.11, SQLite through existing Database, FastAPI service objects, pytest.

---

### Task 1: Local causal-chain analyzer

**Files:**
- Create: src/novel_flywheel/causal_chain.py
- Test: tests/test_causal_chain.py

- [ ] Step 1: Write failing tests for cycle_range, valid repeatable cycles, missing state changes, and missing reversal evidence.
- [ ] Step 2: Run .\.venv\Scripts\python.exe -m pytest -q tests/test_causal_chain.py and verify import failure.
- [ ] Step 3: Implement cycle_range, analyze_short_causal_chain, compact_causal_chain, and extract_short_causal_chain.
- [ ] Step 4: Run the same focused test and verify green.

### Task 2: Persist project causal-chain artifacts

**Files:**
- Modify: src/novel_flywheel/learning.py
- Modify: src/novel_flywheel/projects.py
- Test: tests/test_learning_system.py

- [ ] Write failing tests for build_short_causal_chain saving diagnostics and ProjectStore.load_constraints including active chain content.
- [ ] Add LearningSystem.build_short_causal_chain(project_id, chain) using existing save_artifact.
- [ ] Add short_causal_chain to ProjectStore.load_constraints labels.
- [ ] Run focused tests and verify green.

### Task 3: Extract chain from planning and pass it forward

**Files:**
- Modify: src/novel_flywheel/workflows.py
- Test: tests/test_workflows.py

- [ ] Write failing tests with a fake planning response containing a short_causal_chain JSON block.
- [ ] Implement extraction, artifact saving, and compact draft context. Invalid extraction records a warning and does not block the old workflow.
- [ ] Run focused tests and verify green.

### Task 4: Learning-library causal mechanisms

**Files:**
- Modify: src/novel_flywheel/learning.py
- Test: tests/test_learning_system.py

- [ ] Write failing tests that adopted causal-structure mechanisms enter creative_blueprint.causal_structure.
- [ ] Add minimal mechanism type detection through data.mechanism_type == causal_structure.
- [ ] Run focused tests and verify green.

### Task 5: Final review context and docs

**Files:**
- Modify: src/novel_flywheel/workflows.py
- Modify: docs/maintenance.md
- Test: tests/test_workflows.py

- [ ] Write failing tests that final review prompt includes causal-chain checks when an active chain exists.
- [ ] Add compact chain to full-review prompts and document fallback behavior.
- [ ] Run focused workflow tests and then full pytest -q.
