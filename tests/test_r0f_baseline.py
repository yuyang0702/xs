from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

from novel_flywheel.db import Database
from r0f_baseline_harness import (
    business_run_projection,
    canonical_protected_source_manifest,
    load_baseline,
    ptr12_bounded_capture_protected_source_manifest,
)


REPOSITORY = Path(__file__).resolve().parents[1]
BASELINE = (
    Path(__file__).parent
    / "fixtures" / "reliability" / "r0f" / "r0f-baseline-v1.json"
)
R1_PA1_SUCCESSOR = (
    Path(__file__).parent
    / "fixtures" / "reliability" / "r0f"
    / "r1-pa1-authorized-protected-source-successor-v1.json"
)
R1_D1_SUCCESSOR = (
    Path(__file__).parent
    / "fixtures" / "reliability" / "r0f"
    / "r1-d1-authorized-protected-source-successor-v1.json"
)
R1_D3_SUCCESSOR = (
    Path(__file__).parent
    / "fixtures" / "reliability" / "r0f"
    / "r1-d3-authorized-protected-source-successor-v1.json"
)
R1_PTR1_SUCCESSOR = (
    Path(__file__).parent
    / "fixtures" / "reliability" / "r0f"
    / "r1-ptr1-authorized-protected-source-successor-v1.json"
)
R1_PTR3_SUCCESSOR = (
    Path(__file__).parent
    / "fixtures" / "reliability" / "r0f"
    / "r1-ptr3-authorized-protected-source-successor-v1.json"
)
R1_PTR9_SUCCESSOR = (
    Path(__file__).parent
    / "fixtures" / "reliability" / "r0f"
    / "r1-ptr9-authorized-protected-source-successor-v1.json"
)
R1_PTR12_OBSERVER_SUCCESSOR = (
    Path(__file__).parent
    / "fixtures" / "reliability" / "r0f"
    / "r1-ptr12-observer-authorized-protected-source-successor-v1.json"
)
R1_PTR12_BOUNDED_CAPTURE_SUCCESSOR = (
    Path(__file__).parent
    / "fixtures" / "reliability" / "r0f"
    / "r1-ptr12-bounded-capture-authorized-protected-source-successor-v1.json"
)
R1_PTR12_NESTED_TAIL_SUCCESSOR = (
    Path(__file__).parent
    / "fixtures" / "reliability" / "r0f"
    / "r1-ptr12-nested-tail-truthfulness-authorized-protected-source-successor-v1.json"
)
R1_PTR12_ANTHROPIC_CAP_SUCCESSOR = (
    Path(__file__).parent
    / "fixtures" / "reliability" / "r0f"
    / "r1-ptr12-anthropic-effective-cap-authorized-protected-source-successor-v1.json"
)
R1_PTR12_STREAM_REASONING_SUCCESSOR = (
    Path(__file__).parent
    / "fixtures" / "reliability" / "r0f"
    / "r1-ptr12-stream-reasoning-usage-authorized-protected-source-successor-v1.json"
)
R1_PTR12_DIAGNOSTIC_CONTEXT_SUCCESSOR = (
    Path(__file__).parent
    / "fixtures" / "reliability" / "r0f"
    / "r1-ptr12-diagnostic-context-fail-open-"
    "authorized-protected-source-successor-v1.json"
)
R1_PTR12_SHARED_CAPTURE_EXHAUSTION_SUCCESSOR = (
    Path(__file__).parent
    / "fixtures" / "reliability" / "r0f"
    / "r1-ptr12-shared-capture-exhaustion-propagation-"
    "authorized-protected-source-successor-v1.json"
)
R1_PTR12_OBSERVER_SCHEMA = (
    "R1PTR12ObserverAuthorizedProtectedSourceSuccessorV1"
)
R1_PTR12_OBSERVER_VERSION = 1
R1_PTR12_OBSERVER_PARENT_HEAD = (
    "a264ee200c99c6c0a5d03a7aeb398773b4d3f3f5"
)
R1_PTR12_OBSERVER_IMPLEMENTATION_HEAD = (
    "ef2eb22bfad85be5e04855bbf4464318745737ae"
)
R1_PTR12_OBSERVER_PROTECTED_TREE_SHA256 = (
    "078e4229abd9458b881a4c13a6ded71ad953b9f30297514f5e01a47037f24709"
)
R1_PTR12_BOUNDED_CAPTURE_SCHEMA = (
    "R1PTR12BoundedCaptureAuthorizedProtectedSourceSuccessorV1"
)
R1_PTR12_BOUNDED_CAPTURE_PARENT_HEAD = (
    "536204b6c503548d7045147ac015d4e465bf50ab"
)
R1_PTR12_BOUNDED_CAPTURE_IMPLEMENTATION_HEAD = (
    "3db95cd58fcdc74bd03b9a517f607b5bc765bbcd"
)
R1_PTR12_BOUNDED_CAPTURE_PROTECTED_TREE_SHA256 = (
    "573b09cafe1fd8fb0e43394610ce558007309026e3d434aa7677582116bbe08c"
)
R1_PTR12_NESTED_TAIL_SCHEMA = (
    "R1PTR12NestedTailTruthfulnessAuthorizedProtectedSourceSuccessorV1"
)
R1_PTR12_NESTED_TAIL_VERSION = 1
R1_PTR12_NESTED_TAIL_PARENT_HEAD = (
    "a1b36a42a0dfe6464159eb02097727912858478d"
)
R1_PTR12_NESTED_TAIL_IMPLEMENTATION_HEAD = (
    "ef5e79482f99a62df529234567ba83888875f1e3"
)
R1_PTR12_NESTED_TAIL_PROTECTED_TREE_SHA256 = (
    "fcf39949ad80e755d0e21883aaaa6c1a65b3f2ad8d0079701526255d3a788289"
)
R1_PTR12_ANTHROPIC_CAP_SCHEMA = (
    "R1PTR12AnthropicEffectiveCapAuthorizedProtectedSourceSuccessorV1"
)
R1_PTR12_ANTHROPIC_CAP_VERSION = 1
R1_PTR12_ANTHROPIC_CAP_PARENT_HEAD = (
    "776d5e581c50c1527064fedb987a03f77315db4a"
)
R1_PTR12_ANTHROPIC_CAP_IMPLEMENTATION_HEAD = (
    "14cc284604293fcf3f4f8340956470cdb92211c2"
)
R1_PTR12_ANTHROPIC_CAP_PROTECTED_TREE_SHA256 = (
    "671d0d918ee626cd525b2e0b2c29c254b47326bc540f8c9500fa13294e8b0025"
)
R1_PTR12_STREAM_REASONING_SCHEMA = (
    "R1PTR12StreamReasoningUsageAuthorizedProtectedSourceSuccessorV1"
)
R1_PTR12_STREAM_REASONING_VERSION = 1
R1_PTR12_STREAM_REASONING_PARENT_HEAD = (
    "93727d4d7e1223a9a4b87848b403f05e8a4b10af"
)
R1_PTR12_STREAM_REASONING_IMPLEMENTATION_HEAD = (
    "1fbc7824f9ad35bdca540ffd3d25955b2c84b766"
)
R1_PTR12_STREAM_REASONING_PROTECTED_TREE_SHA256 = (
    "f8355455accfa8291b6e274318fd27c488840080ddf880744f326deade0acfba"
)
R1_PTR12_DIAGNOSTIC_CONTEXT_SCHEMA = (
    "R1PTR12DiagnosticContextFailOpenAuthorizedProtectedSourceSuccessorV1"
)
R1_PTR12_DIAGNOSTIC_CONTEXT_VERSION = 1
R1_PTR12_DIAGNOSTIC_CONTEXT_PARENT_HEAD = (
    "ca0d7bd34bfc0e0e242a1cd9216d5416b5bfeb70"
)
R1_PTR12_DIAGNOSTIC_CONTEXT_IMPLEMENTATION_HEAD = (
    "f2f7fce1a077413c3c1fbbea9bdf1cb8d0a89bf0"
)
R1_PTR12_DIAGNOSTIC_CONTEXT_PROTECTED_TREE_SHA256 = (
    "c11f763c51eba9fc258b91e0e8b4a16fad0046380ca01fc091bb9641d6258764"
)
R1_PTR12_SHARED_CAPTURE_EXHAUSTION_SCHEMA = (
    "R1PTR12SharedCaptureExhaustionPropagation"
    "AuthorizedProtectedSourceSuccessorV1"
)
R1_PTR12_SHARED_CAPTURE_EXHAUSTION_VERSION = 1
R1_PTR12_SHARED_CAPTURE_EXHAUSTION_PARENT_HEAD = (
    "56dce5deff83d278179a29b2dd01138e92ea9189"
)
R1_PTR12_SHARED_CAPTURE_EXHAUSTION_IMPLEMENTATION_HEAD = (
    "df1e433b33434071df92764563bd0befe2aa6997"
)
R1_PTR12_SHARED_CAPTURE_EXHAUSTION_PROTECTED_TREE_SHA256 = (
    "1dffc840bd403032a0b572ed54ebc0d689bfe3db3bd45f24fc7b3b3306ba9689"
)


