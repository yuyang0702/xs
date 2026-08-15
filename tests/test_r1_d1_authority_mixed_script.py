from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from novel_flywheel import prose_quality


REQUIRED_API = (
    "AUTHORITY_LATIN_NORMALIZATION_VERSION",
    "AuthorityApprovedLatinTermSetV1",
    "AuthorityTermProjectionFieldV1",
    "AuthorityTermSourceArtifactV1",
    "DraftProseAuthorityContextV1",
    "build_authority_approved_latin_term_set",
)
IMPLEMENTED = all(hasattr(prose_quality, name) for name in REQUIRED_API)
requires_r1_d1 = pytest.mark.skipif(
    not IMPLEMENTED,
    reason="R1-D1A characterization precedes the narrow implementation",
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _context(
    *terms: str,
    segment_binding: str | None = None,
    revision: int = 7,
    authority_sha256: str | None = None,
):
    source_hash = _sha("planning-segment-authority")
    segment_binding = segment_binding or _sha("segment-01")
    authority_sha256 = authority_sha256 or _sha("draft-authority")
    source = prose_quality.AuthorityTermSourceArtifactV1(
        artifact_kind="planning_segment_ir",
        artifact_sha256=source_hash,
        contract="PlanningSegmentIR",
        version=1,
        authority_status="accepted_current",
    )
    fields = tuple(
        prose_quality.AuthorityTermProjectionFieldV1(
            source_artifact_sha256=source_hash,
            field_path=f"segments/1/event_body/{_sha(term)[:16]}",
            value=f"权威字段包含{term}并要求原样保留",
            segment_binding_sha256=segment_binding,
        )
        for index, term in enumerate(terms)
    )
    term_set = prose_quality.build_authority_approved_latin_term_set(
        draft_authority_revision=revision,
        draft_authority_sha256=authority_sha256,
        segment_binding_sha256=segment_binding,
        source_artifacts=(source,),
        fields=fields,
    )
    return prose_quality.DraftProseAuthorityContextV1(
        term_set=term_set,
        current_draft_authority_revision=revision,
        current_draft_authority_sha256=authority_sha256,
        current_segment_binding_sha256=segment_binding,
        current_source_artifact_sha256s=(source_hash,),
    )


def _blocking(text: str, context=None) -> list[str]:
    return [
        str(item["code"])
        for item in prose_quality.analyze_prose(
            text, authority_context=context,
        )["findings"]
        if item["blocking"]
    ]


def test_authority_term_contract_is_available_in_r1_d1b() -> None:
    assert IMPLEMENTED


def test_pre_fix_characterization_rejects_sanitized_approved_shape() -> None:
    assert [
        item["code"]
        for item in prose_quality.analyze_prose(
            "她核对了SignalKey记录，确认编号仍然一致。"
        )["findings"]
        if item["blocking"]
    ] == ["mixed_script_corruption"]


@requires_r1_d1
@pytest.mark.parametrize(
    ("approved", "text"),
    [
        ("SignalKey", "她核对了SignalKey记录。"),
        ("SignalKey", "档案SignalKey仍在。"),
        ("SignalKey", "她核对“SignalKey”记录。"),
        ("AIX", "系统AIX仍在线。"),
        ("Node7", "节点Node7已锁定。"),
        ("GPT-5", "调用GPT-5接口。"),
        ("API-v2.1", "协议API-v2.1版本已启用。"),
        ("SignalKey", "SignalKey记录与SignalKey日志一致。"),
    ],
)
def test_authority_approved_exact_terms_are_accepted(
    approved: str, text: str,
) -> None:
    assert _blocking(text, _context(approved)) == []


@requires_r1_d1
def test_multiple_terms_and_duplicate_provenance_are_deterministic() -> None:
    first = _context("SignalKey", "Node7", "SignalKey")
    second = _context("Node7", "SignalKey")

    assert _blocking("节点Node7引用SignalKey记录。", first) == []
    assert first.term_set.term_set_sha256 == second.term_set.term_set_sha256
    assert len(first.term_set.approved_terms) == 2


@requires_r1_d1
@pytest.mark.parametrize(
    ("approved", "text"),
    [
        ("AI", "系统AIX仍在线。"),
        ("AI", "系统AIabc仍在线。"),
        ("AI", "系统XAI仍在线。"),
        ("GPT", "调用GPTgarbage接口。"),
        ("GPT-5", "调用GPT-5-malformed-extra接口。"),
        ("SignalKey", "系统RandomNoise输出异常。"),
        ("SignalKey", "系统aaaaaaaa输出异常。"),
    ],
)
def test_substrings_extensions_and_unapproved_tokens_remain_rejected(
    approved: str, text: str,
) -> None:
    assert _blocking(text, _context(approved)) == ["mixed_script_corruption"]


@requires_r1_d1
def test_wrong_segment_stale_authority_and_missing_provenance_fail_closed() -> None:
    current = _context("SignalKey")
    wrong_segment = replace(
        current,
        current_segment_binding_sha256=_sha("segment-02"),
    )
    stale_authority = replace(
        current,
        current_draft_authority_sha256=_sha("new-draft-authority"),
    )
    missing_source = replace(
        current,
        current_source_artifact_sha256s=(_sha("other-source"),),
    )
    for context in (wrong_segment, stale_authority, missing_source):
        assert _blocking("她核对了SignalKey记录。", context) == [
            "mixed_script_corruption"
        ]


@requires_r1_d1
def test_unknown_normalization_fails_closed() -> None:
    current = _context("SignalKey")
    unknown = replace(
        current,
        term_set=replace(current.term_set, normalization_version="unknown-v9"),
    )

    assert _blocking("她核对了SignalKey记录。", unknown) == [
        "mixed_script_corruption"
    ]


@requires_r1_d1
def test_nfkc_width_normalization_is_exact_and_case_sensitive() -> None:
    context = _context("ＳｉｇｎａｌＫｅｙ")

    assert _blocking("她核对了SignalKey记录。", context) == []
    assert _blocking("她核对了signalkey记录。", context) == [
        "mixed_script_corruption"
    ]


@requires_r1_d1
def test_removing_term_restores_original_rejection() -> None:
    allowed = _context("SignalKey")
    removed = _context()

    assert _blocking("她核对了SignalKey记录。", allowed) == []
    assert _blocking("她核对了SignalKey记录。", removed) == [
        "mixed_script_corruption"
    ]


@requires_r1_d1
def test_non_mixed_script_prose_validators_remain_blocking() -> None:
    context = _context("SignalKey")
    report = prose_quality.analyze_prose(
        "她核对了SignalKey记录。\ufffd\x00", authority_context=context,
    )
    codes = {item["code"] for item in report["findings"] if item["blocking"]}

    assert "mixed_script_corruption" not in codes
    assert "unicode_replacement_character" in codes
    assert "invalid_control_character" in codes


@requires_r1_d1
def test_receipt_is_hash_only_and_explains_allow_and_reject_decisions() -> None:
    context = _context("SignalKey")
    allowed = prose_quality.analyze_prose(
        "她核对了SignalKey记录。", authority_context=context,
    )
    rejected = prose_quality.analyze_prose(
        "她核对了RandomNoise记录。", authority_context=context,
    )

    assert allowed["mixed_script_decisions"][0]["decision"] == (
        "exempt_authority_approved_term"
    )
    assert rejected["mixed_script_decisions"][0]["decision"] == (
        "reject_unapproved_mixed_script"
    )
    serialized = repr(
        allowed["mixed_script_decisions"] + rejected["mixed_script_decisions"]
    )
    assert "SignalKey" not in serialized
    assert "RandomNoise" not in serialized


@requires_r1_d1
def test_receipt_explains_stale_and_ambiguous_rejections_hash_only() -> None:
    current = _context("SignalKey")
    stale = replace(
        current,
        current_draft_authority_sha256=_sha("advanced-authority"),
    )
    stale_report = prose_quality.analyze_prose(
        "她核对了SignalKey记录。", authority_context=stale,
    )
    ambiguous_report = prose_quality.analyze_prose(
        "她核对了SignalKey—extra记录。", authority_context=current,
    )

    assert stale_report["mixed_script_decisions"][0]["decision"] == (
        "reject_stale_authority"
    )
    assert {
        item["decision"] for item in ambiguous_report["mixed_script_decisions"]
    } == {"reject_ambiguous_term"}
    serialized = repr(
        stale_report["mixed_script_decisions"]
        + ambiguous_report["mixed_script_decisions"]
    )
    assert "SignalKey" not in serialized
    assert "extra" not in serialized


@requires_r1_d1
def test_term_set_diagnostic_projection_never_contains_term_text() -> None:
    context = _context("SignalKey", "Node7")

    diagnostic = context.term_set.diagnostic_payload()
    serialized = repr(diagnostic)

    assert diagnostic["schema"] == "AuthorityApprovedLatinTermSetV1"
    assert diagnostic["normalization_version"] == (
        prose_quality.AUTHORITY_LATIN_NORMALIZATION_VERSION
    )
    assert diagnostic["term_set_sha256"] == context.term_set.term_set_sha256
    assert "SignalKey" not in serialized
    assert "Node7" not in serialized


@requires_r1_d1
def test_term_set_hash_changes_with_authority_revision_not_input_order() -> None:
    first = _context("SignalKey", "Node7", revision=7)
    reordered = _context("Node7", "SignalKey", revision=7)
    advanced = _context("SignalKey", "Node7", revision=8)

    assert first.term_set.term_set_sha256 == reordered.term_set.term_set_sha256
    assert first.term_set.term_set_sha256 != advanced.term_set.term_set_sha256


@requires_r1_d1
def test_default_non_draft_report_shape_is_unchanged() -> None:
    report = prose_quality.analyze_prose("系统SignalKey记录异常。")

    assert "mixed_script_decisions" not in report
    assert _blocking("系统SignalKey记录异常。") == [
        "mixed_script_corruption"
    ]
    assert _blocking("系统ＳｉｇｎａｌＫｅｙ记录异常。") == []


@requires_r1_d1
def test_authority_evaluation_does_not_expand_the_legacy_candidate_set() -> None:
    context = _context("SignalKey")

    assert _blocking(
        "系统ＳｉｇｎａｌＫｅｙ记录异常。", context,
    ) == []
