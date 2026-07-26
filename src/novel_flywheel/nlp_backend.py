from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


class LocalNLPManager:
    """Manages an optional LTP install; ordinary startup never downloads models."""

    PACKAGE = "ltp>=4.2,<5"
    TRANSFORMERS_PACKAGE = "transformers>=4,<5"
    HUGGINGFACE_HUB_PACKAGE = "huggingface-hub<1"
    BACKEND_VERSION = "ltp-v2"

    def __init__(self, state_path: Path, runner=subprocess.Popen, command_runner=subprocess.run) -> None:
        self.state_path = state_path
        self.runner = runner
        self.command_runner = command_runner
        self.process = None

    def status(self) -> dict:
        installed = importlib.util.find_spec("ltp") is not None
        state = self._read()
        running = bool(self.process and self.process.poll() is None)
        return {
            "backend": "ltp", "installed": installed, "enabled": bool(state.get("enabled") and installed),
            "operation": "installing" if running else state.get("operation", "idle"),
            "download_notice": "安装包及模型可能占用数 GB；首次启用分析时由 LTP 下载模型",
            "hardware_notice": "CPU 单任务运行，分析结束后工作进程退出并释放内存",
            "license_url": "https://github.com/HIT-SCIR/ltp",
        }

    def install(self) -> dict:
        if self.process and self.process.poll() is None:
            return self.status()
        self.process = self.runner(
            [sys.executable, "-m", "pip", "install", self.PACKAGE,
             self.TRANSFORMERS_PACKAGE,
             self.HUGGINGFACE_HUB_PACKAGE],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self._write({"enabled": False, "operation": "installing"})
        return self.status()

    def uninstall(self) -> dict:
        if self.process and self.process.poll() is None:
            raise ValueError("NLP installation is still running")
        self.process = self.runner(
            [sys.executable, "-m", "pip", "uninstall", "-y", "ltp"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self._write({"enabled": False, "operation": "uninstalling"})
        return self.status()

    def enable(self, enabled: bool) -> dict:
        if enabled and importlib.util.find_spec("ltp") is None:
            raise ValueError("LTP is not installed")
        self._write({"enabled": enabled, "operation": "idle"})
        return self.status()

    def analyze(self, text: str) -> dict:
        status = self.status()
        if not status["enabled"]:
            return {"backend": "rules", "available": False,
                    "backend_version": self.BACKEND_VERSION,
                    "reason": "LTP is disabled or unavailable"}
        digest = hashlib.sha256((self.BACKEND_VERSION + "\0" + text).encode("utf-8")).hexdigest()
        cache = self.state_path.parent / "nlp-cache" / f"{digest}.json"
        try:
            return {
                **json.loads(cache.read_text(encoding="utf-8")),
                "backend_version": self.BACKEND_VERSION,
                "cached": True,
            }
        except (OSError, json.JSONDecodeError):
            pass
        try:
            environment = os.environ.copy()
            environment.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
            environment["PYTHONUTF8"] = "1"
            completed = self.command_runner(
                [sys.executable, "-m", "novel_flywheel.nlp_worker"], input=text,
                text=True, encoding="utf-8", capture_output=True, timeout=300, check=True,
                env=environment,
            )
            result = json.loads(completed.stdout)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            return {**result, "backend_version": self.BACKEND_VERSION, "cached": False}
        except Exception as exc:
            return {"backend": "rules", "available": False,
                    "backend_version": self.BACKEND_VERSION, "reason": str(exc)[:300]}

    def _read(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