def _protected_tree_sha256(manifest: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _assert_r1_ptr12_successor_exact(
    successor: dict[str, Any],
) -> None:
    assert successor["schema"] == R1_PTR12_OBSERVER_SCHEMA
    assert type(successor["version"]) is int
    assert successor["version"] == R1_PTR12_OBSERVER_VERSION
    assert successor["parent_source_head"] == R1_PTR12_OBSERVER_PARENT_HEAD
    assert (
        successor["implementation_source_head"]
        == R1_PTR12_OBSERVER_IMPLEMENTATION_HEAD
    )
    assert successor["phase"] == "R1-PTR12-OBSERVER-IMPLEMENTATION"
    assert successor["business_behavior_changed"] is False
    assert successor["protected_deltas"] == {
        "business_artifacts": 0,
        "domain_validator": 0,
        "initial_prompt": 0,
        "model_call_upper_bound": 0,
        "output_budget": 0,
        "retry_fallback_attempt_limits": 0,
        "same_fingerprint_redispatch": 0,
        "route_model_identity": 0,
        "final_artifact_capability_memory": 0,
        "diagnostic_event_types": 4,
    }

    recorded_manifest = successor["current_protected_sources"]
    tree_sha256 = successor["implementation_protected_tree_sha256"]
    assert isinstance(tree_sha256, str)
    assert re.fullmatch(r"[0-9a-f]{64}", tree_sha256)
    assert tree_sha256 == R1_PTR12_OBSERVER_PROTECTED_TREE_SHA256
    assert tree_sha256 == _protected_tree_sha256(recorded_manifest)

    ptr12_hashes = {
        item["path"]: item["sha256"]
        for item in successor["current_protected_sources"]
    }
    assert all(
        item["after_sha256"] == ptr12_hashes[item["path"]]
        for item in successor["authorized_source_deltas"]
    )
    assert {
        item["path"] for item in successor["authorized_source_deltas"]
    } == {
        "src/novel_flywheel/contract_runtime.py",
        "src/novel_flywheel/generated_artifacts.py",
        "src/novel_flywheel/models.py",
        "src/novel_flywheel/workflows.py",
    }


def _tamper_ptr12_successor(
    successor: dict[str, Any],
    case: str,
) -> None:
    if case == "wrong_schema":
        successor["schema"] = (
            "R1PTR12ObserverAuthorizedProtectedSourceSuccessorV999"
        )
    elif case == "missing_schema":
        successor.pop("schema")
    elif case == "wrong_version":
        successor["version"] = 2
    elif case == "wrong_type_version":
        successor["version"] = "1"
    elif case == "boolean_version":
        successor["version"] = True
    elif case == "missing_version":
        successor.pop("version")
    elif case == "wrong_protected_tree":
        successor["implementation_protected_tree_sha256"] = "0" * 64
    elif case == "missing_protected_tree":
        successor.pop("implementation_protected_tree_sha256")
    elif case == "reordered_manifest_protected_tree":
        manifest = list(reversed(successor["current_protected_sources"]))
        successor["implementation_protected_tree_sha256"] = (
            _protected_tree_sha256(manifest)
        )
    elif case == "wrong_implementation":
        successor["implementation_source_head"] = "0" * 40
    elif case == "tampered_individual_hash":
        successor["current_protected_sources"][0]["sha256"] = "0" * 64
    else:  # pragma: no cover - test data is a closed tuple below
        raise ValueError(f"unknown tamper case: {case}")


def _assert_r1_ptr12_bounded_capture_successor_exact(
    successor: dict[str, Any],
) -> None:
    assert successor["schema"] == R1_PTR12_BOUNDED_CAPTURE_SCHEMA
    assert type(successor["version"]) is int
    assert successor["version"] == 1
    assert (
        successor["parent_source_head"]
        == R1_PTR12_BOUNDED_CAPTURE_PARENT_HEAD
    )
    assert (
        successor["implementation_source_head"]
        == R1_PTR12_BOUNDED_CAPTURE_IMPLEMENTATION_HEAD
    )
    assert successor["phase"] == (
        "R1-PTR12-BOUNDED-SINGLE-PASS-RAW-SHAPE-CAPTURE-FIX"
    )
    assert successor["business_behavior_changed"] is False
    assert successor["parent_successor"] == {
        "path": (
            "tests/fixtures/reliability/r0f/"
            "r1-ptr12-observer-authorized-protected-source-successor-v1.json"
        ),
        "sha256": (
            "d8f45ea76810ed4f2a1870f4169fa1944d4a66d9f33db367bcbc3c50dcbcf8f9"
        ),
        "protected_tree_sha256": R1_PTR12_OBSERVER_PROTECTED_TREE_SHA256,
    }
    assert successor["protected_deltas"] == {
        "business_artifacts": 0,
        "domain_validator": 0,
        "initial_prompt": 0,
        "model_call_upper_bound": 0,
        "output_budget": 0,
        "retry_fallback_attempt_limits": 0,
        "same_fingerprint_redispatch": 0,
        "route_model_identity": 0,
        "final_artifact_capability_memory": 0,
        "diagnostic_event_types": 0,
        "raw_shape_capture_max_touches": 128,
        "raw_shape_capture_max_details": 128,
        "raw_shape_capture_max_unknown_details": 32,
        "raw_shape_capture_max_hash_input_bytes": 512,
    }

    recorded_manifest = successor["current_protected_sources"]
    tree_sha256 = successor["implementation_protected_tree_sha256"]
    assert isinstance(tree_sha256, str)
    assert re.fullmatch(r"[0-9a-f]{64}", tree_sha256)
    assert tree_sha256 == R1_PTR12_BOUNDED_CAPTURE_PROTECTED_TREE_SHA256
    assert tree_sha256 == _protected_tree_sha256(recorded_manifest)
    current_paths = {
        item["path"]
        for item in ptr12_bounded_capture_protected_source_manifest(REPOSITORY)
    }
    assert {item["path"] for item in recorded_manifest} == current_paths

    authorized = successor["authorized_source_deltas"]
    assert authorized == [{
        "path": "src/novel_flywheel/provider_output.py",
        "before_sha256": (
            "d95d44ec90903ff8a06cb92cc8a491bf482d22e8e32affe94023b13ec52db559"
        ),
        "after_sha256": (
            "6623e77a8c07bebe9207c88d767bdd076ddc964ebdc04d2c07756cf4bea4002a"
        ),
    }]
    recorded_hashes = {
        item["path"]: item["sha256"] for item in recorded_manifest
    }
    assert authorized[0]["after_sha256"] == recorded_hashes[
        authorized[0]["path"]
    ]


def _tamper_ptr12_bounded_capture_successor(
    successor: dict[str, Any], case: str,
) -> None:
    if case == "wrong_schema":
        successor["schema"] = "R1PTR12BoundedCaptureSuccessorV999"
    elif case == "missing_version":
        successor.pop("version")
    elif case == "boolean_version":
        successor["version"] = True
    elif case == "wrong_parent":
        successor["parent_source_head"] = "0" * 40
    elif case == "wrong_implementation":
        successor["implementation_source_head"] = "0" * 40
    elif case == "wrong_parent_fixture":
        successor["parent_successor"]["sha256"] = "0" * 64
    elif case == "wrong_tree":
        successor["implementation_protected_tree_sha256"] = "0" * 64
    elif case == "missing_provider_output":
        successor["current_protected_sources"] = [
            item for item in successor["current_protected_sources"]
            if item["path"] != "src/novel_flywheel/provider_output.py"
        ]
    elif case == "tampered_provider_output":
        next(
            item for item in successor["current_protected_sources"]
            if item["path"] == "src/novel_flywheel/provider_output.py"
        )["sha256"] = "0" * 64
    elif case == "wrong_before_hash":
        successor["authorized_source_deltas"][0]["before_sha256"] = "0" * 64
    elif case == "wrong_after_hash":
        successor["authorized_source_deltas"][0]["after_sha256"] = "0" * 64
    else:  # pragma: no cover - test data is a closed tuple below
        raise ValueError(f"unknown tamper case: {case}")


def _assert_r1_ptr12_nested_tail_successor_exact(
    successor: dict[str, Any],
) -> None:
    assert successor["schema"] == R1_PTR12_NESTED_TAIL_SCHEMA
    assert type(successor["version"]) is int
    assert successor["version"] == R1_PTR12_NESTED_TAIL_VERSION
    assert successor["parent_source_head"] == R1_PTR12_NESTED_TAIL_PARENT_HEAD
    assert (
        successor["implementation_source_head"]
        == R1_PTR12_NESTED_TAIL_IMPLEMENTATION_HEAD
    )
    assert successor["phase"] == (
        "R1-PTR12-NESTED-TOPOLOGY-TAIL-TRUTHFULNESS-FIX"
    )
    assert successor["business_behavior_changed"] is False
    assert successor["parent_successor"] == {
        "path": (
            "tests/fixtures/reliability/r0f/"
            "r1-ptr12-bounded-capture-authorized-protected-source-successor-v1.json"
        ),
        "sha256": (
            "bf2bcad4689794dc3be7bc9c21f943102a6b965ad9357ac5c3e923a91061bcef"
        ),
        "protected_tree_sha256": (
            R1_PTR12_BOUNDED_CAPTURE_PROTECTED_TREE_SHA256
        ),
    }
    assert successor["protected_deltas"] == {
        "business_artifacts": 0,
        "domain_validator": 0,
        "initial_prompt": 0,
        "model_call_upper_bound": 0,
        "output_budget": 0,
        "retry_fallback_attempt_limits": 0,
        "same_fingerprint_redispatch": 0,
        "route_model_identity": 0,
        "final_artifact_capability_memory": 0,
        "diagnostic_event_types": 0,
        "raw_shape_capture_max_touches": 128,
        "raw_shape_capture_max_details": 128,
        "raw_shape_capture_max_unknown_details": 32,
        "raw_shape_capture_max_hash_input_bytes": 512,
        "unsafe_nested_iterator_consumption": 0,
        "false_absence_from_uninspected_tail": 0,
        "false_topology_exact_from_uninspected_nested": 0,
    }

    recorded_manifest = successor["current_protected_sources"]
    tree_sha256 = successor["implementation_protected_tree_sha256"]
    assert isinstance(tree_sha256, str)
    assert re.fullmatch(r"[0-9a-f]{64}", tree_sha256)
    assert tree_sha256 == R1_PTR12_NESTED_TAIL_PROTECTED_TREE_SHA256
    assert tree_sha256 == _protected_tree_sha256(recorded_manifest)
    current_paths = {
        item["path"]
        for item in ptr12_bounded_capture_protected_source_manifest(REPOSITORY)
    }
    assert {item["path"] for item in recorded_manifest} == current_paths

    authorized = successor["authorized_source_deltas"]
    assert authorized == [{
        "path": "src/novel_flywheel/provider_output.py",
        "before_sha256": (
            "6623e77a8c07bebe9207c88d767bdd076ddc964ebdc04d2c07756cf4bea4002a"
        ),
        "after_sha256": (
            "1d95525945120440f0ae927f347bc7ffb7361345ebb076239e97964f4d267d85"
        ),
    }]
    recorded_hashes = {
        item["path"]: item["sha256"] for item in recorded_manifest
    }
    assert authorized[0]["after_sha256"] == recorded_hashes[
        authorized[0]["path"]
    ]


def _tamper_ptr12_nested_tail_successor(
    successor: dict[str, Any], case: str,
) -> None:
    if case == "wrong_schema":
        successor["schema"] = "R1PTR12NestedTailSuccessorV999"
    elif case == "wrong_version":
        successor["version"] = 2
    elif case == "boolean_version":
        successor["version"] = True
    elif case == "wrong_implementation":
        successor["implementation_source_head"] = "0" * 40
    elif case == "wrong_protected_tree":
        successor["implementation_protected_tree_sha256"] = "0" * 64
    elif case == "single_file_hash_tamper":
        successor["current_protected_sources"][0]["sha256"] = "0" * 64
    else:  # pragma: no cover - test data is a closed tuple below
        raise ValueError(f"unknown tamper case: {case}")


def _assert_r1_ptr12_anthropic_cap_successor_exact(
    successor: dict[str, Any],
) -> None:
    assert successor["schema"] == R1_PTR12_ANTHROPIC_CAP_SCHEMA
    assert type(successor["version"]) is int
    assert successor["version"] == R1_PTR12_ANTHROPIC_CAP_VERSION
    assert successor["parent_source_head"] == R1_PTR12_ANTHROPIC_CAP_PARENT_HEAD
    assert (
        successor["implementation_source_head"]
        == R1_PTR12_ANTHROPIC_CAP_IMPLEMENTATION_HEAD
    )
    assert successor["phase"] == (
        "R1-PTR12-ANTHROPIC-EFFECTIVE-CAP-LINEAGE-FIX"
    )
    assert successor["business_behavior_changed"] is False
    assert successor["parent_successor"] == {
        "path": (
            "tests/fixtures/reliability/r0f/"
            "r1-ptr12-nested-tail-truthfulness-"
            "authorized-protected-source-successor-v1.json"
        ),
        "sha256": (
            "dd91b7ee4de110194908580f62894e5fcc6931a2ce14acbbb3a80b285f6ef517"
        ),
        "protected_tree_sha256": R1_PTR12_NESTED_TAIL_PROTECTED_TREE_SHA256,
    }
    assert successor["protected_deltas"] == {
        "business_artifacts": 0,
        "domain_validator": 0,
        "initial_prompt": 0,
        "model_call_upper_bound": 0,
        "output_budget": 0,
        "retry_fallback_attempt_limits": 0,
        "same_fingerprint_redispatch": 0,
        "route_model_identity": 0,
        "final_artifact_capability_memory": 0,
        "diagnostic_event_types": 0,
        "anthropic_default_max_tokens": 8192,
        "anthropic_request_kwargs_diff_count": 0,
        "provider_accepted_cap_inferred_from_request": False,
    }

    recorded_manifest = successor["current_protected_sources"]
    tree_sha256 = successor["implementation_protected_tree_sha256"]
    assert isinstance(tree_sha256, str)
    assert re.fullmatch(r"[0-9a-f]{64}", tree_sha256)
    assert tree_sha256 == R1_PTR12_ANTHROPIC_CAP_PROTECTED_TREE_SHA256
    assert tree_sha256 == _protected_tree_sha256(recorded_manifest)

    authorized = successor["authorized_source_deltas"]
    assert authorized == [{
        "path": "src/novel_flywheel/provider_output.py",
        "before_sha256": (
            "1d95525945120440f0ae927f347bc7ffb7361345ebb076239e97964f4d267d85"
        ),
        "after_sha256": (
            "ef0d57089245072a34fb6573079441ce87e9e0dac425bb860c5cc7331c5f03a6"
        ),
    }]
    current_hashes = {
        item["path"]: item["sha256"] for item in recorded_manifest
    }
    assert authorized[0]["after_sha256"] == current_hashes[
        authorized[0]["path"]
    ]


def _tamper_ptr12_anthropic_cap_successor(
    successor: dict[str, Any], case: str,
) -> None:
    if case == "wrong_schema":
        successor["schema"] = "R1PTR12AnthropicEffectiveCapSuccessorV999"
    elif case == "wrong_version":
        successor["version"] = 2
    elif case == "boolean_version":
        successor["version"] = True
    elif case == "wrong_implementation":
        successor["implementation_source_head"] = "0" * 40
    elif case == "wrong_protected_tree":
        successor["implementation_protected_tree_sha256"] = "0" * 64
    elif case == "single_file_hash_tamper":
        successor["current_protected_sources"][0]["sha256"] = "0" * 64
    elif case == "wrong_before_hash":
        successor["authorized_source_deltas"][0]["before_sha256"] = "0" * 64
    elif case == "wrong_after_hash":
        successor["authorized_source_deltas"][0]["after_sha256"] = "0" * 64
    else:  # pragma: no cover - test data is a closed tuple below
        raise ValueError(f"unknown tamper case: {case}")


def _assert_r1_ptr12_stream_reasoning_successor_exact(
    successor: dict[str, Any],
) -> None:
    assert successor["schema"] == R1_PTR12_STREAM_REASONING_SCHEMA
    assert type(successor["version"]) is int
    assert successor["version"] == R1_PTR12_STREAM_REASONING_VERSION
    assert successor["parent_source_head"] == R1_PTR12_STREAM_REASONING_PARENT_HEAD
    assert (
        successor["implementation_source_head"]
        == R1_PTR12_STREAM_REASONING_IMPLEMENTATION_HEAD
    )
    assert successor["phase"] == (
        "R1-PTR12-STREAM-REASONING-USAGE-LINEAGE-FIX"
    )
    assert successor["business_behavior_changed"] is False
    assert successor["parent_successor"] == {
        "path": (
            "tests/fixtures/reliability/r0f/"
            "r1-ptr12-anthropic-effective-cap-"
            "authorized-protected-source-successor-v1.json"
        ),
        "sha256": (
            "66445af55c61593b4303c7e2f23d2ceb8f1be0a727ca976bb1707060b3c56a0c"
        ),
        "protected_tree_sha256": R1_PTR12_ANTHROPIC_CAP_PROTECTED_TREE_SHA256,
    }
    assert successor["protected_deltas"] == {
        "business_artifacts": 0,
        "domain_validator": 0,
        "initial_prompt": 0,
        "model_call_upper_bound": 0,
        "output_budget": 0,
        "retry_fallback_attempt_limits": 0,
        "same_fingerprint_redispatch": 0,
        "route_model_identity": 0,
        "final_artifact_capability_memory": 0,
        "diagnostic_event_types": 0,
        "formally_exposed_stream_reasoning_usage_preserved": True,
        "reasoning_usage_inferred_from_aggregate_count": 0,
        "deepseek_reasoning_usage_inference_from_aggregate": False,
        "diagnostic_context_construction_fail_open_status": "OPEN",
    }

    recorded_manifest = successor["current_protected_sources"]
    tree_sha256 = successor["implementation_protected_tree_sha256"]
    assert isinstance(tree_sha256, str)
    assert re.fullmatch(r"[0-9a-f]{64}", tree_sha256)
    assert tree_sha256 == R1_PTR12_STREAM_REASONING_PROTECTED_TREE_SHA256
    assert tree_sha256 == _protected_tree_sha256(recorded_manifest)

    authorized = successor["authorized_source_deltas"]
    assert authorized == [{
        "path": "src/novel_flywheel/provider_output.py",
        "before_sha256": (
            "ef0d57089245072a34fb6573079441ce87e9e0dac425bb860c5cc7331c5f03a6"
        ),
        "after_sha256": (
            "0405dc32039a074e1484c82b6a94eccaf866d0372e14572be36dbf3bfb1302b7"
        ),
    }]
    current_hashes = {
        item["path"]: item["sha256"] for item in recorded_manifest
    }
    assert authorized[0]["after_sha256"] == current_hashes[
        authorized[0]["path"]
    ]


def _tamper_ptr12_stream_reasoning_successor(
    successor: dict[str, Any], case: str,
) -> None:
    if case == "wrong_schema":
        successor["schema"] = "R1PTR12StreamReasoningUsageSuccessorV999"
    elif case == "wrong_version":
        successor["version"] = 2
    elif case == "wrong_implementation":
        successor["implementation_source_head"] = "0" * 40
    elif case == "wrong_protected_tree":
        successor["implementation_protected_tree_sha256"] = "0" * 64
    elif case == "single_file_hash_tamper":
        successor["current_protected_sources"][0]["sha256"] = "0" * 64
    elif case == "wrong_before_hash":
        successor["authorized_source_deltas"][0]["before_sha256"] = "0" * 64
    elif case == "wrong_after_hash":
        successor["authorized_source_deltas"][0]["after_sha256"] = "0" * 64
    else:  # pragma: no cover - test data is a closed tuple below
        raise ValueError(f"unknown tamper case: {case}")


def _assert_r1_ptr12_diagnostic_context_successor_exact(
    successor: dict[str, Any],
) -> None:
    assert successor["schema"] == R1_PTR12_DIAGNOSTIC_CONTEXT_SCHEMA
    assert type(successor["version"]) is int
    assert successor["version"] == R1_PTR12_DIAGNOSTIC_CONTEXT_VERSION
    assert (
        successor["parent_source_head"]
        == R1_PTR12_DIAGNOSTIC_CONTEXT_PARENT_HEAD
    )
    assert (
        successor["implementation_source_head"]
        == R1_PTR12_DIAGNOSTIC_CONTEXT_IMPLEMENTATION_HEAD
    )
    assert successor["phase"] == (
        "R1-PTR12-DIAGNOSTIC-CONTEXT-CONSTRUCTION-FAIL-OPEN-FIX"
    )
    assert successor["business_behavior_changed"] is False
    assert successor["parent_successor"] == {
        "path": (
            "tests/fixtures/reliability/r0f/"
            "r1-ptr12-stream-reasoning-usage-"
            "authorized-protected-source-successor-v1.json"
        ),
        "sha256": (
            "6959d184b96a50a7eea1ea5d111c930ce3f28df11402aeb459d7a113afd018a6"
        ),
        "protected_tree_sha256": R1_PTR12_STREAM_REASONING_PROTECTED_TREE_SHA256,
    }
    assert successor["protected_deltas"] == {
        "business_artifacts": 0,
        "domain_validator": 0,
        "initial_prompt": 0,
        "model_call_upper_bound": 0,
        "output_budget": 0,
        "retry_fallback_attempt_limits": 0,
        "same_fingerprint_redispatch": 0,
        "route_model_identity": 0,
        "final_artifact_capability_memory": 0,
        "diagnostic_event_types": 0,
        "observer_context_failure_dispatch_diff": 0,
        "observer_context_failure_argument_diff_count": 0,
        "observer_context_failure_retry_count": 0,
        "observer_context_failure_fallback_count": 0,
        "diagnostic_context_construction_fail_open_status": "PASS",
    }

    recorded_manifest = successor["current_protected_sources"]
    tree_sha256 = successor["implementation_protected_tree_sha256"]
    assert isinstance(tree_sha256, str)
    assert re.fullmatch(r"[0-9a-f]{64}", tree_sha256)
    assert tree_sha256 == R1_PTR12_DIAGNOSTIC_CONTEXT_PROTECTED_TREE_SHA256
    assert tree_sha256 == _protected_tree_sha256(recorded_manifest)

    authorized = successor["authorized_source_deltas"]
    assert authorized == [{
        "path": "src/novel_flywheel/workflows.py",
        "before_sha256": (
            "34788904808fbfeb4da1c49345dd260266507917bfb200c33a868ea1209f28ba"
        ),
        "after_sha256": (
            "5e9613bd7fa332cd89c0122d4fb16b4efa2d36103a96abbf53630f12ddcfd68f"
        ),
    }]
    current_hashes = {
        item["path"]: item["sha256"] for item in recorded_manifest
    }
    assert authorized[0]["after_sha256"] == current_hashes[
        authorized[0]["path"]
    ]


def _assert_r1_ptr12_shared_capture_exhaustion_successor_exact(
    successor: dict[str, Any],
) -> None:
    assert successor["schema"] == R1_PTR12_SHARED_CAPTURE_EXHAUSTION_SCHEMA
    assert type(successor["version"]) is int
    assert successor["version"] == R1_PTR12_SHARED_CAPTURE_EXHAUSTION_VERSION
    assert (
        successor["parent_source_head"]
        == R1_PTR12_SHARED_CAPTURE_EXHAUSTION_PARENT_HEAD
    )
    assert (
        successor["implementation_source_head"]
        == R1_PTR12_SHARED_CAPTURE_EXHAUSTION_IMPLEMENTATION_HEAD
    )
    assert successor["phase"] == (
        "R1-PTR12-SHARED-CAPTURE-EXHAUSTION-PROPAGATION-FIX"
    )
    assert successor["business_behavior_changed"] is False
    assert successor["parent_successor"] == {
        "path": (
            "tests/fixtures/reliability/r0f/"
            "r1-ptr12-diagnostic-context-fail-open-"
            "authorized-protected-source-successor-v1.json"
        ),
        "sha256": (
            "4420522de8cd044306969fc1a0db19f9ddc226df3466600496d448d9422fd4b6"
        ),
        "protected_tree_sha256": (
            R1_PTR12_DIAGNOSTIC_CONTEXT_PROTECTED_TREE_SHA256
        ),
    }
    assert successor["protected_deltas"] == {
        "business_artifacts": 0,
        "domain_validator": 0,
        "initial_prompt": 0,
        "model_call_upper_bound": 0,
        "output_budget": 0,
        "retry_fallback_attempt_limits": 0,
        "same_fingerprint_redispatch": 0,
        "route_model_identity": 0,
        "final_artifact_capability_memory": 0,
        "diagnostic_event_types": 0,
        "shared_capture_budget_count": 1,
        "per_container_independent_budget_count": 0,
        "max_successful_touches": 128,
        "max_rejected_touch_calls": 1,
        "max_total_touch_calls": 129,
        "post_exhaustion_redundant_touch_calls": 0,
        "shared_capture_exhaustion_propagation_status": "PASS",
    }

    current_manifest = ptr12_bounded_capture_protected_source_manifest(
        REPOSITORY,
    )
    assert successor["current_protected_sources"] == current_manifest
    tree_sha256 = successor["implementation_protected_tree_sha256"]
    assert isinstance(tree_sha256, str)
    assert re.fullmatch(r"[0-9a-f]{64}", tree_sha256)
    assert tree_sha256 == (
        R1_PTR12_SHARED_CAPTURE_EXHAUSTION_PROTECTED_TREE_SHA256
    )
    assert tree_sha256 == _protected_tree_sha256(current_manifest)

    authorized = successor["authorized_source_deltas"]
    assert authorized == [{
        "path": "src/novel_flywheel/provider_output.py",
        "before_sha256": (
            "0405dc32039a074e1484c82b6a94eccaf866d0372e14572be36dbf3bfb1302b7"
        ),
        "after_sha256": (
            "f10b5c240f046405902988b62a95e669b4a465ea4775c8ceabdca80d9725b3ab"
        ),
    }]
    current_hashes = {
        item["path"]: item["sha256"] for item in current_manifest
    }
    assert authorized[0]["after_sha256"] == current_hashes[
        authorized[0]["path"]
    ]


def _tamper_ptr12_shared_capture_exhaustion_successor(
    successor: dict[str, Any], case: str,
) -> None:
    if case == "wrong_schema":
        successor["schema"] = "R1PTR12SharedCaptureExhaustionSuccessorV999"
    elif case == "wrong_version":
        successor["version"] = 2
    elif case == "wrong_implementation":
        successor["implementation_source_head"] = "0" * 40
    elif case == "wrong_protected_tree":
        successor["implementation_protected_tree_sha256"] = "0" * 64
    elif case == "single_file_hash_tamper":
        successor["current_protected_sources"][0]["sha256"] = "0" * 64
    elif case == "wrong_before_hash":
        successor["authorized_source_deltas"][0]["before_sha256"] = "0" * 64
    elif case == "wrong_after_hash":
        successor["authorized_source_deltas"][0]["after_sha256"] = "0" * 64
    else:  # pragma: no cover - test data is a closed tuple below
        raise ValueError(f"unknown tamper case: {case}")


def _tamper_ptr12_diagnostic_context_successor(
    successor: dict[str, Any], case: str,
) -> None:
    if case == "wrong_schema":
        successor["schema"] = "R1PTR12DiagnosticContextSuccessorV999"
    elif case == "wrong_version":
        successor["version"] = 2
    elif case == "wrong_implementation":
        successor["implementation_source_head"] = "0" * 40
    elif case == "wrong_protected_tree":
        successor["implementation_protected_tree_sha256"] = "0" * 64
    elif case == "single_file_hash_tamper":
        successor["current_protected_sources"][0]["sha256"] = "0" * 64
    elif case == "wrong_before_hash":
        successor["authorized_source_deltas"][0]["before_sha256"] = "0" * 64
    elif case == "wrong_after_hash":
        successor["authorized_source_deltas"][0]["after_sha256"] = "0" * 64
    else:  # pragma: no cover - test data is a closed tuple below
        raise ValueError(f"unknown tamper case: {case}")


def make_database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "app.db")
    db.migrate()
    db.save_project("book", "Book", "long", tmp_path / "book")
    return db


