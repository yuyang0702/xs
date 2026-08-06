import json
import os
import socket
import sys

import pytest

from novel_flywheel import launcher
from novel_flywheel.config import configure_runtime_environment


def test_launcher_reserves_requested_port_until_server_starts(tmp_path) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    opened = []

    result = launcher.resolve_launch(port, tmp_path, opened.append)

    listener = result["socket"]
    try:
        assert result["action"] == "start"
        assert result["url"] == f"http://127.0.0.1:{port}"
        assert opened == []
        with socket.socket() as competitor:
            with pytest.raises(OSError):
                competitor.bind(("127.0.0.1", port))
    finally:
        listener.close()


def test_launcher_reuses_same_console_instead_of_random_port(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(launcher, "reserve_port", lambda port: None)
    monkeypatch.setattr(
        launcher, "probe_existing_console",
        lambda port, fingerprint, expected_runtime=None: True,
    )
    opened = []

    result = launcher.resolve_launch(8765, tmp_path, opened.append)

    assert result == {
        "action": "reuse", "url": "http://127.0.0.1:8765", "port": 8765,
    }
    assert opened == ["http://127.0.0.1:8765"]


def test_launcher_refuses_foreign_process_on_8765(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(launcher, "reserve_port", lambda port: None)
    monkeypatch.setattr(
        launcher, "probe_existing_console",
        lambda port, fingerprint, expected_runtime=None: False,
    )

    with pytest.raises(SystemExit, match="8765端口已被其他程序占用"):
        launcher.resolve_launch(8765, tmp_path, lambda url: None)


@pytest.mark.parametrize("port", [0, -1, 65536])
def test_launcher_rejects_invalid_port_without_random_fallback(tmp_path, port) -> None:
    with pytest.raises(SystemExit, match="端口必须是 1 到 65535 之间的整数"):
        launcher.resolve_launch(port, tmp_path, lambda url: None)


def test_main_reuses_console_without_configuring_or_starting_app(tmp_path, monkeypatch) -> None:
    missing_data_dir = tmp_path / "not-created"
    monkeypatch.setattr(sys, "argv", ["novel-flywheel", "--no-browser"])
    monkeypatch.setenv("NOVEL_FLYWHEEL_DATA_DIR", str(missing_data_dir))
    monkeypatch.setattr(
        launcher,
        "resolve_launch",
        lambda *args: {"action": "reuse", "url": "http://127.0.0.1:8765"},
    )
    monkeypatch.setattr(
        launcher,
        "configure_runtime_environment",
        lambda *args: pytest.fail("复用已有实例时不应配置运行环境"),
    )
    monkeypatch.setattr(
        launcher.uvicorn,
        "Server",
        lambda *args: pytest.fail("复用已有实例时不应启动应用"),
    )

    launcher.main()

    assert not missing_data_dir.exists()


def test_main_hands_prebound_socket_to_uvicorn(tmp_path, monkeypatch) -> None:
    class Listener:
        closed = False

        def close(self) -> None:
            self.closed = True

    listener = Listener()
    received = {}

    class Server:
        def __init__(self, config) -> None:
            received["config"] = config

        def run(self, *, sockets) -> None:
            received["sockets"] = sockets

    monkeypatch.setattr(sys, "argv", ["novel-flywheel", "--no-browser"])
    monkeypatch.setenv("NOVEL_FLYWHEEL_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        launcher,
        "resolve_launch",
        lambda *args: {
            "action": "start",
            "url": "http://127.0.0.1:8765",
            "socket": listener,
        },
    )
    monkeypatch.setattr(launcher, "configure_runtime_environment", lambda *args: None)
    monkeypatch.setattr(launcher.uvicorn, "Config", lambda *args, **kwargs: kwargs)
    monkeypatch.setattr(launcher.uvicorn, "Server", Server)
    monkeypatch.setattr(
        launcher.uvicorn,
        "run",
        lambda *args, **kwargs: pytest.fail("必须把预绑定 socket 交给 Server"),
    )

    launcher.main()

    assert received["sockets"] == [listener]
    assert listener.closed is True


def test_probe_requires_matching_service_and_data_directory(monkeypatch) -> None:
    payload = [{
        "status": "ok",
        "service": "novel-flywheel-console",
        "data_dir_fingerprint": "same-data",
    }]

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self) -> bytes:
            return json.dumps(payload[0]).encode("utf-8")

    monkeypatch.setattr(launcher, "urlopen", lambda url, timeout: Response())

    assert launcher.probe_existing_console(8765, "same-data") is True
    assert launcher.probe_existing_console(8765, "same-data", "new-runtime") is False
    payload[0]["runtime_fingerprint"] = "new-runtime"
    assert launcher.probe_existing_console(8765, "same-data", "new-runtime") is True
    assert launcher.probe_existing_console(8765, "other-data") is False
    payload[0] = ["foreign-service"]
    assert launcher.probe_existing_console(8765, "same-data") is False


def test_launcher_starts_new_port_for_stale_same_data_runtime(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(launcher, "reserve_port", lambda port: None)
    monkeypatch.setattr(launcher, "runtime_fingerprint", lambda: "new-runtime")
    monkeypatch.setattr(
        launcher, "probe_existing_console",
        lambda port, fingerprint, expected_runtime=None: expected_runtime is None,
    )
    monkeypatch.setattr(
        launcher, "_reserve_next_port", lambda port: (port + 1, object()),
    )
    opened = []
    result = launcher.resolve_launch(8765, tmp_path, opened.append)

    assert result["action"] == "start"
    assert result["port"] == 8766
    assert result["replaced_stale_runtime"] is True
    assert opened == []


def test_runtime_environment_never_relocates_windows_credentials(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", "C:/Users/test/AppData/Local")

    configure_runtime_environment(tmp_path, tmp_path / "crewai")

    assert os.environ["LOCALAPPDATA"] == "C:/Users/test/AppData/Local"
    assert os.environ["CREWAI_STORAGE_DIR"] == str(tmp_path / "crewai" / "storage")
