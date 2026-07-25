import socket
import os

from novel_flywheel.config import configure_runtime_environment
from novel_flywheel.launcher import find_free_port, local_url


def test_launcher_selects_local_free_port() -> None:
    port = find_free_port()
    assert local_url(port) == f"http://127.0.0.1:{port}"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))


def test_runtime_environment_never_relocates_windows_credentials(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", "C:/Users/test/AppData/Local")

    configure_runtime_environment(tmp_path, tmp_path / "crewai")

    assert os.environ["LOCALAPPDATA"] == "C:/Users/test/AppData/Local"
    assert os.environ["CREWAI_STORAGE_DIR"] == str(tmp_path / "crewai" / "storage")
