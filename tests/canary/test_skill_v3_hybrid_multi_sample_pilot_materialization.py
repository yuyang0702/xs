from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.canary import skill_v3_character_heavy_pilot as prior
from tools.canary.skill_v3_hybrid_character_heavy_pilot import (
    HybridFakeDispatcher,
    HybridPilotLedger,
    SEQUENCE,
    _validate_dispatcher,
    fake_permission,
    fake_signed_approval,
    launch_one_sealed_hybrid_sample,
    load_sealed_pilot,
    reconstruct_sample_input,
)
from tools.canary.skill_v3_real_execution_boundary import RealPilotDispatcherV1
from tools.diagnostics.materialize_skill_v3_hybrid_multi_sample_pilot import (
    EXTERNAL_ZERO,
    LITERARY_POLICY_SHA256,
    REPORT_ROOT,
    build_materialization,
    canonical_bytes,
    sha_bytes,
)


ROOT = Path(__file__).resolve().parents[2]


def _json(name: str) -> dict:
    return json.loads((ROOT / REPORT_ROOT / name).read_text(encoding="utf-8"))


def test_materializer_is_deterministic_and_manifest_exact() -> None:
    validation = {
        "focused": {
            key: value for key, value in _json("focused-test-receipt-v1.json").items()
            if key != "schema"
        },
        "related": {
            key: value for key, value in _json("related-test-receipt-v1.json").items()
            if key != "schema"
        },
        "full": {
            key: value for key, value in _json("full-suite-receipt-v1.json").items()
            if key != "schema"
        },
        "strict_l3": {
            key: value for key, value in _json("strict-l3-receipt-v1.json").items()
            if key != "schema"
        },
    }
    expected = build_materialization(ROOT, validation)
    actual = {
        path.relative_to(ROOT / REPORT_ROOT).as_posix(): path.read_bytes()
        for path in (ROOT / REPORT_ROOT).rglob("*") if path.is_file()
    }
    assert expected == actual
    sealed = load_sealed_pilot(ROOT)
    assert sealed["manifest"]["status"] == "EXACT"
    assert len(actual) == 32


def test_fresh_ids_locks_sequence_and_experiment_binding() -> None:
    sealed = load_sealed_pilot(ROOT)
    rows = sealed["samples"]
    assert tuple(row["SAMPLE_SLOT"] for row in rows) == SEQUENCE
    assert len({row["SAMPLE_ID"] for row in rows}) == 6
    assert len({row["SAMPLE_LOCK_SHA256"] for row in rows}) == 6
    old = _json_from(
        ROOT / "docs/superpowers/reports/"
        "skill-v3-character-heavy-multi-sample-pilot-approval-readiness-recheck-v1/"
        "six-sample-locks-v1.json"
    )
    assert not {row["SAMPLE_ID"] for row in rows} & {
        row["sample_id"] for row in old["locks"]
    }
    for row in rows:
        unsigned = dict(row)
        declared = unsigned.pop("SAMPLE_LOCK_SHA256")
        assert hashlib.sha256(canonical_bytes(unsigned)).hexdigest() == declared
        assert row["EXPERIMENT_LOCK_SHA256"] == sealed["experiment"][
            "EXPERIMENT_LOCK_SHA256"
        ]