def test_r0f_baseline_is_bound_to_clean_r0e_head_and_full_suite() -> None:
    baseline = load_baseline(BASELINE)

    assert baseline["schema"] == "R0FBaselineV1"
    assert baseline["baseline_head"] == (
        "dc15a525f656344c510f973630adaf7cbc3fecf2"
    )
    assert baseline["full_suite"] == {
        "passed": 2409,
        "skipped": 1,
        "strict_xfailed": 5,
        "failed": 0,
    }
    successor = load_baseline(R1_PA1_SUCCESSOR)
    original = {item["path"]: item["sha256"] for item in baseline["protected_sources"]}
    authorized = {
        item["path"]: (item["before_sha256"], item["after_sha256"])
        for item in successor["authorized_source_deltas"]
    }
    assert all(
        before == original[path]
        for path, (before, _after) in authorized.items()
    )
    assert successor["parent_baseline_head"] == baseline["baseline_head"]
    assert successor["phase"] == "R1-PA1"
    assert successor["business_behavior_changed"] is False
    assert successor["protected_deltas"] == baseline["protected_deltas"]
    assert baseline["protected_deltas"] == {
        "model_calls": 0,
        "prompt": 0,
        "retry_fallback_sequence": 0,
        "business_artifacts": 0,
    }
    r1_d1 = load_baseline(R1_D1_SUCCESSOR)
    assert r1_d1["parent_source_head"] == (
        "caa3c0fd07b19ed0806a28f94a1184cf3d697a6d"
    )
    assert r1_d1["phase"] == "R1-D1"
    assert r1_d1["business_behavior_changed"] is True
    assert r1_d1["protected_deltas"] == baseline["protected_deltas"]
    current_hashes = {
        item["path"]: item["sha256"]
        for item in r1_d1["current_protected_sources"]
    }
    assert all(
        item["after_sha256"] == current_hashes[item["path"]]
        for item in r1_d1["authorized_source_deltas"]
    )
    assert {
        item["path"] for item in r1_d1["authorized_source_deltas"]
    } == {
        "src/novel_flywheel/prose_quality.py",
        "src/novel_flywheel/workflows.py",
    }
    r1_d3 = load_baseline(R1_D3_SUCCESSOR)
    assert r1_d3["parent_source_head"] == (
        "d992b1b0c7cfdd957df71f8bdb0d75bf4c9d41ab"
    )
    assert r1_d3["implementation_source_head"] == (
        "148ddc62c8065ea86b0a70e20e9ceffb5d56f141"
    )
    assert r1_d3["phase"] == "R1-D3"
    assert r1_d3["business_behavior_changed"] is True
    assert r1_d3["protected_deltas"] == {
        "business_artifacts": 0,
        "model_call_upper_bound": 0,
        "initial_prompt": 0,
        "retry_prompt_policy": 1,
        "retry_fallback_sequence": 0,
    }
    r1_d3_hashes = {
        item["path"]: item["sha256"]
        for item in r1_d3["current_protected_sources"]
    }
    assert all(
        item["after_sha256"] == r1_d3_hashes[item["path"]]
        for item in r1_d3["authorized_source_deltas"]
    )
    assert {
        item["path"] for item in r1_d3["authorized_source_deltas"]
    } == {"src/novel_flywheel/workflows.py"}
    r1_ptr1 = load_baseline(R1_PTR1_SUCCESSOR)
    assert r1_ptr1["parent_source_head"] == (
        "4305858dee4843ce2f83a2cc1ebf1f02f58a3804"
    )
    assert r1_ptr1["phase"] == "R1-PTR1"
    assert r1_ptr1["business_behavior_changed"] is False
    assert r1_ptr1["protected_deltas"] == {
        "business_artifacts": 0,
        "domain_validator": 0,
        "model_calls": 0,
        "output_budget": 0,
        "prompt": 0,
        "route_model": 0,
        "retry_fallback_sequence": 0,
    }
    r1_ptr1_hashes = {
        item["path"]: item["sha256"]
        for item in r1_ptr1["current_protected_sources"]
    }
    assert all(
        item["after_sha256"] == r1_ptr1_hashes[item["path"]]
        for item in r1_ptr1["authorized_source_deltas"]
    )
    assert {
        item["path"] for item in r1_ptr1["authorized_source_deltas"]
    } == {
        "src/novel_flywheel/contract_runtime.py",
        "src/novel_flywheel/generated_artifacts.py",
        "src/novel_flywheel/models.py",
        "src/novel_flywheel/workflows.py",
    }
    r1_ptr3 = load_baseline(R1_PTR3_SUCCESSOR)
    assert r1_ptr3["parent_source_head"] == (
        "ae5361008feab76d02dff726be4196040d3b3d9c"
    )
    assert r1_ptr3["implementation_source_head"] == (
        "a6d16638bdc55c5639979be7e2b50ffb0d927461"
    )
    assert r1_ptr3["phase"] == "R1-PTR3"
    assert r1_ptr3["business_behavior_changed"] is True
    assert r1_ptr3["protected_deltas"] == {
        "business_artifacts": 0,
        "domain_validator": 0,
        "initial_prompt": 0,
        "model_call_upper_bound": 0,
        "output_budget": 0,
        "retry_fallback_sequence": 0,
        "retry_prompt_policy": 1,
        "route_model": 0,
    }
    ptr3_hashes = {
        item["path"]: item["sha256"]
        for item in r1_ptr3["current_protected_sources"]
    }
    assert all(
        item["after_sha256"] == ptr3_hashes[item["path"]]
        for item in r1_ptr3["authorized_source_deltas"]
    )
    assert {
        item["path"] for item in r1_ptr3["authorized_source_deltas"]
    } == {
        "src/novel_flywheel/contract_runtime.py",
        "src/novel_flywheel/workflows.py",
    }
    r1_ptr9 = load_baseline(R1_PTR9_SUCCESSOR)
    assert r1_ptr9["parent_source_head"] == (
        "d68b0f7c5566fca9cb2898e14bfdda06f4480a6b"
    )
    assert r1_ptr9["phase"] == "R1-PTR9"
    assert r1_ptr9["business_behavior_changed"] is True
    assert r1_ptr9["protected_deltas"] == {
        "business_artifacts": 0,
        "domain_validator": 0,
        "initial_prompt": 0,
        "model_call_upper_bound": 0,
        "output_budget": 0,
        "retry_fallback_attempt_limits": 0,
        "same_fingerprint_redispatch": -1,
        "route_model_identity": 0,
        "final_artifact_capability_memory": 1,
    }
    ptr9_hashes = {
        item["path"]: item["sha256"]
        for item in r1_ptr9["current_protected_sources"]
    }
    assert all(
        item["after_sha256"] == ptr9_hashes[item["path"]]
        for item in r1_ptr9["authorized_source_deltas"]
    )
    assert {
        item["path"] for item in r1_ptr9["authorized_source_deltas"]
    } == {
        "src/novel_flywheel/contract_runtime.py",
        "src/novel_flywheel/models.py",
    }
    r1_ptr12 = load_baseline(R1_PTR12_OBSERVER_SUCCESSOR)
    _assert_r1_ptr12_successor_exact(r1_ptr12)
    r1_ptr12_bounded = load_baseline(R1_PTR12_BOUNDED_CAPTURE_SUCCESSOR)
    _assert_r1_ptr12_bounded_capture_successor_exact(r1_ptr12_bounded)
    r1_ptr12_nested_tail = load_baseline(R1_PTR12_NESTED_TAIL_SUCCESSOR)
    _assert_r1_ptr12_nested_tail_successor_exact(r1_ptr12_nested_tail)
    r1_ptr12_anthropic_cap = load_baseline(R1_PTR12_ANTHROPIC_CAP_SUCCESSOR)
    _assert_r1_ptr12_anthropic_cap_successor_exact(r1_ptr12_anthropic_cap)
    r1_ptr12_stream_reasoning = load_baseline(R1_PTR12_STREAM_REASONING_SUCCESSOR)
    _assert_r1_ptr12_stream_reasoning_successor_exact(
        r1_ptr12_stream_reasoning,
    )
    r1_ptr12_diagnostic_context = load_baseline(
        R1_PTR12_DIAGNOSTIC_CONTEXT_SUCCESSOR,
    )
    _assert_r1_ptr12_diagnostic_context_successor_exact(
        r1_ptr12_diagnostic_context,
    )
    r1_ptr12_shared_capture_exhaustion = load_baseline(
        R1_PTR12_SHARED_CAPTURE_EXHAUSTION_SUCCESSOR,
    )
    _assert_r1_ptr12_shared_capture_exhaustion_successor_exact(
        r1_ptr12_shared_capture_exhaustion,
    )


