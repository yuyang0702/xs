import socket

from novel_flywheel.launcher import find_free_port, local_url


def test_launcher_selects_local_free_port() -> None:
    port = find_free_port()
    assert local_url(port) == f"http://127.0.0.1:{port}"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))
