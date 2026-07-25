from novel_flywheel.nlp_backend import LocalNLPManager


class Process:
    def poll(self):
        return None


def test_install_only_starts_after_explicit_action(tmp_path) -> None:
    calls = []
    manager = LocalNLPManager(tmp_path / "nlp.json", runner=lambda command, **kwargs: calls.append(command) or Process())
    assert not calls
    result = manager.install()
    assert calls[0][2:4] == ["pip", "install"]
    assert result["operation"] == "installing"


def test_analysis_fails_open_when_backend_is_unavailable(tmp_path) -> None:
    manager = LocalNLPManager(tmp_path / "nlp.json")
    result = manager.analyze("一段正文")
    assert result["backend"] == "rules"
    assert result["available"] is False
