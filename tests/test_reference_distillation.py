from __future__ import annotations

import json

import pytest

from novel_flywheel.generated_artifacts import GeneratedArtifactGateway
from novel_flywheel.reference_distillation import (
    DistillationReceiptV2,
    SourceUseMode,
    compile_creative_recipe,
    distillation_needs_reduction,
    distillation_regions,
    leaf_distillation_items,
    promoted_distillation_items,
    source_use_mode,
    validate_distillation_receipt,
)


def claims(count: int) -> list[dict]:
    return [{
        "data": {
            "window": index + 1,
            "window_start": index * 100,
            "window_end": index * 100 + 140,
            "result": {"events": [f"event-{index}"], "state_changes": []},
        },
    } for index in range(count)]


def test_distillation_regions_have_exact_ordered_coverage_at_every_level() -> None:
    leaves = leaf_distillation_items(claims(17))
    level_zero = distillation_regions(leaves, fanout=4)
    assert [child for region in level_zero for child in region.child_ids] == [
        f"window:{index}" for index in range(1, 18)
    ]
    results = [{"mechanisms": [], "attraction_map": {}, "style_profile": {}}
               for _region in level_zero]
    promoted = promoted_distillation_items(level_zero, results)
    assert [
        child
        for item in promoted
        for child in item.payload["runtime_coverage"]["child_ids"]
    ] == [f"window:{index}" for index in range(1, 18)]
    assert all(
        item.payload["runtime_coverage"]["semantic_sha256"]
        for item in promoted
    )
    level_one = distillation_regions(promoted, level=1, fanout=4)
    assert len(level_one) == 2
    assert sum(len(item.child_ids) for item in level_one) == len(level_zero)


def test_distillation_receipt_requires_exact_dispositions_and_nonempty_promotion() -> None:
    region = distillation_regions(leaf_distillation_items(claims(2)))[0]
    empty_semantic = {
        "mechanisms": [], "attraction_map": {}, "style_profile": {},
    }
    promoted = {
        "version": 2,
        "covered_child_ids": list(region.child_ids),
        "child_dispositions": [
            {
                "child_id": child_id, "disposition": "promoted",
                "reason": "该窗口包含可迁移的结构发现",
            }
            for child_id in region.child_ids
        ],
        "semantic": empty_semantic,
    }
    with pytest.raises(ValueError, match="non-empty semantics"):
        validate_distillation_receipt(region, promoted)

    no_transfer = {
        **promoted,
        "child_dispositions": [
            {
                "child_id": child_id, "disposition": "no_transferable_claim",
                "reason": "该窗口没有可安全迁移的抽象发现",
            }
            for child_id in region.child_ids
        ],
    }
    assert validate_distillation_receipt(region, no_transfer) == empty_semantic

    missing = {**no_transfer, "covered_child_ids": list(region.child_ids[:-1])}
    with pytest.raises(ValueError, match="coverage mismatch"):
        validate_distillation_receipt(region, missing)


def test_distillation_receipt_cannot_discard_semantics_promoted_by_a_prior_level() -> None:
    leaves = leaf_distillation_items(claims(7))
    level_zero = distillation_regions(leaves, fanout=6)
    promoted = promoted_distillation_items(level_zero, [
        {
            "mechanisms": [{"name": f"retained-{index}"}],
            "attraction_map": {}, "style_profile": {},
        }
        for index, _region in enumerate(level_zero)
    ])
    level_one = distillation_regions(promoted, level=1, fanout=6)[0]
    discarding_receipt = {
        "version": 2,
        "covered_child_ids": list(level_one.child_ids),
        "child_dispositions": [
            {
                "child_id": child_id,
                "disposition": "no_transferable_claim",
                "reason": "错误地尝试丢弃上一层已经保留的发现",
            }
            for child_id in level_one.child_ids
        ],
        "semantic": {
            "mechanisms": [], "attraction_map": {}, "style_profile": {},
        },
    }

    with pytest.raises(ValueError, match="cannot be discarded"):
        validate_distillation_receipt(level_one, discarding_receipt)


