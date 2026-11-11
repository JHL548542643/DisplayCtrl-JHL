"""Packaged DisplayCtl entry: local API + native window + system tray."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from typing import Sequence

import uvicorn

from displayctl.api import create_app
from displayctl.paths import web_dist_dir

# Preferred loopback port; always fall back if busy (unless --strict-port).
DEFAULT_PORT = 8765


def install_dir() -> Path:
    """Directory of the running EXE when frozen; otherwise cwd."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def log_path() -> Path:
    return install_dir() / "displayctl-preview.log"


def append_log(message: str) -> None:
    try:
        path = log_path()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + message.rstrip() + "\n")
    except OSError:
        pass


class _SafeStdio:
    """Stand-in when PyInstaller windowed builds leave sys.stdout/stderr as None."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fh = None

    def _ensure(self):
        if self._fh is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self._path.open("a", encoding="utf-8", buffering=1)
        return self._fh

    def write(self, data: str) -> int:
        if not data:
            return 0
        try:
            self._ensure().write(data)
        except OSError:
            return 0
        return len(data)

    def flush(self) -> None:
        try:
            if self._fh is not None:
                self._fh.flush()
        except OSError:
            pass

    def isatty(self) -> bool:
        return False


def ensure_stdio() -> None:
    """Windowed EXE has no console; point stdio at the preview log so uvicorn can start."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    sink = _SafeStdio(log_path())
    if sys.stdout is None:
        sys.stdout = sink  # type: ignore[assignment]
    if sys.stderr is None:
        sys.stderr = sink  # type: ignore[assignment]


def say(message: str, *, error: bool = False) -> None:
    """Print with flush so consoles / redirected runs show lines immediately."""
    stream = sys.stderr if error else sys.stdout
    print(message, file=stream, flush=True)


def pause_if_interactive(reason: str | None = None) -> None:
    """Keep a console open after double-click so the user can read errors."""
    if reason:
        say(reason, error=True)
    if not sys.stdin or not sys.stdin.isatty():
        return
    try:
        input("\nPress Enter to close… ")
    except EOFError:
        pass


