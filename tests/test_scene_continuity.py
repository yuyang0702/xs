from pathlib import Path

import pytest

from novel_flywheel.scene_continuity import (
    LocationRef,
    assess_scene_transition,
    build_location_catalog,
)


def test_catalog_uses_formal_names_aliases_features_and_parent_locations(
    tmp_path: Path,
) -> None:
    locations = tmp_path / "worldbuilding" / "locations"
    locations.mkdir(parents=True)
    (locations / "shen-fu.md").write_text(
        """---
name: "沈府"
aliases:
  - 沈家宅院
---

## Notable Features

- **厨房**：后院西侧
- **库房**：存放物件
""",
        encoding="utf-8",
    )
    (locations / "old-tree.md").write_text(
        """---
name: "沈府后院老槐树下"
---
""",
        encoding="utf-8",
    )

    catalog = build_location_catalog(tmp_path, {})

    assert catalog["沈府"] == LocationRef("沈府", "沈府")
    assert catalog["沈家宅院"] == LocationRef("沈府", "沈府")
    assert catalog["库房"] == LocationRef("库房", "沈府")
    assert catalog["沈府后院老槐树下"] == LocationRef(
        "沈府后院老槐树下", "沈府",
    )


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            "---\r\nname： '轨道站'\r\naliases： [\"Orbital Station\", 轨道空间站]\r\n---\r\n"
            "\r\n## 地点特征\r\n\r\n- **A 舱**：主控舱\r\n",
            {"轨道站", "OrbitalStation", "轨道空间站", "A舱"},
        ),
        (
            "# 月面基地\n\n## 重要特征\n\n- **着陆区**：飞船起降区域\n",
            {"月面基地", "着陆区"},
        ),
    ],
)
def test_catalog_accepts_realistic_markdown_variants(
    tmp_path: Path, body: str, expected: set[str],
) -> None:
    locations = tmp_path / "worldbuilding" / "locations"
    locations.mkdir(parents=True)
    (locations / "variant.md").write_text(body, encoding="utf-8")

    catalog = build_location_catalog(tmp_path, {})

    assert expected <= set(catalog)


def test_catalog_ignores_fenced_templates_and_drops_ambiguous_aliases(
    tmp_path: Path,
) -> None:
    locations = tmp_path / "worldbuilding" / "locations"
    locations.mkdir(parents=True)
    (locations / "template.md").write_text(
        "```markdown\n# 幽灵地点\n## Notable Features\n- **假入口**：模板\n```\n"
        "<!--\n# 注释地点\n-->\n",
        encoding="utf-8",
    )
    for filename, name in (("alpha.md", "甲城"), ("beta.md", "乙城")):
        (locations / filename).write_text(
            f'---\nname: "{name}"\naliases:\n  - 同名站\n---\n',
            encoding="utf-8",
        )
    (locations / "malformed.md").write_text(
        '---\nname: "丙城"\naliases: ["未闭合]\n---\n',
        encoding="utf-8",
    )

    catalog = build_location_catalog(tmp_path, {})

    assert "幽灵地点" not in catalog
    assert "假入口" not in catalog
    assert "注释地点" not in catalog
    assert "同名站" not in catalog
    assert "未闭合" not in catalog
    assert {"甲城", "乙城", "丙城"} <= set(catalog)


def test_production_warehouse_handoff_inside_same_residence_does_not_block() -> None:
    catalog = {
        "沈府": LocationRef("沈府", "沈府"),
        "库房": LocationRef("库房", "沈府"),
    }

    findings = assess_scene_transition(
        "她在库房查清账册，随后与裴砚行站在回廊说话。",
        "库房案刚刚平息，花穗在沈府里逐渐站稳脚跟。",
        catalog,
    )

    assert not any(item["blocking"] for item in findings)


def test_distinct_known_scifi_locations_without_bridge_block() -> None:
    catalog = {
        "远航号": LocationRef("远航号", "远航号"),
        "月面基地": LocationRef("月面基地", "月面基地"),
    }

    findings = assess_scene_transition(
        "她留在远航号舰桥。",
        "月面基地的警报突然响起。",
        catalog,
    )

    assert [
        item["code"] for item in findings if item["blocking"]
    ] == ["scene_transition_missing"]


def test_location_matching_normalizes_whitespace_in_formal_names() -> None:
    catalog = {
        "OrbitalStation": LocationRef("Orbital Station", "Orbital Station"),
        "MoonBase": LocationRef("Moon Base", "Moon Base"),
    }

    findings = assess_scene_transition(
        "She remained aboard Orbital Station.",
        "Moon Base sounded the evacuation alarm.",
        catalog,
    )

    assert [
        item["code"] for item in findings if item["blocking"]
    ] == ["scene_transition_missing"]


def test_explicit_movement_between_modern_locations_passes() -> None:
    catalog = {
        "公司": LocationRef("公司", "公司"),
        "医院": LocationRef("医院", "医院"),
    }

    findings = assess_scene_transition(
        "她仍在公司整理证据。",
        "下班后，她乘车赶到医院，走进急诊大厅。",
        catalog,
    )

    assert not findings


def test_same_root_child_location_without_clear_movement_is_warning_only() -> None:
    catalog = {
        "教学楼": LocationRef("教学楼", "学校"),
        "地下车库": LocationRef("地下车库", "学校"),
    }

    findings = assess_scene_transition(
        "她站在教学楼门口。",
        "地下车库里只剩一盏灯。",
        catalog,
    )

    assert findings == [{
        "code": "scene_transition_uncertain",
        "message": "场景似乎在同一地点范围内变化，但没有识别到明确移动交代",
        "blocking": False,
        "previous_location": "教学楼",
        "current_location": "地下车库",
    }]


def test_unknown_locations_and_explicit_dream_transition_do_not_false_block() -> None:
    assert not assess_scene_transition(
        "她留在没有资料的旧站台。", "陌生海岸响起潮声。", {},
    )
    catalog = {
        "卧室": LocationRef("卧室", "现实"),
        "黑森林": LocationRef("黑森林", "梦境"),
    }
    assert not assess_scene_transition(
        "她在卧室闭上眼睛。", "梦中，她走进黑森林。", catalog,
    )
