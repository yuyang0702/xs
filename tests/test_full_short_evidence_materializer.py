from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.diagnostics.materialize_full_short_failure_surface_architecture_closure import (
    _git,
    _verified_json_receipt,
    _verified_junit_receipt,
)


def test_junit_receipt_requires_a_nonempty_exact_pass_bound_to_head(
    tmp_path: Path,
) -> None:
    repo = Path.cwd()
    head = _git(repo, "rev-parse", "HEAD")
    valid = tmp_path / "valid.xml"
    valid.write_text(
        '<testsuite tests="1" failures="0" errors="0" skipped="0">'
        '<testcase classname="tests.boundary" name="test_real_boundary"/>'
        "</testsuite>",
        encoding="utf-8",
    )

    receipt = _verified_junit_receipt(
        valid, repo=repo, head=head, classification="FOCUSED",
    )

    assert receipt["status"] == "PASS"
    assert receipt["source_head"] == head
    assert receipt["tests"] == 1
    assert receipt["_testcase_names"] == ["test_real_boundary"]

    for counters in (
        'tests="0" failures="0" errors="0" skipped="0"',
        'tests="1" failures="1" errors="0" skipped="0"',
        'tests="1" failures="0" errors="0" skipped="1"',
    ):
        invalid = tmp_path / f"invalid-{hash(counters)}.xml"
        invalid.write_text(f"<testsuite {counters}/>", encoding="utf-8")
        with pytest.raises(ValueError, match="exact nonempty PASS"):
            _verified_junit_receipt(
                invalid, repo=repo, head=head, classification="FOCUSED",
            )


def test_json_receipt_requires_exact_schema_head_and_pass(tmp_path: Path) -> None:
    repo = Path.cwd()
    head = _git(repo, "rev-parse", "HEAD")
    path = tmp_path / "receipt.json"
    base = {
        "schema": "EvidenceV1", "source_head": head, "status": "PASS",
    }
    path.write_text(json.dumps(base), encoding="utf-8")

    value = _verified_json_receipt(
        path, repo=repo, head=head, schema="EvidenceV1",
    )

    assert value["receipt_sha256"]
    for mutation in (
        {"schema": "WrongV1"}, {"source_head": "0" * 40}, {"status": "FAIL"},
    ):
        path.write_text(json.dumps({**base, **mutation}), encoding="utf-8")
        with pytest.raises(ValueError):
            _verified_json_receipt(
                path, repo=repo, head=head, schema="EvidenceV1",
            )
