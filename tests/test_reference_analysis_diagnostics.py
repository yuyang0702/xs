from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from novel_flywheel.learning import LearningSystem
from novel_flywheel.reference_analysis_diagnostics import (
    CAPTURE_FLAG,
    ReferenceAnalysisDiagnosticContextV1,
    capture_candidate,
    observe_stage,
)
import novel_flywheel.reference_analysis_diagnostics as diagnostics_module
from novel_flywheel.reference_distillation import (
    DistillationRegionV1,
    DistillationSemanticValidationError,
    validate_distillation_receipt,
)


def _region(child_ids=None) -> DistillationRegionV1:
    child_ids = list(child_ids or ["window:1"])
    payload = {"events": [{"fact": "证据", "start": 0, "end": 2}]}
    import hashlib

    digest = hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    return DistillationRegionV1(
        level=0, region_index=0, child_ids=child_ids,
        source_start=0, source_end=2,
        input_sha256=hashlib.sha256(json.dumps({
            "level": 0, "child_ids": child_ids, "payloads": [payload for _ in child_ids],
            "source_range": [0, 2],
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        payloads=[payload for _ in child_ids],
    )


def _receipt(*, semantic=None, child_id="window:1", path="/mechanisms/0"):
    return {
        "version": 2,
        "covered_child_ids": [child_id],
        "child_dispositions": [{
            "child_id": child_id, "disposition": "promoted", "reason": "evidence-is-valid",
        }],
        "child_attributions": [{
            "child_id": child_id, "relation": "claim", "semantic_path": path,
        }],
        "semantic": semantic or {"mechanisms": [{"name": "规则"}]},
    }


def test_distillation_failures_keep_rule_and_safe_object_identity() -> None:
    region = _region()
    with pytest.raises(ValidationError) as missing:
        validate_distillation_receipt(region, {"version": 2, "semantic": {}})
    assert any(item["loc"] == ("covered_child_ids",) for item in missing.value.errors())

    with pytest.raises(DistillationSemanticValidationError) as coverage:
        validate_distillation_receipt(region, {
            **_receipt(), "covered_child_ids": ["window:other"],
        })
    assert coverage.value.rule_code == "child_coverage_mismatch"
    assert coverage.value.field_path == "/covered_child_ids"
    assert coverage.value.child_ids == ("window:1",)

    with pytest.raises(DistillationSemanticValidationError) as path:
        validate_distillation_receipt(region, {
            **_receipt(path="/mechanisms/99"),
        })
    assert path.value.rule_code == "attribution_path_missing"
    assert path.value.field_path == "/mechanisms/99"

    with pytest.raises(DistillationSemanticValidationError) as disposition:
        validate_distillation_receipt(region, {
            **_receipt(), "child_dispositions": [{
                "child_id": "other", "disposition": "promoted", "reason": "evidence-is-valid",
            }],
        })
    assert disposition.value.rule_code == "disposition_coverage_mismatch"

    two = _region(["window:1", "window:2"])
    duplicate = {
        "version": 2,
        "covered_child_ids": ["window:1", "window:2"],
        "child_dispositions": [{
            "child_id": child, "disposition": "promoted", "reason": "evidence-is-valid",
        } for child in ["window:1", "window:2"]],
        "child_attributions": [{
            "child_id": child, "relation": "claim", "semantic_path": "/mechanisms/0",
        } for child in ["window:1", "window:2"]],
        "semantic": {"mechanisms": [{"name": "规则"}]},
    }
    with pytest.raises(DistillationSemanticValidationError) as duplicate_error:
        validate_distillation_receipt(two, duplicate)
    assert duplicate_error.value.rule_code == "attribution_path_duplicate"


def test_normalization_cannot_hide_reference_invalidation() -> None:
    region = _region()
    rules = [{
        "field": "viewpoint", "rule": f"规则{index}",
        "when_to_use": "需要时", "avoid": "不要滥用", "supporting_windows": [1],
    } for index in range(1, 6)]
    semantic = {
        "mechanisms": [{"name": "规则", "supporting_windows": [1], "transfer_guidance": "迁移"}],
        "attraction_map": {},
        "style_profile": {"summary": "简洁", "rules": rules, "uncertainties": []},
    }
    receipt = _receipt(semantic=semantic, path="/style_profile/rules/4")
    first = validate_distillation_receipt(region, receipt)
    normalized = LearningSystem._synthesis_result(first)
    with pytest.raises(DistillationSemanticValidationError) as second:
        validate_distillation_receipt(
            region, {**receipt, "semantic": normalized},
        )
    assert second.value.rule_code == "attribution_path_missing"
    assert second.value.field_path == "/style_profile/rules/4"


def test_private_capture_is_attempt_scoped_and_diagnostic_write_is_not_business_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CAPTURE_FLAG, "1")
    base = ReferenceAnalysisDiagnosticContextV1(
        project_root=tmp_path, source_id="source", source_version_id="version",
        source_content_sha256="a" * 64, task_id="task", run_id="task",
    )
    first = base.__class__(**{**base.__dict__, "lane": "primary", "attempt": 1})
    second = base.__class__(**{**base.__dict__, "lane": "configured_fallback", "attempt": 2})
    capture_candidate(first, phase="candidate_arrived", visible_text="甲", receipt={})
    capture_candidate(second, phase="candidate_arrived", visible_text="乙", receipt={})
    files = list((tmp_path / "runtime" / "reference-analysis-captures").rglob("*.json"))
    assert len(files) == 2
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in files]
    assert {item["attempt"] for item in payloads} == {1, 2}
    assert {item["lane"] for item in payloads} == {"primary", "configured_fallback"}
    assert {item["visible_text"] for item in payloads} == {"甲", "乙"}
    assert all("api_key" not in path.read_text(encoding="utf-8") for path in files)


def test_diagnostic_write_failure_is_fail_open_and_does_not_create_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ReferenceAnalysisDiagnosticContextV1(
        project_root=tmp_path, source_id="source", source_version_id="version",
        source_content_sha256="a" * 64, task_id="task", run_id="task",
    )
    monkeypatch.setattr(diagnostics_module, "emit_observation", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("trace down")))
    assert observe_stage(
        context, stage="schema_validation", status="passed", candidate_sha256="b" * 64,
    ) is False
    with pytest.raises(DistillationSemanticValidationError):
        validate_distillation_receipt(_region(), {
            **_receipt(path="/mechanisms/99"),
        })
