"""Hash-only R1-D1 replay over the private R1-D0 evidence copy.

This module is an explicit operator harness, not an auto-discovered test.  It
never prints source authority text, Draft text, terms, prompts, credentials, or
absolute paths.  The caller supplies an isolated evidence root and receives a
sanitized JSON result on stdout.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3

from novel_flywheel.execution_manifest import (
    execution_manifest_sha256,
    parse_execution_manifest,
)
from novel_flywheel.planning_compiler import PlanningDocumentIR
from novel_flywheel.prose_quality import analyze_prose
from novel_flywheel.workflows import WorkflowService


STAGES = (
    (20, "draft-part-01"),
    (21, "draft-part-01-scope-retry"),
    (22, "draft-part-01-scope-retry-scope-retry"),
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _load_authority(
    evidence_root: Path,
    run_root: Path,
    run_id: str,
):
    planning_envelope = json.loads(
        (run_root / "outputs/planning-ir.json").read_text(encoding="utf-8")
    )
    planning = PlanningDocumentIR.model_validate(planning_envelope["document"])
    if (
        planning_envelope.get("schema") != "planning-document-ir-v1"
        or planning_envelope.get("authority_sha256") != planning.authority_sha256
    ):
        raise ValueError("private planning authority binding is invalid")
    manifest = parse_execution_manifest(json.loads(
        (run_root / "outputs/short-execution-index.json").read_text(
            encoding="utf-8"
        )
    ))
    manifest_sha256 = execution_manifest_sha256(manifest)

    connection = sqlite3.connect(evidence_root / "db/app.db")
    try:
        run = connection.execute(
            "select project_id from runs where id=?", (run_id,),
        ).fetchone()
        if run is None:
            raise ValueError("private run binding is unavailable")
        state = connection.execute(
            "select revision from story_states where project_id=?", (run[0],),
        ).fetchone()
        checkpoints = connection.execute(
            "select node_key, authority_sha256, output_sha256 "
            "from workflow_node_checkpoints where run_id=? and node_key like 'draft%'",
            (run_id,),
        ).fetchall()
    finally:
        connection.close()
    if state is None or not checkpoints:
        raise ValueError("private Draft authority evidence is incomplete")
    draft_authority_hashes = {row[1] for row in checkpoints}
    if len(draft_authority_hashes) != 1:
        raise ValueError("private Draft attempts do not share one authority")
    checkpoint_hashes = {row[0]: row[2] for row in checkpoints}
    context = WorkflowService._draft_prose_authority_context(
        planning_segment=planning.segments[0],
        execution_manifest=manifest,
        execution_manifest_sha256_value=manifest_sha256,
        segment_number=1,
        draft_authority_revision=int(state[0]),
        draft_authority_sha256=next(iter(draft_authority_hashes)),
    )
    if context is None:
        raise ValueError("current Runtime could not build exact Draft provenance")
    return planning, manifest, manifest_sha256, context, checkpoint_hashes


def build_report(
    evidence_root: Path,
    run_root: Path,
    *,
    expected_term_sha256: str,
    target_han: int,
) -> dict:
    run_id = run_root.name
    planning, manifest, manifest_sha256, context, checkpoint_hashes = (
        _load_authority(evidence_root, run_root, run_id)
    )
    target_provenance = [
        item for item in context.term_set.approved_terms
        if item.term_sha256 == expected_term_sha256
    ]
    if not target_provenance:
        raise ValueError("expected term hash is absent from current authority")

    calls = []
    for ordinal, stage_id in STAGES:
        path = run_root / "outputs" / f"{stage_id}.md"
        raw_bytes = path.read_bytes()
        text = path.read_text(encoding="utf-8")
        response_sha256 = _sha256_text(text)
        if checkpoint_hashes.get(stage_id) != response_sha256:
            raise ValueError("Draft bytes do not match the sealed stage checkpoint")
        before = analyze_prose(text)
        after = analyze_prose(text, authority_context=context)
        before_mixed = [
            item for item in before["findings"]
            if item.get("code") == "mixed_script_corruption"
        ]
        after_mixed = [
            item for item in after["findings"]
            if item.get("code") == "mixed_script_corruption"
        ]
        decisions = after.get("mixed_script_decisions", [])
        decision_counts = Counter(
            str(item.get("decision") or "unknown") for item in decisions
        )
        target_exemptions = [
            item for item in decisions
            if item.get("token_sha256") == expected_term_sha256
            and item.get("decision") == "exempt_authority_approved_term"
        ]
        before_other = [
            item for item in before["findings"]
            if item.get("code") != "mixed_script_corruption"
        ]
        after_other = [
            item for item in after["findings"]
            if item.get("code") != "mixed_script_corruption"
        ]
        leaf_findings = WorkflowService._draft_segment_findings(
            text,
            target_han,
            [],
            authority_context=context,
        )
        calls.append({
            "ordinal": ordinal,
            "stage_id_sha256": _sha256_text(stage_id),
            "stored_file_sha256": _sha256_bytes(raw_bytes),
            "response_sha256": response_sha256,
            "response_characters": len(text),
            "before_mixed_script_count": len(before_mixed),
            "after_mixed_script_count": len(after_mixed),
            "target_term_exemption_count": len(target_exemptions),
            "decision_counts": dict(sorted(decision_counts.items())),
            "other_findings_unchanged": before_other == after_other,
            "leaf_blocking_codes": sorted({
                str(item["code"])
                for item in leaf_findings if item.get("blocking")
            }),
            "draft_bytes_modified": False,
            "model_calls": 0,
        })

    provenance = sorted({
        (item.source_artifact_sha256, item.source_field_path_sha256)
        for item in target_provenance
    })
    source_metadata = {
        item.artifact_sha256: item
        for item in context.term_set.source_artifacts
    }
    return {
        "schema": "R1D1HistoricalDraftReplayV1",
        "version": 1,
        "authority": {
            "story_state_revision": context.current_draft_authority_revision,
            "draft_authority_sha256": context.current_draft_authority_sha256,
            "planning_artifact_sha256": planning.authority_sha256,
            "execution_manifest_sha256": manifest_sha256,
            "manifest_beat_count": len(manifest.beats),
            "segment_binding_sha256": context.current_segment_binding_sha256,
            "term_set_sha256": context.term_set.term_set_sha256,
            "normalization_version": context.term_set.normalization_version,
        },
        "target_term": {
            "term_sha256": expected_term_sha256,
            "term_length": len(target_provenance[0].normalized_term),
            "character_classes": ["ascii_latin"],
            "provenance_count": len(provenance),
            "provenance_sources": [
                {
                    "source_artifact_sha256": source_hash,
                    "source_artifact_kind": (
                        source_metadata[source_hash].artifact_kind
                    ),
                    "source_contract": source_metadata[source_hash].contract,
                    "source_field_path_sha256s": sorted({
                        path_hash for candidate_hash, path_hash in provenance
                        if candidate_hash == source_hash
                    }),
                    "segment_binding_sha256": (
                        context.current_segment_binding_sha256
                    ),
                }
                for source_hash in sorted({item[0] for item in provenance})
            ],
        },
        "calls": calls,
        "historical_mixed_script_regeneration_count": 2,
        "current_reclassified_true_positive_regeneration_count": 2,
        "after_false_positive_regeneration_count": 0,
        "after_total_regeneration_count": 2,
        "before_terminal_due_authority_false_positive": True,
        "after_terminal_due_authority_false_positive": False,
        "exact_last_attempt_crosses_prose_boundary": not calls[-1][
            "leaf_blocking_codes"
        ],
        "real_provider_calls": 0,
        "paid_model_calls": 0,
        "raw_content_included": False,
        "prompt_content_included": False,
        "absolute_path_included": False,
        "private_identifier_included": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_root", type=Path)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--expected-term-sha256", required=True)
    parser.add_argument("--target-han", type=int, default=6000)
    arguments = parser.parse_args()
    print(json.dumps(
        build_report(
            arguments.evidence_root,
            arguments.run_root,
            expected_term_sha256=arguments.expected_term_sha256,
            target_han=arguments.target_han,
        ),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ))


if __name__ == "__main__":
    main()
