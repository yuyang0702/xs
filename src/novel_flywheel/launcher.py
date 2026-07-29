import argparse
import hashlib
import json
import os
import socket
import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path
from urllib.request import urlopen

import uvicorn

from novel_flywheel.config import configure_runtime_environment


def data_dir_fingerprint(path: Path) -> str:
    value = str(path.resolve()).casefold().encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:16]


def reserve_port(port: int) -> socket.socket | None:
    listener = socket.socket()
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("127.0.0.1", port))
        listener.listen(socket.SOMAXCONN)
    except OSError:
        listener.close()
        return None
    return listener


def local_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def probe_existing_console(port: int, fingerprint: str) -> bool:
    try:
        with urlopen(f"{local_url(port)}/api/health", timeout=0.75) as response:
            payload = json.loads(response.read())
    except Exception:
        return False
    return (
        isinstance(payload, dict)
        and payload.get("status") == "ok"
        and payload.get("service") == "novel-flywheel-console"
        and payload.get("data_dir_fingerprint") == fingerprint
    )


def resolve_launch(
    port: int, data_dir: Path, open_browser: Callable[[str], object],
) -> dict[str, object]:
    if not 1 <= port <= 65535:
        raise SystemExit("端口必须是 1 到 65535 之间的整数。")
    url = local_url(port)
    listener = reserve_port(port)
    if listener is not None:
        return {"action": "start", "url": url, "socket": listener}
    if probe_existing_console(port, data_dir_fingerprint(data_dir)):
        open_browser(url)
        return {"action": "reuse", "url": url}
    raise SystemExit(f"{port}端口已被其他程序占用，请关闭占用程序后重新启动。")


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the local Novel Flywheel Console")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    data_dir = Path(
        os.environ.get("NOVEL_FLYWHEEL_DATA_DIR", Path.home() / ".novel-flywheel")
    ).resolve()
    launch = resolve_launch(
        args.port,
        data_dir,
        (lambda url: None) if args.no_browser else webbrowser.open,
    )
    if launch["action"] == "reuse":
        print(f"小说飞轮控制台已在运行：{launch['url']}")
        return
    listener = launch["socket"]
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        configure_runtime_environment(data_dir)
        url = str(launch["url"])
        if not args.no_browser:
            threading.Timer(1.2, lambda: webbrowser.open(url)).start()
        print(f"小说飞轮控制台：{url}")
        config = uvicorn.Config(
            "novel_flywheel.app:create_app",
            factory=True,
            host="127.0.0.1",
            port=args.port,
        )
        uvicorn.Server(config).run(sockets=[listener])
    finally:
        listener.close()


if __name__ == "__main__":
    main()
