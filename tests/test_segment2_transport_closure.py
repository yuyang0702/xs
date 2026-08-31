from pathlib import Path

import pytest

from tools.diagnostics.materialize_segment2_transport_closure import (
    _production_matrix_receipt,
)


def _write_junit(path: Path, *, failed: bool = False) -> None:
    failure = '<failure message="failed" />' if failed else ""
    path.write_text(
        "<testsuite tests=\"3\">"
        '<testcase name="matrix[13000]">' + failure + "</testcase>"
        '<testcase name="matrix[20000]" />'
        '<testcase name="matrix[30000]" />'
        "</testsuite>",
        encoding="utf-8",
    )


def test_production_matrix_receipt_requires_all_three_passing_lengths(
    tmp_path: Path,
) -> None:
    junit = tmp_path / "matrix.xml"
    _write_junit(junit)

    receipt = _production_matrix_receipt(junit)

    assert receipt["13000"] == "PASS"
    assert receipt["20000"] == "PASS"
    assert receipt["30000"] == "PASS"
    assert len(receipt["junit_sha256"]) == 64


def test_production_matrix_receipt_rejects_a_failed_length(tmp_path: Path) -> None:
    junit = tmp_path / "matrix.xml"
    _write_junit(junit, failed=True)

    with pytest.raises(AssertionError):
        _production_matrix_receipt(junit)