def _json_from(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_arm_pair_and_reference_identity() -> None:
    arms = _json("arm-identities-v1.json")
    pairs = _json("matched-pair-identity-v1.json")
    primary = _json("primary-changed-variable-v1.json")
    assert arms["TREATMENT_BASELINE_PREFIX_SHA"] == arms["CONTROL_ARM"][
        "skill_context_sha256"
    ]
    assert arms["SUPPLEMENT_REPLACES_BASELINE"] == "NO"
    assert arms["REFERENCE_GUIDANCE_IDENTICAL_ACROSS_ARMS"] == "YES"
    assert primary["PRIMARY_CHANGED_VARIABLE"] == "SKILL_CONTEXT_TREATMENT_LAYER_ONLY"
    assert primary["UNCONTROLLED_VARIABLE_COUNT"] == 0
    assert len(pairs["pairs"]) == 3
    for row in pairs["pairs"]:
        assert row["NON_SKILL_MODEL_VISIBLE_BYTES_IDENTICAL"] == "YES"
        assert row["ONLY_SKILL_CONTEXT_TREATMENT_LAYER_DIFFERS"] == "YES"
        assert row["UNCONTROLLED_VARIABLE_COUNT"] == 0
        assert row["CONTROL_WIRE_INPUT_SHA256"] != row["HYBRID_WIRE_INPUT_SHA256"]


def test_reconstructed_inputs_match_all_hashes_and_capacity() -> None:
    sealed = load_sealed_pilot(ROOT)
    controls = []
    treatments = []
    for row in sealed["samples"]:
        value = reconstruct_sample_input(ROOT, row["SAMPLE_ID"])
        assert value.wire_input_sha256 == row["WIRE_INPUT_SHA256"]
        assert value.model_input_component_binding_sha256 == row[
            "MODEL_INPUT_COMPONENT_SHA256"
        ]
        assert value.advisory_truncation_occurred is False
        assert value.advisory_shedding_occurred is False
        assert row["ESTIMATED_INPUT_TOKENS"] + row["OUTPUT_CAP"] <= row[
            "SAFE_CONTEXT_WINDOW_TOKEN_CAP"
        ]
        (controls if row["ARM"] == "CONTROL" else treatments).append(value)
    assert len({value.wire_input_sha256 for value in controls}) == 1
    assert len({value.wire_input_sha256 for value in treatments}) == 1
    assert controls[0].wire_input_sha256 != treatments[0].wire_input_sha256


def test_route_destination_egress_output_and_request_caps() -> None:
    route = _json("provider-model-route-binding-v1.json")
    destination = _json("destination-binding-v1.json")
    egress = _json("egress-policy-v1.json")
    output = _json("output-cap-v1.json")
    budget = _json("budget-policy-v1.json")
    assert route["status"] == "EXACT_OFFLINE"
    assert destination["DESTINATION_ORIGIN"] == "https://lingsuan.org"
    assert destination["DESTINATION_PATH"] == "/v1/messages"
    assert destination["OPERATOR_CLASSIFICATION"] == "THIRD_PARTY_RELAY_LOCAL_METADATA_ONLY"
    assert len({row["EGRESS_POLICY_SHA256"] for row in egress["sample_policies"]}) == 6
    assert all(value == "NO" for key, value in egress.items() if key.endswith("_EGRESS"))
    assert output["PER_SAMPLE_OUTPUT_TOKEN_HARD_CAP"] == 4624
    assert output["TOTAL_SIX_SAMPLE_OUTPUT_TOKEN_HARD_CAP"] == 27744
    assert output["OUTPUT_CAP_IDENTICAL_ACROSS_6"] == "YES"
    assert budget["TOTAL_PROVIDER_REQUEST_HARD_CAP"] == 6
    assert budget["TOTAL_NETWORK_ATTEMPT_HARD_CAP"] == 6
    assert budget["MONETARY_COST_CAP"] == "UNKNOWN_NOT_SEALED"
    assert all(budget[key] == "NO" for key in (
        "RETRY", "TRANSPORT_RETRY", "FALLBACK", "ROUTE_SWITCH",
        "RESUME_DISPATCH", "SECOND_DISPATCH", "ALTERNATE_DESTINATION",
        "CROSS_ORIGIN_REDIRECT", "AUTO_REPLACEMENT_SAMPLE",
    ))


def test_methodology_blind_policy_stop_loss_and_contamination() -> None:
    methodology = _json("methodology-binding-v1.json")
    blind = _json("blind-bundle-policy-v1.json")
    stop_loss = _json("stop-loss-policy-v1.json")
    contamination = _json("cross-sample-contamination-v1.json")
    assert methodology["LITERARY_POLICY_SHA256"] == LITERARY_POLICY_SHA256
    assert methodology["REQUIRED_BLIND_EVALUATOR_COUNT"] == 2
    assert methodology["REQUIRED_EVALUATOR_BY_BATCH_VOTES"] == 6
    assert blind["MAPPING_HIDDEN_UNTIL_BLIND_FREEZE"] == "YES"
    assert blind["REQUIRED_VOTE_SET_COMPLETE_BEFORE_REVEAL"] == "YES"
    assert stop_loss["on_trigger"] == "HYBRID_AS_QUALITY_ENHANCEMENT_DOES_NOT_AUTO_ITERATE"
    assert contamination["CROSS_SAMPLE_CONTAMINATION"] == 0
    assert contamination["NO_OUTPUT_FEEDBACK_LOOP"] == "YES"


def test_approval_packet_and_authorization_plaintext_are_inert_and_deterministic() -> None:
    packet = _json("approval-readiness-packet-v1.json")
    nonce = _json("jit-approval-nonce-policy-v1.json")
    text = (ROOT / REPORT_ROOT / "campaign-authorization-plaintext-v1.txt").read_bytes()
    report = (ROOT / REPORT_ROOT / "final-report-v1.md").read_text(encoding="utf-8")
    assert packet["EXECUTION_AUTHORIZED"] is False
    assert packet["NAMED_APPROVER"] is None
    assert packet["USER_AUTHORIZATION_PRESENT"] == "NO"
    assert packet["SIGNED_APPROVAL_CREATED"] == "NO"
    assert packet["REAL_NONCE_CREATED"] == "NO"
    assert nonce["PRECREATE_LATER_SAMPLE_APPROVALS"] == "NO"
    assert nonce["PRECREATE_LATER_NONCES"] == "NO"
    assert sha_bytes(text) in report
    assert b"This text is an authorization template only" in text
    assert b"max 6 paid requests" not in text  # exact prose is long-form, not a token shortcut
    assert all(packet[key] == 0 for key in EXTERNAL_ZERO)


def test_real_dispatcher_accepts_sealed_hybrid_cap_without_external_action(tmp_path: Path) -> None:
    sealed = load_sealed_pilot(ROOT)
    first = sealed["samples"][0]
    dispatcher = RealPilotDispatcherV1(
        repo_root=ROOT,
        route_database=ROOT / "data/app.db",
        execution_root=tmp_path / "never-dispatched",
        expected_sampling_policy_sha256=first["SAMPLING_FINGERPRINT"],
        expected_output_cap=first["OUTPUT_CAP"],
    )
    model_input = reconstruct_sample_input(ROOT, first["SAMPLE_ID"])
    _validate_dispatcher(dispatcher, model_input)
    assert dispatcher.output_cap == 4624
    assert dispatcher.credential_lookup_count == 0
    assert dispatcher.provider_client_creation_count == 0
    assert not (tmp_path / "never-dispatched").exists()


@pytest.mark.asyncio
async def test_offline_fake_six_sample_jit_nonce_and_one_shot(tmp_path: Path) -> None:
    sealed = load_sealed_pilot(ROOT)
    ledger = HybridPilotLedger()
    nonce_store = prior.FakeNonceStore()
    for row in sealed["samples"]:
        result = await launch_one_sealed_hybrid_sample(
            repo_root=ROOT,
            pilot_id=sealed["identity"]["PILOT_ID"],
            sample_id=row["SAMPLE_ID"],
            expected_sample_lock_sha256=row["SAMPLE_LOCK_SHA256"],
            expected_experiment_lock_sha256=row["EXPERIMENT_LOCK_SHA256"],
            permission=fake_permission(row, sealed["identity"]["PILOT_ID"]),
            signed_approval=fake_signed_approval(row, sealed["identity"]["PILOT_ID"]),
            nonce_store=nonce_store,
            ledger=ledger,
            dispatcher=HybridFakeDispatcher(ROOT),
            output_root=tmp_path / row["SAMPLE_SLOT"],
            offline_fake=True,
        )
        assert result["status"] == "SEALED_VALID"
        assert result["attempts"] == {
            "logical_model_call_count": 1,
            "provider_dispatch_attempt_count": 1,
            "http_post_attempt_count": 1,
            "network_request_attempt_count": 1,
        }
        assert result["real_boundary_reached"] == 0
    assert nonce_store.reservation_count == 6
    assert len(ledger.sample_states) == 6


@pytest.mark.asyncio
async def test_first_failure_stops_campaign_and_no_second_dispatch(tmp_path: Path) -> None:
    sealed = load_sealed_pilot(ROOT)
    first, second = sealed["samples"][:2]
    ledger = HybridPilotLedger()
    nonce_store = prior.FakeNonceStore()
    with pytest.raises(prior.PilotBoundaryError, match="PROVIDER_BOUNDARY_FAILED"):
        await launch_one_sealed_hybrid_sample(
            repo_root=ROOT,
            pilot_id=sealed["identity"]["PILOT_ID"],
            sample_id=first["SAMPLE_ID"],
            expected_sample_lock_sha256=first["SAMPLE_LOCK_SHA256"],
            expected_experiment_lock_sha256=first["EXPERIMENT_LOCK_SHA256"],
            permission=fake_permission(first, sealed["identity"]["PILOT_ID"]),
            signed_approval=fake_signed_approval(first, sealed["identity"]["PILOT_ID"]),
            nonce_store=nonce_store,
            ledger=ledger,
            dispatcher=HybridFakeDispatcher(ROOT, "TIMEOUT"),
            output_root=tmp_path / "failed",
            offline_fake=True,
        )
    assert ledger.stop_condition_fired is True
    with pytest.raises(prior.PilotBoundaryError, match="STOP_CONDITION_ALREADY_FIRED"):
        await launch_one_sealed_hybrid_sample(
            repo_root=ROOT,
            pilot_id=sealed["identity"]["PILOT_ID"],
            sample_id=second["SAMPLE_ID"],
            expected_sample_lock_sha256=second["SAMPLE_LOCK_SHA256"],
            expected_experiment_lock_sha256=second["EXPERIMENT_LOCK_SHA256"],
            permission=fake_permission(second, sealed["identity"]["PILOT_ID"]),
            signed_approval=fake_signed_approval(second, sealed["identity"]["PILOT_ID"]),
            nonce_store=nonce_store,
            ledger=ledger,
            dispatcher=HybridFakeDispatcher(ROOT),
            output_root=tmp_path / "must-not-run",
            offline_fake=True,
        )
