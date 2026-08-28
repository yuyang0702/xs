from __future__ import annotations

import hashlib
import json
import random
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from novel_flywheel.selective_skill_compiler import (
    BudgetInputV1,
    SectionIndexError,
    SelectionInputV1,
    SelectiveSkillCompilerV1,
    SelectiveSkillShadowObserverV1,
    SkillContextOverflowError,
    SkillSectionIndexV1,
)
from novel_flywheel.models import ModelResult
from tools.diagnostics.materialize_skill_v3_shadow_evidence import scenario_records

from test_phase05_evidence_closure import _service


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "vendor/novel-skills/skill-section-index-v1.json"
SOURCE_ROOT = ROOT / "vendor/novel-skills/source"
PLANNING_SKILLS = (
    "story-init", "plot-structure", "character-management", "worldbuilding",
)
DEMANDS = (
    "character-heavy", "world-heavy", "conflict-pacing-heavy",
    "setup-payoff-heavy", "mixed",
)


def _refresh_index_definition(payload: dict) -> None:
    unsigned = dict(payload)
    unsigned.pop("index_definition_sha256", None)
    payload["index_definition_sha256"] = hashlib.sha256(json.dumps(
        unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _skill_hashes(index: SkillSectionIndexV1) -> tuple[tuple[str, str], ...]:
    return tuple((name, index.skill_source_sha256[name]) for name in PLANNING_SKILLS)


def _request(index: SkillSectionIndexV1, demand: str = "character-heavy") -> SelectionInputV1:
    return SelectionInputV1(
        resolved_skill_ids=PLANNING_SKILLS,
        resolved_skill_source_hashes=_skill_hashes(index),
        stage="planning",
        substage="event_realization",
        task_contract_id="planning_event_realization_shadow_v1@1",
        task_contract_schema_sha256="1" * 64,
        creative_demand_class=demand,
        authority_fact_hashes=(("parent_authority", "2" * 64),),
    )


def _compiler(index_path: Path = INDEX, root: Path = ROOT) -> SelectiveSkillCompilerV1:
    return SelectiveSkillCompilerV1(SkillSectionIndexV1.load(index_path, root))


def test_section_index_is_stable_complete_and_source_bound() -> None:
    index = SkillSectionIndexV1.load(INDEX, ROOT)
    assert len(index.skill_ids) == 11
    assert set(index.skill_ids) == {
        "story-init", "plot-structure", "character-management", "worldbuilding",
        "revision-continuity", "chapter-writing", "novel-writing", "dialogue",
        "humanizer-zh", "story-maintenance", "better-writing",
    }
    assert len(index.sections) == len({section.section_id for section in index.sections})
    assert all(section.source_text for section in index.sections)
    assert all(section.source_file_sha256 for section in index.sections)
    assert all(section.section_content_sha256 for section in index.sections)


def test_stale_source_sha_rejects_the_index(tmp_path: Path) -> None:
    copied = tmp_path / "repo"
    shutil.copytree(SOURCE_ROOT, copied / "vendor/novel-skills/source")
    shutil.copy2(INDEX, copied / "vendor/novel-skills/skill-section-index-v1.json")
    target = copied / "vendor/novel-skills/source/plot-structure/SKILL.md"
    target.write_text(target.read_text(encoding="utf-8") + "\n<!-- stale -->\n", encoding="utf-8")
    with pytest.raises(
        SectionIndexError, match="PRIMARY_SKILL_DOCUMENT_IDENTITY_MISMATCH",
    ):
        SkillSectionIndexV1.load(
            copied / "vendor/novel-skills/skill-section-index-v1.json", copied,
        )


def test_stale_section_content_identity_rejects_the_index(tmp_path: Path) -> None:
    payload = json.loads(INDEX.read_text(encoding="utf-8"))
    payload["sections"][0]["section_content_sha256"] = "0" * 64
    _refresh_index_definition(payload)
    stale = tmp_path / "stale-section-index.json"
    stale.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(
        SectionIndexError, match="SECTION_CONTENT_IDENTITY_MISMATCH",
    ):
        SkillSectionIndexV1.load(stale, ROOT)


def test_selector_is_repeatable_and_catalog_order_independent(tmp_path: Path) -> None:
    compiler = _compiler()
    first = compiler.select(_request(compiler.index, "mixed"))
    second = compiler.select(_request(compiler.index, "mixed"))
    assert [item.section_id for item in first] == [item.section_id for item in second]

    payload = json.loads(INDEX.read_text(encoding="utf-8"))
    random.Random(20260826).shuffle(payload["sections"])
    _refresh_index_definition(payload)
    shuffled = tmp_path / "index.json"
    shuffled.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    shuffled_compiler = _compiler(shuffled)
    third = shuffled_compiler.select(_request(shuffled_compiler.index, "mixed"))
    assert [item.section_id for item in first] == [item.section_id for item in third]


def test_missing_dependency_and_cycle_fail_closed(tmp_path: Path) -> None:
    payload = json.loads(INDEX.read_text(encoding="utf-8"))
    payload["sections"][0]["dependency_section_ids"] = ["sv3-missing"]
    _refresh_index_definition(payload)
    missing = tmp_path / "missing.json"
    missing.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SectionIndexError, match="missing dependency"):
        SkillSectionIndexV1.load(missing, ROOT)

    payload = json.loads(INDEX.read_text(encoding="utf-8"))
    core = [
        item for item in payload["sections"]
        if item["selection_class"] == "ALWAYS_ON_STAGE_CORE"
    ]
    core[0]["dependency_section_ids"] = [core[1]["section_id"]]
    core[1]["dependency_section_ids"] = [core[0]["section_id"]]
    _refresh_index_definition(payload)
    cycle = tmp_path / "cycle.json"
    cycle.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    compiler = _compiler(cycle)
    with pytest.raises(ValueError, match="dependency cycle"):
        compiler.select(_request(compiler.index))


def test_five_scenario_evidence_materialization_is_reproducible() -> None:
    first, _ = scenario_records()
    second, _ = scenario_records()
    assert first == second
    assert tuple(first) == DEMANDS
    assert all(record["capacity_status"] == "PASS" for record in first.values())


@pytest.mark.parametrize("demand", DEMANDS)
def test_five_demand_scenarios_close_dependencies_and_filter_ownership(demand: str) -> None:
    compiler = _compiler()
    selected = compiler.select(_request(compiler.index, demand))
    selected_ids = {item.section_id for item in selected}
    assert selected
    assert all(set(item.dependency_section_ids) <= selected_ids for item in selected)
    assert all(compiler._ownership_allowed(item) for item in selected)
    contaminated = compiler.index.known_planning_wrong_layer_ids & selected_ids
    assert contaminated <= compiler.index.planning_shared_subset_exception_ids
    assert all("/references/" in item.source_path for item in selected)


def test_verbatim_rendering_is_canonical_exact_and_ordered() -> None:
    compiler = _compiler()
    selected = compiler.select(_request(compiler.index, "character-heavy"))
    rendered = compiler.render(selected)
    assert rendered.creative_semantic_reauthoring_count == 0
    assert rendered.runtime_generated_creative_sentence_count == 0
    assert rendered.wrapper_creative_summary_count == 0
    assert [part.section_id for part in rendered.parts] == [item.section_id for item in selected]
    for part, section in zip(rendered.parts, selected, strict=True):
        assert part.body == section.source_text
        assert hashlib.sha256(part.body.encode("utf-8")).hexdigest() == section.section_content_sha256
        assert rendered.text[part.body_start:part.body_end] == section.source_text


def test_budget_drops_optional_only_and_never_truncates_mandatory() -> None:
    compiler = _compiler()
    request = replace(_request(compiler.index, "mixed"), include_optional_support=True)
    roomy = BudgetInputV1(32768, 4624, 800, 224)
    materialized = compiler.materialize(request, roomy, task_case="mixed")
    assert materialized.receipt.capacity_status == "PASS"
    assert all(part.body in materialized.rendered.text for part in materialized.rendered.parts)

    impossible = BudgetInputV1(2400, 1400, 800, 224)
    with pytest.raises(SkillContextOverflowError) as caught:
        compiler.materialize(request, impossible, task_case="mixed")
    assert caught.value.status in {"STAGE_SPLIT_REQUIRED", "FAIL_CLOSED"}
    assert caught.value.auto_summarize_to_fit is False
    assert caught.value.silent_truncation is False


def test_provenance_reconstructs_and_cache_key_invalidates_semantic_inputs() -> None:
    compiler = _compiler()
    budget = BudgetInputV1(32768, 4624, 800, 224)
    base = compiler.materialize(_request(compiler.index), budget, task_case="character")
    again = compiler.materialize(_request(compiler.index), budget, task_case="character")
    assert base.receipt.cache_key_sha256 == again.receipt.cache_key_sha256
    assert compiler.reconstruct(base.receipt) == base.rendered.text

    changed_demand = compiler.materialize(
        _request(compiler.index, "mixed"), budget, task_case="character",
    )
    changed_contract = compiler.materialize(
        replace(_request(compiler.index), task_contract_schema_sha256="3" * 64),
        budget, task_case="character",
    )
    changed_authority = compiler.materialize(
        replace(_request(compiler.index), authority_fact_hashes=(("parent", "4" * 64),)),
        budget, task_case="character",
    )
    assert len({
        base.receipt.cache_key_sha256,
        changed_demand.receipt.cache_key_sha256,
        changed_contract.receipt.cache_key_sha256,
        changed_authority.receipt.cache_key_sha256,
    }) == 4


def test_unknown_demand_and_wrong_stage_fail_closed() -> None:
    compiler = _compiler()
    with pytest.raises(ValueError, match="creative demand"):
        compiler.select(replace(_request(compiler.index), creative_demand_class="unknown"))
    with pytest.raises(ValueError, match="Planning/Event Realization"):
        compiler.select(replace(_request(compiler.index), stage="draft"))


@pytest.mark.asyncio
async def test_workflow_shadow_observer_is_hash_only_fail_open_and_prompt_exact(
    tmp_path: Path,
) -> None:
    class Gateway:
        def __init__(self) -> None:
            self.calls: list[tuple[object, ...]] = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls.append((role, system, user, max_output_tokens))
            return ModelResult("{}", {"role": role, "model_name": "offline"})

    gateway = Gateway()
    _db, store, project, service = _service(
        tmp_path, mode="short", gateway=gateway, title="Skill V3 shadow isolation",
    )
    project.metadata["creative_demand_class"] = "character-heavy"
    constraints = store.load_constraints(project.id)
    run_a, path_a = service._begin_run(project, "short-story", "skill-v3-off")
    await service._stage(
        run_a, path_a, project, "planning", constraints, "same task",
        allow_tools=False,
    )

    observer = SelectiveSkillShadowObserverV1(_compiler())
    service.skill_context_shadow_observer = observer
    run_b, path_b = service._begin_run(project, "short-story", "skill-v3-on")
    await service._stage(
        run_b, path_b, project, "planning", constraints, "same task",
        allow_tools=False,
    )
    assert gateway.calls[0] == gateway.calls[1]
    assert len(observer.observations) == 1
    projection = observer.observations[0]
    assert projection["model_input_used"] is False
    assert projection["validator_used"] is False
    assert projection["authority_used"] is False
    assert "rendered_context" not in projection

    service.skill_context_shadow_observer = lambda _payload: (_ for _ in ()).throw(
        RuntimeError("observer failed")
    )
    run_c, path_c = service._begin_run(project, "short-story", "skill-v3-fail")
    await service._stage(
        run_c, path_c, project, "planning", constraints, "same task",
        allow_tools=False,
    )
    assert gateway.calls[1] == gateway.calls[2]
