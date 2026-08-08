from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


CORE_EXACT_PATHS = {
    "src/novel_flywheel/causal_chain.py",
    "src/novel_flywheel/context_packet.py",
    "src/novel_flywheel/db.py",
    "src/novel_flywheel/draft_split.py",
    "src/novel_flywheel/execution_manifest.py",
    "src/novel_flywheel/incremental_review.py",
    "src/novel_flywheel/learning.py",
    "src/novel_flywheel/memory.py",
    "src/novel_flywheel/migration.py",
    "src/novel_flywheel/model_output.py",
    "src/novel_flywheel/models.py",
    "src/novel_flywheel/narrative_ledger.py",
    "src/novel_flywheel/outlines.py",
    "src/novel_flywheel/planning_adaptation.py",
    "src/novel_flywheel/planning_recovery.py",
    "src/novel_flywheel/projects.py",
    "src/novel_flywheel/publication.py",
    "src/novel_flywheel/secrets.py",
    "src/novel_flywheel/skill_runtime.py",
    "src/novel_flywheel/skills.py",
    "src/novel_flywheel/storage.py",
    "src/novel_flywheel/story_state.py",
    "src/novel_flywheel/tasks.py",
    "src/novel_flywheel/tools.py",
    "src/novel_flywheel/workflows.py",
    "src/novel_flywheel/api/projects.py",
    "src/novel_flywheel/api/providers.py",
    "src/novel_flywheel/api/revisions.py",
    "src/novel_flywheel/api/runs.py",
    "src/novel_flywheel/api/skills.py",
    "src/novel_flywheel/api/wizards.py",
}
CORE_PREFIXES = (
    "src/novel_flywheel/api/",
    "src/novel_flywheel/context_",
    "src/novel_flywheel/planning_",
    "src/novel_flywheel/providers/",
    "src/novel_flywheel/prose_",
    "src/novel_flywheel/quality",
    "src/novel_flywheel/reference_",
    "src/novel_flywheel/repair_",
    "src/novel_flywheel/revision",
    "src/novel_flywheel/style_",
)
USER_VISIBLE_PREFIXES = (
    "src/novel_flywheel/static/",
    "src/novel_flywheel/api/",
)
UI_PREFIXES = ("src/novel_flywheel/static/",)
PROTECTED_PREFIXES = ("data/", "manuscript/", "runs/")
DOCUMENTATION_PATHS = {"README.md", "docs/maintenance.md"}
LEVEL_ORDER = {"L1": 1, "L2": 2, "L3": 3}
FORWARD_RISK_DISPOSITIONS = {
    "fixed_and_tested",
    "tested_not_susceptible",
    "not_applicable",
}
SCOPE_CLASSIFICATIONS = {"open_world", "closed_world"}
RESOLUTION_STATUSES = {
    "contained",
    "case_fixed",
    "systemically_resolved",
    "unresolved",
}


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
    )


def _decode_path(value: bytes) -> str:
    return value.decode("utf-8", errors="surrogateescape").replace("\\", "/")


def _parse_status_z(raw: bytes) -> list[str]:
    chunks = raw.split(b"\0")
    paths: list[str] = []
    index = 0
    while index < len(chunks):
        entry = chunks[index]
        if not entry:
            index += 1
            continue
        if len(entry) < 4:
            raise RuntimeError("malformed git porcelain entry")
        status = entry[:2].decode("ascii", errors="replace")
        paths.append(_decode_path(entry[3:]))
        if "R" in status or "C" in status:
            index += 1
            if index >= len(chunks) or not chunks[index]:
                raise RuntimeError("malformed git rename/copy entry")
            paths.append(_decode_path(chunks[index]))
        index += 1
    return sorted(set(paths))


def _status_paths(root: Path) -> list[str]:
    result = _git(
        root,
        "-c",
        "core.quotepath=false",
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(message or "git status failed")
    return _parse_status_z(result.stdout)


def _fingerprint(root: Path, relative: str) -> dict[str, object]:
    path = root / relative
    if not path.exists():
        return {"exists": False}
    if path.is_dir():
        return {"exists": True, "kind": "directory"}
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"exists": True, "kind": "file", "sha256": digest}


def _worktree_state(root: Path) -> dict[str, dict[str, object]]:
    return {path: _fingerprint(root, path) for path in _status_paths(root)}


def _task_changed_paths(
    baseline: dict[str, dict[str, object]],
    current: dict[str, dict[str, object]],
) -> list[str]:
    return sorted(
        path
        for path in set(baseline) | set(current)
        if baseline.get(path) != current.get(path)
    )


