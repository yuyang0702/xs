from __future__ import annotations

import json

from novel_flywheel.narrative_contract import (
    confirm_narrative_contract,
    ensure_narrative_contract,
    first_person_prose_issues,
    render_narrative_contract,
    resolve_narrative_contract,
)
from novel_flywheel.projects import Project


def _project(tmp_path, *, pov: str = "first", characters: list[tuple[str, str, str]]):
    project_path = tmp_path / "story"
    (project_path / "characters").mkdir(parents=True)
    (project_path / "plot").mkdir()
    for character_id, name, role in characters:
        (project_path / "characters" / f"{character_id}.md").write_text(
            "---\n"
            f'name: "{name}"\n'
            f"role: {role}\n"
            "---\n\n# Character\n",
            encoding="utf-8",
        )
    (project_path / "plot" / "outline.md").write_text(
        "# 大纲\n\n- 视角：第一人称（女主视角）\n",
        encoding="utf-8",
    )
    metadata = {
        "id": "story-id",
        "title": "测试作品",
        "mode": "short",
        "pov": pov,
        "premise": "第一人称（女主视角）",
    }
    (project_path / "project.json").write_text(
        json.dumps(metadata, ensure_ascii=False), encoding="utf-8",
    )
    return Project("story-id", "测试作品", "short", project_path, metadata)


def test_unique_protagonist_becomes_the_first_person_narrator(tmp_path) -> None:
    project = _project(
        tmp_path,
        characters=[
            ("hua-sui", "花穗", "protagonist"),
            ("pei-yan-xing", "裴砚行", "deuteragonist"),
        ],
    )

    contract = resolve_narrative_contract(project)

    assert contract.status == "ready"
    assert contract.mode == "first_person_limited"
    assert contract.narrator_character_id == "hua-sui"
    assert contract.narrator_name == "花穗"
    assert contract.self_reference == "我"
    rendered = render_narrative_contract(contract)
    assert "花穗自身必须用“我”叙述" in rendered
    assert "不得把花穗写成“花穗/她”" in rendered


def test_multiple_protagonists_require_confirmation_instead_of_guessing(tmp_path) -> None:
    project = _project(
        tmp_path,
        characters=[
            ("lin-yu", "林雨", "protagonist"),
            ("zhou-ye", "周野", "protagonist"),
        ],
    )

    contract = resolve_narrative_contract(project)

    assert contract.status == "needs_confirmation"
    assert contract.narrator_character_id == ""
    assert [item["name"] for item in contract.candidates] == ["林雨", "周野"]

    confirmed = confirm_narrative_contract(project, "zhou-ye")
    assert confirmed.status == "ready"
    assert confirmed.narrator_name == "周野"
    persisted = json.loads(
        (project.path / "memory" / "narrative-contract.json").read_text(
            encoding="utf-8",
        )
    )
    assert persisted["contract"]["narrator_character_id"] == "zhou-ye"
    assert ensure_narrative_contract(project).narrator_name == "周野"


def test_third_person_project_does_not_activate_first_person_rules(tmp_path) -> None:
    project = _project(
        tmp_path,
        pov="third-limited",
        characters=[("hua-sui", "花穗", "protagonist")],
    )
    project.metadata["premise"] = "受限第三人称"

    contract = resolve_narrative_contract(project)

    assert contract.status == "ready"
    assert contract.mode == "third_person_limited"
    assert "花穗自身必须用“我”叙述" not in render_narrative_contract(contract)


def test_high_confidence_third_person_drift_is_detected_without_banning_other_women(
    tmp_path,
) -> None:
    project = _project(
        tmp_path,
        characters=[("hua-sui", "花穗", "protagonist")],
    )
    contract = resolve_narrative_contract(project)

    drifted = (
        "花穗蹲在井边嗑瓜子。花穗抬头看见沈大小姐走来。"
        "花穗心里盘算着二十两银子，随后又低头继续刨土。"
    )
    valid = (
        "我蹲在井边嗑瓜子。沈大小姐走过来，她身后的丫鬟低着头。"
        "我心里盘算着二十两银子，手上却没停。"
    )

    assert {item["code"] for item in first_person_prose_issues(contract, drifted)} == {
        "first_person_self_reference_missing",
        "narrator_third_person_drift",
    }
    assert first_person_prose_issues(contract, valid) == []
    dialogue_only_name = (
        "她拍了拍桌子：‘花穗，你倒是说句话。’另一个人也喊：‘花穗，快走！’"
        "门外风急，灯影晃了两下。"
    )
    assert first_person_prose_issues(contract, dialogue_only_name) == []
