from __future__ import annotations

from pathlib import Path

from r0e_evidence import (
    GATES,
    primary_scope_unclassified_rows,
    residual_prioritization_matrix,
    verify_parent_seal,
)


ROOT = Path(__file__).resolve().parents[1]


def test_r0_parent_evidence_is_content_addressed_and_unchanged() -> None:
    seal = verify_parent_seal(ROOT)

    assert seal["verified"] is True, seal["mismatches"]
    assert seal["incident_count"] == 123
    assert seal["residual_family_count"] == 44
    assert seal["residual_incident_count"] == 97
    assert seal["focused_baseline"] == {
        "command": (
            ".venv/Scripts/python.exe -m pytest -q "
            "tests/test_r0_incident_manifest.py "
            "tests/test_r0_high_frequency_replay.py tests/test_r0_reports.py"
        ),
        "passed": 31,
        "failed": 0,
        "duration_seconds": 67.35,
    }


def test_residual_prioritization_covers_exact_parent_denominator() -> None:
    matrix = residual_prioritization_matrix(ROOT)

    assert matrix["family_count"] == 44
    assert matrix["historical_incident_count"] == 97
    assert len({row["family"] for row in matrix["rows"]}) == 44
    assert all(row["gate"] in GATES for row in matrix["rows"])
    assert all(
        row["expected_policy_outcome"] and row["policy_source"]
        for row in matrix["rows"]
    )
    assert all(
        row["policy_violation"] is None
        for row in matrix["rows"]
    )
    probes = matrix["mechanism_probes"]
    assert {item["historical_count"] for item in probes} == {0}
    assert all(item["historical_family_binding"] is None for item in probes)
    assert all(item["gate"] == "MECHANISM_FIX_CANDIDATE" for item in probes)


def test_six_primary_unclassified_incidents_remain_individually_named() -> None:
    rows = primary_scope_unclassified_rows(ROOT)

    assert [row["incident_id"] for row in rows] == [
        "r0-b2c6ed395bad574738d3",
        "r0-2f3df4e27c4d75b9306c",
        "r0-f8482e3405d5ebda0db3",
        "r0-5dd22b699f99af2aa213",
        "r0-df399434efc6c2888061",
        "r0-69887d2c16314e257c90",
    ]
    assert all(
        row["runtime_build_status"] == "unknown_runtime" for row in rows
    )

