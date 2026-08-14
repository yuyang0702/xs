from pathlib import Path

import pytest

from tools.canary.hash_manifest import (
    CanaryDependencyError,
    launcher_dependency_manifest,
    validate_import_closure,
)


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