@pytest.mark.parametrize(
    "case",
    (
        "wrong_schema",
        "missing_schema",
        "wrong_version",
        "wrong_type_version",
        "boolean_version",
        "missing_version",
        "wrong_protected_tree",
        "missing_protected_tree",
        "reordered_manifest_protected_tree",
        "wrong_implementation",
        "tampered_individual_hash",
    ),
)
def test_r1_ptr12_successor_rejects_in_memory_tamper(case: str) -> None:
    successor = copy.deepcopy(load_baseline(R1_PTR12_OBSERVER_SUCCESSOR))
    _tamper_ptr12_successor(successor, case)

    with pytest.raises((AssertionError, KeyError)):
        _assert_r1_ptr12_successor_exact(successor)


def test_r1_ptr12_successor_accepts_exact_frozen_fixture() -> None:
    _assert_r1_ptr12_successor_exact(
        load_baseline(R1_PTR12_OBSERVER_SUCCESSOR),
    )


def test_r1_ptr12_successor_fixture_is_required(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_baseline(tmp_path / R1_PTR12_OBSERVER_SUCCESSOR.name)


@pytest.mark.parametrize(
    "case",
    (
        "wrong_schema",
        "missing_version",
        "boolean_version",
        "wrong_parent",
        "wrong_implementation",
        "wrong_parent_fixture",
        "wrong_tree",
        "missing_provider_output",
        "tampered_provider_output",
        "wrong_before_hash",
        "wrong_after_hash",
    ),
)
def test_r1_ptr12_bounded_capture_successor_rejects_tamper(
    case: str,
) -> None:
    successor = copy.deepcopy(load_baseline(R1_PTR12_BOUNDED_CAPTURE_SUCCESSOR))
    _tamper_ptr12_bounded_capture_successor(successor, case)

    with pytest.raises((AssertionError, KeyError)):
        _assert_r1_ptr12_bounded_capture_successor_exact(successor)


def test_r1_ptr12_bounded_capture_successor_accepts_exact_fixture() -> None:
    _assert_r1_ptr12_bounded_capture_successor_exact(
        load_baseline(R1_PTR12_BOUNDED_CAPTURE_SUCCESSOR),
    )


def test_r1_ptr12_bounded_capture_successor_fixture_is_required(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError):
        load_baseline(tmp_path / R1_PTR12_BOUNDED_CAPTURE_SUCCESSOR.name)


@pytest.mark.parametrize(
    "case",
    (
        "wrong_schema",
        "wrong_version",
        "boolean_version",
        "wrong_implementation",
        "wrong_protected_tree",
        "single_file_hash_tamper",
    ),
)
def test_r1_ptr12_nested_tail_successor_rejects_tamper(case: str) -> None:
    successor = copy.deepcopy(load_baseline(R1_PTR12_NESTED_TAIL_SUCCESSOR))
    _tamper_ptr12_nested_tail_successor(successor, case)

    with pytest.raises((AssertionError, KeyError)):
        _assert_r1_ptr12_nested_tail_successor_exact(successor)


def test_r1_ptr12_nested_tail_successor_accepts_exact_fixture() -> None:
    _assert_r1_ptr12_nested_tail_successor_exact(
        load_baseline(R1_PTR12_NESTED_TAIL_SUCCESSOR),
    )


def test_r1_ptr12_nested_tail_successor_fixture_is_required(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError):
        load_baseline(tmp_path / R1_PTR12_NESTED_TAIL_SUCCESSOR.name)


@pytest.mark.parametrize(
    "case",
    (
        "wrong_schema",
        "wrong_version",
        "boolean_version",
        "wrong_implementation",
        "wrong_protected_tree",
        "single_file_hash_tamper",
        "wrong_before_hash",
        "wrong_after_hash",
    ),
)
def test_r1_ptr12_anthropic_cap_successor_rejects_tamper(
    case: str,
) -> None:
    successor = copy.deepcopy(load_baseline(R1_PTR12_ANTHROPIC_CAP_SUCCESSOR))
    _tamper_ptr12_anthropic_cap_successor(successor, case)

    with pytest.raises((AssertionError, KeyError)):
        _assert_r1_ptr12_anthropic_cap_successor_exact(successor)


def test_r1_ptr12_anthropic_cap_successor_accepts_exact_fixture() -> None:
    _assert_r1_ptr12_anthropic_cap_successor_exact(
        load_baseline(R1_PTR12_ANTHROPIC_CAP_SUCCESSOR),
    )


def test_r1_ptr12_anthropic_cap_successor_fixture_is_required(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError):
        load_baseline(tmp_path / R1_PTR12_ANTHROPIC_CAP_SUCCESSOR.name)


@pytest.mark.parametrize(
    "case",
    (
        "wrong_schema",
        "wrong_version",
        "wrong_implementation",
        "wrong_protected_tree",
        "single_file_hash_tamper",
        "wrong_before_hash",
        "wrong_after_hash",
    ),
)
def test_r1_ptr12_stream_reasoning_successor_rejects_tamper(
    case: str,
) -> None:
    successor = copy.deepcopy(load_baseline(R1_PTR12_STREAM_REASONING_SUCCESSOR))
    _tamper_ptr12_stream_reasoning_successor(successor, case)

    with pytest.raises((AssertionError, KeyError)):
        _assert_r1_ptr12_stream_reasoning_successor_exact(successor)


def test_r1_ptr12_stream_reasoning_successor_accepts_exact_fixture() -> None:
    _assert_r1_ptr12_stream_reasoning_successor_exact(
        load_baseline(R1_PTR12_STREAM_REASONING_SUCCESSOR),
    )


def test_r1_ptr12_stream_reasoning_successor_fixture_is_required(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError):
        load_baseline(tmp_path / R1_PTR12_STREAM_REASONING_SUCCESSOR.name)


@pytest.mark.parametrize(
    "case",
    (
        "wrong_schema",
        "wrong_version",
        "wrong_implementation",
        "wrong_protected_tree",
        "single_file_hash_tamper",
        "wrong_before_hash",
        "wrong_after_hash",
    ),
)
def test_r1_ptr12_diagnostic_context_successor_rejects_tamper(
    case: str,
) -> None:
    successor = copy.deepcopy(load_baseline(
        R1_PTR12_DIAGNOSTIC_CONTEXT_SUCCESSOR,
    ))
    _tamper_ptr12_diagnostic_context_successor(successor, case)

    with pytest.raises((AssertionError, KeyError)):
        _assert_r1_ptr12_diagnostic_context_successor_exact(successor)


def test_r1_ptr12_diagnostic_context_successor_accepts_exact_fixture() -> None:
    _assert_r1_ptr12_diagnostic_context_successor_exact(
        load_baseline(R1_PTR12_DIAGNOSTIC_CONTEXT_SUCCESSOR),
    )


def test_r1_ptr12_diagnostic_context_successor_fixture_is_required(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError):
        load_baseline(tmp_path / R1_PTR12_DIAGNOSTIC_CONTEXT_SUCCESSOR.name)


@pytest.mark.parametrize(
    "case",
    (
        "wrong_schema",
        "wrong_version",
        "wrong_implementation",
        "wrong_protected_tree",
        "single_file_hash_tamper",
        "wrong_before_hash",
        "wrong_after_hash",
    ),
)
def test_r1_ptr12_shared_capture_exhaustion_successor_rejects_tamper(
    case: str,
) -> None:
    successor = copy.deepcopy(load_baseline(
        R1_PTR12_SHARED_CAPTURE_EXHAUSTION_SUCCESSOR,
    ))
    _tamper_ptr12_shared_capture_exhaustion_successor(successor, case)

    with pytest.raises((AssertionError, KeyError)):
        _assert_r1_ptr12_shared_capture_exhaustion_successor_exact(successor)


def test_r1_ptr12_shared_capture_exhaustion_successor_accepts_exact_fixture(
) -> None:
    _assert_r1_ptr12_shared_capture_exhaustion_successor_exact(
        load_baseline(R1_PTR12_SHARED_CAPTURE_EXHAUSTION_SUCCESSOR),
    )


def test_r1_ptr12_shared_capture_exhaustion_successor_fixture_is_required(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError):
        load_baseline(
            tmp_path / R1_PTR12_SHARED_CAPTURE_EXHAUSTION_SUCCESSOR.name,
        )


def test_r0f_baseline_characterizes_supervised_run_business_projection(
    tmp_path: Path,
) -> None:
    db = make_database(tmp_path)

    assert db.activate_supervised_run(
        run_id="run-new",
        project_id="book",
        workflow="long-chapter",
        resume_payload={"chapter_goal": "deterministic fixture"},
        retry_budgets={
            "protocol_retry": 1,
            "fallback_route": 1,
            "semantic_repair": 1,
            "quality_repair": 1,
        },
    )
    assert db.enter_supervised_run_running("run-new")
    assert db.commit_supervised_completion("run-new")

    projection = business_run_projection(
        db.get_run("run-new") or {}, db.list_run_events("run-new"),
    )
    assert projection == load_baseline(BASELINE)["supervised_run_projection"]


def test_r0f_baseline_keeps_phase1b_cutover_closed(tmp_path: Path) -> None:
    db = make_database(tmp_path)

    assert os.getenv("NOVEL_SHORT_CANONICAL_V2", "0") == "0"
    assert db.feature_flag(
        "short_canonical_v2", project_id="book", default=False,
    )["enabled"] is False
