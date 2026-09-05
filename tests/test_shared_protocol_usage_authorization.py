"""Offline compatibility and exact-proof binding for the successor authority."""

from __future__ import annotations

import copy

import pytest

from novel_flywheel.full_short_campaign_authorization import (
    FullShortCampaignAuthorizationError,
    FullShortSharedProtocolSafeUsageRecoveryAndSuccessorExecutionAuthorizationV1,
    SHARED_USAGE_RECOVERY_SCHEMA,
    SHARED_USAGE_RECOVERY_SOURCE_IDENTITY,
    SHARED_USAGE_RECOVERY_SOURCE_SHA256,
    canonical_json_bytes,
    render_full_short_one_round_budget_unblocked_execution_authorization_v1 as render,
    validate_full_short_one_round_budget_unblocked_execution_authorization_v1 as validate,
)
from test_full_short_campaign_authorization import KEY, _authorization


PROOF_FIELDS = (
    "authoritative_usage_semantics", "exact_replay", "request_zero_diff",
    "response_regression_matrix",
    "workload_disposition",
)


def _successor():
    authority, policy, public = _authorization()
    authority["schema"] = SHARED_USAGE_RECOVERY_SCHEMA
    authority["authorization_source"] = {
        "identity": SHARED_USAGE_RECOVERY_SOURCE_IDENTITY,
        "sha256": SHARED_USAGE_RECOVERY_SOURCE_SHA256,
    }
    authority["shared_protocol_usage_recovery"] = {
        **{
            name: {"identity": f"docs/proofs/{name}.json", "sha256": str(i) * 64}
            for i, name in enumerate(PROOF_FIELDS, 1)
        },
        "raw_capture_sha256": (
            "de1cdf7b6eefcab2fa28f6bab664aad159be87d1d4e152250a77e61974bef713"
        ),
        "probe01_disposition": "FRESH_REPLACEMENT_REQUIRED",
    }
    return authority, policy, public


def _dependencies(policy, public):
    return {
        "full_short_policy": policy, "full_short_public_bindings": public,
        "verification_keys": {"campaign-key-v1": KEY},
    }


@pytest.mark.parametrize("factory", [_authorization, _successor])
def test_old_and_successor_authority_roundtrips_are_byte_identical_and_idempotent(factory):
    authority, policy, public = factory()
    original = copy.deepcopy(authority)
    original_bytes = canonical_json_bytes(authority)
    dependencies = _dependencies(policy, public)
    for _ in range(2):
        raw = render(authority, **dependencies)
        assert raw == original_bytes
        restored = validate(raw, expected=authority, **dependencies)
        restored.pop("authorization_sha256")
        assert render(restored, **dependencies) == original_bytes
        assert restored == original
    assert authority == original


def test_successor_model_retains_nested_authority_and_exact_eight_serial_cases():
    authority, policy, public = _successor()
    model = FullShortSharedProtocolSafeUsageRecoveryAndSuccessorExecutionAuthorizationV1.model_validate(authority)
    assert render(model, **_dependencies(policy, public)) == canonical_json_bytes(authority)
    assert [case.ordinal for case in model.probe_campaign.cases] == list(range(1, 9))
    assert model.probe_campaign.blocked_shape_coverage_count == 111
    assert model.probe_campaign.sequential is True
    assert model.budgets.plan_derived_max_input_tokens == 3_071_771


@pytest.mark.parametrize("field", [*PROOF_FIELDS, "raw_capture_sha256", "probe01_disposition"])
def test_each_recovery_proof_is_required(field):
    authority, policy, public = _successor()
    del authority["shared_protocol_usage_recovery"][field]
    with pytest.raises(FullShortCampaignAuthorizationError, match="SHAPE_OR_VALUE"):
        render(authority, **_dependencies(policy, public))


