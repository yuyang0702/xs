from novel_flywheel.recovery_engine import (
    FailureClass,
    RecoveryAction,
    RecoveryCandidate,
    RecoveryController,
    RecoveryIssue,
    ReliabilityFailure,
    ValidationStage,
    compare_recovery_candidates,
)


def test_candidate_requires_issue_reduction_without_quality_or_scope_regression() -> None:
    previous = RecoveryCandidate(
        frozenset({"identity", "promise"}),
        scope_hashes={"segment-1": "a", "segment-2": "b"},
        quality={"detail": 0.8, "voice": 0.9},
    )
    candidate = RecoveryCandidate(
        frozenset({"promise"}),
        scope_hashes={"segment-1": "c", "segment-2": "b"},
        quality={"detail": 0.8, "voice": 0.9},
    )

    decision = compare_recovery_candidates(
        previous, candidate, changed_scopes={"segment-1"},
    )

    assert decision.accepted is True
    assert decision.resolved_issue_keys == ("identity",)


def test_candidate_cannot_delete_prose_quality_to_pass_semantics() -> None:
    previous = RecoveryCandidate(
        frozenset({"identity"}), quality={"detail": 0.8, "voice": 0.9},
    )
    candidate = RecoveryCandidate(
        frozenset(), quality={"detail": 0.4, "voice": 0.9},
    )

    decision = compare_recovery_candidates(previous, candidate)

    assert decision.accepted is False
    assert decision.reason == "quality_regression"
    assert decision.quality_regressions == ("detail",)


def test_candidate_cannot_modify_an_unowned_scope() -> None:
    previous = RecoveryCandidate(
        frozenset({"identity"}), scope_hashes={"one": "a", "two": "b"},
    )
    candidate = RecoveryCandidate(
        frozenset(), scope_hashes={"one": "c", "two": "changed"},
    )

    decision = compare_recovery_candidates(
        previous, candidate, changed_scopes={"one"},
    )

    assert decision.accepted is False
    assert decision.reason == "unowned_scope_changed"
    assert decision.changed_unowned_scopes == ("two",)


def test_typed_recovery_ladder_separates_protocol_semantics_and_transport() -> None:
    controller = RecoveryController()

    protocol = ReliabilityFailure(
        "receipt_schema", FailureClass.SYNTAX_PROTOCOL, "planning-review",
        unit_id="segment-5", protocol_only=True,
    )
    semantic = ReliabilityFailure(
        "knowledge_regression", FailureClass.SEMANTIC_INVARIANT, "planning",
        unit_id="segment-5",
    )
    transport = ReliabilityFailure(
        "connection_reset", FailureClass.TRANSPORT, "planning",
        unit_id="segment-5",
    )

    assert controller.next_action(protocol) == RecoveryAction.LOCAL_NORMALIZE
    assert controller.next_action(protocol) == RecoveryAction.RECEIPT_ONLY_RETRY
    assert controller.next_action(semantic) == RecoveryAction.PATCH_SMALLEST_UNIT
    assert controller.next_action(transport) == RecoveryAction.RETRY_SAME_ROUTE


def test_strict_progress_refreshes_only_the_remaining_unit_budget() -> None:
    controller = RecoveryController()
    failure_a = ReliabilityFailure(
        "drift", FailureClass.SEMANTIC_INVARIANT, "draft", unit_id="a",
    )
    failure_b = ReliabilityFailure(
        "drift", FailureClass.SEMANTIC_INVARIANT, "draft", unit_id="b",
    )
    assert controller.next_action(failure_a) == RecoveryAction.PATCH_SMALLEST_UNIT
    assert controller.next_action(failure_a) == RecoveryAction.REBUILD_COMPLETE_UNIT
    assert controller.next_action(failure_b) == RecoveryAction.PATCH_SMALLEST_UNIT

    controller.record_progress("a")

    assert controller.next_action(failure_a) == RecoveryAction.PATCH_SMALLEST_UNIT
    assert controller.next_action(failure_b) == RecoveryAction.REBUILD_COMPLETE_UNIT


def test_later_schema_regression_reenters_the_unified_recovery_loop() -> None:
    controller = RecoveryController()
    semantic = ReliabilityFailure(
        "identity", FailureClass.SEMANTIC_INVARIANT, "polish", unit_id="segment-3",
    )
    schema = ReliabilityFailure(
        "receipt_schema", FailureClass.SYNTAX_PROTOCOL, "polish", unit_id="segment-3",
        protocol_only=True,
    )

    assert controller.next_action(semantic) == RecoveryAction.PATCH_SMALLEST_UNIT
    assert controller.next_action(schema) == RecoveryAction.LOCAL_NORMALIZE
    assert controller.next_action(schema) == RecoveryAction.RECEIPT_ONLY_RETRY
    controller.record_progress("segment-3")
    assert controller.next_action(semantic) == RecoveryAction.PATCH_SMALLEST_UNIT


def test_earlier_stage_progress_may_reveal_later_existing_issues() -> None:
    previous = RecoveryCandidate(
        frozenset({"missing-fields"}),
        issues=(RecoveryIssue(
            "missing-fields", ValidationStage.SYNTAX, unit_id="segment-1",
        ),),
    )
    candidate = RecoveryCandidate(
        frozenset({"event-a", "event-b"}),
        issues=(
            RecoveryIssue(
                "event-a", ValidationStage.OWNERSHIP, unit_id="segment-1",
            ),
            RecoveryIssue(
                "event-b", ValidationStage.OWNERSHIP, unit_id="segment-1",
            ),
        ),
    )

    decision = compare_recovery_candidates(previous, candidate)

    assert decision.accepted is True
    assert decision.reason == "stage_progress_revealed_later_issue"
    assert decision.introduced_issue_keys == ()
    assert decision.revealed_issue_keys == ("event-a", "event-b")
    assert decision.previous_stage == "syntax"
    assert decision.candidate_stage == "ownership"


def test_same_or_earlier_stage_regression_is_not_revealed_progress() -> None:
    previous = RecoveryCandidate(
        frozenset({"event-a"}),
        issues=(RecoveryIssue("event-a", ValidationStage.OWNERSHIP),),
    )
    candidate = RecoveryCandidate(
        frozenset({"syntax-new"}),
        issues=(RecoveryIssue("syntax-new", ValidationStage.SYNTAX),),
    )

    decision = compare_recovery_candidates(previous, candidate)

    assert decision.accepted is False
    assert decision.reason == "introduced_hard_issue"
    assert decision.introduced_issue_keys == ("syntax-new",)
