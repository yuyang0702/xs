from pathlib import Path

from r0_incident_corpus import (
    build_incident_manifest,
    event_time_epoch,
    manifest_summary,
    post_fix_exposure,
)


ROOT = Path(__file__).resolve().parents[1]
LIVE_DB = ROOT / "data" / "app.db"


def test_fix_epoch_names_do_not_claim_an_unknown_runtime_build() -> None:
    assert event_time_epoch("2026-08-12 04:00:00") == "pre_fix"
    assert event_time_epoch("2026-08-12 05:00:00") == "migration_window"
    assert event_time_epoch("2026-08-12 16:12:48") == (
        "post_declared_pre_hardening"
    )
    assert event_time_epoch("2026-08-13 07:00:00") == "post_hardening"
    assert event_time_epoch(None) == "unknown_time"


def test_live_incident_manifest_preserves_stored_and_current_identity() -> None:
    manifest = build_incident_manifest(LIVE_DB)
    summary = manifest_summary(manifest)

    assert summary["incident_count"] == 123
    assert summary["stable_key_count"] == 54
    assert summary["family_count"] == 45
    assert summary["high_frequency_count"] == 26
    assert summary["unclassified_count"] == 44
    assert sum(
        1 for item in manifest["incidents"]
        if item["primary_live_scope"]
        and item["current_reclassified_family"].startswith("unclassified.")
    ) == 6
    assert summary["epochs"] == {
        "migration_window": 3,
        "post_declared_pre_hardening": 1,
        "pre_fix": 119,
    }
    assert all(
        "stored_incident_key" in item
        and "stored_historical_family" in item
        and item["current_reclassified_family"]
        and item["incident_catalog_version"].startswith("sha256:")
        and item["reclassification_reason"]
        for item in manifest["incidents"]
    )

    post_declared = [
        item for item in manifest["incidents"]
        if item["event_time_epoch"] == "post_declared_pre_hardening"
    ]
    assert len(post_declared) == 1
    assert post_declared[0]["runtime_build_status"] == "unknown_runtime"


def test_post_fix_exposure_uses_started_workflows_as_denominator() -> None:
    exposure = post_fix_exposure(LIVE_DB)
    post_hardening = exposure["epochs"]["post_d22a28f"]

    assert "short_workflow_started" in post_hardening
    assert "model_stage_attempts" in post_hardening
    assert "terminal_failures" in post_hardening
    if post_hardening["short_workflow_started"] == 0:
        assert post_hardening["production_exposure_sufficient"] is False
