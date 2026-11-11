"""Tests for packaged app entry helpers."""

from __future__ import annotations

import socket

from displayctl import app_main


def test_pick_listen_port_preferred_free() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    chosen = app_main.pick_listen_port("127.0.0.1", port, auto=False)
    assert chosen == port


def test_pick_listen_port_auto_skips_busy() -> None:
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    holder.bind(("127.0.0.1", 0))
    busy = holder.getsockname()[1]
    try:
        chosen = app_main.pick_listen_port("127.0.0.1", busy, auto=True, span=5)
        assert chosen is not None
        assert chosen != busy
        assert busy < chosen < busy + 5
    finally:
        holder.close()


def test_classify_api_down() -> None:
    assert app_main.classify_api("http://127.0.0.1:1") == "down"


def test_default_port_constant() -> None:
    assert app_main.DEFAULT_PORT == 8765


def test_build_parser_no_gui_flag() -> None:
    args = app_main.build_parser().parse_args(["--no-gui", "--port", "9001"])
    assert args.no_gui is True
    assert args.port == 9001
