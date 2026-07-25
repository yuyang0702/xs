from novel_flywheel.db import Database
from novel_flywheel.learning import LearningSystem
from novel_flywheel.projects import ProjectCreate, ProjectStore
from novel_flywheel.reference_library import ReferenceLibrary
from types import SimpleNamespace


def setup_system(tmp_path):
    db = Database(tmp_path / "app.db")
    db.migrate()
    library = ReferenceLibrary(db, tmp_path / "references")
    projects = ProjectStore(db, tmp_path / "projects")
    return db, library, projects, LearningSystem(db, library, projects)


def test_analysis_creates_evidenced_mechanisms_and_reuses_windows(tmp_path) -> None:
    _db, library, _projects, system = setup_system(tmp_path)
    source = library.import_text(
        title="样本", source_type="paste",
        text="她以为门外无人，推门后却看见失踪多年的兄长。\n\n先前那封无名信，此刻终于有了答案。",
    )
    first = system.analyze_reference(source["id"])
    second = system.analyze_reference(source["id"])
    assert first["mechanisms"]
    assert first["mechanisms"][0]["evidence"]
    assert second["cached_windows"] == second["window_count"]


def test_adoption_requires_confirmation_and_never_overwrites_outline(tmp_path) -> None:
    _db, library, projects, system = setup_system(tmp_path)
    project = projects.create(ProjectCreate(
        title="测试书", mode="short", genre="悬疑", premise="秘密推动关系变化",
        target_words=20_000,
    ))
    source = library.import_text(title="样本", source_type="paste", text="谜底揭晓后，旧盟友突然成为阻碍。")
    mechanism = system.analyze_reference(source["id"])["mechanisms"][0]
    outline = project.path / "outline.md"
    outline.write_text("# 原大纲\n", encoding="utf-8")
    recommendation = system.recommend(project.id, mechanism["id"])
    assert recommendation["status"] == "proposed"
    assert not system.list_adoptions(project.id)
    adopted = system.adopt(project.id, mechanism["id"], {"position": "中段"})
    assert adopted["status"] == "adopted"
    assert outline.read_text(encoding="utf-8") == "# 原大纲\n"
    assert system.get_artifact(project.id, "creative_blueprint")["data"]["mechanisms"]


def test_line_edit_is_candidate_only_and_preserves_locked_facts(tmp_path) -> None:
    _db, _library, projects, system = setup_system(tmp_path)
    project = projects.create(ProjectCreate(
        title="精修书", mode="short", genre="都市", premise="测试", target_words=10_000,
    ))
    result = system.create_line_edit_candidate(
        project.id, "林知晚必须留下。她很确定。", "林知晚必须留下。她从门锁上的新痕判断，对方刚离开。",
        issues=["overprecise_cognition"], locked_facts=["林知晚必须留下"],
    )
    assert result["status"] == "pending"
    assert not (project.path / "manuscript" / "story.md").exists()
    assert "林知晚必须留下" in result["candidate"]


def test_material_change_marks_derived_artifacts_stale(tmp_path) -> None:
    _db, _library, projects, system = setup_system(tmp_path)
    project = projects.create(ProjectCreate(
        title="影响书", mode="short", genre="古风", premise="测试", target_words=10_000,
    ))
    system.save_artifact(project.id, "voice_profiles", {"人物甲": {"habit": "记笔记"}})
    impact = system.mark_material_change(project.id, "characters/a.md", ["人物甲不再记笔记"])
    assert impact["affected"]
    assert system.get_artifact(project.id, "voice_profiles")["status"] == "stale"
    assert "Character Voice Profiles" not in projects.load_constraints(project.id)


def test_deleting_source_keeps_adoption_as_reviewable_tombstone(tmp_path) -> None:
    db, library, projects, system = setup_system(tmp_path)
    project = projects.create(ProjectCreate(
        title="墓碑", mode="short", genre="悬疑", premise="测试", target_words=10_000,
    ))
    source = library.import_text(title="样本", source_type="paste", text="他推门后却发现真相。")
    node = system.analyze_reference(source["id"])["mechanisms"][0]
    system.adopt(project.id, node["id"])
    library.delete(source["id"])
    with db.connect() as connection:
        status = connection.execute("SELECT status FROM project_adoptions WHERE project_id=?", (project.id,)).fetchone()[0]
    assert status == "review_source_deleted"


def test_active_learning_artifacts_join_existing_constraint_path(tmp_path) -> None:
    _db, _library, projects, system = setup_system(tmp_path)
    project = projects.create(ProjectCreate(
        title="上下文", mode="short", genre="都市", premise="测试", target_words=10_000,
    ))
    system.build_prose_baseline(project.id, {"dialogue": "每次回应都改变关系或信息"})
    constraints = projects.load_constraints(project.id)
    assert "Executable Prose Baseline" in constraints
    assert "每次回应都改变关系或信息" in constraints


class FakeGateway:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.roles = []

    async def complete(self, role, system, user, **kwargs):
        self.roles.append(role)
        return SimpleNamespace(text=next(self.outputs), receipt={"model_id": "fake"})


async def test_model_analysis_uses_explicit_roles_and_keeps_claims_proposed(tmp_path) -> None:
    db, library, projects, _system = setup_system(tmp_path)
    gateway = FakeGateway([
        '{"events":[{"start":0,"end":3,"fact":"发现线索","interpretation":"信息变化","confidence":0.8}]}',
        '{"mechanisms":[{"name":"延迟揭示","supporting_windows":[1],"trigger_conditions":["线索"],'
        '"structural_position":"中段","state_change":"获得信息","emotional_effect":"意外",'
        '"required_preparation":["伏笔"],"downstream_consequence":"改变选择",'
        '"transfer_guidance":"替换内容包装","incompatible_conditions":[],"confidence":0.8}]}',
    ])
    system = LearningSystem(db, library, projects, gateway)
    source = library.import_text(title="模型样本", source_type="paste", text="他忽然发现了线索。")
    result = await system.model_analyze_reference(source["id"])
    assert gateway.roles == ["reference_analysis", "reference_synthesis"]
    assert result["mechanisms"][0]["status"] == "proposed"


async def test_model_line_edit_routes_to_line_edit_and_remains_candidate(tmp_path) -> None:
    db, library, projects, _system = setup_system(tmp_path)
    gateway = FakeGateway(["事实甲。她从门缝的光判断，屋里还有人。"])
    system = LearningSystem(db, library, projects, gateway)
    project = projects.create(ProjectCreate(
        title="模型精修", mode="short", genre="都市", premise="测试", target_words=10_000,
    ))
    result = await system.model_line_edit(
        project.id, "事实甲。她很确定屋里有人。", issues=["unsupported_certainty"], locked_facts=["事实甲"],
    )
    assert gateway.roles == ["line_edit"]
    assert result["status"] == "pending"
