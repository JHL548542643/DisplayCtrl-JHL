import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from displayctl.dev import API_BASE, api_launch_command, classify_api, main


def _serve(payload: bytes, status: int = 200) -> tuple[ThreadingHTTPServer, int]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, fmt, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def test_classify_displayctl_other_and_down():
    server, port = _serve(b'{"ok":true,"service":"displayctl-jhl"}')
    try:
        assert classify_api(f"http://127.0.0.1:{port}") == "displayctl"
    finally:
        server.shutdown()
        server.server_close()

    server, port = _serve(b'{"ok":true,"service":"something-else"}')
    try:
        assert classify_api(f"http://127.0.0.1:{port}") == "other"
    finally:
        server.shutdown()
        server.server_close()

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    closed_port = sock.getsockname()[1]
    sock.close()
    assert classify_api(f"http://127.0.0.1:{closed_port}", timeout=0.3) == "down"


def test_api_launch_stays_on_loopback():
    command = api_launch_command("python", demo=False)
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert command[command.index("--port") + 1] == "8765"
    assert "--demo" not in command
    assert "0.0.0.0" not in command
    demo = api_launch_command("python", demo=True)
    assert demo[-1] == "--demo"
    assert API_BASE == "http://127.0.0.1:8765"


def test_other_listener_does_not_start_processes(monkeypatch):
    monkeypatch.setattr("displayctl.dev.find_root", lambda: Path("."))
    monkeypatch.setattr("displayctl.dev.web_node", lambda web: "node")
    monkeypatch.setattr("displayctl.dev.classify_api", lambda *args, **kwargs: "other")

    def fail_open(*args, **kwargs):
        raise AssertionError("should not spawn")

    monkeypatch.setattr("displayctl.dev.open_logged", fail_open)
    assert main([]) == 1


def test_dev_wiring_is_single_system():
    root = Path(__file__).resolve().parents[1]
    vite = (root / "web" / "vite.config.ts").read_text(encoding="utf-8")
    api = (root / "web" / "src" / "api.ts").read_text(encoding="utf-8")
    launcher = (root / "displayctl" / "dev.py").read_text(encoding="utf-8")
    assert "strictPort: false" in vite
    assert "proxy" in vite
    assert "127.0.0.1:8765" in vite
    assert "import.meta.env.DEV" in api
    assert "DEV_PORTS" not in api
    assert "127.0.0.1:8765" in api
    assert API_BASE in launcher
    assert "0.0.0.0" not in launcher