def test_promoted_children_require_runtime_verifiable_output_attribution() -> None:
    region = distillation_regions(leaf_distillation_items(claims(2)))[0]
    semantic = {
        "mechanisms": [{"name": "状态变化机制"}],
        "attraction_map": {}, "style_profile": {},
    }
    receipt = {
        "version": 2,
        "covered_child_ids": list(region.child_ids),
        "child_dispositions": [{
            "child_id": child_id, "disposition": "promoted",
            "reason": "说明文字声称两个窗口都已保留",
        } for child_id in region.child_ids],
        "child_attributions": [{
            "child_id": region.child_ids[0], "relation": "claim",
            "semantic_path": "/mechanisms/0", "related_child_ids": [],
        }],
        "semantic": semantic,
    }

    with pytest.raises(ValueError, match="exact one-to-one semantic attribution"):
        validate_distillation_receipt(region, receipt)

    receipt["child_attributions"].append({
        "child_id": region.child_ids[1], "relation": "merged",
        "semantic_path": None, "related_child_ids": [region.child_ids[0]],
    })
    assert validate_distillation_receipt(region, receipt) == semantic


def test_registered_distillation_adapter_normalizes_alternate_v2_ledger() -> None:
    """Replay the five-window production failure's representation class."""

    region = distillation_regions(leaf_distillation_items(claims(2)))[0]
    semantic = {
        "mechanisms": [{"name": "A transferable state-change mechanism"}],
        "attraction_map": {}, "style_profile": {},
    }
    alternate = {
        "version": 2,
        "covered_child_ids": list(region.child_ids),
        "child_dispositions": [{
            "child_id": region.child_ids[0], "disposition": "promoted",
        }, {
            "child_id": region.child_ids[1], "disposition": "merged",
            "related_child_ids": [region.child_ids[0]],
        }],
        "child_attributions": [{
            "child_id": region.child_ids[0],
            "attribution_type": "claim",
            "semantic_path": "/semantic/mechanisms/0",
        }],
        "semantic": semantic,
    }

    converted = GeneratedArtifactGateway().convert_object(
        json.dumps(alternate),
        contract_name="reference_distillation_region",
        semantic_normalizer=lambda value: (
            DistillationReceiptV2.model_validate(value).model_dump(mode="json")
        ),
    )

    receipt = DistillationReceiptV2.model_validate(converted.payload)
    assert [item.disposition for item in receipt.child_dispositions] == [
        "promoted", "promoted",
    ]
    assert all(item.reason.strip() for item in receipt.child_dispositions)
    assert [item.relation for item in receipt.child_attributions] == [
        "claim", "merged",
    ]
    assert receipt.child_attributions[0].semantic_path == "/mechanisms/0"
    assert validate_distillation_receipt(region, converted.payload) == semantic
    assert "reference_distillation_v2_ledger_alignment" in converted.audit.transformations


def test_distillation_adapter_rejects_ambiguous_merged_ownership() -> None:
    region = distillation_regions(leaf_distillation_items(claims(2)))[0]
    alternate = {
        "version": 2,
        "covered_child_ids": list(region.child_ids),
        "child_dispositions": [{
            "child_id": region.child_ids[0], "disposition": "promoted",
        }, {
            "child_id": region.child_ids[1], "disposition": "merged",
            "related_child_ids": [region.child_ids[0]],
        }],
        "child_attributions": [{
            "child_id": region.child_ids[0], "attribution_type": "claim",
            "semantic_path": "/semantic/mechanisms/0",
        }, {
            "child_id": region.child_ids[1], "attribution_type": "claim",
            "semantic_path": "/semantic/mechanisms/1",
        }],
        "semantic": {
            "mechanisms": [{"name": "first"}, {"name": "conflicting second"}],
            "attraction_map": {}, "style_profile": {},
        },
    }

    with pytest.raises(ValueError):
        GeneratedArtifactGateway().convert_object(
            json.dumps(alternate),
            contract_name="reference_distillation_region",
            semantic_normalizer=lambda value: (
                DistillationReceiptV2.model_validate(value).model_dump(mode="json")
            ),
        )


