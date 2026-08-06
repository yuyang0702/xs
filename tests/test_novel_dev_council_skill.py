from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents" / "skills" / "novel-dev-council"


def _load_script(name: str):
    path = SKILL / "scripts" / name
    spec = importlib.util.spec_from_file_location(f"novel_dev_council_{path.stem}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_change_gate_parses_nul_porcelain_with_unicode_and_rename() -> None:
    gate = _load_script("inspect_change_gate.py")
    raw = (
        " M src/novel_flywheel/测试 文件.py\0"
        "R  src/novel_flywheel/new name.py\0"
        "src/novel_flywheel/old name.py\0"
    ).encode("utf-8")

    assert gate._parse_status_z(raw) == [
        "src/novel_flywheel/new name.py",
        "src/novel_flywheel/old name.py",
        "src/novel_flywheel/测试 文件.py",
    ]


def test_change_gate_baseline_isolates_preexisting_dirty_files() -> None:
    gate = _load_script("inspect_change_gate.py")
    baseline = {
        "tests/test_unrelated.py": {"exists": True, "sha256": "old-test"},
        "README.md": {"exists": True, "sha256": "old-doc"},
    }
    current = {
        **baseline,
        "src/novel_flywheel/workflows.py": {"exists": True, "sha256": "new-code"},
    }

    changed = gate._task_changed_paths(baseline, current)
    report = gate._classify(changed)

    assert changed == ["src/novel_flywheel/workflows.py"]
    assert report["recommended_level"] == "L3"
    assert report["test_paths"] == []
    assert any("regression test" in item for item in report["warnings"])
    assert any("README.md" in item for item in report["warnings"])


def test_change_gate_classifies_ui_and_requires_console_test() -> None:
    gate = _load_script("inspect_change_gate.py")

    missing = gate._classify(["src/novel_flywheel/static/app.js"])
    passing = gate._classify(
        ["src/novel_flywheel/static/app.js", "tests/test_console.py"]
    )

    assert missing["recommended_level"] == "L2"
    assert any("tests/test_console.py" in item for item in missing["warnings"])
    assert passing["warnings"] == []


def test_change_gate_declared_test_satisfies_nonstandard_mapping() -> None:
    gate = _load_script("inspect_change_gate.py")
    report = gate._classify(
        [
            "src/novel_flywheel/workflows.py",
            "docs/maintenance.md",
        ],
        {
            "src/novel_flywheel/workflows.py": {
                "tests/test_execution_manifest_workflow.py"
            }
        },
    )

    assert report["recommended_level"] == "L3"
    assert report["warnings"] == []


def test_change_gate_mapping_covers_only_its_named_source() -> None:
    gate = _load_script("inspect_change_gate.py")
    report = gate._classify(
        [
            "src/novel_flywheel/workflows.py",
            "src/novel_flywheel/story_state.py",
            "docs/maintenance.md",
        ],
        {
            "src/novel_flywheel/workflows.py": {
                "tests/test_execution_manifest_workflow.py"
            }
        },
    )

    assert any("story_state.py" in item for item in report["warnings"])
    assert not any("workflows.py ->" in item for item in report["warnings"])


def test_change_gate_validates_related_test_mapping_paths() -> None:
    gate = _load_script("inspect_change_gate.py")
    changed = ["src/novel_flywheel/workflows.py"]

    valid = gate._related_test_mappings(
        ["src/novel_flywheel/workflows.py=tests/test_workflows.py"], ROOT, changed
    )

    assert valid == {
        "src/novel_flywheel/workflows.py": {"tests/test_workflows.py"}
    }

    for invalid in (
        "tests/test_workflows.py",
        "src/novel_flywheel/other.py=tests/test_workflows.py",
        "src/novel_flywheel/workflows.py=README.md",
        "src/novel_flywheel/workflows.py=tests/does_not_exist.py",
        "src/novel_flywheel/workflows.py=tests/../src/novel_flywheel/workflows.py",
    ):
        try:
            gate._related_test_mappings([invalid], ROOT, changed)
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"invalid mapping accepted: {invalid}")


def test_change_gate_allows_explicit_ui_test_mapping() -> None:
    gate = _load_script("inspect_change_gate.py")
    report = gate._classify(
        ["src/novel_flywheel/static/app.js"],
        {
            "src/novel_flywheel/static/app.js": {
                "tests/test_novel_dev_council_skill.py"
            }
        },
    )

    assert report["warnings"] == []


def test_change_gate_treats_all_api_code_as_l3() -> None:
    gate = _load_script("inspect_change_gate.py")
    report = gate._classify(
        [
            "src/novel_flywheel/api/references.py",
            "tests/api/test_references.py",
            "docs/maintenance.md",
        ]
    )

    assert report["automatic_level"] == "L3"
    assert report["recommended_level"] == "L3"
    assert report["warnings"] == []


