from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest

from tools.diagnostics.fixture_provenance import (
    CANONICAL_TEXT_LF_V1,
    RAW_BYTES_V1,
    CanonicalTextProvenanceDecodeError,
    canonicalize_fixture_bytes,
    observe_fixture_provenance,
)
from tools.diagnostics.short_plan_v2_slice1 import (
    Slice1ReplayProvenanceError,
    run_canonical_replay,
    run_replay,
)


ROOT = Path(__file__).parents[1]
FIXTURE = (
    ROOT / "tests" / "fixtures" / "reliability" / "short_plan_v2_slice1"
    / "event-realization-shadow-corpus-v1.json"
)
BINDING = FIXTURE.with_suffix(".provenance.json")
EXPECTED_CANONICAL_SHA256 = (
    "6ff08d5e4045bd51ad992f372928e467255a07ab7c13a1ff01b7e5be2227daa6"
)
WINDOWS_RAW_SHA256 = (
    "a1442835a44471b9be5c87c4feb4ec89853a3b4348d7215185de62ced4a4fab4"
)


def _clock(*values: float):
    iterator = iter(values)
    return lambda: next(iterator)


def _write_binding(path: Path, **updates: object) -> Path:
    value = json.loads(BINDING.read_text(encoding="utf-8"))
    value.update(updates)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def test_current_windows_fixture_normalizes_to_sealed_lf_sha() -> None:
    raw = FIXTURE.read_bytes()
    observation = observe_fixture_provenance(raw, CANONICAL_TEXT_LF_V1)

    assert observation["fixture_provenance_contract"] == CANONICAL_TEXT_LF_V1
    assert observation["canonical_fixture_sha256"] == EXPECTED_CANONICAL_SHA256
    assert observation["canonical_byte_length"] == 4436
    if observation["observed_eol_shape"] == "CRLF":
        assert hashlib.sha256(raw).hexdigest() == WINDOWS_RAW_SHA256
        assert observation["raw_byte_length"] == 4486
        assert observation["canonicalization_applied"] is True
    else:
        assert observation["observed_eol_shape"] == "LF"
        assert hashlib.sha256(raw).hexdigest() == EXPECTED_CANONICAL_SHA256
        assert observation["raw_byte_length"] == 4436
        assert observation["canonicalization_applied"] is False


def test_lf_crlf_lone_cr_and_mixed_eol_share_canonical_identity() -> None:
    lf = b"alpha\nbeta\ngamma\n"
    variants = (
        lf,
        b"alpha\r\nbeta\r\ngamma\r\n",
        b"alpha\rbeta\rgamma\r",
        b"alpha\r\nbeta\rgamma\n",
    )

    assert {canonicalize_fixture_bytes(value, CANONICAL_TEXT_LF_V1) for value in variants} == {lf}
    assert [observe_fixture_provenance(value, CANONICAL_TEXT_LF_V1)["observed_eol_shape"] for value in variants] == [
        "LF", "CRLF", "CR", "MIXED",
    ]


def test_final_newline_and_trailing_spaces_remain_identity_significant() -> None:
    without_final = canonicalize_fixture_bytes(b"alpha\r\nbeta", CANONICAL_TEXT_LF_V1)
    with_final = canonicalize_fixture_bytes(b"alpha\r\nbeta\r\n", CANONICAL_TEXT_LF_V1)
    plain = canonicalize_fixture_bytes(b"alpha\r\n", CANONICAL_TEXT_LF_V1)
    trailing = canonicalize_fixture_bytes(b"alpha  \r\n", CANONICAL_TEXT_LF_V1)

    assert without_final == b"alpha\nbeta"
    assert with_final == b"alpha\nbeta\n"
    assert hashlib.sha256(without_final).digest() != hashlib.sha256(with_final).digest()
    assert trailing == b"alpha  \n"
    assert hashlib.sha256(plain).digest() != hashlib.sha256(trailing).digest()


def test_unicode_is_not_normalized_beyond_eol() -> None:
    nfc = unicodedata.normalize("NFC", "Cafe\u0301").encode("utf-8") + b"\r\n"
    nfd = unicodedata.normalize("NFD", "Caf\u00e9").encode("utf-8") + b"\r\n"

    canonical_nfc = canonicalize_fixture_bytes(nfc, CANONICAL_TEXT_LF_V1)
    canonical_nfd = canonicalize_fixture_bytes(nfd, CANONICAL_TEXT_LF_V1)

    assert canonical_nfc[:-1] == nfc[:-2]
    assert canonical_nfd[:-1] == nfd[:-2]
    assert canonical_nfc != canonical_nfd


def test_binary_or_untyped_contract_remains_raw_bytes() -> None:
    binary = b"\xff\x00alpha\r\nbeta\r"

    assert canonicalize_fixture_bytes(binary, RAW_BYTES_V1) == binary
    observation = observe_fixture_provenance(binary, RAW_BYTES_V1)
    assert observation["canonicalization_applied"] is False
    assert observation["canonical_fixture_sha256"] == observation["raw_worktree_sha256"]


