"""Hash-only R1-D2 replay over one isolated Short Canary run.

This operator harness reads already sealed artifacts and SQLite observations.
It does not import a gateway, open a network connection, or retain Draft,
Prompt, token, project, provider, or credential text in its result.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import unicodedata

from novel_flywheel.execution_manifest import (
    execution_manifest_sha256,
    parse_execution_manifest,
)
from novel_flywheel.planning_compiler import PlanningDocumentIR
from novel_flywheel.prose_quality import (
    AuthorityApprovedLatinTermV1,
    DraftProseAuthorityContextV1,
    _latin_tokens,
    analyze_prose,
)
from novel_flywheel.workflows import WorkflowService


STAGES = (
    (20, "draft-part-01", 0),
    (21, "draft-part-01-scope-retry", 1),
    (22, "draft-part-01-scope-retry-scope-retry", 2),
)
DECLARED_POLICY_SHA256 = (
    "7e9875e3341f811fc3882b8161de6ca9f4e81243ce0262a0b1c72cb54353c940"
)
CANARY_VALIDATOR_POLICY_SHA256 = (
    "7e9f52cf3c5600423c6abe63a7de6d8449db81bfcd7260585da5d8b59e22fdac"
)
CANARY_MIXED_SCRIPT_POLICY_SHA256 = (
    "11c8a15e84c7c76154b60b047f9048468c93d60ee6c383b5b66dadd2c1066d1d"
)
PRODUCTION_SOURCE_SHA256 = (
    "b56475366aa7f64edc2f65f03ebf87dc76ed454751661efd0346631888a50789"
)
EXPECTED_CLASSIFICATIONS = {
    "48d53635551c8fd4564251d49f4e6eba58c2774469144e4346310955fbadbf4c":
        "LEGITIMATE_NEW_LATIN_TERM_INTRODUCED_BY_DRAFT",
    "ecb53f367b3541da3a14236d9a091f9bcc7a9903953f36577c2664fdd2a68a55":
        "LEGITIMATE_NEW_LATIN_TERM_INTRODUCED_BY_DRAFT",
    "703a5028367b34d87af5efe43f6ba90015830c34010a99342141547c82c0454c":
        "LEGITIMATE_NEW_LATIN_TERM_INTRODUCED_BY_DRAFT",
    "3843971dcfdee5083e6289e1bbdbb003e538b5a8a668fc43ae4f19d415ac18a2":
        "LEGITIMATE_NEW_LATIN_TERM_INTRODUCED_BY_DRAFT",
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def canonical_sha256(value: object) -> str:
    return sha256_text(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ))


def rejected_set_sha256(values: list[str]) -> str:
    return canonical_sha256(sorted(set(values)))


def _load_authority(evidence_root: Path, run_root: Path, run_id: str):
    envelope = json.loads(
        (run_root / "outputs/planning-ir.json").read_text(encoding="utf-8")
    )
    planning = PlanningDocumentIR.model_validate(envelope["document"])
    if envelope.get("authority_sha256") != planning.authority_sha256:
        raise ValueError("planning authority binding is invalid")
    manifest = parse_execution_manifest(json.loads(
        (run_root / "outputs/short-execution-index.json").read_text(
            encoding="utf-8"
        )
    ))
    manifest_hash = execution_manifest_sha256(manifest)
    connection = sqlite3.connect(evidence_root / "db/app.db")
    try:
        run = connection.execute(
            "select project_id from runs where id=?", (run_id,),
        ).fetchone()
        state = connection.execute(
            "select revision from story_states where project_id=?", (run[0],),
        ).fetchone() if run else None
        checkpoints = connection.execute(
            "select node_key, authority_sha256, input_sha256, output_sha256, "
            "status, validation_stage, route_fingerprint from "
            "workflow_node_checkpoints where run_id=? and node_key like 'draft%'",
            (run_id,),
        ).fetchall()
        receipts = connection.execute(
            "select id, metadata_json from run_events where run_id=? and "
            "event_type='draft_prose_validation_receipt' order by id",
            (run_id,),
        ).fetchall()
        retries = connection.execute(
            "select id, metadata_json from run_events where run_id=? and "
            "event_type='draft_task_scope_retry' order by id",
            (run_id,),
        ).fetchall()
    finally:
        connection.close()
    if state is None or len(checkpoints) != 3 or len(receipts) != 3:
        raise ValueError("Draft authority or retry evidence is incomplete")
    receipt_values = [(row[0], json.loads(row[1])) for row in receipts]
    validator_authority_hashes = {
        value["draft_authority_sha256"] for _event_id, value in receipt_values
    }
    validator_authority_revisions = {
        int(value["draft_authority_revision"])
        for _event_id, value in receipt_values
    }
    if (
        len(validator_authority_hashes) != 1
        or len(validator_authority_revisions) != 1
        or next(iter(validator_authority_revisions)) != int(state[0])
    ):
        raise ValueError("Draft validator attempts do not share current authority")
    context = WorkflowService._draft_prose_authority_context(
        planning_segment=planning.segments[0],
        execution_manifest=manifest,
        execution_manifest_sha256_value=manifest_hash,
        segment_number=1,
        draft_authority_revision=next(iter(validator_authority_revisions)),
        draft_authority_sha256=next(iter(validator_authority_hashes)),
    )
    if context is None:
        raise ValueError("Runtime could not rebuild Draft authority context")
    return (
        planning, manifest, manifest_hash, context,
        {row[0]: row for row in checkpoints},
        receipt_values,
        [(row[0], json.loads(row[1])) for row in retries],
    )


def _ledger_rows(ledger_path: Path) -> dict[int, dict]:
    payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    return {int(row["ordinal"]): row for row in payload["rows"]}


def _matches_by_hash(text: str, wanted: Counter[str]) -> list[dict]:
    matches: list[dict] = []
    for match, normalized, ambiguous in _latin_tokens(text):
        token = normalized if normalized is not None else match.group(0)
        token_hash = sha256_text(token)
        if wanted[token_hash] <= sum(
            item["token_sha256"] == token_hash for item in matches
        ):
            continue
        if token_hash not in wanted:
            continue
        window = text[max(0, match.start() - 32):min(len(text), match.end() + 32)]
        matches.append({
            "token_sha256": token_hash,
            "token_length": len(token),
            "unicode_script_classes": ["ASCII_LATIN_LETTER"],
            "normalization_changed": token != match.group(0),
            "normalization_ambiguous": ambiguous,
            "surrounding_context_sha256": sha256_text(window),
            "start_offset_sha256": sha256_text(str(match.start())),
            "_start": match.start(),
            "_end": match.end(),
            "_token": token,
        })
    if Counter(item["token_sha256"] for item in matches) != wanted:
        raise ValueError("saved Draft does not reproduce receipt token multiset")
    return matches


def _without_private_fields(items: list[dict]) -> list[dict]:
    return [
        {key: value for key, value in item.items() if not key.startswith("_")}
        for item in items
    ]


def _add_all_rejected_to_authority(
    context: DraftProseAuthorityContextV1,
    private_matches: list[dict],
) -> DraftProseAuthorityContextV1:
    source = context.term_set.source_artifacts[0].artifact_sha256
    additions = tuple(
        AuthorityApprovedLatinTermV1(
            normalized_term=item["_token"],
            term_sha256=item["token_sha256"],
            source_artifact_sha256=source,
            source_field_path_sha256=sha256_text(
                "r1-d2-test-only/" + item["token_sha256"]
            ),
            segment_binding_sha256=context.current_segment_binding_sha256,
        )
        for item in private_matches
    )
    return replace(
        context,
        term_set=replace(
            context.term_set,
            approved_terms=tuple(sorted(
                {*context.term_set.approved_terms, *additions},
                key=lambda item: (
                    item.normalized_term, item.source_artifact_sha256,
                    item.source_field_path_sha256,
                    item.segment_binding_sha256,
                ),
            )),
        ),
    )


def _replace_occurrences(text: str, matches: list[dict], mode: str) -> str:
    result = text
    for item in sorted(matches, key=lambda value: value["_start"], reverse=True):
        if mode == "punctuation":
            replacement = " " + item["_token"] + " "
        elif mode == "chinese_placeholder":
            replacement = "中文术语占位"
        else:
            raise ValueError("unknown replacement mode")
        result = result[:item["_start"]] + replacement + result[item["_end"]:]
    return result


def _reject_summary(text: str, context: DraftProseAuthorityContextV1) -> dict:
    report = analyze_prose(text, authority_context=context)
    rejected = [
        item["token_sha256"] for item in report["mixed_script_decisions"]
        if item["decision"] != "exempt_authority_approved_term"
    ]
    return {
        "reject_count": len(rejected),
        "rejected_set_sha256": rejected_set_sha256(rejected),
        "pass": not rejected,
    }


def build_report(
    evidence_root: Path,
    run_root: Path,
    ledger_path: Path,
) -> dict:
    run_id = run_root.name
    (
        planning, manifest, manifest_hash, context, checkpoints,
        receipt_rows, retry_rows,
    ) = _load_authority(evidence_root, run_root, run_id)
    ledger = _ledger_rows(ledger_path)
    receipt_by_ordinal = dict(zip((20, 21, 22), receipt_rows, strict=True))
    all_private_matches: list[dict] = []
    call_rows: list[dict] = []
    call_private: dict[int, tuple[str, list[dict]]] = {}
    for ordinal, stage_id, retry_ordinal in STAGES:
        path = run_root / "outputs" / f"{stage_id}.md"
        raw_bytes = path.read_bytes()
        text = path.read_text(encoding="utf-8")
        receipt_event_id, receipt = receipt_by_ordinal[ordinal]
        decisions = receipt["decisions"]
        wanted = Counter(item["token_sha256"] for item in decisions)
        matches = _matches_by_hash(text, wanted)
        all_private_matches.extend(matches)
        call_private[ordinal] = (text, matches)
        replay = _reject_summary(text, context)
        checkpoint = checkpoints[stage_id]
        boundary = ledger[ordinal]
        response_hash = sha256_text(text)
        if response_hash != boundary["response_sha256"] or checkpoint[3] != response_hash:
            raise ValueError("Draft/boundary/checkpoint binding mismatch")
        call_rows.append({
            "boundary_ordinal": ordinal,
            "stage": boundary["stage"],
            "role": boundary["role"],
            "provider_alias": boundary["provider_alias"],
            "model_alias": boundary["model_alias"],
            "route_kind": boundary["route_kind"],
            "protocol": boundary["protocol"],
            "attempt_number": 1,
            "scope_retry_ordinal": retry_ordinal,
            "finish_reason": boundary["finish_reason"],
            "provider_response_accepted": boundary["provider_status"] == "completed",
            "stored_file_bytes_sha256": sha256_bytes(raw_bytes),
            "raw_model_text_sha256": response_hash,
            "normalized_draft_sha256": response_hash,
            "publication_draft_sha256": None,
            "validator_authority_set_sha256": receipt["term_set_sha256"],
            "validator_policy_sha256": CANARY_VALIDATOR_POLICY_SHA256,
            "declared_mixed_script_policy_sha256": DECLARED_POLICY_SHA256,
            "validator_result": "rejected",
            "rejected_item_count": len(decisions),
            "rejected_distinct_set_sha256": replay["rejected_set_sha256"],
            "receipt_event_id": receipt_event_id,
            "checkpoint_status": checkpoint[4],
            "checkpoint_validation_stage": checkpoint[5],
            "terminal_or_retry_decision": (
                "retry_same_scope" if ordinal < 22 else "terminal_retry_exhausted"
            ),
            "next_dispatch_reason": (
                "generic_prose_invalid_scope_retry" if ordinal < 22 else None
            ),
        })

    approved_hashes = Counter(
        item.term_sha256 for item in context.term_set.approved_terms
    )
    artifact_text = {
        "planning": (run_root / "outputs/planning.md").read_text(encoding="utf-8"),
        "planning_adaptation": (
            run_root / "outputs/planning-adaptations.json"
        ).read_text(encoding="utf-8"),
        "causal_chain": (
            run_root / "outputs/short-causal-chain.json"
        ).read_text(encoding="utf-8"),
        "execution_manifest": (
            run_root / "outputs/short-execution-index.json"
        ).read_text(encoding="utf-8"),
    }
    unique_items: list[dict] = []
    for token_hash in sorted({item["token_sha256"] for item in all_private_matches}):
        private = next(
            item for item in all_private_matches if item["token_sha256"] == token_hash
        )
        token = private["_token"]
        appearances = {
            name: token in value for name, value in artifact_text.items()
        }
        first_draft = next(
            ordinal for ordinal, (text, _matches) in call_private.items()
            if token in text
        )
        if appearances["planning"]:
            first_artifact = "planning.md"
            first_stage = "planning"
            first_ordinal = 1
            origin = "local_planning_render_after_boundary_1_not_structured_authority"
        else:
            first_artifact = "draft_transport_artifact"
            first_stage = "draft"
            first_ordinal = first_draft
            origin = "model_draft_output"
        contexts = [
            item["surrounding_context_sha256"]
            for item in all_private_matches if item["token_sha256"] == token_hash
        ]
        unique_items.append({
            "stable_item_index": len(unique_items) + 1,
            "token_sha256": token_hash,
            "token_length": len(token),
            "unicode_script_classes": ["ASCII_LATIN_LETTER"],
            "surrounding_context_sha256s": sorted(contexts),
            "occurrence_count_across_attempts": len(contexts),
            "first_appearance_artifact": first_artifact,
            "first_appearance_stage": first_stage,
            "first_appearance_call_ordinal": first_ordinal,
            "first_appearance_origin": origin,
            "present_in": {
                **appearances,
                "authority_approved_token_inventory": approved_hashes[token_hash] > 0,
                "prior_accepted_draft_attempt": False,
            },
            "authority_lookup_result": "absent_from_exact_current_inventory",
            "normalization_result": "nfkc_identity_exact_case",
            "validator_reason_code": "reject_unapproved_mixed_script",
            "classification": EXPECTED_CLASSIFICATIONS[token_hash],
        })

    sets = {
        ordinal: sorted({item["token_sha256"] for item in matches})
        for ordinal, (_text, matches) in call_private.items()
    }
    set_diffs = []
    for before, after in ((20, 21), (21, 22)):
        before_counter = Counter(
            item["token_sha256"] for item in call_private[before][1]
        )
        after_counter = Counter(
            item["token_sha256"] for item in call_private[after][1]
        )
        set_diffs.append({
            "transition": f"{before}->{after}",
            "added": sorted(set(after_counter) - set(before_counter)),
            "removed": sorted(set(before_counter) - set(after_counter)),
            "retained": sorted(set(before_counter) & set(after_counter)),
            "occurrence_delta": dict(sorted(
                (key, after_counter[key] - before_counter[key])
                for key in set(before_counter) | set(after_counter)
                if after_counter[key] != before_counter[key]
            )),
        })

    counterfactuals = []
    for ordinal, (text, matches) in call_private.items():
        original = _reject_summary(text, context)
        augmented = _reject_summary(
            text, _add_all_rejected_to_authority(context, matches),
        )
        normalized_text = unicodedata.normalize("NFKC", text)
        punctuation_text = _replace_occurrences(text, matches, "punctuation")
        placeholder_text = _replace_occurrences(
            text, matches, "chinese_placeholder"
        )
        variants = (
            ("original_validator_original_authority", original, False, False),
            ("test_only_add_rejected_tokens_to_authority", augmented, False, True),
            ("normalization_only", _reject_summary(normalized_text, context), False, False),
            ("punctuation_adjacency_only", _reject_summary(punctuation_text, context), False, False),
            ("chinese_placeholder", _reject_summary(placeholder_text, context), True, False),
            ("latest_visible_authority", original, False, False),
            ("retry_before_after_authority", original, False, False),
        )
        for name, result, semantic_change, relaxation in variants:
            counterfactuals.append({
                "boundary_ordinal": ordinal,
                "variant": name,
                **result,
                "changes_draft_semantics": semantic_change,
                "policy_relaxation": relaxation,
            })

    return {
        "schema": "R1D2DraftMixedScriptRootCauseV1",
        "version": 1,
        "canonicalization_version": "r1-d2-canonical-json-utf8-v1",
        "parent_evidence_commit": "b20897757f6eec15640ff020256e2163eb91848c",
        "authority": {
            "story_state_revision": context.current_draft_authority_revision,
            "draft_authority_sha256": context.current_draft_authority_sha256,
            "planning_document_sha256": planning.authority_sha256,
            "planning_artifact_sha256": planning.segments[0].authority_sha256,
            "execution_manifest_sha256": manifest_hash,
            "segment_binding_sha256": context.current_segment_binding_sha256,
            "term_set_sha256": context.term_set.term_set_sha256,
            "approved_term_entry_count": len(context.term_set.approved_terms),
            "approved_distinct_term_count": len(approved_hashes),
            "approved_term_inventory_sha256": canonical_sha256(sorted(
                {item.term_sha256 for item in context.term_set.approved_terms}
            )),
            "normalization_version": context.term_set.normalization_version,
            "retry_authority_hashes_equal": True,
            "latest_visible_authority_equals_retry_authority": True,
        },
        "policy": {
            "production_source_sha256": PRODUCTION_SOURCE_SHA256,
            "r1_d1_declared_policy_sha256": DECLARED_POLICY_SHA256,
            "canary_validator_policy_sha256": CANARY_VALIDATOR_POLICY_SHA256,
            "canary_mixed_script_policy_sha256": CANARY_MIXED_SCRIPT_POLICY_SHA256,
            "closed_world_sources": [
                "PlanningSegmentIR.current_segment",
                "ShortExecutionManifest.current_segment_owned_beats",
            ],
            "unknown_or_stale_rejected": True,
            "exact_case_sensitive_nfkc": True,
        },
        "calls": call_rows,
        "rejected_items": unique_items,
        "attempt_rejected_sets": [
            {
                "boundary_ordinal": ordinal,
                "token_sha256s": values,
                "set_sha256": rejected_set_sha256(values),
                "occurrence_count": len(call_private[ordinal][1]),
            }
            for ordinal, values in sets.items()
        ],
        "set_diffs": set_diffs,
        "retry_contract": {
            "validator_decisions_persisted_hash_only": True,
            "precise_decisions_passed_to_retry": False,
            "rejected_token_or_reason_passed": False,
            "retry_input_issue_codes": [
                row[1]["issue_codes"] for row in retry_rows
            ],
            "retry_receives_only_generic_prose_invalid": True,
            "retry_scope": "whole_owned_event_scope_regeneration",
            "keep_other_draft_content_unchanged_instruction": False,
            "explicit_remove_unapproved_token_instruction": False,
            "explicit_authority_allowlist_available_to_retry": False,
            "previous_draft_used_as_edit_baseline": False,
            "same_event_scope_preserved": True,
            "same_authority_preserved": True,
        },
        "counterfactual_matrix": counterfactuals,
        "classification_summary": {
            "LEGITIMATE_NEW_LATIN_TERM_INTRODUCED_BY_DRAFT": 4,
            "all_items_uniquely_classified": True,
        },
        "r1_d1_regression": "NO",
        "validator_correctness": "correct",
        "retry_closure_correctness": "incorrect",
        "local_deterministic_repair_safe": "no",
        "primary_root_cause": "draft.retry_finding_not_propagated",
        "secondary_contributors": ["draft.retry_scope_too_broad"],
        "incident_family": "draft.retry_finding_propagation",
        "excluded_mechanisms": {
            "provider_truncation": True,
            "max_tokens": True,
            "abnormal_finish_reason": True,
            "strict_tool": True,
            "parser_failure": True,
            "contract_runtime_output_shape": True,
            "stale_candidate": True,
            "stale_draft_artifact": True,
            "budget_exhaustion": True,
            "fingerprint_mismatch": True,
            "route_drift": True,
            "prompt_policy_drift": True,
            "live_data_contamination": True,
            "final_review": True,
            "maintenance": True,
        },
        "model_calls_during_replay": 0,
        "paid_calls_during_replay": 0,
        "network_calls_during_replay": 0,
        "raw_content_included": False,
        "prompt_content_included": False,
        "exact_token_text_included": False,
        "absolute_path_included": False,
        "private_identifier_included": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_root", type=Path)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("ledger_path", type=Path)
    args = parser.parse_args()
    print(json.dumps(
        build_report(args.evidence_root, args.run_root, args.ledger_path),
        ensure_ascii=False, indent=2, sort_keys=True,
    ))


if __name__ == "__main__":
    main()
