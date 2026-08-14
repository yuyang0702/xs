from pathlib import Path

from r0_incident_corpus import build_incident_manifest
from r0_report_builder import (
    family_level_report,
    incident_level_report,
    primary_scope_unclassified,
    residual_terminal_families,
    short_stage_coverage_matrix,
)


ROOT = Path(__file__).resolve().parents[1]


def test_stage_coverage_matrix_keeps_mixed_and_bypass_paths_visible() -> None:
    matrix = short_stage_coverage_matrix(ROOT)
    rows = {row["stage"]: row for row in matrix["rows"]}

    assert list(rows) == [
        "Planning", "Causal", "Manifest", "Draft", "Semantic Review",
        "Quality", "Maintenance", "Repair",
    ]
    assert rows["Planning"]["unified_contract_runtime"] == "yes"
    assert rows["Draft"]["unified_contract_runtime"] == "partial"
    assert rows["Maintenance"]["unified_contract_runtime"] == "no"
    assert rows["Maintenance"]["protocol_retry_consistent"] == "no_manual_loop"
    assert rows["Repair"]["unified_contract_runtime"] == "partial"
    assert all(row["caller"] and row["callee"] for row in rows.values())


def test_reports_cover_every_incident_and_six_primary_unclassified_rows() -> None:
    manifest = build_incident_manifest(ROOT / "data" / "app.db")
    incidents = incident_level_report(manifest)
    families = family_level_report(incidents)
    residual = residual_terminal_families(families)

    assert incidents["incident_count"] == 123
    assert sum(
        row["workflow_recovered"] is True for row in incidents["rows"]
    ) == 26
    assert len(primary_scope_unclassified(incidents)) == 6
    assert len(families["rows"]) == 45
    assert residual["incident_count"] == 97
    assert residual["family_count"] >= 43
