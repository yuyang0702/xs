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


def _valid_forward_risk_payload() -> dict:
    return {
        "version": 2,
        "original_requirement": (
            "All future provider-shaped planning receipts must recover without "
            "narrowing to the observed payload."
        ),
        "scope_classification": "open_world",
        "operational_definition": (
            "Normalize structurally equivalent receipts by stable ownership and "
            "authority invariants, then cross the next workflow boundary."
        ),
        "forbidden_narrowing": [
            "Do not support only the currently observed container key.",
            "Do not count fail-closed containment as recovery.",
        ],
        "resolution_status": "systemically_resolved",
        "constraint_traceability": [{
            "requirement": "Recover unseen structurally equivalent model output.",
            "implementation": "Use an invariant-driven normalization boundary.",
            "test_paths": ["tests/test_narrative_contract.py"],
            "evidence": "Metamorphic topology variants cross the next boundary.",
        }],
        "historical_incident_families_checked": [
            "model.context_capacity_preflight"
        ],
        "projected_failure_mechanisms": ["input capacity", "partial checkpoint"],
        "model_output_boundary_changed": True,
        "model_output_variants_tested": [
            "top-level event array",
            "event-id keyed mapping",
            "nested event array",
            "block list realization",
            "unknown alpha container realization",
            "unknown beta wrapper realization",
        ],
        "model_output_topology_classes_tested": [
            "top_level_array",
            "event_id_mapping",
            "nested_event_array",
            "block_list",
        ],
        "unseen_valid_variants_tested": [
            "generated container alpha absent from source and fixtures",
            "generated wrapper beta absent from source and fixtures",
        ],
        "unknown_variant_behavior": (
            "Unambiguous invariant-complete payloads normalize locally; ambiguous "
            "machine control retries the canonical receipt without guessing."
        ),
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
    }


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


def test_change_gate_accepts_current_hash_bound_split_review(tmp_path) -> None:
    gate = _load_script("inspect_change_gate.py")
    core_paths = [
        "src/novel_flywheel/workflows.py",
        "src/novel_flywheel/planning_compiler.py",
        "src/novel_flywheel/quality.py",
    ]
    payload = {
        "version": 1,
        "core_tree_sha256": gate._core_review_sha256(ROOT, core_paths),
        "reviews": [
            {
                "review_id": "planning-authority",
                "reviewer": "reviewer-a",
                "status": "passed",
                "core_paths": core_paths[:2],
                "test_paths": ["tests/test_workflows.py"],
                "evidence": "Exact authority ownership and next-boundary tests passed.",
            },
            {
                "review_id": "quality-authority",
                "reviewer": "reviewer-b",
                "status": "passed",
                "core_paths": core_paths[2:],
                "test_paths": ["tests/test_quality.py"],
                "evidence": "Runtime issue ownership and terminal reconciliation passed.",
            },
        ],
    }
    report_path = tmp_path / "split-review.json"
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    report = gate._load_split_review_report(report_path, ROOT, core_paths)

    assert report["core_tree_sha256"] == payload["core_tree_sha256"]
    assert len(report["reviews"]) == 2


def test_change_gate_rejects_stale_or_incomplete_split_review(tmp_path) -> None:
    gate = _load_script("inspect_change_gate.py")
    core_paths = [
        "src/novel_flywheel/workflows.py",
        "src/novel_flywheel/planning_compiler.py",
        "src/novel_flywheel/quality.py",
    ]
    payload = {
        "version": 1,
        "core_tree_sha256": "0" * 64,
        "reviews": [],
    }
    report_path = tmp_path / "split-review.json"
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        gate._load_split_review_report(report_path, ROOT, core_paths)
    except RuntimeError as exc:
        assert "current core file snapshot" in str(exc)
    else:
        raise AssertionError("stale split review was accepted")

    payload["core_tree_sha256"] = gate._core_review_sha256(ROOT, core_paths)
    payload["reviews"] = [
        {
            "review_id": "incomplete",
            "reviewer": "reviewer-a",
            "status": "passed",
            "core_paths": core_paths[:2],
            "test_paths": ["tests/test_workflows.py"],
            "evidence": "One slice only.",
        },
        {
            "review_id": "duplicate",
            "reviewer": "reviewer-b",
            "status": "passed",
            "core_paths": [core_paths[0]],
            "test_paths": ["tests/test_quality.py"],
            "evidence": "Duplicates one path and omits another.",
        },
    ]
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        gate._load_split_review_report(report_path, ROOT, core_paths)
    except RuntimeError as exc:
        assert "reviewed more than once" in str(exc)
    else:
        raise AssertionError("overlapping split review was accepted")


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
    report_path.write_text(
        json.dumps(_valid_forward_risk_payload(), ensure_ascii=False),
        encoding="utf-8",
    )

    report = gate._load_forward_risk_report(report_path, ROOT)

    assert report["historical_incident_families_checked"] == [
        "model.context_capacity_preflight"
    ]
    assert len(report["model_output_variants_tested"]) == 6
    assert len(report["invalid_output_variants_tested"]) == 2
    assert len(report["transport_capacity_variants_tested"]) == 2
    assert len(report["model_output_topology_classes_tested"]) == 4
    assert len(report["unseen_valid_variants_tested"]) == 2
    assert report["scope_classification"] == "open_world"
    assert report["resolution_status"] == "systemically_resolved"
    assert report["sibling_boundaries"][0]["disposition"] == (
        "tested_not_susceptible"
    )


