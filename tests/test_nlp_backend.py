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
    assert "ltp>=4.2,<5" in calls[0]
    assert "transformers>=4,<5" in calls[0]
    assert "huggingface-hub<1" in calls[0]
    assert result["operation"] == "installing"


def test_analysis_worker_uses_utf8_and_default_huggingface_mirror(tmp_path, monkeypatch) -> None:
    calls = []

    class Completed:
        stdout = '{"backend":"ltp","available":true,"result":{}}'

    monkeypatch.setattr("novel_flywheel.nlp_backend.importlib.util.find_spec", lambda _name: object())
    manager = LocalNLPManager(
        tmp_path / "nlp.json",
        command_runner=lambda command, **kwargs: calls.append((command, kwargs)) or Completed(),
    )
    manager.enable(True)

    result = manager.analyze("中文输入")

    assert result["available"] is True
    environment = calls[0][1]["env"]
    assert environment["PYTHONUTF8"] == "1"
    assert environment["HF_ENDPOINT"] == "https://hf-mirror.com"


def test_analysis_fails_open_when_backend_is_unavailable(tmp_path) -> None:
    manager = LocalNLPManager(tmp_path / "nlp.json")
    result = manager.analyze("一段正文")
    assert result["backend"] == "rules"
    assert result["available"] is False
    assert result["backend_version"] == manager.BACKEND_VERSION
