import argparse
import os
import socket
import threading
import webbrowser
from pathlib import Path

import uvicorn


def find_free_port(preferred: int = 8765) -> int:
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            probe.bind(("127.0.0.1", 0))
            return int(probe.getsockname()[1])


def local_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the local Novel Flywheel Console")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    port = find_free_port(args.port)
    data_dir = Path(os.environ.get("NOVEL_FLYWHEEL_DATA_DIR", Path.home() / ".novel-flywheel"))
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["NOVEL_FLYWHEEL_DATA_DIR"] = str(data_dir)
    os.environ["CREWAI_STORAGE_DIR"] = str(data_dir / "crewai" / "storage")
    os.environ["LOCALAPPDATA"] = str(data_dir / "runtime")
    os.environ["OTEL_SDK_DISABLED"] = "true"
    url = local_url(port)
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"Novel Flywheel Console: {url}")
    uvicorn.run("novel_flywheel.app:create_app", factory=True, host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
