"""Start the loopback API and the Vite console in one terminal."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = "http://127.0.0.1:8765"
API_HOST = "127.0.0.1"
API_PORT = "8765"


def find_root() -> Path:
    candidates = [Path.cwd(), Path(__file__).resolve().parents[1]]
    for candidate in candidates:
        if (candidate / "web" / "package.json").is_file() and (candidate / "displayctl" / "api.py").is_file():
            return candidate
    raise SystemExit("请在 DisplayCtl-JHL 仓库根目录运行 python -m displayctl.dev。")


def web_node(web: Path) -> str | None:
    node = shutil.which("node")
    vite_js = web / "node_modules" / "vite" / "bin" / "vite.js"
    if node and vite_js.is_file():
        return node
    return None


def api_launch_command(python: str, *, demo: bool) -> list[str]:
    command = [
        python,
        "-u",
        "-m",
        "displayctl.api",
        "--host",
        API_HOST,
        "--port",
        API_PORT,
    ]
    if demo:
        command.append("--demo")
    return command


def classify_api(base_url: str, timeout: float = 1.5) -> str:
    """Return displayctl, other, or down for a loopback health URL."""
    request = urllib.request.Request(base_url.rstrip("/") + "/api/health", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(65536)
    except urllib.error.HTTPError:
        return "other"
    except (urllib.error.URLError, TimeoutError, OSError):
        return "down"
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return "other"
    if isinstance(payload, dict) and payload.get("ok") is True and payload.get("service") == "displayctl-jhl":
        return "displayctl"
    return "other"


def open_logged(command: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.Popen[str]:
    kwargs: dict[str, object] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        **kwargs,
    )


def _pump(stream, prefix: str, lock: threading.Lock) -> None:
    for line in stream:
        text = line.rstrip("\r\n")
        if not text:
            continue
        with lock:
            print(f"{prefix} {text}", flush=True)


def _start_pump(proc: subprocess.Popen[str], prefix: str, lock: threading.Lock) -> None:
    assert proc.stdout is not None
    threading.Thread(target=_pump, args=(proc.stdout, prefix, lock), daemon=True).start()


def _exit_code(proc: subprocess.Popen[str]) -> int:
    if proc.returncode is None:
        return 1
    return proc.returncode


def stop_process(proc: subprocess.Popen[str] | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _wait_until_ready(base: str, proc: subprocess.Popen[str], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        if classify_api(base, timeout=0.5) == "displayctl":
            return True
        time.sleep(0.15)
    return classify_api(base, timeout=0.5) == "displayctl"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m displayctl.dev",
        description="同时启动本机 API（127.0.0.1:8765）和 Vite 控制台",
    )
    parser.add_argument("--demo", action="store_true", help="API 使用内存显示器，不打开 dxva2")
    args = parser.parse_args(argv)

    try:
        root = find_root()
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 1
    web = root / "web"
    node = web_node(web)
    if node is None:
        print("还没有安装控制台依赖。在 web 目录执行 npm install，并确认 node 在 PATH 里。", file=sys.stderr)
        return 1

    kind = classify_api(API_BASE)
    if kind == "other":
        print(f"[api] {API_BASE} 已被其它程序占用，没有启动。请先释放 8765。", file=sys.stderr)
        return 1

    children: list[subprocess.Popen[str]] = []
    lock = threading.Lock()
    stop = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True

    previous_int = signal.getsignal(signal.SIGINT)
    previous_term = signal.getsignal(signal.SIGTERM)
    previous_hup = signal.getsignal(signal.SIGHUP) if hasattr(signal, "SIGHUP") else None
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, request_stop)
    try:
        if kind == "displayctl":
            print(f"[api] {API_BASE} 已在运行，继续使用现有进程。", flush=True)
        else:
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            api_proc = open_logged(api_launch_command(sys.executable, demo=args.demo), cwd=root, env=env)
            children.append(api_proc)
            _start_pump(api_proc, "[api]", lock)
            if not _wait_until_ready(API_BASE, api_proc, 20):
                time.sleep(0.3)
                print("[api] 控制服务没有在 127.0.0.1:8765 就绪。", file=sys.stderr)
                return 1
            print(f"[api] 控制服务就绪：{API_BASE}", flush=True)

        web_env = os.environ.copy()
        web_env["VITE_API_BASE"] = API_BASE
        web_proc = open_logged([node, str(web / "node_modules" / "vite" / "bin" / "vite.js")], cwd=web, env=web_env)
        children.append(web_proc)
        _start_pump(web_proc, "[web]", lock)
        print("[web] 打开下面打印的 Local 地址。不要另找端口，API 固定是 127.0.0.1:8765。", flush=True)

        while not stop:
            if len(children) == 2 and children[0].poll() is not None:
                print("[api] 控制服务已退出。", file=sys.stderr)
                return _exit_code(children[0])
            if web_proc.poll() is not None:
                print("[web] 控制台已退出。", file=sys.stderr)
                return _exit_code(web_proc)
            time.sleep(0.2)
        print("\n正在停止…", flush=True)
        return 0
    finally:
        signal.signal(signal.SIGINT, previous_int)
        signal.signal(signal.SIGTERM, previous_term)
        if previous_hup is not None:
            signal.signal(signal.SIGHUP, previous_hup)
        for proc in reversed(children):
            stop_process(proc)


if __name__ == "__main__":
    raise SystemExit(main())
