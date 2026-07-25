# Console Visual Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the existing console a readable dark-sidebar/light-content visual system with restrained blue-violet accents and subtle accessible motion, without changing any function or operation path.

**Architecture:** Keep the current HTML and JavaScript behavior intact and implement the design through the existing `app.css`. Add stylesheet contract assertions to the existing console test so the key visual and accessibility decisions cannot disappear silently. No new file, component framework, runtime dependency, API, or state is introduced.

**Tech Stack:** Existing static HTML, vanilla JavaScript, CSS, FastAPI `TestClient`, pytest.

## Global Constraints

- Preserve every existing feature, navigation path, handler, API, storage contract, workflow, and model route.
- Use the existing HTML, JavaScript, and CSS; prefer CSS-only changes.
- Use a deep blue-black sidebar, soft gray-white canvas, white primary surfaces, and blue-violet accent.
- Keep moderate spacing and information density for long-form Chinese reading.
- Motion must last 150–200 ms, must not run continuously, and must be removed under `prefers-reduced-motion: reduce`.
- Preserve visible keyboard focus and never communicate state through color alone.
- Preserve the existing mobile layout and prevent horizontal overflow at approximately 390 px.
- Add no UI framework, icon library, animation library, particle effect, or glassmorphism.
- Preserve unrelated working-tree changes and commit only the files named by each task.

## File Structure

- Modify `src/novel_flywheel/static/app.css`: own all visual tokens, component styling, interaction feedback, accessibility, and responsive behavior.
- Modify `tests/test_console.py`: assert the required stylesheet contract through the existing local asset endpoint.
- No HTML or JavaScript change is planned. If implementation reveals that a stable selector is genuinely missing, stop and amend this plan before changing either file.

---

### Task 1: Visual tokens, application shell, and controls

**Files:**
- Modify: `src/novel_flywheel/static/app.css:1-47`
- Test: `tests/test_console.py:7-18`

**Interfaces:**
- Consumes: `/static/app.css` served by the existing FastAPI application.
- Produces: CSS custom properties `--accent`, `--accent-strong`, `--accent-soft`, `--sidebar`, `--surface`, `--shadow-sm`, and `--motion`; shared focus, button, form, navigation, and surface behavior used by Tasks 2 and 3.

- [ ] **Step 1: Add a failing stylesheet contract test**

Add this test after `test_console_and_assets_are_served_locally`:

```python
def test_console_stylesheet_has_visual_system_and_accessible_motion(tmp_path) -> None:
    client = TestClient(create_app(
        Database(tmp_path / "app.db"), MemorySecretStore(),
        skill_roots=[tmp_path / "skills"], workspace_root=tmp_path / "workspace",
    ))
    css = client.get("/static/app.css").text

    assert "--accent:#6d5dfc" in css
    assert "--sidebar:#15182a" in css
    assert "--motion:180ms" in css
    assert ":focus-visible" in css
```

- [ ] **Step 2: Run the test and verify that the new contract fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_console.py::test_console_stylesheet_has_visual_system_and_accessible_motion -v
```

Expected: FAIL because `--accent:#6d5dfc` is absent from the current stylesheet.

- [ ] **Step 3: Replace the visual tokens and normalize the shell**

At the start of `app.css`, use this compact token set:

```css
:root {
  color-scheme:light;
  --ink:#202235;
  --muted:#6c7085;
  --line:#dfe1eb;
  --paper:#f5f6fa;
  --white:#fff;
  --surface:#fff;
  --sidebar:#15182a;
  --accent:#6d5dfc;
  --accent-strong:#5747e8;
  --accent-soft:#eeecff;
  --green:#19825f;
  --green-dark:#12694c;
  --amber:#b36b16;
  --red:#a63d35;
  --shadow-sm:0 6px 18px rgba(28,31,51,.07);
  --motion:180ms;
}
```

Update only existing global selectors:

