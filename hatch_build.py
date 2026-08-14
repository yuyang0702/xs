"""Hatch wheel hook embedding an independently verifiable build manifest."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict) -> None:
        if self.target_name != "wheel":
            return
        root = Path(self.root).resolve()
        module_path = root / "src" / "novel_flywheel" / "runtime_fingerprint_build.py"
        spec = importlib.util.spec_from_file_location(
            "novel_flywheel_runtime_fingerprint_build_hook", module_path,
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("runtime fingerprint build module is unavailable")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        target_dir = Path(tempfile.mkdtemp(prefix="novel-r0f-build-"))
        manifest = target_dir / module.EMBEDDED_MANIFEST_NAME
        module.write_embedded_build_manifest(root, manifest)
        build_data.setdefault("force_include", {})[str(manifest)] = (
            f"novel_flywheel/{module.EMBEDDED_MANIFEST_NAME}"
        )
