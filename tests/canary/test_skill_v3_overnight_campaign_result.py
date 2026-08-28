from __future__ import annotations

import hashlib
import json
from pathlib import Path

from novel_flywheel.runtime_fingerprint_build import domain_sha256
from tools.diagnostics import materialize_skill_v3_overnight_campaign_result as result


def test_anonymous_ids_are_stable_unique_and_do_not_disclose_slots() -> None:
    ids = {
        result._anon_id("a" * 64, pair_index, side_index)
        for pair_index in range(1, 4)
        for side_index in range(1, 3)
    }
    assert len(ids) == 6
    assert all(value.startswith("blind-") for value in ids)
    assert all(slot not in value for value in ids for slot in ("A1", "B1", "A2", "B2", "A3", "B3"))


def test_manifest_covers_nested_files_and_excludes_itself(tmp_path) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "a.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "nested" / "b.md").write_text("x\n", encoding="utf-8")
    (tmp_path / "sha256-manifest-v1.json").write_text("stale", encoding="utf-8")
    manifest = result._manifest(tmp_path, "TestManifestV1")
    assert [row["path"] for row in manifest["entries"]] == ["a.json", "nested/b.md"]
    assert manifest["entries"][0]["sha256"] == hashlib.sha256((tmp_path / "a.json").read_bytes()).hexdigest()


def test_domain_verification_rejects_tamper() -> None:
    body = {"schema": "State", "status": "SEALED_VALID"}
    sealed = {**body, "state_sha256": domain_sha256("domain", body)}
    result._verify_domain(sealed, "state_sha256", "domain")
    sealed["status"] = "STOPPED"
    try:
        result._verify_domain(sealed, "state_sha256", "domain")
    except RuntimeError as exc:
        assert str(exc) == "DOMAIN_SHA_MISMATCH:state_sha256"
    else:
        raise AssertionError("tamper accepted")


def test_privacy_scan_finds_secrets_without_persisting_them() -> None:
    clean = result._scan([json.dumps({"value": "hash-only"}).encode()])
    assert clean["status"] == "PASS"
    dirty = result._scan([b"Authorization: " + b"Bearer " + b"abcdefghijklmnop"])
    assert dirty["status"] == "FAIL"


def test_pair_order_is_complete_and_alternating_shuffle_is_balanced() -> None:
    assert result.PAIR_ORDER == (("A1", "B1"), ("A2", "B2"), ("A3", "B3"))
    visible_orders = [tuple(reversed(pair)) if index % 2 else pair for index, pair in enumerate(result.PAIR_ORDER, 1)]
    assert visible_orders == [("B1", "A1"), ("A2", "B2"), ("B3", "A3")]


def _verify_manifest(root: Path) -> None:
    manifest = json.loads((root / "sha256-manifest-v1.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "EXACT"
    assert manifest["entry_count"] == len(manifest["entries"])
    for entry in manifest["entries"]:
        data = (root / entry["path"]).read_bytes()
        assert len(data) == entry["bytes"]
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]


def test_materialized_campaign_and_blind_handoff_are_exact_and_uncontaminated() -> None:
    repo = Path(__file__).resolve().parents[2]
    campaign = repo / result.CAMPAIGN_EVIDENCE_RELATIVE
    blind = repo / result.BLIND_BUNDLE_RELATIVE
    mapping = repo / result.MAPPING_RELATIVE
    for root in (campaign, blind, mapping):
        _verify_manifest(root)
    visible = b"\n".join(path.read_bytes() for path in blind.rglob("*") if path.is_file())
    sealed_mapping = json.loads((mapping / "sealed-mapping-v1.json").read_text(encoding="utf-8"))
    for row in sealed_mapping["rows"]:
        assert row["sample_id"].encode() not in visible
    assert b'"arm": "A"' not in visible
    assert b'"arm": "B"' not in visible