def win_message(title: str, text: str, *, error: bool = False) -> None:
    """Topmost Win32 message box so Explorer double-click always gets a cue."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        icon = 0x00000010 if error else 0x00000040  # MB_ICONERROR / MB_ICONINFORMATION
        flags = 0x00000000 | 0x00010000 | 0x00040000 | icon  # OK | SETFOREGROUND | TOPMOST
        ctypes.windll.user32.MessageBoxW(0, text, title, flags)
    except Exception:  # noqa: BLE001
        pass


def _port_open(host: str, port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _wait_ready(host: str, port: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open(host, port):
            return True
        time.sleep(0.15)
    return False


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


def pick_listen_port(host: str, preferred: int, *, auto: bool, span: int = 20) -> int | None:
    """Return preferred if free; if auto, the next free port in [preferred, preferred+span)."""
    candidates = [preferred] if not auto else list(range(preferred, preferred + max(1, span)))
    probe = host if host not in ("0.0.0.0", "::") else "127.0.0.1"
    family = socket.AF_INET6 if ":" in host and host != "0.0.0.0" else socket.AF_INET
    for port in candidates:
        if _port_open(probe, port):
            continue
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.bind((host, port))
            return port
        except OSError:
            continue
    return None


def open_browser(url: str) -> None:
    say(f"Opening browser {url}")
    append_log(f"open browser {url}")
    opened = False
    if sys.platform == "win32":
        try:
            os.startfile(url)  # type: ignore[attr-defined]
            opened = True
        except OSError as exc:
            append_log(f"startfile error: {exc}")
    if not opened:
        import webbrowser

        try:
            webbrowser.open(url)
        except Exception as exc:  # noqa: BLE001
            say(f"Could not open browser: {exc}", error=True)
            append_log(f"browser error: {exc}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="DisplayCtl",
        description="DisplayCtl preview — local API + native window (portable Windows build).",
    )
    p.add_argument("--host", default="127.0.0.1", help="Bind address (default 127.0.0.1)")
    p.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Preferred HTTP port (default {DEFAULT_PORT}; auto-falls back if busy)",
    )
    p.add_argument(
        "--strict-port",
        action="store_true",
        help="Fail if --port is busy instead of trying the next free ports.",
    )
    p.add_argument(
        "--demo",
        action="store_true",
        help="Use the in-memory demo monitor backend (no physical DDC).",
    )
    p.add_argument(
        "--no-gui",
        action="store_true",
        help="Do not open the native window / tray (API only; useful for CI smoke).",
    )
    p.add_argument(
        "--browser",
        action="store_true",
        help="Open the system browser instead of the native window (fallback).",
    )
    p.add_argument(
        "--no-browser",
        action="store_true",
        help="With --browser or --no-gui: do not open a browser tab.",
    )
    p.add_argument(
        "--reload",
        action="store_true",
        help="Dev-only: uvicorn auto-reload (ignored when frozen).",
    )
    return p


def _start_uvicorn(app, host: str, port: int, *, reload: bool) -> uvicorn.Server:
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        reload=reload and not getattr(sys, "frozen", False),
    )
    server = uvicorn.Server(config)

    def _run() -> None:
        try:
            server.run()
        except Exception:  # noqa: BLE001
            append_log("uvicorn crashed:\n" + traceback.format_exc())

    threading.Thread(target=_run, name="displayctl-uvicorn", daemon=True).start()
    return server


def main(argv: Sequence[str] | None = None) -> int:
    ensure_stdio()
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    host = str(args.host)
    preferred = int(args.port)
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    browse_preferred = f"http://{probe_host}:{preferred}/"
    frozen = bool(getattr(sys, "frozen", False))

    append_log(f"start host={host} port={preferred} frozen={frozen} no_gui={args.no_gui}")

    # Already a DisplayCtl on the preferred port — tell the user; do not start a second API.
    existing = classify_api(browse_preferred)
    if existing == "displayctl":
        msg = (
            f"DisplayCtl is already running at {browse_preferred}\n\n"
            "Use the existing tray icon / window.\n"
            "If you do not see it, check the notification area overflow."
        )
        say(msg)
        append_log("reuse existing instance")
        if args.browser and not args.no_browser:
            open_browser(browse_preferred)
        if frozen or sys.platform == "win32":
            win_message("DisplayCtl", msg)
            pause_if_interactive()
        return 0
    if existing == "other":
        say(
            f"Port {preferred} is in use by another program (not DisplayCtl).",
            error=True,
        )
        append_log(f"port {preferred} occupied by other")

    static = web_dist_dir()
    if static is None:
        say(
            "WARNING: web/dist not found — API only. "
            "Rebuild with scripts/build_windows.ps1 so the UI is bundled.",
            error=True,
        )
        append_log("web/dist missing")
    else:
        say(f"Serving UI from {static}")

    auto = not bool(args.strict_port)
    port = pick_listen_port(host, preferred, auto=auto)
    if port is None:
        err = (
            f"Could not bind any port from {preferred}"
            + (f"..{preferred + 19}" if auto else "")
            + ". Close the other program or pass --port."
        )
        say(err, error=True)
        append_log(err)
        if frozen or sys.platform == "win32":
            win_message("DisplayCtl — port busy", err, error=True)
            pause_if_interactive()
        return 1
    if port != preferred:
        say(f"Port {preferred} busy — using {port} instead.")
        append_log(f"fell back to port {port}")

    app = create_app(demo=bool(args.demo), static_dir=static)
    url = f"http://{host}:{port}/"
    browse = f"http://{probe_host}:{port}/"

    server = _start_uvicorn(
        app,
        host,
        port,
        reload=bool(args.reload),
    )
    say(f"DisplayCtl listening on {url}")
    say(f"UI: {browse}")
    append_log(f"listening {url}")

    if not _wait_ready(probe_host, port):
        err = f"Server did not become ready on {browse}. See {log_path()}"
        say(err, error=True)
        append_log(err)
        if frozen or sys.platform == "win32":
            win_message("DisplayCtl — failed to start", err, error=True)
            pause_if_interactive()
        return 1

    use_gui = (not args.no_gui) and (not args.browser) and static is not None
    if use_gui:
        try:
            from displayctl.desktop import run_desktop

            append_log(f"desktop window {browse}")
            return run_desktop(browse, server=server, log=append_log)
        except Exception as exc:  # noqa: BLE001
            append_log("desktop failed:\n" + traceback.format_exc())
            say(f"Native window failed ({exc}); falling back to browser.", error=True)
            if frozen or sys.platform == "win32":
                win_message(
                    "DisplayCtl — window failed",
                    f"Could not open the native window:\n{exc}\n\nFalling back to the browser.\n\n{browse}",
                    error=True,
                )
            use_gui = False

    if not args.no_browser and (args.browser or args.no_gui or not use_gui):
        if not args.no_gui or args.browser:
            open_browser(browse)

    if frozen and not args.no_gui:
        win_message(
            "DisplayCtl",
            f"DisplayCtl is running at:\n{browse}\n\n"
            "Browser / API mode (no native window).\n"
            f"Log: {log_path()}",
        )

    say("Press Ctrl+C to quit.")
    try:
        while not server.should_exit:
            time.sleep(0.4)
    except KeyboardInterrupt:
        say("\nShutting down…")
        server.should_exit = True
    return 0


if __name__ == "__main__":
    try:
        ensure_stdio()
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        append_log("fatal:\n" + traceback.format_exc())
        say(f"Fatal error: {exc}", error=True)
        if getattr(sys, "frozen", False) or sys.platform == "win32":
            win_message("DisplayCtl — fatal error", str(exc), error=True)
            pause_if_interactive()
        raise SystemExit(1) from exc