def test_change_gate_declared_level_can_raise_but_not_lower_risk() -> None:
    gate = _load_script("inspect_change_gate.py")

    raised = gate._classify(["AGENTS.md"], declared_level="L3")
    not_lowered = gate._classify(
        [
            "src/novel_flywheel/workflows.py",
            "tests/test_workflows.py",
            "docs/maintenance.md",
        ],
        declared_level="L1",
    )

    assert raised["automatic_level"] == "L1"
    assert raised["recommended_level"] == "L3"
    assert not_lowered["automatic_level"] == "L3"
    assert not_lowered["recommended_level"] == "L3"


def test_change_gate_validates_forward_risk_report(tmp_path) -> None:
    gate = _load_script("inspect_change_gate.py")
    report_path = tmp_path / "forward-risk.json"
    report_path.write_text(json.dumps({
        "version": 1,
        "historical_incident_families_checked": ["model.context_capacity_preflight"],
        "projected_failure_mechanisms": ["input capacity", "partial checkpoint"],
        "model_output_boundary_changed": True,
        "model_output_variants_tested": [
            "dialogue-led valid realization",
            "action-led valid realization",
            "verbose wrapped valid realization",
            "terse valid realization",
            "pronoun-led valid realization",
            "multilingual-label valid realization",
        ],
        "invalid_output_variants_tested": [
            "normal-finish incomplete receipt",
            "contradictory actor-action binding",
        ],
        "transport_capacity_variants_tested": [
            "unknown provider context overflow",
            "SSE disconnect after a partial payload",
        ],
        "why_previous_tests_missed": (
            "The old fake provider never reproduced production payload proportions."
        ),
        "sibling_boundaries": [{
            "boundary": "polish semantic review",
            "disposition": "tested_not_susceptible",
            "evidence": (
                "tests/test_context_capacity_incidents.py exercises the guarded route"
            ),
        }],
        "production_shaped_tests": ["tests/test_context_capacity_incidents.py"],
        "next_authoritative_boundary_tests": [
            "tests/test_planning_adaptation_workflow.py"
        ],
        "invariant_test_paths": ["tests/test_narrative_contract.py"],
        "remaining_risks": [],
    }, ensure_ascii=False), encoding="utf-8")

    report = gate._load_forward_risk_report(report_path, ROOT)

    assert report["historical_incident_families_checked"] == [
        "model.context_capacity_preflight"
    ]
    assert len(report["model_output_variants_tested"]) == 6
    assert len(report["invalid_output_variants_tested"]) == 2
    assert len(report["transport_capacity_variants_tested"]) == 2
    assert report["sibling_boundaries"][0]["disposition"] == (
        "tested_not_susceptible"
    )


def test_change_gate_rejects_incomplete_forward_risk_report(tmp_path) -> None:
    gate = _load_script("inspect_change_gate.py")
    report_path = tmp_path / "forward-risk.json"
    report_path.write_text(json.dumps({
        "version": 1,
        "historical_incident_families_checked": [],
    }), encoding="utf-8")

    try:
        gate._load_forward_risk_report(report_path, ROOT)
    except RuntimeError as exc:
        assert "historical_incident_families_checked" in str(exc)
    else:
        raise AssertionError("incomplete forward-risk report was accepted")


def test_scope_script_confirms_repository_without_writing() -> None:
    result = subprocess.run(
        [str(ROOT / ".venv" / "Scripts" / "python.exe"), "-X", "utf8", str(SKILL / "scripts" / "check_project_scope.py")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert Path(payload["git_root"]).resolve() == ROOT.resolve()


def test_repository_policy_requires_explicit_team_review_opt_in() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")

    assert "Team review is opt-in only" in agents
    assert "**团队评审**" in agents
    assert "Team review is opt-in" in skill
    assert "Never infer that authorization" in skill


def test_repository_policy_requires_granular_recovery_isolation() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "## Granular Recovery Isolation Gate" in agents
    assert "MUST NOT automatically revoke another unit" in agents
    assert "whole-story validation" in agents
    assert "downstream collateral rollback" in agents
    assert "polish, and targeted/manual revision" in agents


def test_repository_policy_requires_forward_incident_projection_and_variants() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    shield = (SKILL / "references" / "regression-shield.md").read_text(
        encoding="utf-8"
    )

    assert "forward-risk scan" in agents
    assert "complete historical incident catalog" in agents
    assert "## Non-Deterministic Model Output Gate" in agents
    assert "six materially different valid realizations" in agents
    assert "forward-risk report" in skill
    assert "strict gate must fail" in skill
    assert "Forward incident projection" in shield
    assert "why_previous_tests_missed" in shield
    assert "Non-deterministic model output" in shield