def test_distillation_adapter_replays_current_five_window_failure_topology() -> None:
    """Sanitized replay: 5 children, 3 anchors, and 2 declared merges."""

    region = distillation_regions(leaf_distillation_items(claims(5)))[0]
    anchors = (region.child_ids[0], region.child_ids[2], region.child_ids[4])
    semantic = {
        "mechanisms": [
            {"name": "anchor-zero"},
            {"name": "anchor-two"},
            {"name": "anchor-four"},
        ],
        "attraction_map": {},
        "style_profile": {},
    }
    alternate = {
        "version": 2,
        "covered_child_ids": list(region.child_ids),
        "child_dispositions": [
            {"child_id": region.child_ids[0], "disposition": "promoted"},
            {
                "child_id": region.child_ids[1], "disposition": "merged",
                "related_child_ids": [region.child_ids[0]],
            },
            {"child_id": region.child_ids[2], "disposition": "promoted"},
            {
                "child_id": region.child_ids[3], "disposition": "merged",
                "related_child_ids": [region.child_ids[2], region.child_ids[4]],
            },
            {"child_id": region.child_ids[4], "disposition": "promoted"},
        ],
        "child_attributions": [
            {
                "child_id": child_id, "attribution_type": "claim",
                "semantic_path": f"/semantic/mechanisms/{index}",
            }
            for index, child_id in enumerate(anchors)
        ],
        "semantic": semantic,
    }

    converted = GeneratedArtifactGateway().convert_object(
        json.dumps(alternate),
        contract_name="reference_distillation_region",
        semantic_normalizer=lambda value: (
            DistillationReceiptV2.model_validate(value).model_dump(mode="json")
        ),
    )

    assert validate_distillation_receipt(region, converted.payload) == semantic
    assert [
        item["relation"] for item in converted.payload["child_attributions"]
    ] == ["claim", "claim", "claim", "merged", "merged"]


def test_promoted_children_cannot_claim_the_same_semantic_path_independently() -> None:
    region = distillation_regions(leaf_distillation_items(claims(2)))[0]
    receipt = {
        "version": 2,
        "covered_child_ids": list(region.child_ids),
        "child_dispositions": [{
            "child_id": child_id, "disposition": "promoted",
            "reason": "该窗口声明保留到结构化输出中",
        } for child_id in region.child_ids],
        "child_attributions": [{
            "child_id": child_id, "relation": "claim",
            "semantic_path": "/mechanisms/0", "related_child_ids": [],
        } for child_id in region.child_ids],
        "semantic": {
            "mechanisms": [{"name": "只有一个实际输出机制"}],
            "attraction_map": {}, "style_profile": {},
        },
    }

    with pytest.raises(ValueError, match="unique semantic paths"):
        validate_distillation_receipt(region, receipt)


def test_promoted_attribution_rejects_empty_path_cycles_and_whitespace_reason() -> None:
    region = distillation_regions(leaf_distillation_items(claims(2)))[0]
    base = {
        "version": 2,
        "covered_child_ids": list(region.child_ids),
        "child_dispositions": [{
            "child_id": child_id, "disposition": "promoted",
            "reason": "该窗口的语义通过结构化关系保留",
        } for child_id in region.child_ids],
        "child_attributions": [{
            "child_id": region.child_ids[0], "relation": "merged",
            "related_child_ids": [region.child_ids[1]],
        }, {
            "child_id": region.child_ids[1], "relation": "superseded",
            "related_child_ids": [region.child_ids[0]],
        }],
        "semantic": {
            "mechanisms": [{"name": "机制"}],
            "attraction_map": {}, "style_profile": {},
        },
    }
    with pytest.raises(ValueError, match="cannot contain a cycle"):
        validate_distillation_receipt(region, base)

    empty_path = {
        **base,
        "child_attributions": [{
            "child_id": child_id, "relation": "claim",
            "semantic_path": "/style_profile", "related_child_ids": [],
        } for child_id in region.child_ids],
    }
    with pytest.raises(ValueError, match="semantic path is empty"):
        validate_distillation_receipt(region, empty_path)

    whitespace_reason = {
        **base,
        "child_dispositions": [{
            "child_id": child_id, "disposition": "promoted", "reason": "          ",
        } for child_id in region.child_ids],
    }
    with pytest.raises(ValueError):
        validate_distillation_receipt(region, whitespace_reason)


