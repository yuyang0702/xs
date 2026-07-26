import pytest

from novel_flywheel.db import Database
from novel_flywheel.reference_library import ReferenceLibrary


def library(tmp_path) -> ReferenceLibrary:
    db = Database(tmp_path / "app.db")
    db.migrate()
    return ReferenceLibrary(db, tmp_path / "references")


def test_import_text_is_versioned_and_global_duplicates_reuse_source(tmp_path) -> None:
    references = library(tmp_path)

    source = references.import_text(title="雪夜", text="第一段。\r\n\r\n第二段。", source_type="paste")
    same = references.import_text(title="重复标题", text="第一段。\n\n第二段。", source_type="paste")
    updated = references.add_version(source["id"], "修改后的正文。")

    assert source["latest_version"]["version"] == 1
    assert references.read_text(source["id"]) == "修改后的正文。"
    assert same["id"] == source["id"]
    assert updated["version"] == 2
    assert [item["version"] for item in references.get(source["id"])["versions"]] == [2, 1]


def test_import_stores_classification_and_metadata_can_be_updated(tmp_path) -> None:
    references = library(tmp_path)
    source = references.import_text(
        title="知乎高赞样本", text="热门回答正文。", source_type="paste",
        platform="知乎", content_type="popular_sample",
    )
    assert source["platform"] == "知乎"
    assert source["content_type"] == "popular_sample"
    updated = references.update_metadata(
        source["id"], platform="番茄", content_type="competitor_work", project_id=None,
    )
    assert updated["platform"] == "番茄"
    assert updated["content_type"] == "competitor_work"


@pytest.mark.parametrize("title,text,source_type", [
    ("", "正文", "paste"),
    ("x" * 121, "正文", "paste"),
    ("标题", "  \n", "paste"),
        ("标题", "正文", "html"),
])
def test_import_text_rejects_invalid_input(tmp_path, title, text, source_type) -> None:
    with pytest.raises(ValueError):
        library(tmp_path).import_text(title=title, text=text, source_type=source_type)


def test_source_ids_cannot_escape_storage_root(tmp_path) -> None:
    references = library(tmp_path)

    with pytest.raises(ValueError):
        references.read_text("../outside")


def test_delete_removes_source_files_without_touching_siblings(tmp_path) -> None:
    references = library(tmp_path)
    first = references.import_text(title="甲", text="甲的正文。", source_type="paste")
    second = references.import_text(title="乙", text="乙的正文。", source_type="paste")

    references.delete(first["id"])

    assert references.list() == [references.get(second["id"])]
    assert references.read_text(second["id"]) == "乙的正文。"
    with pytest.raises(LookupError):
        references.get(first["id"])


def test_local_analysis_is_cached_per_source_version(tmp_path) -> None:
    references = library(tmp_path)
    source = references.import_text(
        title="诊断", text="血是暗红色，静脉血。插得不深，没伤到大动脉。刀还不能拔。",
        source_type="paste",
    )

    first = references.analyze(source["id"])
    second = references.analyze(source["id"])
    new_version = references.add_version(source["id"], "她借着火光看清伤口，先按住了刀柄。")
    third = references.analyze(source["id"], new_version["id"])

    assert first["id"] == second["id"]
    assert first["cached"] is False
    assert second["cached"] is True
    assert "checklist_judgment" in {item["rule_id"] for item in first["result"]["findings"]}
    assert third["id"] != first["id"]
