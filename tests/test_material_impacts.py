import json
from pathlib import Path

import pytest

from novel_flywheel.material_impacts import MaterialImpactService


class FakeGateway:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    async def complete(self, role, system, user, max_output_tokens=None):
        return type("Result", (), {"text": json.dumps(self.payload, ensure_ascii=False)})()


def test_character_edit_creates_persistent_pending_impact(tmp_path: Path) -> None:
    service = MaterialImpactService(FakeGateway({}))

    impact = service.record(
        "book", tmp_path, "characters/lin.md",
        "## Personality\n\nCarries a notebook.",
        "## Personality\n\nTrusts her memory.",
        retire_removed_settings=True,
    )

    assert impact is not None
    assert impact["status"] == "pending"
    assert impact["removed_lines"] == ["Carries a notebook."]
    assert service.list(tmp_path)[0]["id"] == impact["id"]


def test_character_edit_can_skip_link_analysis(tmp_path: Path) -> None:
    service = MaterialImpactService(FakeGateway({}))

    impact = service.record(
        "book", tmp_path, "characters/lin.md", "Old trait", "New trait",
        retire_removed_settings=False,
    )

    assert impact is None


@pytest.mark.asyncio
async def test_analysis_keeps_only_exact_safe_material_patches(tmp_path: Path) -> None:
    plot = tmp_path / "plot" / "arc.md"
    plot.parent.mkdir(parents=True)
    plot.write_text("She checks her notebook to find the date.", encoding="utf-8")
    service = MaterialImpactService(FakeGateway({
        "summary": "The notebook habit affects one plot beat.",
        "proposals": [
            {
                "path": "plot/arc.md", "reason": "Replace the retired habit.",
                "old_text": "She checks her notebook to find the date.",
                "new_text": "She recognizes the date carved into the wall.",
            },
            {
                "path": "../outside.md", "reason": "unsafe",
                "old_text": "x", "new_text": "y",
            },
        ],
    }))
    impact = service.record(
        "book", tmp_path, "characters/lin.md", "Carries a notebook.",
        "Trusts her memory.", retire_removed_settings=True,
    )

    result = await service.analyze(tmp_path, impact["id"], [{
        "path": "plot/arc.md", "content": plot.read_text(encoding="utf-8"),
    }])

    assert result["status"] == "ready"
    assert len(result["proposals"]) == 1
    assert result["proposals"][0]["path"] == "plot/arc.md"
    assert result["proposals"][0]["target_hash"]


def test_prepare_apply_rejects_material_changed_after_analysis(tmp_path: Path) -> None:
    plot = tmp_path / "plot" / "arc.md"
    plot.parent.mkdir(parents=True)
    plot.write_text("Old beat", encoding="utf-8")
    service = MaterialImpactService(FakeGateway({}))
    impact = service.record(
        "book", tmp_path, "characters/lin.md", "Old trait", "New trait",
        retire_removed_settings=True,
    )
    stored = service.get(tmp_path, impact["id"])
    stored.update({
        "status": "ready",
        "proposals": [{
            "id": "patch-1", "path": "plot/arc.md", "old_text": "Old beat",
            "new_text": "New beat", "reason": "linked",
            "target_hash": service.content_hash("Old beat"),
        }],
    })
    service.save(tmp_path, stored)
    plot.write_text("Manually changed", encoding="utf-8")

    with pytest.raises(ValueError, match="material_stale"):
        service.prepare_apply(tmp_path, impact["id"], ["patch-1"])
