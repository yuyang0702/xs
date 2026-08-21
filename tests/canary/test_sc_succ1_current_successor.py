from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from novel_flywheel.runtime_fingerprint_build import domain_sha256
from tools.canary.network_sentinel import FailClosedNetworkSentinel
import tools.canary.ptr3_readiness as readiness


ROOT = Path(__file__).resolve().parents[2]


def _document() -> dict:
    return json.loads(readiness.CURRENT_SUCCESSOR_PATH.read_text(encoding="utf-8"))


def _plan(value: dict | None = None) -> dict:
    return readiness.current_successor_plan_projection(value or _document())


def _reseal(value: dict) -> dict:
    body = deepcopy(value)
    body.pop("definition_sha256", None)
    body["definition_sha256"] = domain_sha256(readiness.CURRENT_DOMAIN, body)
    return body


def _write(tmp_path: Path, value: dict) -> Path:
    path = tmp_path / "successor.json"
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def test_historical_ptr3_evidence_is_immutable_and_exact() -> None:
    evidence = readiness.historical_ptr3_evidence_v1(ROOT)
    assert evidence["successor_sha256"] == readiness.HISTORICAL_PTR3_SHA256
    assert evidence["blob_id"] == readiness.HISTORICAL_PTR3_BLOB_ID
    assert evidence["report_tree_id"] == readiness.HISTORICAL_PTR3_REPORT_TREE_ID


def test_cross_era_source_mismatch_is_explicitly_identified() -> None:
    value = _document()
    mismatch = value["source_lineage"]["historical_to_current_mismatch"]
    assert mismatch["historical_aggregate_sha256"] == (
        "ead7727bae076daefc807e1316fb2cf6caa688192f31e45dc214326db92a5f8a"
    )
    assert mismatch["current_aggregate_sha256"] == (
        "71446b917737904cef05760c1c06da570bafb5677e0e91f0715958d08b999513"
    )
    assert [item["path"] for item in mismatch["files"]] == [
        "src/novel_flywheel/contract_runtime.py",
        "src/novel_flywheel/models.py",
    ]


def test_valid_fresh_current_successor_passes() -> None:
    value = readiness.validate_current_ptr3_successor_v1(
        repo_root=ROOT, production_plan=_plan(),
    )
    assert value["profile"] == readiness.CURRENT_PROFILE
    assert value["readiness_status"] == "exact"


def test_stale_successor_fails_closed(tmp_path: Path) -> None:
    value = _document()
    value["current_successor_evidence"]["baseline_head"] = "0" * 40
    with pytest.raises(readiness.SuccessorReadinessError, match="current_successor_head_stale"):
        readiness.validate_current_ptr3_successor_v1(
            repo_root=ROOT, production_plan=_plan(),
            successor_path=_write(tmp_path, _reseal(value)),
        )


def test_altered_current_production_source_fails_closed(monkeypatch) -> None:
    original = readiness._source_sha256

    def changed(root: Path, relative: str) -> str:
        if relative == "src/novel_flywheel/models.py":
            return "0" * 64
        return original(root, relative)

    monkeypatch.setattr(readiness, "_source_sha256", changed)
    with pytest.raises(readiness.SuccessorReadinessError, match="current_successor_source_mismatch"):
        readiness.validate_current_ptr3_successor_v1(
            repo_root=ROOT, production_plan=_plan(),
        )


def test_broken_commit_ancestry_fails_closed(monkeypatch) -> None:
    original = readiness._git

    def broken(root: Path, *args: str) -> str:
        if args[:2] == ("merge-base", "--is-ancestor"):
            raise readiness.SuccessorReadinessError("current_successor_ancestry_broken")
        return original(root, *args)

    monkeypatch.setattr(readiness, "_git", broken)
    with pytest.raises(readiness.SuccessorReadinessError, match="current_successor_ancestry_broken"):
        readiness.validate_current_ptr3_successor_v1(
            repo_root=ROOT, production_plan=_plan(),
        )


def test_missing_historical_evidence_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        readiness, "HISTORICAL_SUCCESSOR_RELATIVE_PATH", "tests/fixtures/missing.json",
    )
    with pytest.raises(readiness.SuccessorReadinessError, match="ptr3_historical_evidence_missing"):
        readiness.validate_current_ptr3_successor_v1(
            repo_root=ROOT, production_plan=_plan(),
        )


