from pathlib import Path
import sys

import pytest

from novel_flywheel.db import Database
from novel_flywheel.skills import SkillGate, SkillScanner


def write_skill(root: Path, name: str, body: str, script: str | None = None) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test skill\n---\n\n{body}\n",
        encoding="utf-8",
    )
    if script is not None:
        scripts = folder / "scripts"
        scripts.mkdir()
        (scripts / "run.py").write_text(script, encoding="utf-8")
    return folder


def test_scanner_discovers_prompt_and_executable_skills(tmp_path) -> None:
    root = tmp_path / "skills"
    write_skill(root, "humanizer", "Remove AI patterns.")
    write_skill(root, "maintenance", "Run scripts/run.py.", "print('checked')")

    skills = {skill.name: skill for skill in SkillScanner([root]).scan()}

    assert skills["humanizer"].executable is False
    assert skills["maintenance"].executable is True
    assert len(skills["maintenance"].content_hash) == 64


def test_scanner_does_not_mark_unreferenced_validation_script_executable(tmp_path) -> None:
    root = tmp_path / "skills"
    write_skill(root, "better-writing", "Improve prose.", "print('repo validation')")

    skill = SkillScanner([root]).scan()[0]

    assert skill.executable is False
    assert skill.has_scripts is True


def test_prompt_skill_executes_automatically_and_records_receipt(tmp_path) -> None:
    root = tmp_path / "skills"
    write_skill(root, "humanizer", "Remove AI patterns.")
    db = Database(tmp_path / "app.db")
    db.migrate()
    gate = SkillGate(db, SkillScanner([root]))

    result = gate.run_required("polish", ["humanizer"])

    assert "Remove AI patterns." in result.prompt
    assert result.receipts[0].status == "succeeded"
    assert db.list_skill_receipts()[0]["skill_name"] == "humanizer"


def test_optional_prompt_skill_loads_instructions_even_with_bundled_scripts(tmp_path) -> None:
    root = tmp_path / "skills"
    write_skill(root, "better-writing", "Preserve voice and remove uniform prose.", "print('validator')")
    db = Database(tmp_path / "app.db")
    db.migrate()
    gate = SkillGate(db, SkillScanner([root]))

    result = gate.load_optional_prompts("polish", ["better-writing"])

    assert "Preserve voice" in result.prompt
    assert result.receipts[0].skill_name == "better-writing"
    assert result.receipts[0].output == "instructions-loaded"


def test_missing_optional_prompt_skill_does_not_block_stage(tmp_path) -> None:
    db = Database(tmp_path / "app.db")
    db.migrate()
    gate = SkillGate(db, SkillScanner([tmp_path / "skills"]))

    result = gate.load_optional_prompts("draft", ["better-writing"])

    assert result.prompt == ""
    assert result.receipts == []


def test_executable_skill_requires_approval_for_current_hash(tmp_path) -> None:
    root = tmp_path / "skills"
    folder = write_skill(root, "maintenance", "Run scripts/run.py.", "print('checked')")
    db = Database(tmp_path / "app.db")
    db.migrate()
    gate = SkillGate(db, SkillScanner([root]))

    with pytest.raises(PermissionError, match="maintenance"):
        gate.run_required("archive", ["maintenance"], {"maintenance": ["scripts/run.py"]})

    skill = gate.skills()["maintenance"]
    db.approve_skill(skill.name, skill.content_hash)
    result = gate.run_required("archive", ["maintenance"], {"maintenance": ["scripts/run.py"]})
    assert result.receipts[0].status == "succeeded"
    assert result.receipts[0].output == "checked"

    (folder / "SKILL.md").write_text(
        "---\nname: maintenance\n---\nchanged; run scripts/run.py",
        encoding="utf-8",
    )
    with pytest.raises(PermissionError, match="maintenance"):
        gate.run_required("archive", ["maintenance"], {"maintenance": ["scripts/run.py"]})


def test_missing_or_failed_required_skill_blocks_stage(tmp_path) -> None:
    root = tmp_path / "skills"
    write_skill(root, "broken", "Run scripts/run.py.", "import sys\nprint('validation detail', file=sys.stderr)\nraise SystemExit(2)")
    db = Database(tmp_path / "app.db")
    db.migrate()
    gate = SkillGate(db, SkillScanner([root]))

    with pytest.raises(LookupError, match="missing"):
        gate.run_required("review", ["missing"])

    skill = gate.skills()["broken"]
    db.approve_skill(skill.name, skill.content_hash)
    with pytest.raises(RuntimeError, match="broken"):
        gate.run_required("review", ["broken"], {"broken": ["scripts/run.py"]})
    receipt = db.list_skill_receipts()[-1]
    assert receipt["status"] == "failed"
    assert "skill.execution_failed" in receipt["output"]
    assert "validation detail" not in receipt["output"]


def test_javascript_skill_uses_configured_bundled_runtime(tmp_path) -> None:
    root = tmp_path / "skills"
    folder = write_skill(root, "maintenance", "Run scripts/run.js.")
    scripts = folder / "scripts"
    scripts.mkdir()
    (scripts / "run.js").write_text("print('bundled')", encoding="utf-8")
    db = Database(tmp_path / "app.db")
    db.migrate()
    gate = SkillGate(db, SkillScanner([root]), node_executable=Path(sys.executable))
    skill = gate.skills()["maintenance"]
    db.approve_skill(skill.name, skill.content_hash)

    result = gate.run_required("archive", ["maintenance"], {"maintenance": ["scripts/run.js"]})

    assert result.receipts[0].output == "bundled"


def test_project_skill_is_discovered_per_run_and_overrides_global(tmp_path) -> None:
    global_root = tmp_path / "global"
    write_skill(global_root, "dialogue", "Global voice")
    project = tmp_path / "project"
    gate = SkillGate(Database(tmp_path / "app.db"), SkillScanner([global_root]))
    gate.db.migrate()

    write_skill(project / ".agents" / "skills", "dialogue", "Project voice")
    result = gate.run_required("draft", ["dialogue"], project_root=project)

    assert "Project voice" in result.prompt
    assert "Global voice" not in result.prompt