def test_distillation_capacity_splits_large_small_count_without_truncation() -> None:
    large_claims = [{
        "data": {
            "window": index + 1,
            "window_start": index * 100,
            "window_end": index * 100 + 100,
            "result": {"marker": f"window-{index}", "body": "甲" * 3_000},
        },
    } for index in range(6)]
    regions = distillation_regions(
        leaf_distillation_items(large_claims),
        fanout=6, max_payload_characters=48_000, max_payload_tokens=6_500,
    )

    assert len(regions) == 3
    assert [child for region in regions for child in region.child_ids] == [
        f"window:{index}" for index in range(1, 7)
    ]
    serialized = "".join(
        json.dumps(region.payloads, ensure_ascii=False) for region in regions
    )
    assert all(f"window-{index}" in serialized for index in range(6))
    assert distillation_needs_reduction(
        leaf_distillation_items(large_claims), fanout=6,
        max_payload_characters=48_000, max_payload_tokens=6_500,
    )


def test_distillation_rejects_one_indivisible_item_over_token_capacity() -> None:
    oversized = leaf_distillation_items([{
        "data": {
            "window": 1, "window_start": 0, "window_end": 100,
            "result": {"body": "甲" * 2_000},
        },
    }])

    with pytest.raises(ValueError, match="one distillation item exceeds"):
        distillation_regions(
            oversized, max_payload_characters=48_000, max_payload_tokens=1_024,
        )


def test_source_use_modes_keep_competitors_risk_only() -> None:
    assert source_use_mode("competitor_work") == SourceUseMode.COMPETITOR_RISK_ONLY
    assert source_use_mode("popular_sample") == SourceUseMode.REFERENCE_STYLE
    assert source_use_mode("writing_tutorial") == SourceUseMode.REFERENCE_MECHANISM


def test_creative_recipe_unifies_mechanism_attraction_and_style_without_raw_evidence() -> None:
    recipe = compile_creative_recipe("book", [
        {
            "node_id": "mechanism-1",
            "node_type": "mechanism",
            "data": {
                "transfer_guidance": "Escalate the cost after each failed attempt.",
                "structural_position": "middle",
                "trigger_conditions": ["goal blocked"],
                "state_change": "options narrow",
                "provenance": {"source_id": "source-1", "node_id": "mechanism-1"},
                "evidence": "distinctive source quotation must not enter recipe",
            },
        },
        {
            "node_id": "attraction-1",
            "node_type": "attraction_map",
            "data": {
                "mechanism_type": "attraction_guidance",
                "opening_rule": "Open with pressure and a concrete anomaly.",
                "ending_rule": "Pay the surface and emotional costs separately.",
                "provenance": {"source_id": "source-2", "node_id": "attraction-1"},
            },
        },
        {
            "node_id": "style-1",
            "node_type": "style_rule",
            "data": {
                "field": "dialogue", "rule": "Let replies change leverage.",
                "when_to_use": "conflict scenes", "avoid": "exposition-only exchanges",
                "provenance": {"source_id": "source-3", "node_id": "style-1"},
            },
        },
    ])

    assert len(recipe.mechanisms) == 1
    assert len(recipe.attraction_guidance) == 1
    assert len(recipe.style_rules) == 1
    serialized = recipe.model_dump_json()
    assert "distinctive source quotation" not in serialized
    assert "source-1" not in serialized
    assert len(recipe.provenance_sha256) == 3


def test_creative_recipe_uses_node_type_instead_of_editable_markers() -> None:
    recipe = compile_creative_recipe("book", [
        {
            "node_id": "style-1", "node_type": "style_rule",
            "data": {
                "field": "dialogue", "rule": "Keep each reply consequential.",
                "mechanism_type": "causal_structure",
                "transfer_guidance": "FORGED_PLOT_METHOD",
            },
        },
        {
            "node_id": "mechanism-1", "node_type": "mechanism",
            "data": {
                "name": "Escalate costs", "mechanism_type": "attraction_guidance",
                "transfer_guidance": "Narrow the next choice.",
                "opening_rule": "FORGED_ATTRACTION_RULE",
            },
        },
    ])

    assert len(recipe.style_rules) == 1
    assert len(recipe.mechanisms) == 1
    assert recipe.attraction_guidance == []
    assert "FORGED_PLOT_METHOD" not in recipe.model_dump_json()