def _is_core(path: str) -> bool:
    return path in CORE_EXACT_PATHS or any(path.startswith(prefix) for prefix in CORE_PREFIXES)


def _expected_tests(source_path: str) -> set[str]:
    path = Path(source_path)
    stem = path.stem
    if "/api/" in source_path:
        return {f"tests/api/test_{stem}.py"}
    return {f"tests/test_{stem}.py"}


def _classify(
    changed: list[str], related_tests: dict[str, set[str]] | None = None,
    declared_level: str | None = None,
) -> dict[str, object]:
    declared_test_map = {
        source.replace("\\", "/"): {test.replace("\\", "/") for test in tests}
        for source, tests in (related_tests or {}).items()
    }
    source = [path for path in changed if path.startswith("src/") and path.endswith(".py")]
    tests = [path for path in changed if path.startswith("tests/") and path.endswith(".py")]
    docs = [path for path in changed if path in DOCUMENTATION_PATHS]
    core = [path for path in changed if _is_core(path)]
    user_visible = [path for path in changed if path.startswith(USER_VISIBLE_PREFIXES)]
    ui = [path for path in changed if path.startswith(UI_PREFIXES)]
    protected = [
        path for path in changed if any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES)
    ]
    warnings: list[str] = []
    blockers: list[str] = []
    changed_tests = set(tests)

    missing_associations: list[str] = []
    for source_path in source:
        expected = _expected_tests(source_path)
        mapped = declared_test_map.get(source_path, set())
        if not expected & changed_tests and not mapped:
            missing_associations.append(
                f"{source_path} -> one of {', '.join(sorted(expected))}"
            )
    if missing_associations:
        warnings.append(
            "No task-local regression test was changed or explicitly mapped for: "
            + "; ".join(missing_associations)
        )

    missing_ui = [
        path
        for path in ui
        if "tests/test_console.py" not in changed_tests
        and not declared_test_map.get(path)
    ]
    if missing_ui:
        warnings.append(
            "User-visible UI paths changed without task-local tests/test_console.py "
            "or an explicit source=test mapping: " + ", ".join(missing_ui)
        )
    if core and not docs:
        warnings.append(
            "Authority-critical code changed without task-local README.md or docs/maintenance.md."
        )
    if len(core) > 2:
        warnings.append("More than two authority-critical modules changed; require an L3 split review.")
    if protected:
        blockers.append(
            "Protected project/runtime artifacts appear in the task change: "
            + ", ".join(protected)
        )

    automatic_level = "L3" if core or protected else "L2" if source or user_visible else "L1"
    level = automatic_level
    if declared_level and LEVEL_ORDER[declared_level] > LEVEL_ORDER[level]:
        level = declared_level
    return {
        "recommended_level": level,
        "automatic_level": automatic_level,
        "declared_level": declared_level,
        "changed_paths": changed,
        "source_paths": source,
        "test_paths": tests,
        "declared_related_tests": {
            source: sorted(tests) for source, tests in sorted(declared_test_map.items())
        },
        "core_paths": core,
        "user_visible_paths": user_visible,
        "ui_paths": ui,
        "documentation_paths": docs,
        "warnings": warnings,
        "blockers": blockers,
    }


