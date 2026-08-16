from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from tools.canary.fingerprint_profiles import (
    FINGERPRINT_COLLECTION_PROFILE_NOT_COMPARABLE,
    PRODUCTION_MIRROR_SHORT_PROFILE_ID,
    R1_D3_OFFLINE_PROFILE_ID,
    FingerprintCollectionProfileError,
    compare_execution_fingerprint_profiles_v1,
    load_r1_d3_evidence_v1,
)


ROOT = Path(__file__).parents[2]


def _identity(profile_id: str) -> dict[str, str]:
    return {
        "collection_profile_id": profile_id,
        "execution_config_sha256": "a" * 64,
        "runtime_execution_sha256": "b" * 64,
    }


def test_offline_and_production_execution_hashes_are_typed_not_comparable() -> None:
    expected = _identity(R1_D3_OFFLINE_PROFILE_ID)
    actual = _identity(PRODUCTION_MIRROR_SHORT_PROFILE_ID)
    actual["execution_config_sha256"] = "c" * 64
    actual["runtime_execution_sha256"] = "d" * 64

    result = compare_execution_fingerprint_profiles_v1(expected, actual)

    assert result["execution_config_comparison"]["status"] == (
        FINGERPRINT_COLLECTION_PROFILE_NOT_COMPARABLE
    )
    assert result["runtime_execution_comparison"]["status"] == (
        FINGERPRINT_COLLECTION_PROFILE_NOT_COMPARABLE
    )
    assert result["execution_config_comparison"]["reason_code"] == (
        "fingerprint_collection_profile_not_comparable"
    )
    assert result["execution_config_comparison"]["equal"] is None


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("execution_config_sha256", "execution_config_fingerprint_mismatch"),
        ("runtime_execution_sha256", "runtime_execution_fingerprint_mismatch"),
    ],
)
def test_same_production_profile_drift_still_fails_closed(
    field: str, reason: str,
) -> None:
    expected = _identity(PRODUCTION_MIRROR_SHORT_PROFILE_ID)
    actual = deepcopy(expected)
    actual[field] = "f" * 64

    with pytest.raises(FingerprintCollectionProfileError, match=reason) as caught:
        compare_execution_fingerprint_profiles_v1(expected, actual)

    assert caught.value.reason_code == reason


@pytest.mark.parametrize(
    ("profile_id", "reason"),
    [
        (None, "fingerprint_collection_profile_missing"),
        ("unknown-profile-v1", "fingerprint_collection_profile_unknown"),
    ],
)
def test_missing_or_unknown_profile_fails_closed(
    profile_id: str | None, reason: str,
) -> None:
    expected = _identity(PRODUCTION_MIRROR_SHORT_PROFILE_ID)
    actual = _identity(PRODUCTION_MIRROR_SHORT_PROFILE_ID)
    if profile_id is None:
        actual.pop("collection_profile_id")
    else:
        actual["collection_profile_id"] = profile_id

    with pytest.raises(FingerprintCollectionProfileError, match=reason):
        compare_execution_fingerprint_profiles_v1(expected, actual)


def test_r1_d3_v1_evidence_remains_readable_and_manifest_bound() -> None:
    evidence = load_r1_d3_evidence_v1(ROOT)

    assert evidence["manifest_status"] == "exact"
    assert evidence["manifest_entry_count"] == 13
    assert evidence["validation_receipt"]["version"] == 1
    assert evidence["validation_receipt"]["runtime_fingerprints"]["profile"] == (
        R1_D3_OFFLINE_PROFILE_ID
    )
