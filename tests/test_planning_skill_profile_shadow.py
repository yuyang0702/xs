from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "tools/diagnostics/planning_skill_profile_shadow.py"


def test_shadow_diagnostic_check_only_is_offline_and_exact(tmp_path: Path):
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(REPO), "--output-dir", str(tmp_path), "--check-only"],
        cwd=REPO, capture_output=True, text=True, check=True,
    )
    result = json.loads(completed.stdout)
    assert result["overall_status"] == "exact"
    assert result["external_actions"] == {
        "credential": 0, "provider_client": 0, "network": 0, "model": 0, "paid": 0,
    }
    assert result["production_reachable"] is False
    assert result["prompt_byte_runtime_replay"] == "NOT_RUN_SAFE_BOUNDARY"
    assert list(tmp_path.iterdir()) == []


def test_shadow_module_has_no_production_import_reachability():
    result = subprocess.run(
        ["git", "grep", "-n", "runtime_skill_profiles", "--", "src/novel_flywheel"],
        cwd=REPO, capture_output=True, text=True,
    )
    hits = [line for line in result.stdout.splitlines() if "runtime_skill_profiles.py:" not in line]
    assert hits == []
