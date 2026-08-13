from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

import pytest

_TESTS = str(Path(__file__).parent)
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

from novel_flywheel.models import ModelResult
from novel_flywheel.project_transactions import (
    load_project_mutation_journal,
    project_mutation_journal_path,
    recover_project_mutations,
)
from novel_flywheel.reliability_trace import read_trace, trace_file_for_project
from novel_flywheel.story_state import StoryStateStore
from novel_flywheel.short_canonical_promotion import (
    SHORT_CANONICAL_GATE_NAME,
    SHORT_CANONICAL_RECEIPT,
)

from test_phase05_evidence_closure import RecordingFakeGateway, _service


def _formal_manifest(project) -> dict[str, str]:
    result = {}
    for relative in (
        "manuscript/story.md", "chapters/chapter-01.md", "memory/canon.json",
    ):
        path = project.path / relative
        result[relative] = (
            hashlib.sha256(path.read_bytes()).hexdigest()
            if path.is_file() else "absent"
        )
    return result


class ReservedHoldGateway(RecordingFakeGateway):
    async def complete(self, role, system, user, max_output_tokens=None):
        if role == "maintenance":
            self.calls.append({
                "role": role,
                "system_sha256": hashlib.sha256(system.encode()).hexdigest(),
                "user_sha256": hashlib.sha256(user.encode()).hexdigest(),
                "max_output_tokens": max_output_tokens,
            })
            return ModelResult(json.dumps({
                "facts": [{
                    "key": "Aster.location.current",
                    "value": "North Gate",
                    "evidence": "Human, polished prose.",
                }],
            }), {"role": role, "model_name": "offline-maintenance"})
        return await super().complete(
            role, system, user, max_output_tokens=max_output_tokens,
        )


async def _run(
    root: Path, monkeypatch, *, environment: bool, project_flag: bool,
    gateway=None, run_id: str = "phase1b-short",
):
    gateway = gateway or RecordingFakeGateway()
    db, store, project, service = _service(
        root, mode="short", gateway=gateway, title="Phase 1B Short",
    )
    db.set_feature_flag(
        "short_canonical_v2", project_flag,
        scope_type="project", scope_id=project.id,
    )
    monkeypatch.setenv(
        "NOVEL_SHORT_CANONICAL_V2", "1" if environment else "0",
    )
    before = _formal_manifest(project)
    state_before = StoryStateStore(db).ensure(project.id, project.path)
    result = await service.run_short(
        project.id, use_crewai=False, run_id=run_id,
    )
    state_after = StoryStateStore(db).get(project.id)
    assert state_after is not None
    return {
        "db": db, "store": store, "project": project, "service": service,
        "gateway": gateway, "result": result, "before": before,
        "after": _formal_manifest(project), "state_before": state_before,
        "state_after": state_after,
    }


