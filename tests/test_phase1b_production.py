from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import pytest

_TESTS = str(Path(__file__).parent)
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

from novel_flywheel.canonical_shadow import (
    resolve_shadow_slot,
    story_state_authority_hash,
)
from novel_flywheel.db import Database
from novel_flywheel.project_transactions import (
    load_project_mutation_journal,
    project_mutation_journal_path,
)
from novel_flywheel.projects import ProjectStore
from novel_flywheel.short_canonical_promotion import (
    SHORT_CANONICAL_RECEIPT,
    classify_legacy_disposition,
    evaluate_short_canonical_gate,
    make_maintenance_inventory,
    proposal_units_from_candidate,
)
from novel_flywheel.story_state import StoryStateStore

import test_workflows as workflow_tests


@pytest.mark.asyncio
@pytest.mark.parametrize("target_words", [13_000, 20_000, 30_000])
async def test_phase1b_candidate_lane_production_length_matrix(
    tmp_path, target_words, monkeypatch,
) -> None:
    original_create = ProjectStore.create

    def create_with_project_canary(self, payload):
        project = original_create(self, payload)
        self.db.set_feature_flag(
            "short_canonical_v2", True,
            scope_type="project", scope_id=project.id,
        )
        return project

    monkeypatch.setattr(ProjectStore, "create", create_with_project_canary)
    monkeypatch.setenv("NOVEL_SHORT_CANONICAL_V2", "1")
    started = time.perf_counter()
    production_workflow = (
        workflow_tests
        .test_short_ir_first_production_length_matrix_reaches_formal_manuscript
    )
    await production_workflow(tmp_path, target_words)
    elapsed_seconds = time.perf_counter() - started

    db = Database(tmp_path / "app.db")
    store = ProjectStore(db, tmp_path / "workspace")
    project = store.list()[0]
    run = db.list_runs(project.id)[0]
    assert run["status"] == "completed"
    state = StoryStateStore(db).get(project.id)
    assert state is not None
    journal = load_project_mutation_journal(project_mutation_journal_path(
        project.path, run["id"],
    ))
    assert journal.status == "committed"
    assert journal.post_commit_gate is not None
    assert journal.post_commit_gate.status == "passed"
    frozen = journal.post_commit_gate.payload
    assert frozen["lane"] == "short_canonical_v2"
    assert frozen["feature_flag_snapshot"]["enabled"] is True
    assert len(frozen["accepted_mutation_ids"]) == 1
    assert frozen["held_mutation_ids"] == []
    receipt_path = (
        project.path / "runs" / run["id"] / "receipts"
        / SHORT_CANONICAL_RECEIPT
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["story_state_commit_count"] == 1
    assert receipt["target_revision"] == state.revision
    assert receipt["target_authority_hash"] == story_state_authority_hash(
        state.data
    )
    inventory = json.loads(next((
        project.path / "runs" / run["id"] / "receipts"
    ).glob("maintenance-inventory-*.json")).read_text(encoding="utf-8"))
    assert inventory["complete"] is True
    assert inventory["structurally_valid_unit_count"] == len(
        inventory["units"]
    )

    output_root = os.environ.get("NOVEL_PHASE1B_PRODUCTION_REPORT_DIR")
    if output_root:
        output = Path(output_root)
        output.mkdir(parents=True, exist_ok=True)
        formal = project.path / "manuscript" / "story.md"
        run_root = project.path / "runs" / run["id"]
        payload = {
            "schema": "Phase1BProductionLengthEvidenceV1",
            "target_words": target_words,
            "run_status": run["status"],
            "formal_sha256": hashlib.sha256(formal.read_bytes()).hexdigest(),
            "story_state_revision": state.revision,
            "story_state_hash": story_state_authority_hash(state.data),
            "journal_status": journal.status,
            "gate_status": journal.post_commit_gate.status,
            "accepted_mutation_count": len(
                frozen["accepted_mutation_ids"]
            ),
            "held_mutation_count": len(frozen["held_mutation_ids"]),
            "writer_plan_hash": frozen["writer_plan_hash"],
            "proposed_claim_batch_hash": frozen[
                "proposed_claim_batch_hash"
            ],
            "receipt_hash": receipt["receipt_hash"],
            "story_state_commit_count": receipt[
                "story_state_commit_count"
            ],
            "lost_before_v2": (
                inventory["structurally_valid_unit_count"]
                - len(inventory["units"])
            ),
            "paid_model_calls": 0,
            "elapsed_seconds": elapsed_seconds,
            "run_artifact_bytes": sum(
                path.stat().st_size
                for path in run_root.rglob("*") if path.is_file()
            ),
        }
        (output / f"production-{target_words}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )


def test_phase1b_replay_corpus_report(tmp_path) -> None:
    corpus_path = (
        Path(__file__).parent / "fixtures" / "canonical"
        / "phase1b-replay-corpus-v1.json"
    )
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    samples = corpus["samples"]
    characters = tmp_path / "characters"
    characters.mkdir()
    (characters / "aster.md").write_text(
        "---\nname: Aster\naliases: [A]\n---\n", encoding="utf-8",
    )
    (characters / "rowan.md").write_text(
        "---\nname: Rowan\n---\n", encoding="utf-8",
    )
    metrics = Counter()
    hold_reasons = Counter()
    writer_ownership = Counter()
    parity_rows = {}
    for sample in samples:
        source = sample["source"].encode("utf-8")
        units = proposal_units_from_candidate(
            sample["proposal"], source_mode=sample["mode"],
            source_locator=sample["id"], source_attempt=1,
        )
        accepted = (
            sample["proposal"] if sample["legacy"] == "accepted"
            else {"facts": [], "state": {}, "state_transitions": []}
        )
        units = classify_legacy_disposition(units, accepted)
        inventory = make_maintenance_inventory(
            source_mode=sample["mode"],
            source_artifact_hash=hashlib.sha256(source).hexdigest(),
            base_authority_revision=4,
            base_authority_hash=story_state_authority_hash(sample["state"]),
            units=units,
        )
        evaluation = evaluate_short_canonical_gate(
            project_root=tmp_path, project_id="replay-project",
            inventory=inventory, final_source_bytes=source,
            story_state_revision=4, story_state_data=sample["state"],
        )
        metrics["sample_total"] += 1
        metrics["proposal_total"] += evaluation.replay_counts[
            "proposal_total"
        ]
        metrics["legacy_accepted"] += evaluation.replay_counts[
            "legacy_accepted"
        ]
        metrics["legacy_rejected"] += evaluation.replay_counts[
            "legacy_rejected"
        ]
        metrics["v2_eligible"] += evaluation.replay_counts["v2_eligible"]
        metrics["v2_hold"] += evaluation.replay_counts["v2_hold"]
        metrics["lost_before_v2"] += evaluation.replay_counts[
            "lost_before_v2"
        ]
        metrics["legacy_accept_v2_reject"] += evaluation.replay_counts[
            "legacy_accept_v2_reject"
        ]
        metrics["legacy_reject_v2_accept"] += evaluation.replay_counts[
            "legacy_reject_v2_accept"
        ]
        metrics["exact_evidence"] += sum(
            item.grounding == "exact" for item in evaluation.evidence
        )
        metrics["identity_ambiguous"] += sum(
            "slot_identity_ambiguous" in item.failure_codes
            for item in evaluation.phase1a_mutations
        )
        metrics["zero_claim"] += not evaluation.claims
        metrics["total_claims"] += len(evaluation.claims)
        metrics["supported_claims"] += len(evaluation.claims)
        metrics["ungrounded"] += sum(
            item.grounding != "exact" for item in evaluation.evidence
        )
        metrics["no_change"] += sum(
            item.eligibility == "no_change"
            for item in evaluation.phase1a_mutations
        )
        metrics["future_normative"] += sum(
            item.semantic_domain == "future_normative"
            for item in evaluation.claims
        )
        metrics["legacy_only"] += sum(
            item.category == "legacy_only" for item in inventory.units
        )
        metrics["value_mismatch"] += sum(
            any(code in {
                "expected_current_mismatch",
                "story_state_multiple_current_values",
            } for code in item.failure_codes)
            for item in evaluation.phase1a_mutations
        )
        metrics["equivalent"] += (
            evaluation.replay_counts["v2_eligible"]
            - evaluation.replay_counts["legacy_reject_v2_accept"]
        )
        metrics["held_batch"] += evaluation.canonical_gate_result == "hold"
        hold_reasons.update(evaluation.canonical_hold_reasons)
        writer_ownership["canonical_v2"] += len(
            evaluation.formal_mutations
        )
        writer_ownership["legacy"] += sum(
            item.category == "legacy_only" for item in inventory.units
        )
        parity_rows[sample["id"].split("-", 1)[1]] = {
            **parity_rows.get(sample["id"].split("-", 1)[1], {}),
            sample["mode"]: {
                "evidence": [item.grounding for item in evaluation.evidence],
                "slots": [
                    item.slot_id for item in evaluation.phase1a_mutations
                ],
                "eligibility": [
                    item.eligibility for item in evaluation.phase1a_mutations
                ],
            },
        }
    gold_state = {
        "manuscript_revision": 0,
        "character_states": {"Aster": {}, "Rowan": {}},
    }
    gold_source = b"gold identity evidence"
    gold_source_hash = hashlib.sha256(gold_source).hexdigest()
    for pair in corpus["identity_gold_pairs"]:
        slots = []
        for key in (pair["left_key"], pair["right_key"]):
            units = proposal_units_from_candidate(
                {"facts": [{
                    "key": key, "value": "gold-value",
                    "evidence": "gold identity evidence",
                }]},
                source_mode="normal", source_locator=pair["id"],
                source_attempt=1,
            )
            inventory = make_maintenance_inventory(
                source_mode="normal",
                source_artifact_hash=gold_source_hash,
                base_authority_revision=1,
                base_authority_hash=story_state_authority_hash(gold_state),
                units=units,
            )
            evaluation = evaluate_short_canonical_gate(
                project_root=tmp_path, project_id="replay-project",
                inventory=inventory, final_source_bytes=gold_source,
                story_state_revision=1, story_state_data=gold_state,
            )
            assert len(evaluation.claims) == 1
            slots.append(resolve_shadow_slot(evaluation.claims[0]).slot_id)
        expected_same = pair["same_slot"] is True
        actual_same = slots[0] == slots[1]
        metrics["identity_gold_pair_total"] += 1
        metrics["false_split"] += expected_same and not actual_same
        metrics["false_merge"] += not expected_same and actual_same
    assert metrics["sample_total"] == 24
    assert metrics["lost_before_v2"] == 0
    assert metrics["legacy_accepted"] > 0
    assert metrics["legacy_rejected"] > 0
    assert metrics["v2_eligible"] > 0
    assert metrics["v2_hold"] > 0
    assert metrics["exact_evidence"] > 0
    assert metrics["identity_ambiguous"] > 0
    assert metrics["zero_claim"] == 4
    assert metrics["identity_gold_pair_total"] == 4
    assert metrics["false_split"] == 0
    assert metrics["false_merge"] == 0
    assert metrics["no_change"] == 2
    assert metrics["future_normative"] == 2
    assert metrics["legacy_only"] == 2
    for row in parity_rows.values():
        assert row["normal"] == row["window"]
    assert hold_reasons["unsupported_reserved_kind"] == 2
    assert writer_ownership["canonical_v2"] > 0
    assert writer_ownership["legacy"] == 2

    output = os.environ.get("NOVEL_PHASE1B_REPLAY_REPORT")
    if output:
        denominator = max(1, metrics["proposal_total"])
        report = {
            "schema": "Phase1BReplayReportV1",
            **dict(metrics),
            "exact_evidence_rate": metrics["exact_evidence"] / denominator,
            "hold_rate": metrics["held_batch"] / metrics["sample_total"],
            "identity_ambiguous_rate": (
                metrics["identity_ambiguous"] / denominator
            ),
            "ungrounded_rate": metrics["ungrounded"] / denominator,
            "false_split_rate": (
                metrics["false_split"]
                / metrics["identity_gold_pair_total"]
            ),
            "false_merge_rate": (
                metrics["false_merge"]
                / metrics["identity_gold_pair_total"]
            ),
            "legacy_v2_mismatch": {
                "legacy_accept_v2_reject": metrics[
                    "legacy_accept_v2_reject"
                ],
                "legacy_reject_v2_accept": metrics[
                    "legacy_reject_v2_accept"
                ],
            },
            "shadow_only": metrics["legacy_reject_v2_accept"],
            "qualification_mismatch": (
                metrics["legacy_accept_v2_reject"]
                + metrics["legacy_reject_v2_accept"]
            ),
            "writer_ownership": dict(writer_ownership),
            "batch_hold_reasons": dict(hold_reasons),
            "zero_claim_rate": metrics["zero_claim"] / metrics["sample_total"],
            "paid_model_calls": 0,
        }
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
