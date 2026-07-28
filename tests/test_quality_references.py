from novel_flywheel.db import Database
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.quality_references import QualityReferenceService
from novel_flywheel.reference_library import ReferenceLibrary


def quality_reference_service(tmp_path):
    db = Database(tmp_path / "app.db")
    db.migrate()
    projects = ProjectStore(db, tmp_path / "workspace")
    project = projects.create(ProjectCreate(
        title="Calibration", mode="short", genre="suspense",
        premise="A friend returns.", target_words=8000,
    ))
    project = projects.apply_platform_profile(project.id, "zhihu-salt-short")
    references = ReferenceLibrary(db, tmp_path / "references")
    popular = references.import_text(
        title="榜单佳作", text="高质量样本文本", source_type="paste",
        platform="zhihu", content_type="popular_sample",
    )
    ordinary = references.import_text(
        title="普通样本", text="普通样本文本", source_type="paste",
        platform="zhihu", content_type="reference_work",
    )
    return db, project, references, QualityReferenceService(
        db, references, projects,
    ), popular, ordinary


def test_recommendations_are_balanced_but_inactive_until_user_confirms(tmp_path) -> None:
    _db, project, _references, service, popular, ordinary = quality_reference_service(
        tmp_path,
    )

    result = service.recommend(project.id, "zhihu-short-v2")

    assert result["model_called"] is False
    assert result["active_group"]["items"] == []
    assert {item["source_id"] for item in result["recommendations"]} == {
        popular["id"], ordinary["id"],
    }
    assert {item["role"] for item in result["recommendations"]} == {
        "high_quality_anchor", "ordinary_anchor",
    }
    assert all(item["status"] == "recommended" for item in result["recommendations"])
    assert "人工评分校准" in result["message"]
    assert {item["label"] for item in result["missing_roles"]} == {
        "已知问题参考", "本项目历史基线", "修改前后对照",
    }


def test_confirmation_rejection_removal_and_history_preserve_source_files(tmp_path) -> None:
    _db, project, references, service, popular, ordinary = quality_reference_service(
        tmp_path,
    )
    recommendations = service.recommend(project.id, "zhihu-short-v2")[
        "recommendations"
    ]
    accepted = next(item for item in recommendations if item["source_id"] == popular["id"])
    rejected = next(item for item in recommendations if item["source_id"] == ordinary["id"])

    confirmed = service.confirm(
        project.id, "zhihu-short-v2",
        accepted_ids=[accepted["id"]], rejected_ids=[rejected["id"]],
    )

    assert confirmed["version"] == 1
    assert [item["id"] for item in confirmed["items"]] == [accepted["id"]]
    assert confirmed["decisions"][rejected["id"]] == "rejected"
    assert service.list_group(project.id, "zhihu-short-v2")["items"][0][
        "title"
    ] == "榜单佳作"

    removed = service.remove(project.id, "zhihu-short-v2", accepted["id"])

    assert removed["version"] == 2
    assert removed["items"] == []
    history = service.history(project.id, "zhihu-short-v2")
    assert [item["action"] for item in history] == ["removed", "confirmed"]
    assert references.get(popular["id"])["title"] == "榜单佳作"
    assert references.get(ordinary["id"])["title"] == "普通样本"