@pytest.mark.asyncio
async def test_dual_gate_requires_environment_and_exact_project_scope(
    tmp_path, monkeypatch,
) -> None:
    env_only = await _run(
        tmp_path / "env-only", monkeypatch,
        environment=True, project_flag=False,
    )
    project_only = await _run(
        tmp_path / "project-only", monkeypatch,
        environment=False, project_flag=True,
    )
    both = await _run(
        tmp_path / "both", monkeypatch,
        environment=True, project_flag=True,
    )
    for disabled in (env_only, project_only):
        assert not (
            disabled["project"].path / "runs" / "phase1b-short"
            / "receipts" / SHORT_CANONICAL_RECEIPT
        ).exists()
        journal = load_project_mutation_journal(project_mutation_journal_path(
            disabled["project"].path, "phase1b-short",
        ))
        assert journal.post_commit_gate is None
    assert env_only["after"] == project_only["after"]
    assert env_only["state_after"].data == project_only["state_after"].data
    receipt_path = (
        both["project"].path / "runs" / "phase1b-short"
        / "receipts" / SHORT_CANONICAL_RECEIPT
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    journal = load_project_mutation_journal(project_mutation_journal_path(
        both["project"].path, "phase1b-short",
    ))
    assert journal.post_commit_gate is not None
    assert journal.post_commit_gate.name == SHORT_CANONICAL_GATE_NAME
    assert journal.post_commit_gate.status == "passed"
    frozen = journal.post_commit_gate.payload
    assert frozen["lane"] == "short_canonical_v2"
    assert frozen["feature_flag_snapshot"]["enabled"] is True
    assert frozen["policy_version"] == "short-canonical-policy-v1"
    assert frozen["writer_plan_hash"]
    assert frozen["proposed_claim_batch_hash"]
    assert frozen["accepted_mutation_ids"] == []
    assert frozen["rejected_mutation_ids"] == []
    assert frozen["held_mutation_ids"] == []
    assert frozen["journal_saga_id"] == "phase1b-short"
    assert frozen["evidence_envelope_set_hash"]
    assert frozen["base_story_state_revision"] == both[
        "state_before"
    ].revision
    assert frozen["candidate_hash"] == frozen["final_narrative_hash"]
    assert frozen["expected_formal_targets"] == [
        "chapters/chapter-01.md", "manuscript/story.md", "memory/canon.json",
    ]
    assert frozen["formal_receipt_deterministic_input_hash"]
    assert receipt["commit_performed"] is True
    assert receipt["story_state_commit_count"] == 1
    assert receipt["journal_saga_id"] == "phase1b-short"
    assert receipt["accepted_mutation_ids"] == []
    assert receipt["rejected_mutation_ids"] == []
    assert receipt["held_mutation_ids"] == []
    assert both["state_after"].revision == both["state_before"].revision + 1
    assert [item["role"] for item in both["gateway"].calls] == [
        item["role"] for item in env_only["gateway"].calls
    ]
    assert [item["max_output_tokens"] for item in both["gateway"].calls] == [
        item["max_output_tokens"] for item in env_only["gateway"].calls
    ]

    def checkpoint_projection(run):
        with run["db"].connect() as connection:
            return [tuple(row) for row in connection.execute(
                "SELECT node_key, status, validation_stage, attempt "
                "FROM workflow_node_checkpoints WHERE run_id=? "
                "ORDER BY node_key, input_sha256",
                ("phase1b-short",),
            )]

    assert checkpoint_projection(both) == checkpoint_projection(env_only)
    candidate_projection = lambda run: sorted(
        (item.kind, item.status)
        for item in StoryStateStore(run["db"]).list_candidates(
            run["project"].id,
        )
    )
    assert candidate_projection(both) == candidate_projection(env_only)
    assert both["after"] == env_only["after"]
    promotion_events = [
        item for item in read_trace(
            trace_file_for_project(both["project"].path),
        ).events
        if item.event_type == "promotion_write"
        and item.source_writer == "short_canonical_v2"
    ]
    assert len(promotion_events) == 1
    assert promotion_events[0].payload["decision"] == "committed"
    assert promotion_events[0].payload["receipt_hash"] == receipt["receipt_hash"]
    assert promotion_events[0].payload["story_state_commit_count"] == 1


@pytest.mark.asyncio
async def test_feature_gate_does_not_change_same_project_prompt_or_budget(
    tmp_path, monkeypatch,
) -> None:
    class PromptGateway:
        def __init__(self) -> None:
            self.calls = []

        async def complete(self, role, system, user, max_output_tokens=None):
            self.calls.append((role, system, user, max_output_tokens))
            return ModelResult("{}", {"role": role, "model_name": "offline"})

    gateway = PromptGateway()
    db, store, project, service = _service(
        tmp_path, mode="short", gateway=gateway, title="Prompt parity",
    )
    constraints = store.load_constraints(project.id)
    monkeypatch.setenv("NOVEL_SHORT_CANONICAL_V2", "0")
    db.set_feature_flag(
        "short_canonical_v2", False,
        scope_type="project", scope_id=project.id,
    )
    run_a, path_a = service._begin_run(project, "short-story", "gate-off")
    await service._stage(
        run_a, path_a, project, "review", constraints, "same task",
        allow_tools=False,
    )
    db.update_run(run_a, "completed")
    monkeypatch.setenv("NOVEL_SHORT_CANONICAL_V2", "1")
    db.set_feature_flag(
        "short_canonical_v2", True,
        scope_type="project", scope_id=project.id,
    )
    run_b, path_b = service._begin_run(project, "short-story", "gate-on")
    await service._stage(
        run_b, path_b, project, "review", constraints, "same task",
        allow_tools=False,
    )
    assert gateway.calls[0] == gateway.calls[1]


@pytest.mark.asyncio
async def test_batch_hold_preserves_formal_state_and_pending_candidate(
    tmp_path, monkeypatch,
) -> None:
    run = await _run(
        tmp_path, monkeypatch, environment=True, project_flag=True,
        gateway=ReservedHoldGateway(), run_id="phase1b-hold",
    )
    assert run["result"]["status"] == "failed"
    assert run["after"] == run["before"]
    assert run["state_after"].revision == run["state_before"].revision
    assert run["state_after"].data == run["state_before"].data
    journal_path = project_mutation_journal_path(
        run["project"].path, "phase1b-hold",
    )
    assert not journal_path.exists()
    candidates = StoryStateStore(run["db"]).list_candidates(
        run["project"].id, kind="polish", status="pending",
    )
    assert len(candidates) == 1
    assert candidates[0].metadata["canonical_v2"] == {
        "status": "hold", "protected": True,
        "decision_hash": candidates[0].metadata["canonical_v2"][
            "decision_hash"
        ],
        "decision_artifact": (
            "receipts/short-canonical-gate-decision-v1.json"
        ),
    }
    decision = json.loads((
        run["project"].path / "runs" / "phase1b-hold" / "receipts"
        / "short-canonical-gate-decision-v1.json"
    ).read_text(encoding="utf-8"))
    assert decision["commit_performed"] is False
    assert "unsupported_reserved_kind" in decision["hold_reasons"]
    assert recover_project_mutations(
        run["store"], workflow="short-story",
    ) == []
    assert _formal_manifest(run["project"]) == run["before"]
    promotion_events = [
        item for item in read_trace(
            trace_file_for_project(run["project"].path),
        ).events
        if item.event_type == "promotion_write"
        and item.source_writer == "short_canonical_v2"
    ]
    assert len(promotion_events) == 1
    assert promotion_events[0].payload["decision"] == "hold"
    assert promotion_events[0].payload["commit_performed"] is False
    assert promotion_events[0].payload["projection_effects"] == []


@pytest.mark.asyncio
async def test_receipt_failure_recovers_from_frozen_journal_without_model_call(
    tmp_path, monkeypatch,
) -> None:
    import novel_flywheel.workflows as workflows_module

    gateway = RecordingFakeGateway()
    original = workflows_module.build_short_commit_receipt_from_frozen_payload

    def fail_receipt_once(**_kwargs):
        raise OSError("injected receipt write boundary failure")

    monkeypatch.setattr(
        workflows_module,
        "build_short_commit_receipt_from_frozen_payload",
        fail_receipt_once,
    )
    run = await _run(
        tmp_path, monkeypatch, environment=True, project_flag=True,
        gateway=gateway, run_id="phase1b-recovery",
    )
    call_count = len(gateway.calls)
    assert run["result"]["status"] == "recovering_protocol"
    assert run["state_after"].revision == run["state_before"].revision + 1
    journal = load_project_mutation_journal(project_mutation_journal_path(
        run["project"].path, "phase1b-recovery",
    ))
    assert journal.status == "committed"
    assert journal.post_commit_gate is not None
    assert journal.post_commit_gate.status == "pending"

    monkeypatch.setattr(
        workflows_module,
        "build_short_commit_receipt_from_frozen_payload",
        original,
    )
    run["db"].set_feature_flag(
        "short_canonical_v2", False, scope_type="project",
        scope_id=run["project"].id,
    )
    monkeypatch.setenv("NOVEL_SHORT_CANONICAL_V2", "0")
    import novel_flywheel.short_canonical_promotion as canonical_module

    monkeypatch.setattr(
        canonical_module, "evaluate_short_canonical_gate",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("recovery must not re-evaluate the canonical gate")
        ),
    )
    recovered = recover_project_mutations(
        run["store"], workflow="short-story",
    )
    assert recovered == ["phase1b-recovery"]
    assert len(gateway.calls) == call_count
    assert run["db"].get_run("phase1b-recovery")["status"] == "completed"
    final_state = StoryStateStore(run["db"]).get(run["project"].id)
    assert final_state is not None
    assert final_state.revision == run["state_after"].revision
    with run["db"].connect() as connection:
        history_count = connection.execute(
            "SELECT COUNT(*) AS count FROM story_state_history WHERE project_id=?",
            (run["project"].id,),
        ).fetchone()["count"]
    assert history_count == 2
    receipt = json.loads((
        run["project"].path / "runs" / "phase1b-recovery" / "receipts"
        / SHORT_CANONICAL_RECEIPT
    ).read_text(encoding="utf-8"))
    assert receipt["target_revision"] == final_state.revision
    assert receipt["target_authority_hash"] == hashlib.sha256(json.dumps(
        final_state.data, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


@pytest.mark.asyncio
async def test_pre_artifact_interruption_rolls_back_v2_saga(
    tmp_path, monkeypatch,
) -> None:
    import novel_flywheel.workflows as workflows_module

    gateway = RecordingFakeGateway()
    db, store, project, service = _service(
        tmp_path, mode="short", gateway=gateway, title="Phase 1B rollback",
    )
    db.set_feature_flag(
        "short_canonical_v2", True,
        scope_type="project", scope_id=project.id,
    )
    monkeypatch.setenv("NOVEL_SHORT_CANONICAL_V2", "1")
    state_before = StoryStateStore(db).ensure(project.id, project.path)
    formal_before = _formal_manifest(project)
    original_atomic_write = workflows_module.atomic_write
    interrupted = False

    def interrupt_first_formal_write(path, *args, **kwargs):
        nonlocal interrupted
        target = Path(path)
        journal_path = project_mutation_journal_path(
            project.path, "phase1b-pre-artifact-interruption",
        )
        if (
            not interrupted
            and target == project.path / "manuscript" / "story.md"
            and journal_path.is_file()
        ):
            interrupted = True
            raise OSError("injected pre-artifact interruption")
        return original_atomic_write(path, *args, **kwargs)

    monkeypatch.setattr(
        workflows_module, "atomic_write", interrupt_first_formal_write,
    )
    with pytest.raises(OSError, match="pre-artifact interruption"):
        await service.run_short(
            project.id, use_crewai=False,
            run_id="phase1b-pre-artifact-interruption",
        )
    assert interrupted is True
    journal = load_project_mutation_journal(project_mutation_journal_path(
        project.path, "phase1b-pre-artifact-interruption",
    ))
    assert journal.status == "rolled_back"
    assert journal.post_commit_gate is not None
    assert journal.post_commit_gate.status == "pending"
    state_after = StoryStateStore(db).get(project.id)
    assert state_after is not None
    assert state_after.revision == state_before.revision
    assert state_after.data == state_before.data
    assert _formal_manifest(project) == formal_before
    assert db.get_run("phase1b-pre-artifact-interruption")["status"] == "failed"


@pytest.mark.asyncio
async def test_enabled_disabled_candidate_lane_overhead_report(
    tmp_path, monkeypatch,
) -> None:
    started = time.perf_counter()
    disabled = await _run(
        tmp_path / "disabled", monkeypatch,
        environment=False, project_flag=False, run_id="phase1b-overhead",
    )
    disabled_seconds = time.perf_counter() - started
    started = time.perf_counter()
    enabled = await _run(
        tmp_path / "enabled", monkeypatch,
        environment=True, project_flag=True, run_id="phase1b-overhead",
    )
    enabled_seconds = time.perf_counter() - started
    assert enabled["after"] == disabled["after"]
    assert enabled["state_after"].data == disabled["state_after"].data
    assert [item["role"] for item in enabled["gateway"].calls] == [
        item["role"] for item in disabled["gateway"].calls
    ]
    assert [item["max_output_tokens"] for item in enabled["gateway"].calls] == [
        item["max_output_tokens"] for item in disabled["gateway"].calls
    ]

    def artifact_bytes(run) -> int:
        root = run["project"].path / "runs" / "phase1b-overhead"
        return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())

    output = os.environ.get("NOVEL_PHASE1B_OVERHEAD_REPORT")
    if output:
        payload = {
            "schema": "Phase1BOverheadReportV1",
            "timing_scope": "one deterministic offline complete short run",
            "disabled_seconds": disabled_seconds,
            "enabled_seconds": enabled_seconds,
            "elapsed_delta_seconds": enabled_seconds - disabled_seconds,
            "disabled_run_artifact_bytes": artifact_bytes(disabled),
            "enabled_run_artifact_bytes": artifact_bytes(enabled),
            "run_artifact_delta_bytes": (
                artifact_bytes(enabled) - artifact_bytes(disabled)
            ),
            "ordered_model_calls_equal": True,
            "model_call_delta": 0,
            "system_prompt_hash_delta": 0,
            "user_prompt_hash_delta": 0,
            "prompt_parity_evidence": (
                "test_feature_gate_does_not_change_same_project_prompt_or_budget"
            ),
            "output_budget_delta": 0,
            "business_artifacts_equal": True,
            "paid_model_calls": 0,
        }
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