def _save_baseline(path: Path, repository: Path) -> None:
    payload = {
        "version": 1,
        "repository": str(repository),
        "state": _worktree_state(repository),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_baseline(path: Path, repository: Path) -> dict[str, dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1:
        raise RuntimeError("unsupported baseline version")
    if Path(str(payload.get("repository", ""))).resolve() != repository:
        raise RuntimeError("baseline repository does not match current repository")
    state = payload.get("state")
    if not isinstance(state, dict):
        raise RuntimeError("baseline state is invalid")
    return state


def _related_test_mappings(
    values: list[str], repository: Path, changed: list[str],
) -> dict[str, set[str]]:
    mappings: dict[str, set[str]] = {}
    changed_set = set(changed)
    tests_root = (repository / "tests").resolve()
    for value in values:
        if "=" not in value:
            raise RuntimeError(
                "--related-test must use CHANGED_SOURCE=TEST_PATH syntax"
            )
        source, test = (item.strip().replace("\\", "/") for item in value.split("=", 1))
        if not source or not test:
            raise RuntimeError("--related-test source and test paths must be non-empty")
        if source not in changed_set:
            raise RuntimeError(f"related-test source is not task-changed: {source}")
        if not test.startswith("tests/") or not test.endswith(".py"):
            raise RuntimeError(f"related-test must be a Python file under tests/: {test}")
        test_path = (repository / test).resolve()
        try:
            test_path.relative_to(tests_root)
        except ValueError as exc:
            raise RuntimeError(f"related-test escapes the tests directory: {test}") from exc
        if not test_path.is_file():
            raise RuntimeError(f"related-test does not exist: {test}")
        canonical_test = test_path.relative_to(repository).as_posix()
        mappings.setdefault(source, set()).add(canonical_test)
    return mappings


def _repository_test_path(repository: Path, value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{field} entries must be non-empty test paths")
    relative = value.strip().replace("\\", "/")
    if not relative.startswith("tests/") or not relative.endswith(".py"):
        raise RuntimeError(f"{field} must contain Python files under tests/: {relative}")
    tests_root = (repository / "tests").resolve()
    test_path = (repository / relative).resolve()
    try:
        test_path.relative_to(tests_root)
    except ValueError as exc:
        raise RuntimeError(f"{field} path escapes the tests directory: {relative}") from exc
    if not test_path.is_file():
        raise RuntimeError(f"{field} test does not exist: {relative}")
    return test_path.relative_to(repository).as_posix()


def _non_empty_strings(payload: dict[str, object], field: str) -> list[str]:
    values = payload.get(field)
    if not isinstance(values, list) or not values:
        raise RuntimeError(f"forward-risk report requires non-empty {field}")
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(
                f"forward-risk report {field} entries must be non-empty strings"
            )
        normalized.append(value.strip())
    return normalized


def _non_empty_string(payload: dict[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"forward-risk report requires non-empty {field}")
    return value.strip()


def _constraint_traceability(
    payload: dict[str, object], repository: Path,
) -> list[dict[str, object]]:
    values = payload.get("constraint_traceability")
    if not isinstance(values, list) or not values:
        raise RuntimeError(
            "forward-risk report requires non-empty constraint_traceability"
        )
    normalized: list[dict[str, object]] = []
    for index, raw in enumerate(values, 1):
        if not isinstance(raw, dict):
            raise RuntimeError(
                f"constraint_traceability[{index}] must be an object"
            )
        requirement = raw.get("requirement")
        implementation = raw.get("implementation")
        evidence = raw.get("evidence")
        if not isinstance(requirement, str) or not requirement.strip():
            raise RuntimeError(
                f"constraint_traceability[{index}] requires requirement"
            )
        if not isinstance(implementation, str) or not implementation.strip():
            raise RuntimeError(
                f"constraint_traceability[{index}] requires implementation"
            )
        if not isinstance(evidence, str) or not evidence.strip():
            raise RuntimeError(
                f"constraint_traceability[{index}] requires evidence"
            )
        test_paths = raw.get("test_paths")
        if not isinstance(test_paths, list) or not test_paths:
            raise RuntimeError(
                f"constraint_traceability[{index}] requires non-empty test_paths"
            )
        normalized_paths = [
            _repository_test_path(
                repository, value,
                field=f"constraint_traceability[{index}].test_paths",
            )
            for value in test_paths
        ]
        normalized.append({
            "requirement": requirement.strip(),
            "implementation": implementation.strip(),
            "test_paths": sorted(set(normalized_paths)),
            "evidence": evidence.strip(),
        })
    return normalized


def _load_forward_risk_report(path: Path, repository: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != 2:
        raise RuntimeError("forward-risk report must be a version 2 JSON object")

    original_requirement = _non_empty_string(payload, "original_requirement")
    scope_classification = payload.get("scope_classification")
    if scope_classification not in SCOPE_CLASSIFICATIONS:
        raise RuntimeError(
            "forward-risk report scope_classification must be one of "
            + ", ".join(sorted(SCOPE_CLASSIFICATIONS))
        )
    operational_definition = _non_empty_string(payload, "operational_definition")
    forbidden_narrowing = _non_empty_strings(payload, "forbidden_narrowing")
    resolution_status = payload.get("resolution_status")
    if resolution_status not in RESOLUTION_STATUSES:
        raise RuntimeError(
            "forward-risk report resolution_status must be one of "
            + ", ".join(sorted(RESOLUTION_STATUSES))
        )
    closed_world_justification = ""
    if scope_classification == "closed_world":
        closed_world_justification = _non_empty_string(
            payload, "closed_world_justification"
        )
    traceability = _constraint_traceability(payload, repository)

    historical = _non_empty_strings(payload, "historical_incident_families_checked")
    mechanisms = _non_empty_strings(payload, "projected_failure_mechanisms")
    model_boundary_changed = payload.get("model_output_boundary_changed")
    if not isinstance(model_boundary_changed, bool):
        raise RuntimeError(
            "forward-risk report requires boolean model_output_boundary_changed"
        )
    variants: list[str] = []
    invalid_variants: list[str] = []
    fault_variants: list[str] = []
    invariant_tests: list[str] = []
    topology_classes: list[str] = []
    unseen_variants: list[str] = []
    unknown_variant_behavior = ""
    not_applicable_evidence = ""
    if model_boundary_changed:
        variants = _non_empty_strings(payload, "model_output_variants_tested")
        invalid_variants = _non_empty_strings(
            payload, "invalid_output_variants_tested"
        )
        fault_variants = _non_empty_strings(
            payload, "transport_capacity_variants_tested"
        )
        topology_classes = _non_empty_strings(
            payload, "model_output_topology_classes_tested"
        )
        unseen_variants = _non_empty_strings(
            payload, "unseen_valid_variants_tested"
        )
        unknown_variant_behavior = _non_empty_string(
            payload, "unknown_variant_behavior"
        )
        if len(variants) < 6:
            raise RuntimeError(
                "forward-risk report requires at least six materially different "
                "model_output_variants_tested"
            )
        if len(invalid_variants) < 2:
            raise RuntimeError(
                "forward-risk report requires at least two invalid_output_variants_tested"
            )
        if len(fault_variants) < 2:
            raise RuntimeError(
                "forward-risk report requires at least two "
                "transport_capacity_variants_tested"
            )
        if len({value.casefold() for value in topology_classes}) < 4:
            raise RuntimeError(
                "forward-risk report requires at least four distinct "
                "model_output_topology_classes_tested"
            )
        if len({value.casefold() for value in unseen_variants}) < 2:
            raise RuntimeError(
                "forward-risk report requires at least two distinct "
                "unseen_valid_variants_tested"
            )
        invariant_tests = [
            _repository_test_path(repository, value, field="invariant_test_paths")
            for value in _non_empty_strings(payload, "invariant_test_paths")
        ]
    else:
        evidence = payload.get("model_output_not_applicable_evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            raise RuntimeError(
                "forward-risk report requires model_output_not_applicable_evidence when "
                "model_output_boundary_changed is false"
            )
        not_applicable_evidence = evidence.strip()
    why_missed = payload.get("why_previous_tests_missed")
    if not isinstance(why_missed, str) or not why_missed.strip():
        raise RuntimeError("forward-risk report requires why_previous_tests_missed")

    boundaries = payload.get("sibling_boundaries")
    if not isinstance(boundaries, list) or not boundaries:
        raise RuntimeError("forward-risk report requires non-empty sibling_boundaries")
    normalized_boundaries: list[dict[str, str]] = []
    for index, item in enumerate(boundaries, 1):
        if not isinstance(item, dict):
            raise RuntimeError(f"sibling_boundaries[{index}] must be an object")
        boundary = item.get("boundary")
        disposition = item.get("disposition")
        evidence = item.get("evidence")
        if not isinstance(boundary, str) or not boundary.strip():
            raise RuntimeError(f"sibling_boundaries[{index}] requires boundary")
        if disposition not in FORWARD_RISK_DISPOSITIONS:
            raise RuntimeError(
                f"sibling_boundaries[{index}] disposition must be one of "
                + ", ".join(sorted(FORWARD_RISK_DISPOSITIONS))
            )
        if not isinstance(evidence, str) or not evidence.strip():
            raise RuntimeError(f"sibling_boundaries[{index}] requires concrete evidence")
        normalized_boundaries.append({
            "boundary": boundary.strip(),
            "disposition": disposition,
            "evidence": evidence.strip(),
        })

    production_tests = [
        _repository_test_path(repository, value, field="production_shaped_tests")
        for value in _non_empty_strings(payload, "production_shaped_tests")
    ]
    boundary_tests = [
        _repository_test_path(repository, value, field="next_authoritative_boundary_tests")
        for value in _non_empty_strings(payload, "next_authoritative_boundary_tests")
    ]
    remaining = payload.get("remaining_risks", [])
    if not isinstance(remaining, list) or any(
        not isinstance(value, str) or not value.strip() for value in remaining
    ):
        raise RuntimeError("forward-risk report remaining_risks must be a list of strings")

    return {
        "version": 2,
        "original_requirement": original_requirement,
        "scope_classification": scope_classification,
        "operational_definition": operational_definition,
        "forbidden_narrowing": forbidden_narrowing,
        "resolution_status": resolution_status,
        "closed_world_justification": closed_world_justification,
        "constraint_traceability": traceability,
        "historical_incident_families_checked": historical,
        "projected_failure_mechanisms": mechanisms,
        "model_output_boundary_changed": model_boundary_changed,
        "model_output_variants_tested": variants,
        "invalid_output_variants_tested": invalid_variants,
        "transport_capacity_variants_tested": fault_variants,
        "model_output_topology_classes_tested": topology_classes,
        "unseen_valid_variants_tested": unseen_variants,
        "unknown_variant_behavior": unknown_variant_behavior,
        "model_output_not_applicable_evidence": not_applicable_evidence,
        "why_previous_tests_missed": why_missed.strip(),
        "sibling_boundaries": normalized_boundaries,
        "production_shaped_tests": sorted(set(production_tests)),
        "next_authoritative_boundary_tests": sorted(set(boundary_tests)),
        "invariant_test_paths": sorted(set(invariant_tests)),
        "remaining_risks": [value.strip() for value in remaining],
    }


def _forward_risk_completion_warnings(report: dict[str, object]) -> list[str]:
    warnings: list[str] = []
    status = report.get("resolution_status")
    scope = report.get("scope_classification")
    if status in {"contained", "unresolved"}:
        warnings.append(
            f"Forward-risk report resolution_status={status}; containment or an "
            "unresolved path cannot satisfy completion."
        )
    if scope == "open_world" and status != "systemically_resolved":
        warnings.append(
            "Open-world requirements require resolution_status=systemically_resolved; "
            "a case-only or containment result must not be reported complete."
        )
    return warnings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect task-local changes against project regression-gate heuristics."
    )
    parser.add_argument("--save-baseline", type=Path, metavar="FILE")
    parser.add_argument("--baseline", type=Path, metavar="FILE")
    parser.add_argument(
        "--forward-risk-report",
        type=Path,
        metavar="FILE",
        help=(
            "Versioned JSON evidence that historical incidents, future sibling paths, and "
            "non-deterministic model-output variants were tested."
        ),
    )
    parser.add_argument(
        "--related-test",
        action="append",
        default=[],
        metavar="CHANGED_SOURCE=TEST_PATH",
    )
    parser.add_argument("--declared-level", choices=tuple(LEVEL_ORDER))
    parser.add_argument(
        "--strict", action="store_true", help="Return non-zero when warnings remain."
    )
    args = parser.parse_args()

    if args.save_baseline and args.baseline:
        parser.error("--save-baseline and --baseline are mutually exclusive")

    repository = Path(__file__).resolve().parents[4]
    if args.save_baseline:
        try:
            _save_baseline(args.save_baseline.resolve(), repository)
        except (OSError, RuntimeError, ValueError) as exc:
            print(json.dumps({"ok": False, "blockers": [str(exc)]}, ensure_ascii=False))
            return 2
        print(
            json.dumps(
                {"ok": True, "baseline": str(args.save_baseline.resolve())},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    try:
        current = _worktree_state(repository)
        if args.baseline:
            baseline = _load_baseline(args.baseline.resolve(), repository)
            changed = _task_changed_paths(baseline, current)
            baseline_used = True
        else:
            changed = sorted(current)
            baseline_used = False
        related_tests = _related_test_mappings(args.related_test, repository, changed)
        report = _classify(changed, related_tests, args.declared_level)
        forward_risk_report = (
            _load_forward_risk_report(args.forward_risk_report.resolve(), repository)
            if args.forward_risk_report else None
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "blockers": [str(exc)]}, ensure_ascii=False))
        return 2

    warnings = list(report["warnings"])
    blockers = list(report["blockers"])
    if args.strict and not baseline_used and (
        report["source_paths"] or report["user_visible_paths"]
    ):
        warnings.insert(
            0,
            "Strict source/UI inspection requires --baseline so unrelated dirty files cannot "
            "satisfy task-local test or documentation gates.",
        )
    if (
        args.strict
        and report["source_paths"]
        and LEVEL_ORDER[str(report["recommended_level"])] >= LEVEL_ORDER["L2"]
        and forward_risk_report is None
    ):
        warnings.append(
            "Strict L2/L3 source inspection requires --forward-risk-report with historical "
            "incident projection, model-output variants, production-shaped tests, and "
            "next-authoritative-boundary evidence."
        )
    if args.strict and forward_risk_report is not None:
        warnings.extend(_forward_risk_completion_warnings(forward_risk_report))

    payload = {
        "ok": not blockers and not (args.strict and warnings),
        "baseline_used": baseline_used,
        "forward_risk_report": forward_risk_report,
        **report,
        "warnings": warnings,
        "blockers": blockers,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if blockers:
        return 2
    if args.strict and warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