@pytest.mark.parametrize("field", PROOF_FIELDS)
@pytest.mark.parametrize("part,value", [("sha256", "9" * 64), ("identity", "docs/proofs/substituted.json")])
def test_well_formed_substituted_proof_does_not_match_expected_authority(field, part, value):
    authority, policy, public = _successor()
    changed = copy.deepcopy(authority)
    changed["shared_protocol_usage_recovery"][field][part] = value
    with pytest.raises(FullShortCampaignAuthorizationError, match="EXACT_BINDING_DRIFT"):
        validate(canonical_json_bytes(changed), expected=authority, **_dependencies(policy, public))


@pytest.mark.parametrize("path,value", [
    (("authorization_source", "identity"), "FULL_SHORT_END_TO_END_ONE_ROUND_INPUT_BUDGET_UNBLOCK_EXECUTE_MASTER"),
    (("authorization_source", "sha256"), "9" * 64),
    (("shared_protocol_usage_recovery", "raw_capture_sha256"), "9" * 64),
    (("shared_protocol_usage_recovery", "probe01_disposition"), "REPLAY_PROVEN_PASS"),
    (("shared_protocol_usage_recovery", "extra"), True),
    (("probe_campaign", "sequential"), False),
    (("probe_campaign", "retry_allowed"), True),
    (("probe_campaign", "blocked_shape_coverage_count"), 110),
    (("budgets", "plan_derived_max_input_tokens"), 4_000_000),
    (("scope", "maximum_real_full_short_executions"), 2),
    (("campaign_usage", "nonces_created"), 1),
])
def test_successor_closed_proofs_source_and_inherited_constraints_reject_drift(path, value):
    authority, policy, public = _successor()
    authority[path[0]][path[1]] = value
    with pytest.raises(FullShortCampaignAuthorizationError, match="SHAPE_OR_VALUE"):
        render(authority, **_dependencies(policy, public))


@pytest.mark.parametrize("identity", ["/absolute.json", "C:/absolute.json", "../outside.json", "docs/../outside.json", "docs\\proof.json", "docs//proof.json", "docs/./proof.json"])
def test_proof_identity_requires_canonical_relative_repository_path(identity):
    authority, policy, public = _successor()
    authority["shared_protocol_usage_recovery"]["exact_replay"]["identity"] = identity
    with pytest.raises(FullShortCampaignAuthorizationError, match="SHAPE_OR_VALUE"):
        render(authority, **_dependencies(policy, public))


def test_missing_recovery_block_unknown_schema_and_bad_proof_hash_are_rejected():
    authority, policy, public = _successor()
    malformed = []
    no_proof = copy.deepcopy(authority)
    del no_proof["shared_protocol_usage_recovery"]
    malformed.append(no_proof)
    unknown_schema = copy.deepcopy(authority)
    unknown_schema["schema"] = "UnknownAuthorizationV1"
    malformed.append(unknown_schema)
    bad_hash = copy.deepcopy(authority)
    bad_hash["shared_protocol_usage_recovery"]["exact_replay"]["sha256"] = "not-a-hash"
    malformed.append(bad_hash)
    for changed in malformed:
        with pytest.raises(FullShortCampaignAuthorizationError, match="SHAPE_OR_VALUE"):
            render(changed, **_dependencies(policy, public))


def test_successor_preserves_dependency_and_nonce_reuse_checks():
    authority, policy, public = _successor()
    dependencies = _dependencies(policy, public)
    raw = render(authority, **dependencies)
    result = validate(raw, expected=authority, **dependencies)
    with pytest.raises(FullShortCampaignAuthorizationError, match="REUSE_FORBIDDEN"):
        validate(raw, expected=authority, consumed_authorization_sha256s={result["authorization_sha256"]}, **dependencies)
    wrong_public = copy.deepcopy(public)
    wrong_public["routes"][0]["model_name"] = "different-model"
    with pytest.raises(FullShortCampaignAuthorizationError):
        render(authority, **_dependencies(policy, wrong_public))