```css
body { background:var(--paper); }
.sidebar { background:var(--sidebar); }
.brand-mark { background:linear-gradient(135deg,#8b7fff,var(--accent)); color:#fff; border-radius:9px; }
.nav-item { border-left-color:transparent; transition:color var(--motion) ease,background var(--motion) ease,border-color var(--motion) ease,transform var(--motion) ease; }
.nav-item:hover,.nav-item.active { background:rgba(109,93,252,.16); border-left-color:#8b7fff; }
.nav-item:hover { transform:translateX(2px); }
.topbar { box-shadow:0 1px 0 rgba(28,31,51,.03); }
input,select,textarea { border-color:#d5d8e5; transition:border-color var(--motion) ease,box-shadow var(--motion) ease,background var(--motion) ease; }
input:focus,select:focus,textarea:focus { border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-soft); }
button { transition:background var(--motion) ease,border-color var(--motion) ease,color var(--motion) ease,box-shadow var(--motion) ease,transform var(--motion) ease; }
button:active:not(:disabled) { transform:scale(.98); }
.primary { background:linear-gradient(135deg,#7667ff,var(--accent-strong)); box-shadow:0 5px 14px rgba(109,93,252,.22); }
.primary:hover { background:linear-gradient(135deg,#6d5dfc,#4f40d8); }
:where(button,input,select,textarea,summary,[tabindex]):focus-visible { outline:3px solid rgba(109,93,252,.35); outline-offset:2px; }
```

Do not change element dimensions, layout grids, handler hooks, or semantic success/warning/error colors in this task.

- [ ] **Step 4: Run the focused test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_console.py::test_console_stylesheet_has_visual_system_and_accessible_motion -v
```

Expected: PASS.

- [ ] **Step 5: Commit the visual foundation**

```powershell
git add -- src/novel_flywheel/static/app.css tests/test_console.py
git commit -m "style: establish console visual system"
```

### Task 2: Content surfaces, statuses, and readable information hierarchy

**Files:**
- Modify: `src/novel_flywheel/static/app.css:48-217`
- Test: `tests/test_console.py`

**Interfaces:**
- Consumes: Task 1 tokens and the existing classes emitted by `index.html` and `app.js`.
- Produces: consistent static and interactive surfaces, status labels with visible markers, readable tables/logs, and blue-violet active states.

- [ ] **Step 1: Extend the stylesheet contract test**

Add these assertions to `test_console_stylesheet_has_visual_system_and_accessible_motion`:

```python
    assert ".status::before" in css
    assert ".project-item:hover" in css
    assert ".learning-artifact" in css
    assert "var(--shadow-sm)" in css
```

- [ ] **Step 2: Run the focused test and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_console.py::test_console_stylesheet_has_visual_system_and_accessible_motion -v
```

Expected: FAIL because `.status::before` is absent.

- [ ] **Step 3: Apply the shared surface hierarchy**

Use existing selectors rather than new markup:

```css
.project-item,.run-row,.data-row,.writing-rules-summary,.material-impact-status,.learning-artifacts,.project-learning-materials,.run-log,.run-context,pre {
  border-color:var(--line);
  background:var(--surface);
  box-shadow:var(--shadow-sm);
}
.project-item,.run-row,.data-row {
  border-radius:10px;
}
.project-item {
  transition:border-color var(--motion) ease,box-shadow var(--motion) ease,transform var(--motion) ease;
}
.project-item:hover {
  border-color:#c9c4ff;
  box-shadow:0 10px 24px rgba(28,31,51,.10);
  transform:translateY(-2px);
}
.eyebrow,.material-tab.active,.wizard-step.active,.summary-item strong {
  color:var(--accent);
}
.material-tab.active {
  border-bottom-color:var(--accent);
}
.wizard-step.active {
  background:var(--accent-soft);
}
.wizard-step.active span,.segmented input:checked + span,.run-tab.active {
  background:var(--accent);
  border-color:var(--accent);
}
```

Keep non-interactive cards static. Do not add hover lift to learning artifacts, logs, manuscript prose, forms, or status panels.

- [ ] **Step 4: Add non-color status markers**

Add a marker to the existing text label:

```css
.status { display:inline-flex; align-items:center; gap:7px; }
.status::before { content:""; width:7px; height:7px; flex:none; border-radius:50%; background:currentColor; box-shadow:0 0 0 3px color-mix(in srgb,currentColor 13%,transparent); }
```

The existing status text remains present, so the marker supplements rather than replaces the label. Do not alter `.status.failed`, `.status.interrupted`, `.status.cancelled`, or `.status.quality-rejected` mappings.

- [ ] **Step 5: Improve tables, logs, and learning cards without changing layout**

Add or update:

