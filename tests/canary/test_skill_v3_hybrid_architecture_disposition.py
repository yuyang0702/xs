from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs/superpowers/reports/skill-v3-hybrid-character-heavy-architecture-disposition-v1"


class SkillV3HybridArchitectureDispositionTest(unittest.TestCase):
    def load(self, name: str) -> dict:
        return json.loads((REPORT / name).read_text(encoding="utf-8"))

    def test_final_decision_and_stop_loss_are_exact(self) -> None:
        decision = self.load("final-quality-decision-binding-v1.json")
        stop = self.load("stop-loss-binding-v1.json")
        self.assertEqual(decision["narrative_non_inferior"], "NO")
        self.assertEqual(decision["engineering_non_inferior"], "YES")
        self.assertEqual(decision["pilot_disposition"], "NO_GO_QUALITY")
        self.assertEqual(decision["critical_dimensions"]["setup_payoff_integrity"], "REGRESSION")
        self.assertEqual(stop["hybrid_stop_loss_active"], "YES")

    def test_production_disposition_is_baseline_and_retired(self) -> None:
        item = self.load("model-visible-architecture-disposition-v1.json")
        self.assertEqual(item["production_skill_path"], "CURRENT_BASELINE_SKILL_GATE_PLUS_SKILL_PROMPT_COMPACTOR")
        self.assertEqual(item["selective_replacement_retired"], "YES")
        self.assertEqual(item["hybrid_model_visible_supplement_retired_for_current_short_path"], "YES")
        self.assertEqual(item["no_remaining_demand_class_validation_for_current_hybrid"], "YES")

    def test_accidental_cutover_and_identity_are_closed(self) -> None:
        item = self.load("accidental-cutover-safety-v1.json")
        self.assertEqual(item["failed_skill_v3_path_accidental_cutover_count"], 0)
        self.assertEqual(item["production_baseline_prompt_bytes_unchanged"], "YES")
        self.assertEqual(item["production_model_input_identity_unchanged"], "YES")
        workflows = (ROOT / "src/novel_flywheel/workflows.py").read_text(encoding="utf-8")
        production = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "src/novel_flywheel").rglob("*.py")
        )
        self.assertIn("hybrid_skill_context_shadow_enabled: bool = False", workflows)
        self.assertNotRegex(production, r"hybrid_skill_context_shadow_enabled\s*=\s*True")

    def test_short_blockers_are_reduced(self) -> None:
        matrix = self.load("full-short-blocker-matrix-v1.json")
        self.assertEqual(matrix["hard_blocker_count"], 2)
        self.assertEqual(matrix["conditional_hard_blocker_count"], 1)
        self.assertEqual({b["blocker_id"] for b in matrix["blockers"]}, {
            "FSB-PLANNING-CONVERGENCE", "FSB-DRAFT-REPAIR-OWNERSHIP", "FSB-SELECTED-STYLE-FIDELITY"
        })
        self.assertIn("canonical V2 cutover", matrix["not_promoted_to_blocker"])

    def test_next_gate_is_consolidated_and_offline_first(self) -> None:
        item = self.load("next-master-gate-v1.json")
        self.assertEqual(item["exact_next_gate"], "SHORT_TRUSTWORTHY_FULL_FLOW_READINESS_AND_CUTOVER_MASTER")
        self.assertIn("real Provider call", item["excluded"])
        self.assertIn("Full Short execution", item["excluded"])

    def test_child_receipts_are_independent_and_offline(self) -> None:
        for name in (
            "child-agent-a-literary-architecture-review-v1.json",
            "child-agent-b-delivery-simplification-review-v1.json",
        ):
            receipt = self.load(name)
            self.assertTrue(receipt["frozen"])
            self.assertEqual(receipt["independence"]["fork_turns"], "none")
            self.assertEqual(receipt["independence"]["external_calls"], 0)

    def test_manifest_is_exact(self) -> None:
        manifest = self.load("sha256-manifest-v1.json")
        self.assertEqual(manifest["entry_count"], len(manifest["entries"]))
        for entry in manifest["entries"]:
            path = ROOT / entry["path"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry["sha256"])
            self.assertEqual(path.stat().st_size, entry["bytes"])

    def test_privacy_and_external_actions(self) -> None:
        privacy = self.load("privacy-scan-v1.json")
        self.assertEqual(privacy["status"], "PASS")
        self.assertEqual(sum(privacy["external_actions"].values()), 0)
        self.assertFalse(privacy["raw_prompt_persisted"])
        self.assertFalse(privacy["raw_story_persisted"])


if __name__ == "__main__":
    unittest.main()