def test_invalid_utf8_under_text_contract_is_typed_failure() -> None:
    with pytest.raises(CanonicalTextProvenanceDecodeError) as captured:
        canonicalize_fixture_bytes(b"\xff\xfe", CANONICAL_TEXT_LF_V1)

    assert captured.value.code == "CANONICAL_TEXT_PROVENANCE_DECODE_ERROR"


def test_historical_v1_receipt_semantics_remain_raw_bytes() -> None:
    receipt = run_replay(FIXTURE, clock=_clock(1.0, 1.001))

    assert receipt["schema"] == "EventRealizationShadowReplayReceiptV1"
    assert receipt["version"] == 1
    assert receipt["fixture_sha256"] == WINDOWS_RAW_SHA256
    assert "fixture_provenance" not in receipt


def test_fresh_v2_receipt_binds_explicit_canonical_contract() -> None:
    receipt = run_canonical_replay(
        FIXTURE, BINDING, clock=_clock(2.0, 2.002),
    )

    assert receipt["schema"] == "EventRealizationShadowReplayReceiptV2"
    assert receipt["version"] == 2
    assert receipt["fixture_provenance"]["fixture_provenance_contract"] == CANONICAL_TEXT_LF_V1
    assert receipt["fixture_provenance"]["canonical_fixture_sha256"] == EXPECTED_CANONICAL_SHA256
    assert receipt["fixture_provenance"]["diagnostic_raw_observation"]["identity_critical"] is False
    assert receipt["case_count"] == 20
    assert receipt["overall_status"] == "exact"


def test_lf_and_crlf_receipts_have_same_canonical_identity(tmp_path: Path) -> None:
    crlf = FIXTURE.read_bytes()
    lf = canonicalize_fixture_bytes(crlf, CANONICAL_TEXT_LF_V1)
    lf_path = tmp_path / "lf.json"
    crlf_path = tmp_path / "crlf.json"
    lf_path.write_bytes(lf)
    crlf_path.write_bytes(lf.replace(b"\n", b"\r\n"))

    left = run_canonical_replay(lf_path, BINDING, clock=_clock(3.0, 3.003))
    right = run_canonical_replay(crlf_path, BINDING, clock=_clock(3.0, 3.003))

    assert left["fixture_provenance"]["diagnostic_raw_observation"]["raw_worktree_sha256"] != right["fixture_provenance"]["diagnostic_raw_observation"]["raw_worktree_sha256"]
    assert left["fixture_provenance"]["canonical_fixture_sha256"] == right["fixture_provenance"]["canonical_fixture_sha256"]
    assert left["canonical_receipt_identity_sha256"] == right["canonical_receipt_identity_sha256"]
    assert left["cases"] == right["cases"]


def test_binding_mismatch_fails_before_semantic_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    binding = _write_binding(
        tmp_path / "binding.json",
        expected_canonical_fixture_sha256="0" * 64,
    )
    dispatched = False

    def forbidden_dispatch(*args: object, **kwargs: object) -> object:
        nonlocal dispatched
        dispatched = True
        raise AssertionError("semantic dispatch must not occur")

    monkeypatch.setattr(
        "tools.diagnostics.short_plan_v2_slice1.run_replay", forbidden_dispatch,
    )
    with pytest.raises(Slice1ReplayProvenanceError) as captured:
        run_canonical_replay(FIXTURE, binding, clock=_clock(4.0, 4.004))

    assert captured.value.code == "CANONICAL_FIXTURE_SHA256_MISMATCH"
    assert dispatched is False


def test_parent_and_case_identity_are_bound_before_dispatch(tmp_path: Path) -> None:
    parent_binding = _write_binding(
        tmp_path / "parent.json",
        parent_sealed_implementation_sha256="f" * 40,
    )
    with pytest.raises(Slice1ReplayProvenanceError) as parent_error:
        run_canonical_replay(FIXTURE, parent_binding)
    assert parent_error.value.code == "SLICE1_PARENT_IMPLEMENTATION_IDENTITY_MISMATCH"

    case_binding = _write_binding(
        tmp_path / "case.json", case_identity_sha256="f" * 64,
    )
    with pytest.raises(Slice1ReplayProvenanceError) as case_error:
        run_canonical_replay(FIXTURE, case_binding)
    assert case_error.value.code == "SLICE1_CORPUS_CASE_IDENTITY_MISMATCH"


def test_cli_emits_fresh_v2_receipt_only_when_binding_is_explicit(
    tmp_path: Path,
) -> None:
    output = tmp_path / "receipt.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.diagnostics.short_plan_v2_slice1",
            "--fixture",
            str(FIXTURE),
            "--provenance-binding",
            str(BINDING),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["schema"] == "EventRealizationShadowReplayReceiptV2"
    assert receipt["fixture_provenance"]["canonical_fixture_sha256"] == EXPECTED_CANONICAL_SHA256
    assert len(receipt["canonical_receipt_identity_sha256"]) == 64
