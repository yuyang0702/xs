from __future__ import annotations

from pathlib import Path


def test_python_sources_contain_no_private_use_mojibake() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "novel_flywheel"
    findings: list[str] = []
    for path in sorted(root.rglob("*.py")):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1,
        ):
            if any(0xE000 <= ord(character) <= 0xF8FF for character in line):
                findings.append(f"{path.relative_to(root)}:{line_number}")
    assert findings == []


def test_style_analysis_has_one_reachable_prompt_authority() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src" / "novel_flywheel" / "style_samples.py"
    ).read_text(encoding="utf-8")
    assert "system=runtime_system or" not in source
    assert "user=runtime_user or" not in source


def test_deprecated_startup_and_raw_error_helper_are_removed() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "novel_flywheel"
    app_source = (root / "app.py").read_text(encoding="utf-8")
    assert '@app.on_event("startup")' not in app_source
    assert "lifespan=_application_lifespan" in app_source
    assert not (root / "errors.py").exists()
