from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.diagnostics import materialize_skill_v3_hybrid_post_campaign as post


ROOT = Path(__file__).resolve().parents[2]


def test_anonymous_ids_are_stable_unique_and_arm_neutral() -> None:
    ids = {
        post.anonymous_id("a" * 64, pair, side)
        for pair in range(1, 4)
        for side in range(1, 3)
    }
    assert len(ids) == 6
    assert all(value.startswith("hybrid-blind-") for value in ids)
    assert all(token not in value for value in ids for token in ("CONTROL", "HYBRID"))


def test_pair_order_is_balanced_and_complete() -> None:
    assert post.PAIR_ORDER == (
        ("CONTROL_1", "HYBRID_1"),
        ("CONTROL_2", "HYBRID_2"),
        ("CONTROL_3", "HYBRID_3"),
    )
    assert post.visible_pair_order(1) == ("HYBRID_1", "CONTROL_1")
    assert post.visible_pair_order(2) == ("CONTROL_2", "HYBRID_2")
    assert post.visible_pair_order(3) == ("HYBRID_3", "CONTROL_3")


def test_vote_validation_requires_exact_three_pairs_and_eight_dimensions() -> None:
    pairs = [
        {
            "anonymous_pair_id": f"hybrid-blind-pair-{index}",
            "position_a_anonymous_sample_id": f"a{index}",
            "position_b_anonymous_sample_id": f"b{index}",
        }
        for index in range(1, 4)
    ]
    votes = post.empty_evaluator_record("e1", pairs)
    for vote in votes["votes"]:
        vote["dimension_relations"] = {dimension: "TIE" for dimension in post.DIMENSIONS}
    post.validate_evaluator_record(votes, pairs)
    del votes["votes"][0]["dimension_relations"][post.DIMENSIONS[0]]
    with pytest.raises(RuntimeError, match="EVALUATOR_DIMENSION_SET_MISMATCH"):
        post.validate_evaluator_record(votes, pairs)


def test_aggregate_requires_six_votes_and_does_not_average() -> None:
    pairs = [
        {
            "anonymous_pair_id": f"hybrid-blind-pair-{index}",
            "position_a_anonymous_sample_id": f"a{index}",
            "position_b_anonymous_sample_id": f"b{index}",
        }
        for index in range(1, 4)
    ]
    records = []
    for evaluator in ("e1", "e2"):
        record = post.empty_evaluator_record(evaluator, pairs)
        for vote in record["votes"]:
            vote["dimension_relations"] = {dimension: "B_BETTER" for dimension in post.DIMENSIONS}
        records.append(record)
    combined = post.aggregate_blind_votes(records, pairs)
    assert combined["observed_evaluator_by_batch_votes"] == 6
    assert combined["scalar_average_created"] is False
    assert all(row["blind_relation"] == "B_BETTER" for row in combined["dimensions"])


def test_manifest_is_recursive_exact_and_excludes_itself(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "a.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "nested" / "b.md").write_text("x\n", encoding="utf-8")
    manifest = post.manifest(tmp_path, "TestManifestV1")
    assert [row["path"] for row in manifest["entries"]] == ["a.json", "nested/b.md"]
    assert manifest["entries"][0]["sha256"] == hashlib.sha256(
        (tmp_path / "a.json").read_bytes()
    ).hexdigest()


def test_phase_a_materialization_is_exact_and_mapping_is_not_visible() -> None:
    campaign = ROOT / post.CAMPAIGN_EVIDENCE_RELATIVE
    blind = ROOT / post.BLIND_BUNDLE_RELATIVE
    mapping = ROOT / post.MAPPING_RELATIVE
    if not campaign.exists():
        pytest.skip("phase A evidence not materialized yet")
    for evidence_root in (campaign, blind, mapping):
        exact = json.loads((evidence_root / "sha256-manifest-v1.json").read_text("utf-8"))
        for row in exact["entries"]:
            data = (evidence_root / row["path"]).read_bytes()
            assert row["bytes"] == len(data)
            assert row["sha256"] == hashlib.sha256(data).hexdigest()
    visible = b"\n".join(path.read_bytes() for path in blind.rglob("*") if path.is_file())
    sealed = json.loads((mapping / "sealed-mapping-v1.json").read_text("utf-8"))
    for row in sealed["rows"]:
        assert row["sample_id"].encode() not in visible
    assert b'"experiment_arm"' not in visible
