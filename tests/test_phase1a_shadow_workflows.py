from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

_TESTS = str(Path(__file__).parent)
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

from novel_flywheel.canonical_shadow import (
    evaluate_maintenance_shadow,
    observe_maintenance_shadow,
)
from novel_flywheel.models import ModelResult
from novel_flywheel.reliability_trace import (
    BestEffortTraceSink,
    canonical_shadow_comparison_matrix,
    read_trace,
    trace_file_for_project,
)
from novel_flywheel.story_state import StoryStateStore

from test_phase05_evidence_closure import (  # noqa: E402
    _run_long_chapters,
    _run_long_setup,
    _run_short,
    _service,
)


class _DeterministicUUIDs:
    def __init__(self) -> None:
        self.index = 0

    def uuid4(self):
        self.index += 1
        return SimpleNamespace(hex=f"{self.index:032x}")


def _reset_stable_ids(monkeypatch) -> None:
    monkeypatch.setattr("novel_flywheel.projects.uuid", _DeterministicUUIDs())
    monkeypatch.setattr("novel_flywheel.story_state.uuid", _DeterministicUUIDs())
    monkeypatch.setattr("novel_flywheel.long_workflow.uuid", _DeterministicUUIDs())


def _formal_manifest(project) -> dict[str, str]:
    selected: list[Path] = []
    for relative in ("manuscript/story.md", "memory/canon.json", "memory/book-plan.md"):
        path = project.path / relative
        if path.is_file():
            selected.append(path)
    selected.extend(sorted((project.path / "chapters").glob("chapter-*.md")))
    return {
        path.relative_to(project.path).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in selected
    }