```css
.material-table th { background:#f3f3fa; color:#4e5269; }
.material-table tbody tr:hover { background:#fafaff; }
.log-row { border-bottom-color:#ececf3; }
.learning-artifact summary,.project-learning-item summary { transition:color var(--motion) ease; }
.learning-artifact summary:hover,.project-learning-item summary:hover { color:var(--accent); }
.badge { border:1px solid #dedfea; background:#f3f3f8; border-radius:999px; }
```

Keep the existing Chinese copy, version labels, grid columns, overflow behavior, and reading line heights unchanged.

- [ ] **Step 6: Run console tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_console.py -v
```

Expected: all console tests pass.

- [ ] **Step 7: Commit the content styling**

```powershell
git add -- src/novel_flywheel/static/app.css tests/test_console.py
git commit -m "style: refine console content hierarchy"
```

### Task 3: Reduced motion, responsive safeguards, and full verification

**Files:**
- Modify: `src/novel_flywheel/static/app.css:218-end`
- Test: `tests/test_console.py`

**Interfaces:**
- Consumes: motion and surface rules from Tasks 1 and 2.
- Produces: reduced-motion override and narrow-screen safeguards completing the stylesheet contract.

- [ ] **Step 1: Add a failing reduced-motion contract assertion**

Add this assertion to `test_console_stylesheet_has_visual_system_and_accessible_motion`:

```python
    assert "@media (prefers-reduced-motion:reduce)" in css
```

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_console.py::test_console_stylesheet_has_visual_system_and_accessible_motion -v
```

Expected: FAIL because the reduced-motion media query is absent.

- [ ] **Step 2: Add reduced-motion behavior**

Append this rule after the existing responsive blocks:

```css
@media (prefers-reduced-motion:reduce) {
  *,*::before,*::after {
    scroll-behavior:auto!important;
    animation-duration:.01ms!important;
    animation-iteration-count:1!important;
    transition-duration:.01ms!important;
  }
  .nav-item:hover,.project-item:hover,button:active:not(:disabled) {
    transform:none;
  }
}
```

- [ ] **Step 3: Preserve narrow-screen usability**

Extend the existing `@media (max-width:800px)` rules rather than creating a competing breakpoint:

```css
@media (max-width:800px) {
  body { overflow-x:hidden; }
  .reference-actions,.material-actions,.wizard-actions { flex-wrap:wrap; }
  .reference-actions > button,.wizard-actions > button { flex:1 1 150px; }
  .project-item:hover { transform:none; }
}
```

Do not change the existing one-column grids, mobile navigation, or 18 px content padding.

- [ ] **Step 4: Run the stylesheet contract and console suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_console.py::test_console_stylesheet_has_visual_system_and_accessible_motion -v
.\.venv\Scripts\python.exe -m pytest tests/test_console.py -v
```

Expected: both commands pass.

- [ ] **Step 5: Run the complete automated test suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Expected: the complete suite passes with no paid model API calls.

- [ ] **Step 6: Verify desktop and mobile rendering**

Start the console only after confirming no run is `queued`, `running`, or `cancelling`, then inspect the existing application at desktop width and 390 px. Verify:

- every navigation item remains visible and reaches the same view;
- topbar, forms, project cards, learning materials, tables, logs, badges, and statuses use the new system;
- keyboard focus is visible;
- primary, secondary, destructive, disabled, success, warning, and error states remain distinct;
- long Chinese labels and project paths wrap without horizontal page overflow;
- interactive cards lift no more than two pixels;
- reduced-motion emulation removes transforms and visible transitions;
- browser console contains no errors.

If a defect appears, change only `app.css`, add the smallest assertion to `test_console_stylesheet_has_visual_system_and_accessible_motion` when it can be checked deterministically, and rerun Steps 4–6.

- [ ] **Step 7: Review the final diff for scope**

Run:

```powershell
git diff --check
git status --short
git diff -- src/novel_flywheel/static/app.css tests/test_console.py
```

Expected: no whitespace errors; only the intended stylesheet and test changes are part of this implementation. Pre-existing unrelated modifications remain unstaged.

- [ ] **Step 8: Commit the responsive and accessibility pass**

```powershell
git add -- src/novel_flywheel/static/app.css tests/test_console.py
git commit -m "style: complete accessible console polish"
```