def test_change_gate_rejects_cosmetic_variants_without_topology_diversity(
    tmp_path,
) -> None:
    gate = _load_script("inspect_change_gate.py")
    payload = _valid_forward_risk_payload()
    payload["model_output_topology_classes_tested"] = [
        "same_mapping",
        "same_mapping",
        "same_mapping",
        "same_mapping",
    ]
    report_path = tmp_path / "forward-risk.json"
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    try:
        gate._load_forward_risk_report(report_path, ROOT)
    except RuntimeError as exc:
        assert "four distinct" in str(exc)
    else:
        raise AssertionError("cosmetic-only topology variants were accepted")


def test_change_gate_rejects_missing_unseen_valid_variants(tmp_path) -> None:
    gate = _load_script("inspect_change_gate.py")
    payload = _valid_forward_risk_payload()
    payload["unseen_valid_variants_tested"] = ["only observed fixture"]
    report_path = tmp_path / "forward-risk.json"
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    try:
        gate._load_forward_risk_report(report_path, ROOT)
    except RuntimeError as exc:
        assert "two distinct unseen_valid_variants_tested" in str(exc)
    else:
        raise AssertionError("report without unseen valid variants was accepted")


def test_change_gate_open_world_case_fix_cannot_claim_completion() -> None:
    gate = _load_script("inspect_change_gate.py")
    payload = _valid_forward_risk_payload()
    payload["resolution_status"] = "case_fixed"

    warnings = gate._forward_risk_completion_warnings(payload)

    assert any("systemically_resolved" in item for item in warnings)
    payload["scope_classification"] = "closed_world"
    assert gate._forward_risk_completion_warnings(payload) == []


def test_change_gate_rejects_incomplete_forward_risk_report(tmp_path) -> None:
    gate = _load_script("inspect_change_gate.py")
    report_path = tmp_path / "forward-risk.json"
    report_path.write_text(json.dumps({
        "version": 2,
        "original_requirement": "keep the requirement open-world",
        "scope_classification": "open_world",
        "operational_definition": "recover equivalent future shapes",
        "forbidden_narrowing": ["do not bind to one fixture"],
        "resolution_status": "systemically_resolved",
        "constraint_traceability": [{
            "requirement": "recover equivalent shapes",
            "implementation": "shared normalization boundary",
            "test_paths": ["tests/test_narrative_contract.py"],
            "evidence": "invariant-based regression",
        }],
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


def test_repository_policy_forbids_open_world_requirement_narrowing() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    contract = (SKILL / "references" / "decision-contract.md").read_text(
        encoding="utf-8"
    )
    shield = (SKILL / "references" / "regression-shield.md").read_text(
        encoding="utf-8"
    )

    assert "## Open-World Requirement Non-Narrowing Gate" in agents
    assert "MUST NOT silently narrow" in agents
    assert "four materially different topology classes" in agents
    assert "systemically_resolved" in agents
    assert "Prevent sample-specific completion claims" in skill
    assert "scope is `open_world` or `closed_world`" in skill
    assert "Forbidden narrowing" in contract
    assert "version 2 JSON report" in shield
    assert "unseen_valid_variants_tested" in shield


def test_repository_policy_requires_root_cause_architecture_convergence() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "## Root-Cause Architecture Convergence Gate" in agents
    assert "mechanism-level root-cause analysis" in agents
    assert "mature standards, maintained libraries" in agents
    assert "Patch accumulation is prohibited" in agents
    assert "convergence budget" in agents
    assert "deprecation, or deletion plan" in agents
    assert "MUST NOT be reported as root resolution" in agents
    assert "never `systemically_resolved`" in agents


def test_repository_policy_requires_durable_systemic_end_to_end_acceptance() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    maintenance = (ROOT / "docs" / "maintenance.md").read_text(
        encoding="utf-8"
    )

    assert "## Systemic Workflow Completion and Forward Acceptance Gate" in agents
    assert "a complete draft candidate" in agents
    assert "segment-level and whole-draft semantic receipts" in agents
    assert "split/merge" in agents
    assert "pre-final-review quality gates" in agents
    assert "Forward-looking acceptance is a separate hard gate" in agents
    for boundary in (
        "causal chain",
        "execution manifest",
        "drafting",
        "polish",
        "targeted and manual revision",
        "final review",
        "formal promotion",
    ):
        assert boundary in agents
    assert "MUST NOT trade away prose quality" in agents
    assert "new task, window, process, or compacted context" in agents
    assert "proportionate acceptance" in agents
    assert "MUST NOT call a paid model API" in agents

    assert "systemic completion gate" in skill
    assert "complete draft candidate" in skill
    assert "forward-looking acceptance" in skill
    assert "new window or compacted context" in skill
    assert "does not require paid-provider execution" in skill

    assert "### Durable systemic completion and forward acceptance" in maintenance
    assert "complete draft candidate" in maintenance
    assert "independent forward-looking gate" in maintenance
    assert "cannot be bypassed by opening a new task" in maintenance
