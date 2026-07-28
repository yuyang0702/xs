import hashlib
import json

from novel_flywheel.quality_records import (
    load_quality_checkpoint,
    reconcile_legacy_checkpoint,
    write_quality_checkpoint,
)


def test_legacy_reconciliation_selects_higher_historical_file_without_rewriting_files(
    tmp_path,
) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    current = "lower current candidate"
    historical = "protected historical candidate"
    (outputs / "best-candidate.md").write_text(current, encoding="utf-8")
    (outputs / "historical-best-64.75.md").write_text(historical, encoding="utf-8")
    (outputs / "quality-report.json").write_text(json.dumps({
        "best_score": 58.35,
        "best_attempt": 1,
        "final_attempts": [{
            "attempt": 1,
            "review": {
                "score": 58.35,
                "dimensions": {"commercial": 60, "story": 58, "prose": 55},
                "issues": [],
            },
        }],
    }), encoding="utf-8")

    checkpoint = reconcile_legacy_checkpoint(tmp_path)

    assert checkpoint["score"] == 64.75
    assert checkpoint["manuscript_path"] == "outputs/historical-best-64.75.md"
    assert checkpoint["manuscript_hash"] == hashlib.sha256(
        historical.encode("utf-8"),
    ).hexdigest()
    assert checkpoint["scoring_profile_id"] == "legacy-v1"
    assert checkpoint["judge_signature"] == "legacy-unknown"
    assert (outputs / "best-candidate.md").read_text(encoding="utf-8") == current
    assert (outputs / "historical-best-64.75.md").read_text(encoding="utf-8") == historical


def test_reconciliation_is_idempotent_and_keeps_matching_review(tmp_path) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    text = "best candidate"
    (outputs / "best-candidate.md").write_text(text, encoding="utf-8")
    review = {
        "score": 82,
        "dimensions": {"commercial": 84, "story": 82, "prose": 78},
        "issues": [{"issue_id": "issue-1", "severity": "medium"}],
        "scoring_profile_id": "zhihu-short-v2",
        "judge_signature": "provider/model",
    }
    (outputs / "quality-report.json").write_text(json.dumps({
        "best_score": 82,
        "best_attempt": 2,
        "scoring_profile_id": "zhihu-short-v2",
        "final_attempts": [{"attempt": 2, "review": review}],
    }), encoding="utf-8")

    first = reconcile_legacy_checkpoint(tmp_path)
    first_bytes = (outputs / "quality-checkpoint.json").read_bytes()
    second = reconcile_legacy_checkpoint(tmp_path)

    assert second == first
    assert (outputs / "quality-checkpoint.json").read_bytes() == first_bytes
    assert first["review"] == review
    assert first["judge_signature"] == "provider/model"


def test_write_and_load_checkpoint_rejects_stale_hash(tmp_path) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    candidate = outputs / "best-candidate.md"
    candidate.write_text("version one", encoding="utf-8")
    checkpoint = {
        "version": 1,
        "manuscript_path": "outputs/best-candidate.md",
        "manuscript_hash": hashlib.sha256(b"version one").hexdigest(),
        "score": 80.0,
        "scoring_profile_id": "zhihu-short-v2",
        "judge_signature": "provider/model",
        "best_attempt": 1,
        "review": None,
    }

    write_quality_checkpoint(tmp_path, checkpoint)
    assert load_quality_checkpoint(tmp_path) == checkpoint

    candidate.write_text("version two", encoding="utf-8")
    assert load_quality_checkpoint(tmp_path) is None


def test_explicit_v2_checkpoint_stays_authoritative_over_legacy_filename_score(tmp_path) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    current = "current fully passed v2 manuscript"
    (outputs / "best-candidate.md").write_text(current, encoding="utf-8")
    (outputs / "historical-best-95.md").write_text("legacy manuscript", encoding="utf-8")
    checkpoint = {
        "version": 1,
        "manuscript_path": "outputs/best-candidate.md",
        "manuscript_hash": hashlib.sha256(current.encode("utf-8")).hexdigest(),
        "score": 82,
        "scoring_profile_id": "zhihu-short-v2",
        "judge_signature": "provider/model",
        "best_attempt": 1,
        "review": {"score": 82},
        "outcome": "passed",
    }
    write_quality_checkpoint(tmp_path, checkpoint)

    reconciled = reconcile_legacy_checkpoint(tmp_path)

    assert reconciled == checkpoint
    assert reconciled["manuscript_path"] == "outputs/best-candidate.md"