def _state_manifest(service, project) -> dict:
    state = StoryStateStore(service.db).get(project.id)
    assert state is not None
    return {
        "revision": state.revision,
        "sha256": hashlib.sha256(json.dumps(
            state.data, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest(),
    }


def _journal_manifest(project) -> list[dict]:
    rows = []
    for path in sorted(project.path.glob(
        "runs/*/outputs/project-mutation-journal.json"
    )):
        payload = json.loads(path.read_text(encoding="utf-8"))
        serialized = json.dumps(payload, ensure_ascii=False).casefold()
        assert "shadowcanonical" not in serialized
        assert "canonicalmutationv1" not in serialized
        story_state = payload.get("story_state") or {}
        rows.append({
            "status": payload.get("status"),
            "operation": payload.get("operation"),
            "source_authority_sha256": payload.get("source_authority_sha256"),
            "expected_story_state_revision": payload.get(
                "expected_story_state_revision"
            ),
            "managed_paths": payload.get("managed_paths"),
            "artifacts": payload.get("artifacts"),
            "story_state_hash": story_state.get("state_sha256"),
            "memory_effects": payload.get("memory_effects"),
        })
    return rows


def _direct_fixture(root: Path) -> tuple[dict, bytes, dict]:
    characters = root / "characters"
    characters.mkdir(parents=True)
    (characters / "hero.md").write_text(
        "---\nname: hero\n---\n", encoding="utf-8",
    )
    (characters / "ally.md").write_text(
        "---\nname: ally\n---\n", encoding="utf-8",
    )
    source = (
        "hero arrives in Beijing. hero learns the sealed letter. "
        "hero now trusts ally."
    ).encode("utf-8")
    state = {"character_states": {"hero": {
        "location": "Shanghai",
        "knowledge": {"sealed-letter": False},
        "relationships": {"ally": "distrust"},
    }}}
    candidate = {
        "facts": [],
        "state": {"hero": {
            "location": "Beijing",
            "knowledge": {"sealed-letter": True},
            "relationships": {"ally": "trust"},
        }},
        "state_transitions": [
            {"character": "hero", "field": "location", "from": "Shanghai",
             "to": "Beijing", "evidence": "arrives in Beijing"},
            {"character": "hero", "field": "knowledge.sealed-letter", "from": False,
             "to": True, "evidence": "learns the sealed letter"},
            {"character": "hero", "field": "relationships.ally", "from": "distrust",
             "to": "trust", "evidence": "now trusts ally"},
        ],
    }
    return candidate, source, state


@pytest.mark.asyncio
async def test_phase1a_production_shaped_shadow_parity_and_coverage(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("NOVEL_RELIABILITY_TRACE", "1")
    monkeypatch.setenv("NOVEL_CANONICAL_SHADOW_V1", "0")
    _reset_stable_ids(monkeypatch)
    short_disabled = await _run_short(
        tmp_path / "short-disabled", trace_enabled=True,
    )

    monkeypatch.setenv("NOVEL_CANONICAL_SHADOW_V1", "1")
    _reset_stable_ids(monkeypatch)
    short_enabled = await _run_short(
        tmp_path / "short-enabled", trace_enabled=True,
    )

    with monkeypatch.context() as failure:
        failure.setenv("NOVEL_CANONICAL_SHADOW_V1", "1")
        failure.setattr(
            BestEffortTraceSink, "emit", lambda _self, _event: False,
        )
        _reset_stable_ids(failure)
        short_sink_failure = await _run_short(
            tmp_path / "short-sink-failure", trace_enabled=True,
        )

    for candidate in (short_enabled, short_sink_failure):
        assert candidate["formal_sha256"] == short_disabled["formal_sha256"]
        assert candidate["story_state_revision"] == short_disabled[
            "story_state_revision"
        ]
        assert candidate["story_state_sha256"] == short_disabled[
            "story_state_sha256"
        ]
        assert _formal_manifest(candidate["project"]) == _formal_manifest(
            short_disabled["project"]
        )
        assert _journal_manifest(candidate["project"]) == _journal_manifest(
            short_disabled["project"]
        )
        assert [
            (item["role"], item["max_output_tokens"])
            for item in candidate["gateway"].calls
        ] == [
            (item["role"], item["max_output_tokens"])
            for item in short_disabled["gateway"].calls
        ]

    short_trace = read_trace(trace_file_for_project(short_enabled["project"].path))
    short_shadow = canonical_shadow_comparison_matrix(short_trace.events)
    assert any(
        row["claim_kind"] == "shadow_batch_summary"
        and row["commit_performed"] is False
        for row in short_shadow
    )

    monkeypatch.setenv("NOVEL_CANONICAL_SHADOW_V1", "0")
    _reset_stable_ids(monkeypatch)
    long_disabled = await _run_long_chapters(
        tmp_path / "long-disabled", chapter_count=1,
    )
    monkeypatch.setenv("NOVEL_CANONICAL_SHADOW_V1", "1")
    _reset_stable_ids(monkeypatch)
    long_enabled = await _run_long_chapters(
        tmp_path / "long-enabled", chapter_count=1,
    )
    assert _formal_manifest(long_enabled["project"]) == _formal_manifest(
        long_disabled["project"]
    )
    assert _state_manifest(
        long_enabled["service"], long_enabled["project"],
    ) == _state_manifest(long_disabled["service"], long_disabled["project"])
    assert _journal_manifest(long_enabled["project"]) == _journal_manifest(
        long_disabled["project"]
    )
    long_trace = read_trace(trace_file_for_project(long_enabled["project"].path))
    long_shadow = canonical_shadow_comparison_matrix(long_trace.events)
    summaries = {
        row["workflow"] for row in long_shadow
        if row["claim_kind"] == "shadow_batch_summary"
    }
    assert summaries == {
        "long-setup-maintenance", "long-chapter-maintenance",
    }
    assert any(
        row["claim_kind"] == "character.location"
        for row in long_shadow
    )

    report = {
        "schema": "Phase1AShadowWorkflowReportV1",
        "short": {
            "formal_sha256": short_disabled["formal_sha256"],
            "story_state_revision": short_disabled["story_state_revision"],
            "story_state_sha256": short_disabled["story_state_sha256"],
            "ordered_model_call_delta": 0,
            "journal_count": len(_journal_manifest(short_disabled["project"])),
            "shadow_rows": short_shadow,
        },
        "long": {
            "formal_manifest": _formal_manifest(long_disabled["project"]),
            "story_state": _state_manifest(
                long_disabled["service"], long_disabled["project"],
            ),
            "journal_count": len(_journal_manifest(long_disabled["project"])),
            "shadow_rows": long_shadow,
        },
        "sink_failure_changed_business": False,
        "paid_llm_call_delta": 0,
    }
    output = os.environ.get("NOVEL_PHASE1A_WORKFLOW_REPORT")
    if output:
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


@pytest.mark.asyncio
async def test_shadow_flag_does_not_change_same_project_stage_prompt(
    tmp_path, monkeypatch,
) -> None:
    class Gateway:
        def __init__(self) -> None:
            self.calls = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls.append((role, system, user, max_output_tokens))
            return ModelResult("{}", {"role": role, "model_name": "offline"})

    gateway = Gateway()
    _db, store, project, service = _service(
        tmp_path, mode="short", gateway=gateway, title="Phase 1A Prompt Parity",
    )
    constraints = store.load_constraints(project.id)
    monkeypatch.setenv("NOVEL_CANONICAL_SHADOW_V1", "0")
    run_a, path_a = service._begin_run(project, "short-story", "shadow-off")
    await service._stage(
        run_a, path_a, project, "review", constraints, "same immutable task",
        allow_tools=False,
    )
    monkeypatch.setenv("NOVEL_CANONICAL_SHADOW_V1", "1")
    run_b, path_b = service._begin_run(project, "short-story", "shadow-on")
    await service._stage(
        run_b, path_b, project, "review", constraints, "same immutable task",
        allow_tools=False,
    )
    assert gateway.calls[0] == gateway.calls[1]
    role, system, user, output_budget = gateway.calls[0]
    report = {
        "schema": "Phase1APromptParityReportV1",
        "call_count_delta": 0,
        "role": role,
        "system_prompt_sha256": hashlib.sha256(
            system.encode("utf-8")
        ).hexdigest(),
        "user_prompt_sha256": hashlib.sha256(
            user.encode("utf-8")
        ).hexdigest(),
        "system_prompt_utf8_bytes": len(system.encode("utf-8")),
        "user_prompt_utf8_bytes": len(user.encode("utf-8")),
        "max_output_tokens": output_budget,
        "exact_call_tuple_equal": True,
    }
    output = os.environ.get("NOVEL_PHASE1A_PROMPT_REPORT")
    if output:
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def test_phase1a_shadow_comparison_and_overhead_report(tmp_path, monkeypatch) -> None:
    candidate, source, state = _direct_fixture(tmp_path)
    normal, normal_rows = evaluate_maintenance_shadow(
        project_root=tmp_path, workflow="short-normal-maintenance",
        legacy_candidate=candidate, final_source_bytes=source,
        story_time="chapter:10", story_state_revision=5,
        story_state_data=state, coverage_mode="complete_source",
    )
    window, window_rows = evaluate_maintenance_shadow(
        project_root=tmp_path, workflow="short-window-maintenance",
        legacy_candidate=candidate, final_source_bytes=source,
        story_time="chapter:10", story_state_revision=5,
        story_state_data=state, coverage_mode="window_union",
    )
    assert normal.claim_count == window.claim_count == 3
    assert normal.eligible_count == window.eligible_count == 3
    assert normal.receipt_hashes == window.receipt_hashes
    assert {row["claim_kind"] for row in normal_rows} == {
        "character.location", "character.knowledge",
        "character.relationship",
    }
    assert all(row["grounding"] == "exact" for row in normal_rows)
    assert all(row["legacy_comparison"] == "equivalent" for row in window_rows)

    monkeypatch.setenv("NOVEL_CANONICAL_SHADOW_V1", "0")
    started = time.perf_counter_ns()
    for _ in range(500):
        observe_maintenance_shadow(
            project_root=tmp_path, workflow="disabled",
            legacy_candidate=candidate, final_source_bytes=source,
            story_time="chapter:10", story_state_revision=5,
            story_state_data=state, coverage_mode="complete_source",
        )
    disabled_ns = time.perf_counter_ns() - started

    started = time.perf_counter_ns()
    iterations = 100
    for _ in range(iterations):
        evaluate_maintenance_shadow(
            project_root=tmp_path, workflow="enabled",
            legacy_candidate=candidate, final_source_bytes=source,
            story_time="chapter:10", story_state_revision=5,
            story_state_data=state, coverage_mode="complete_source",
        )
    enabled_ns = time.perf_counter_ns() - started
    disabled_ns_per_call = disabled_ns / 500
    enabled_ns_per_batch = enabled_ns / iterations
    storage_bytes = len(json.dumps(
        normal_rows, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8"))
    assert disabled_ns_per_call < 5_000_000
    assert enabled_ns_per_batch < 50_000_000
    assert storage_bytes < 2_048 * normal.claim_count + 4_096

    report = {
        "schema": "Phase1AShadowComparisonReportV1",
        "normal": normal.__dict__, "window": window.__dict__,
        "normal_window_receipts_equal": True,
        "identity_false_merge_candidates": 0,
        "identity_false_split_candidates": normal.identity_ambiguous_count,
        "evidence_gap_count": normal.evidence_gap_count,
        "eligibility_distribution": {
            "eligible": normal.eligible_count,
            "no_change": normal.no_change_count,
            "ineligible": normal.ineligible_count,
            "ambiguous": normal.ambiguous_count,
        },
        "disabled_ns_per_call": disabled_ns_per_call,
        "enabled_ns_per_batch": enabled_ns_per_batch,
        "diagnostic_storage_bytes": storage_bytes,
    }
    output = os.environ.get("NOVEL_PHASE1A_COMPARISON_REPORT")
    if output:
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
