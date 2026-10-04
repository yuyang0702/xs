"""Offline Foundation Gate attestation for the Short Runtime closure.

This command never opens a Provider client.  It inspects the same coordinator
object used by the application and writes only safe hashes/identities.  A
caller must provide independent production-shaped test evidence for F8; the
command intentionally refuses to manufacture that result.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from novel_flywheel.reliability_spine import CanonicalDispatchCoordinator


def _valid_f8_evidence(path: Path | None, spine: CanonicalDispatchCoordinator) -> bool:
    if path is None or not path.is_file():
        return False
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(value, dict):
        return False
    if value.get("schema") not in {
        "ShortRuntimeReliabilityCoreMatrixV1",
        "NegativeOldPathReachabilityMatrixV1",
    }:
        return False
    if value.get("provider_http_performed") is not False:
        return False
    if value.get("release_build_id") != spine.release.build_id:
        return False
    if value.get("runtime_path_id") != spine.release.runtime_path_id:
        return False
    checks = value.get("checks")
    return isinstance(checks, dict) and bool(checks) and all(checks.values())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--f8-evidence", type=Path)
    parser.add_argument("--worker-fencing-id", default=None)
    args = parser.parse_args()

    spine = CanonicalDispatchCoordinator(
        args.data_root, require_release=True,
        worker_fencing_id=args.worker_fencing_id,
    )
    attestation = spine.attest()
    negative = spine.negative_old_path_reachability_matrix()
    gates = {
        "F1_CANONICAL_EPISODE_IDENTITY": "PASS",
        "F2_PHYSICAL_REQUEST_LEDGER": "PASS" if spine.ledger_path.parent.is_dir() else "FAIL",
        "F3_TYPED_FAILURE_GRAPH": "PASS" if spine.failures.path.parent.is_dir() else "FAIL",
        "F4_NODE_LEVEL_DURABLE_STATE": "PASS" if spine.nodes.root.is_dir() else "FAIL",
        "F5_CAPTURE_MANIFEST": "PASS" if spine.manifest_root.is_dir() else "FAIL",
        "F6_SINGLE_RECOVERY_COORDINATOR": "PASS" if spine.recovery.version else "FAIL",
        "F7_RELEASE_BUILD_IDENTITY_AND_WORKER_FENCING": (
            "PASS" if attestation.get("release_build_id") and
            attestation.get("worker_fencing_id") and
            attestation.get("runtime_path_id") else "FAIL"
        ),
        "F8_PRODUCTION_SHAPED_CORE_MATRIX": (
            "PASS" if _valid_f8_evidence(args.f8_evidence, spine) else "PENDING"
        ),
    }
    result = {
        "schema": "ShortRuntimeReliabilityFoundationAttestationV1",
        "provider_http_performed": False,
        "attestation": attestation,
        "negative_old_path_reachability": negative,
        "gates": gates,
        "all_foundation_gates_pass": all(value == "PASS" for value in gates.values()),
        "f8_evidence": str(args.f8_evidence) if args.f8_evidence else None,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
