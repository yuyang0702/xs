# Compact Skill Prompts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Send a smaller, deterministic Skill execution prompt to external polish models.

**Architecture:** Add a focused `SkillPromptCompactor` that accepts scanned Skill objects and caches compact text by content hash. Integrate it at the workflow boundary only for `polish`, retaining the current full prompt as the failure fallback.

**Tech Stack:** Python standard library, pytest

---

### Task 1: Compact Skill Prompts

**Files:**
- Create: `src/novel_flywheel/skill_prompts.py`
- Create: `tests/test_skill_prompts.py`

- [ ] Write tests proving hard rules remain, examples are removed, and content hashes control caching.
- [ ] Run `pytest tests/test_skill_prompts.py -q` and confirm the tests fail because the module is missing.
- [ ] Implement deterministic section and normative-line extraction with a full-prompt fallback.
- [ ] Run `pytest tests/test_skill_prompts.py -q` and confirm it passes.

### Task 2: Polish Integration

**Files:**
- Modify: `src/novel_flywheel/workflows.py`
- Modify: `tests/test_workflows.py`

- [ ] Write a workflow test proving `polish` receives compact Skill instructions while another stage receives complete instructions.
- [ ] Run the focused test and confirm it fails before integration.
- [ ] Inject the compactor into `WorkflowService` and use it only when `stage == "polish"`.
- [ ] Run the focused test, then the complete test suite and compilation checks.
- [ ] Commit the implementation and leave the local console running with the new code.
