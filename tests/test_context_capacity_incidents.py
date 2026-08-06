import ast
import json
from pathlib import Path

from novel_flywheel.production_incidents import classify_production_failure
from novel_flywheel.context_policy import (
    bounded_protocol_output_budget,
    classify_input_pressure,
    scoped_creative_output_budget,
    stage_output_budget,
)


def test_indivisible_scope_production_fixture_has_distinct_recovery_family() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "context_capacity_e86225d9.json")
        .read_text(encoding="utf-8")
    )

    incident = classify_production_failure(
        fixture["message"], workflow=fixture["workflow"], stage=fixture["stage"],
    )

    assert incident["incident_family"] == fixture["incident_family"]
    assert "不变量" in incident["known_resolution"]
    assert "重叠证据窗口" in incident["known_resolution"]


def test_bounded_protocol_budget_does_not_inherit_creative_stage_floor() -> None:
    bounded = bounded_protocol_output_budget(
        expected_output_characters=900,
        input_tokens=20_000,
        context_window=32_768,
        declared_output_ceiling=16_384,
    )

    assert 768 <= bounded < stage_output_budget("review")


def test_targeted_repair_production_fixture_fits_after_scope_aware_reserve() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "context_capacity_d785dd5c.json")
        .read_text(encoding="utf-8")
    )

    patch_reserve = bounded_protocol_output_budget(
        expected_output_characters=1600,
        input_tokens=fixture["estimated_input_tokens"],
        context_window=fixture["context_window"],
        declared_output_ceiling=None,
    )
    rebuild_reserve = scoped_creative_output_budget(
        expected_output_characters=1600,
        input_tokens=fixture["estimated_input_tokens"] - 4000,
        context_window=fixture["context_window"],
        declared_output_ceiling=None,
    )
    incident = classify_production_failure(
        fixture["message"], workflow=fixture["workflow"], stage=fixture["stage"],
    )

    assert incident["incident_family"] == fixture["incident_family"]
    assert "定向 JSON 补丁" in incident["known_resolution"]
    assert "主备路由" in incident["known_resolution"]
    assert patch_reserve < fixture["output_reserve_tokens"]
    assert rebuild_reserve < fixture["output_reserve_tokens"]
    assert classify_input_pressure(
        full_input_tokens=fixture["estimated_input_tokens"],
        authority_input_tokens=fixture["authority_input_tokens"],
        output_reserve=patch_reserve,
        context_window=fixture["context_window"],
    ) == "full"


def test_every_guarded_stage_declares_a_capacity_execution_contract() -> None:
    source_path = Path(__file__).parents[1] / "src" / "novel_flywheel" / "workflows.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    missing: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "_stage":
            continue
        keywords = {item.arg: item.value for item in node.keywords if item.arg}
        guard = keywords.get("route_capacity_guard")
        if not isinstance(guard, ast.Constant) or guard.value is not True:
            continue
        if not any(name in keywords for name in (
            "capacity_splitter", "bounded_protocol_output",
            "scoped_creative_output",
        )):
            missing.append(node.lineno)

    assert missing == [], (
        "route_capacity_guard calls must declare semantic splitting, bounded "
        f"protocol output, or scoped creative output; missing at lines {missing}"
    )
