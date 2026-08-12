from pathlib import Path

import pytest

from novel_flywheel.db import Database
from novel_flywheel.originality import OriginalityEngine
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


def test_platform_rules_preserve_complete_rule_text(tmp_path) -> None:
    references = library(tmp_path)
    tail = "PLATFORM-RULE-AFTER-TWENTY-THOUSAND"
    source = references.import_text(
        title="Complete platform policy",
        text=("rule " * 4_100) + tail,
        source_type="paste", platform="example",
        content_type="platform_rule",
    )

    rules = references.platform_rules("example")

    assert [item["id"] for item in rules] == [source["id"]]
    assert rules[0]["text"].endswith(tail)


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


def test_originality_comparison_includes_every_distinct_reference_version(tmp_path) -> None:
    references = library(tmp_path)
    source = references.import_text(
        title="Versioned reference", text="first distinct reference version",
        source_type="paste", content_type="reference_work",
    )
    references.add_version(source["id"], "second distinct reference version")

    comparisons = list(references.comparison_sources())

    assert len(comparisons) == 2
    assert {item.text for item in comparisons} == {
        "first distinct reference version", "second distinct reference version",
    }
    assert all(item.id.startswith(f"reference:{source['id']}:") for item in comparisons)


def test_originality_stream_covers_tail_after_old_prefix_cap_with_absolute_provenance(
    tmp_path,
) -> None:
    references = library(tmp_path)
    marker = "尾部独有证据在旧上限以后仍然必须参与完整原创性核验"
    full_text = "前" * 110_000 + marker + "后" * 12_000
    source = references.import_text(
        title="Long version", text=full_text, source_type="paste",
        content_type="reference_work",
    )

    stream = references.comparison_sources(
        chunk_characters=4_096, overlap_characters=512,
    )
    assert not isinstance(stream, list)
    chunks = list(stream)
    assert len(chunks) == chunks[0].chunk_count
    assert max(len(item.text) for item in chunks) <= 4_096

    cursor = 0
    reconstructed = []
    for chunk in chunks:
        assert chunk.source_start <= cursor
        reconstructed.append(chunk.text[max(0, cursor - chunk.source_start):])
        cursor = max(cursor, chunk.source_end)
    assert "".join(reconstructed) == full_text

    report = OriginalityEngine().scan(f"开场。{marker}。收束。", stream)
    tail_findings = [
        item for item in report.findings
        if item.finding_type == "literal_winnowing" and item.source_start > 100_000
    ]
    assert tail_findings
    expected_version = source["latest_version"]
    assert {
        item.metadata["source_version_id"] for item in tail_findings
    } == {expected_version["id"]}
    assert {
        item.metadata["source_version_sha256"] for item in tail_findings
    } == {expected_version["content_hash"]}


def test_originality_stream_rejects_file_that_no_longer_matches_version_hash(
    tmp_path,
) -> None:
    references = library(tmp_path)
    source = references.import_text(
        title="Bound version", text="受版本哈希约束的完整参考正文。" * 100,
        source_type="paste", content_type="reference_work",
    )
    version_path = source["latest_version"]["storage_path"]
    Path(version_path).write_text(
        "已被外部替换的参考正文。" * 100, encoding="utf-8",
    )

    with pytest.raises(ValueError, match="provenance hash"):
        list(references.comparison_sources())


def test_reference_corpus_authority_is_text_free_and_tracks_every_visible_change(
    tmp_path, monkeypatch,
) -> None:
    references = library(tmp_path)
    references.db.save_project("book", "Book", "short", tmp_path / "book")
    empty = references.reference_corpus_authority("book")
    source = references.import_text(
        title="Scoped source", text="第一版完整参考正文。",
        source_type="paste", content_type="reference_work", project_id="book",
    )

    def forbid_full_text(*_args, **_kwargs):
        raise AssertionError("corpus authority must not read reference prose")

    monkeypatch.setattr(references, "read_text", forbid_full_text)
    first = references.reference_corpus_authority("book")
    assert first["sha256"] != empty["sha256"]
    assert references.reference_corpus_authority("other")["manifest"]["sources"] == []
    manifest_source = first["manifest"]["sources"][0]
    assert manifest_source["project_scope"] == "book"
    assert manifest_source["use_mode"] == "reference_mechanism"
    assert list(manifest_source["versions"][0]) == [
        "version_id", "version", "content_sha256",
    ]
    frozen_version_ids = {
        version["version_id"] for version in manifest_source["versions"]
    }

    references.add_version(source["id"], "第二版完整参考正文。")
    version_changed = references.reference_corpus_authority("book")
    assert version_changed["sha256"] != first["sha256"]
    assert {
        chunk.version_id
        for chunk in references.comparison_sources("book", authority=first)
    } == frozen_version_ids
    assert {
        chunk.version_id
        for chunk in references.comparison_sources(
            "book", authority=version_changed,
        )
    } == {
        version["version_id"]
        for version in version_changed["manifest"]["sources"][0]["versions"]
    }

    references.update_metadata(
        source["id"], platform="番茄", content_type="competitor_work",
        project_id="book",
    )
    classification_changed = references.reference_corpus_authority("book")
    assert classification_changed["sha256"] != version_changed["sha256"]
    assert classification_changed["manifest"]["sources"][0]["use_mode"] \
        == "competitor_risk_only"

    references.delete(source["id"])
    assert references.reference_corpus_authority("book")["sha256"] == empty["sha256"]
