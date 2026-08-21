from __future__ import annotations

import ast
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from tools.diagnostics.short_plan_v2_slice1 import run_replay


ROOT = Path(__file__).parents[1]
FIXTURE = (
    ROOT / "tests" / "fixtures" / "reliability" / "short_plan_v2_slice1"
    / "event-realization-shadow-corpus-v1.json"
)
TOOL = ROOT / "tools" / "diagnostics" / "short_plan_v2_slice1.py"


def _clock(*values: float):
    iterator = iter(values)
    return lambda: next(iterator)


def _tree_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _protected_hash() -> str:
    paths = [
        ROOT / "src" / "novel_flywheel" / "workflows.py",
        ROOT / "src" / "novel_flywheel" / "contract_runtime.py",
        ROOT / "src" / "novel_flywheel" / "planning_semantics.py",
    ]
    paths.extend((ROOT / "baml_src").rglob("*"))
    return _tree_hash([path for path in paths if path.is_file()])


def test_offline_replay_executes_all_required_families_exactly() -> None:
    receipt = run_replay(FIXTURE, clock=_clock(10.0, 10.025))

    assert receipt["overall_status"] == "exact"
    assert receipt["case_count"] == 20
    assert {row["case_family"] for row in receipt["cases"]} >= {
        "latest_real_short_call1",
        "ptr3_targeted_repair",
        "planning_domain_failures",
        "structure_drift",
        "generated_artifact_shape",
        "dependency_impact",
        "successful_controls",
    }
    assert all(row["pass"] for row in receipt["cases"])
    call1 = next(row for row in receipt["cases"] if row["case_id"] == "latest-call1-unknown")
    assert call1["evidence"]["exact_failure_rule"] == "UNKNOWN"
    assert call1["evidence"]["invented_repair"] is False


def test_metrics_and_hard_zero_invariants_are_emitted() -> None:
    receipt = run_replay(FIXTURE, clock=_clock(1.0, 1.012))
    metrics = receipt["metrics"]

    assert metrics["llm_call_count"] == 0
    assert metrics["already_valid_field_mutation_count"] == 0
    assert metrics["freeze_violation_count"] == 0
    assert metrics["stale_finding_count"] == 0
    assert metrics["same_failure_dispatch_count"] == 0
    assert metrics["same_failure_without_state_change_count"] == 1
    assert metrics["dependency_closure_size"] == 2
    assert metrics["slice1_regeneration_count"] == 1
    assert metrics["semantic_regression_count"] == 0
    assert metrics["replay_elapsed_milliseconds"] == 12
    assert len(metrics["replay_case_identity"]) == receipt["case_count"]


def test_replay_is_deterministic_with_the_same_clock_and_preserves_v1_bytes() -> None:
    before = _protected_hash()
    left = run_replay(FIXTURE, clock=_clock(5.0, 5.005))
    right = run_replay(FIXTURE, clock=_clock(5.0, 5.005))
    after = _protected_hash()

    assert left == right
    assert before == after
    assert left["planning_v1_authority_changed"] is False
    assert left["draft_consumes_slice1"] is False
    assert left["story_state_mutated"] is False
    assert left["canon_mutated"] is False
    assert left["ready_mutated"] is False


def test_quality_preservation_is_obligation_based_not_aesthetic_scoring() -> None:
    receipt = run_replay(FIXTURE, clock=_clock(2.0, 2.001))

    assert receipt["quality_preservation"] == {
        "creative_fields": ["title", "narrative"],
        "local_derivation_creative_rewrite_count": 0,
        "obligation_oracle_kind": "explicit_sanitized_fixture_labels",
        "aesthetic_score_used": False,
    }
    valid = [row for row in receipt["cases"] if row["observed_status"] == "validated"]
    assert len(valid) == 6
    assert all(row["evidence"]["creative_content_preserved"] for row in valid)


def test_receipt_is_private_and_all_external_actions_remain_zero() -> None:
    receipt = run_replay(FIXTURE, clock=_clock(3.0, 3.002))
    stored = json.dumps(receipt, ensure_ascii=False, sort_keys=True)

    assert "PRIVATE_SYNTHETIC_PROSE_MARKER" not in stored
    assert receipt["external_actions"] == {
        "credential": 0,
        "provider_client": 0,
        "network": 0,
        "model": 0,
        "paid": 0,
    }


def test_runner_import_boundary_has_no_provider_or_production_writer() -> None:
    tree = ast.parse(TOOL.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        str(node.module)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not imports & {
        "novel_flywheel.workflows",
        "novel_flywheel.contract_runtime",
        "novel_flywheel.credentials",
        "novel_flywheel.providers",
        "httpx",
        "requests",
    }


def test_cli_writes_only_the_caller_selected_receipt(tmp_path) -> None:
    fixture = tmp_path / "fixture.json"
    output = tmp_path / "nested" / "receipt.json"
    shutil.copyfile(FIXTURE, fixture)

    completed = subprocess.run(
        [
            sys.executable, "-m", "tools.diagnostics.short_plan_v2_slice1",
            "--fixture", str(fixture), "--output", str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert output.is_file()
    assert json.loads(output.read_text(encoding="utf-8"))["overall_status"] == "exact"
    assert sorted(path.name for path in tmp_path.rglob("*") if path.is_file()) == [
        "fixture.json", "receipt.json",
    ]
