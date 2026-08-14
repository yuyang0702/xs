from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from r0_incident_corpus import build_incident_manifest, file_sha256
from r0_replay_harness import high_frequency_incidents, replay_incident


ROOT = Path(__file__).resolve().parents[1]
LIVE_DB = ROOT / "data" / "app.db"
INCIDENTS = high_frequency_incidents(build_incident_manifest(LIVE_DB))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("variant", "incident"), enumerate(INCIDENTS),
    ids=[item["incident_id"] for item in INCIDENTS],
)
async def test_high_frequency_incident_runs_through_current_runtime_in_isolation(
    tmp_path: Path, variant: int, incident: dict,
) -> None:
    live_before = file_sha256(LIVE_DB)
    result = await replay_incident(
        tmp_path / "r0", incident, variant=variant,
    )

    assert result["isolation_namespace"] == "r0-replay"
    assert result["database_name"] == "replay-only.db"
    assert result["provider"] == "offline-deterministic"
    assert result["paid_llm_calls"] == 0
    assert result["planning_model_attempts"] >= 1
    assert result["boundary_recovered"] is True
    assert result["stage_recovered"] is True
    assert result["workflow_recovered"] is True, result
    assert result["final_terminal_outcome"] == "WORKFLOW_RECOVERED", result
    assert file_sha256(LIVE_DB) == live_before
    assert not any(
        path.name == "app.db" for path in tmp_path.rglob("*")
    )
    assert hashlib.sha256(
        incident["incident_id"].encode("utf-8"),
    ).hexdigest()
