import importlib
from pathlib import Path

import pytest

from tools.canary.hash_manifest import (
    CanaryDependencyError,
    GENERIC_CANARY_IMPORT_SCOPE_ID,
    PTR4_PROVIDER_PROBE_IMPORT_SCOPE_ID,
    PTR7_REASONING_PROBE_IMPORT_SCOPE_ID,
    launcher_dependency_manifest,
    validate_import_closure,
    validate_profile_import_closure,
)
from tools.canary.network_sentinel import FailClosedNetworkSentinel


def test_launcher_manifest_is_stable_and_byte_sensitive(tmp_path: Path) -> None:
    root = tmp_path / "canary"
    root.mkdir()
    source = root / "entry.py"
    source.write_text("import json\n", encoding="utf-8")
    first = launcher_dependency_manifest(root)
    second = launcher_dependency_manifest(root)
    assert first == second
    source.write_text("import json\nVALUE = 1\n", encoding="utf-8")
    assert launcher_dependency_manifest(root)["launcher_sha256"] != first["launcher_sha256"]


def test_import_closure_allows_only_stdlib_production_and_manifested_third_party(
    tmp_path: Path,
) -> None:
    root = tmp_path / "canary"
    root.mkdir()
    (root / "ok.py").write_text(
        "import json\nfrom novel_flywheel import runtime_fingerprint\n",
        encoding="utf-8",
    )
    validate_import_closure(root)
    (root / "bad.py").write_text("from tests import helper\n", encoding="utf-8")
    with pytest.raises(CanaryDependencyError, match="dependency_not_approved"):
        validate_import_closure(root)


@pytest.mark.parametrize("source,code", [
    ("import importlib\n", "dynamic_import_forbidden"),
    ("exec('pass')\n", "dynamic_code_forbidden"),
])
def test_import_closure_rejects_runtime_code_loading(tmp_path: Path, source: str, code: str) -> None:
    root = tmp_path / "canary"
    root.mkdir()
    (root / "entry.py").write_text(source, encoding="utf-8")
    with pytest.raises(CanaryDependencyError, match=code):
        validate_import_closure(root)


def test_real_launcher_dependency_closure_is_closed() -> None:
    root = Path(__file__).parents[2] / "tools" / "canary"
    manifest = validate_import_closure(root)
    assert manifest["files"]
    assert manifest["approved_third_party"] == []
    assert manifest["import_scope_id"] == GENERIC_CANARY_IMPORT_SCOPE_ID
    assert manifest["excluded_probe_entrypoints"] == [
        "provider_capability_probe_real.py",
        "provider_reasoning_capability_probe_real.py",
    ]
    paths = {item["path"] for item in manifest["files"]}
    assert not paths.intersection(manifest["excluded_probe_entrypoints"])


@pytest.mark.parametrize(
    ("profile_id", "included", "excluded", "approved"),
    [
        (
            PTR4_PROVIDER_PROBE_IMPORT_SCOPE_ID,
            "provider_capability_probe_real.py",
            "provider_reasoning_capability_probe_real.py",
            [],
        ),
        (
            PTR7_REASONING_PROBE_IMPORT_SCOPE_ID,
            "provider_reasoning_capability_probe_real.py",
            "provider_capability_probe_real.py",
            ["httpx"],
        ),
    ],
)
def test_explicit_probe_profile_closure_keeps_its_executable_and_dependencies(
    profile_id: str, included: str, excluded: str, approved: list[str],
) -> None:
    root = Path(__file__).parents[2] / "tools" / "canary"
    manifest = validate_profile_import_closure(root, profile_id=profile_id)
    paths = {item["path"] for item in manifest["files"]}
    assert included in paths
    assert excluded not in paths
    assert manifest["approved_third_party"] == approved
    assert manifest["import_scope_id"] == profile_id


def test_unknown_import_closure_profile_fails_closed() -> None:
    root = Path(__file__).parents[2] / "tools" / "canary"
    with pytest.raises(CanaryDependencyError, match="import_closure_profile_unknown"):
        validate_profile_import_closure(root, profile_id="unknown_canary_profile")


def test_excluded_probe_becoming_reachable_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "canary"
    root.mkdir()
    (root / "entry.py").write_text(
        "from . import provider_reasoning_capability_probe_real\n",
        encoding="utf-8",
    )
    (root / "provider_reasoning_capability_probe_real.py").write_text(
        "import httpx\n", encoding="utf-8",
    )
    with pytest.raises(CanaryDependencyError, match="excluded_module_reachable"):
        validate_import_closure(root)


def test_probe_scope_does_not_hide_a_real_dependency_failure(tmp_path: Path) -> None:
    root = tmp_path / "canary"
    root.mkdir()
    (root / "provider_reasoning_capability_probe_real.py").write_text(
        "import dependency_that_is_not_approved\n", encoding="utf-8",
    )
    with pytest.raises(CanaryDependencyError, match="dependency_not_approved"):
        validate_profile_import_closure(
            root, profile_id=PTR7_REASONING_PROBE_IMPORT_SCOPE_ID,
        )


@pytest.mark.parametrize("module_name", [
    "tools.canary.provider_capability_probe_real",
    "tools.canary.provider_reasoning_capability_probe_real",
])
def test_explicit_probe_module_import_has_no_network_side_effect(
    module_name: str,
) -> None:
    sentinel = FailClosedNetworkSentinel()
    with sentinel:
        importlib.import_module(module_name)
    assert sentinel.network_call_count == 0