def test_altered_historical_evidence_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(readiness, "HISTORICAL_PTR3_SHA256", "0" * 64)
    with pytest.raises(readiness.SuccessorReadinessError, match="ptr3_historical_sha256_mismatch"):
        readiness.validate_current_ptr3_successor_v1(
            repo_root=ROOT, production_plan=_plan(),
        )


def test_wrong_current_head_fails_closed(monkeypatch) -> None:
    original = readiness._git

    def wrong(root: Path, *args: str) -> str:
        if args == ("rev-parse", "HEAD"):
            return "f" * 40
        return original(root, *args)

    monkeypatch.setattr(readiness, "_git", wrong)
    with pytest.raises(readiness.SuccessorReadinessError, match="current_successor_ancestry_broken"):
        readiness.validate_current_ptr3_successor_v1(
            repo_root=ROOT, production_plan=_plan(),
        )


@pytest.mark.parametrize(
    "field",
    [
        "approved_build_fingerprint",
        "approved_execution_config_fingerprint",
        "expected_runtime_execution_fingerprint",
    ],
)
def test_wrong_runtime_build_config_fingerprint_fails_closed(field: str) -> None:
    plan = _plan()
    plan[field] = "0" * 64
    with pytest.raises(readiness.SuccessorReadinessError, match="current_successor_fingerprint_mismatch"):
        readiness.validate_current_ptr3_successor_v1(repo_root=ROOT, production_plan=plan)


def test_unknown_successor_profile_fails_closed(tmp_path: Path) -> None:
    value = _document()
    value["profile"] = "unknown"
    with pytest.raises(readiness.SuccessorReadinessError, match="current_successor_profile_unknown"):
        readiness.validate_current_ptr3_successor_v1(
            repo_root=ROOT, production_plan=_plan(),
            successor_path=_write(tmp_path, _reseal(value)),
        )


def test_failed_semantic_revalidation_fails_closed(tmp_path: Path) -> None:
    value = _document()
    value["semantic_revalidation"]["overall_status"] = "failed"
    with pytest.raises(readiness.SuccessorReadinessError, match="ptr3_semantic_revalidation_not_exact"):
        readiness.validate_current_ptr3_successor_v1(
            repo_root=ROOT, production_plan=_plan(),
            successor_path=_write(tmp_path, _reseal(value)),
        )


def test_ptr3_semantic_revalidation_receipt_is_exact() -> None:
    value = readiness.validate_current_ptr3_successor_v1(
        repo_root=ROOT, production_plan=_plan(),
    )
    assert value["semantic_revalidation"]["stale_finding_count"] == 0
    assert value["semantic_revalidation"]["required_case_count"] >= 15


def test_ptr9_compatibility_is_bound() -> None:
    value = readiness.validate_current_ptr3_successor_v1(
        repo_root=ROOT, production_plan=_plan(),
    )
    ptr9 = value["compatibility"]["ptr9"]
    assert ptr9["guard_identity"] == "REASONING_ONLY_MAX_TOKENS_GUARD_V1"
    assert ptr9["status"] == "pass"


def test_ptr10_invariants_remain_bound() -> None:
    value = readiness.validate_current_ptr3_successor_v1(
        repo_root=ROOT, production_plan=_plan(),
    )
    assert value["compatibility"]["ptr10"]["status"] == "pass"


def test_sc_ic1_import_closure_remains_bound() -> None:
    value = readiness.validate_current_ptr3_successor_v1(
        repo_root=ROOT, production_plan=_plan(),
    )
    sc_ic1 = value["compatibility"]["sc_ic1"]
    assert sc_ic1["identity"] == "PROBE_MODULE_IMPORT_ISOLATION_V1"
    assert sc_ic1["status"] == "pass"


def test_validate_only_has_zero_external_actions() -> None:
    with FailClosedNetworkSentinel() as sentinel:
        value = readiness.validate_current_ptr3_successor_v1(
            repo_root=ROOT, production_plan=_plan(),
        )
    assert sentinel.network_call_count == 0
    assert value["external_actions"] == {
        "credential": 0, "provider_client": 0, "network": 0,
        "model": 0, "paid": 0,
    }
