from __future__ import annotations

from pathlib import Path

from novel_flywheel.material_audit_authority import (
    build_material_audit_packets,
    build_material_reference_authority,
    material_audit_checkpoint_payload,
    material_audit_packet_prompt,
    merge_material_audit_receipts,
    normalize_material_audit_receipt,
    validate_material_audit_checkpoint,
)
from novel_flywheel.quality import review_windows


def _project_materials(root: Path) -> None:
    (root / "characters").mkdir(parents=True)
    (root / "worldbuilding").mkdir()
    (root / "plot").mkdir()
    (root / "constraints.md").write_text("不得改变已确认结局。", encoding="utf-8")


def test_reference_authority_covers_every_character_beyond_legacy_prefix(
    tmp_path,
) -> None:
    _project_materials(tmp_path)
    content = ("人物事实甲。\n\n" * 7_000) + "尾部唯一事实：角色从不饮酒。"
    path = tmp_path / "characters" / "hero.md"
    path.write_text(content, encoding="utf-8")

    bundle = build_material_reference_authority(
        tmp_path, target_characters=4_000,
    )
    chunks = [
        item for item in bundle.authority.chunks if item.path == "characters/hero.md"
    ]

    assert "".join(bundle.text_for(item) for item in chunks) == content
    assert sum(item.end - item.start for item in chunks) == len(content)
    assert "尾部唯一事实" in bundle.text_for(chunks[-1])


def test_packet_topology_is_complete_cross_product_and_hash_bound(tmp_path) -> None:
    _project_materials(tmp_path)
    (tmp_path / "characters" / "hero.md").write_text(
        "角色设定甲。\n\n角色设定乙。" * 600, encoding="utf-8",
    )
    manuscript = "正文事实甲。\n\n正文事实乙。" * 800
    bundle = build_material_reference_authority(
        tmp_path, target_characters=1_200,
    )
    windows = review_windows(manuscript, target=1_000, overlap=100)
    packets = build_material_audit_packets(bundle, manuscript, windows)

    assert len(packets) == len(windows) * len(bundle.authority.chunks)
    assert [item.sequence for item in packets] == list(range(1, len(packets) + 1))
    first = packets[0]
    prompt = material_audit_packet_prompt(
        first,
        manuscript_text=manuscript[first.manuscript_start:first.manuscript_end],
        reference_text=bundle.text_for(first.reference_chunk),
    )
    assert first.packet_id in prompt
    assert first.reference_chunk.path in prompt


def test_receipt_preserves_existing_descriptive_evidence_and_binds_checkpoint(
    tmp_path,
) -> None:
    _project_materials(tmp_path)
    manuscript = "沈砚端起酒杯，一饮而尽。"
    bundle = build_material_reference_authority(
        tmp_path, target_characters=1_000,
    )
    packet = build_material_audit_packets(
        bundle, manuscript, review_windows(manuscript),
    )[0]
    valid = {"issues": [{
        "category": "character_habit", "severity": "high",
        "evidence": "一饮而尽", "location": "开篇",
        "old_setting": "饮酒", "new_setting": "从不饮酒",
        "action": "修订动作",
    }]}

    normalized = normalize_material_audit_receipt(
        valid, manuscript_text=manuscript,
    )
    assert normalized == valid
    descriptive = {
        "issues": [{**valid["issues"][0], "evidence": "一段描述性转述"}],
    }
    assert normalize_material_audit_receipt(
        descriptive,
        manuscript_text=manuscript,
    ) == descriptive

    checkpoint = material_audit_checkpoint_payload(packet, valid)
    assert validate_material_audit_checkpoint(
        checkpoint, packet, manuscript_text=manuscript,
    ) == valid
    checkpoint["packet_id"] = "0" * 64
    assert validate_material_audit_checkpoint(
        checkpoint, packet, manuscript_text=manuscript,
    ) is None


def test_reducer_only_deduplicates_byte_equivalent_business_issues() -> None:
    issue = {
        "category": "timeline", "severity": "critical",
        "evidence": "天亮前返回", "location": "结尾",
        "old_setting": "尚未返回", "new_setting": "已经返回",
        "action": "核对时间线",
    }
    distinct = {**issue, "location": "中段"}

    assert merge_material_audit_receipts([
        {"issues": [issue]}, {"issues": [issue, distinct]},
    ]) == [issue, distinct]


def test_empty_reference_still_builds_one_bounded_runtime_packet(tmp_path) -> None:
    manuscript = "只有正文，没有项目资料。"
    bundle = build_material_reference_authority(
        tmp_path, target_characters=1_000,
    )
    packet = build_material_audit_packets(
        bundle, manuscript, review_windows(manuscript),
    )[0]

    assert packet.reference_chunk.path == ".runtime/empty-reference"
    assert bundle.text_for(packet.reference_chunk) == ""
