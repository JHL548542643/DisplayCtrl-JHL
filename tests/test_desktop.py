"""Tests for native-window theme caption helpers."""

from __future__ import annotations

from pathlib import Path

from displayctl import desktop


def test_normalize_theme_known_and_fallback() -> None:
    assert desktop.normalize_theme("night") == "night"
    assert desktop.normalize_theme("graphite") == "graphite"
    assert desktop.normalize_theme("day") == "day"
    assert desktop.normalize_theme("unknown") == "night"
    assert desktop.normalize_theme(None) == "night"


def test_chrome_matches_css_tokens() -> None:
    assert desktop.chrome_for("night") == {"bg": "#10140f", "text": "#f3f6ea", "dark": True}
    assert desktop.chrome_for("graphite") == {"bg": "#101317", "text": "#e8eef6", "dark": True}
    assert desktop.chrome_for("day") == {"bg": "#e5e1d4", "text": "#1c2118", "dark": False}


def test_colorref_pack_order() -> None:
    assert desktop.colorref("#10140f") == 0x000F1410
    assert desktop.colorref("#e8eef6") == 0x00F6EEE8
    assert desktop.colorref("1c2118") == 0x0018211C


def test_load_and_save_theme(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "theme.txt"
    monkeypatch.setenv("DISPLAYCTL_THEME_FILE", str(path))
    assert desktop.load_saved_theme() == "night"
    desktop.save_theme("graphite")
    assert path.read_text(encoding="utf-8").strip() == "graphite"
    assert desktop.load_saved_theme() == "graphite"
    desktop.save_theme("nope")
    assert desktop.load_saved_theme() == "night"


def test_window_settings_uses_theme_background(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "theme.txt"
    monkeypatch.setenv("DISPLAYCTL_THEME_FILE", str(path))
    night = desktop.window_settings("night")
    assert night["title"] == "DisplayCtl"
    assert night.get("frameless") is not True
    assert night["confirm_close"] is False
    assert night["background_color"] == "#10140f"
    assert night["min_size"] == (880, 600)
    day = desktop.window_settings("day")
    assert day["background_color"] == "#e5e1d4"
    desktop.save_theme("graphite")
    saved = desktop.window_settings()
    assert saved["background_color"] == "#101317"


def test_apply_caption_theme_skips_without_hwnd() -> None:
    assert desktop.apply_caption_theme(None, "day") == "day"
    assert desktop.apply_caption_theme(None, "bogus") == "night"


class _FakeEvents:
    def __init__(self) -> None:
        self.shown: list = []
        self.loaded: list = []

    def __iadd__(self, other):  # pragma: no cover - not used as a single object
        return self


class _EventHook:
    def __init__(self) -> None:
        self.handlers: list = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class _FakeWindow:
    def __init__(self) -> None:
        self.native = None
        self.events = type("E", (), {})()
        self.events.shown = _EventHook()
        self.events.loaded = _EventHook()


def test_desktop_api_set_theme_without_hwnd(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "theme.txt"
    monkeypatch.setenv("DISPLAYCTL_THEME_FILE", str(path))
    api = desktop.DesktopApi(theme="night")
    assert api.set_theme("graphite") == "graphite"
    assert api.theme == "graphite"
    assert desktop.load_saved_theme() == "graphite"
    assert api.set_theme("weird") == "night"


def test_desktop_api_bind_hooks_shown(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "theme.txt"
    monkeypatch.setenv("DISPLAYCTL_THEME_FILE", str(path))
    applied: list[tuple] = []

    def fake_apply(hwnd, theme):
        applied.append((hwnd, theme))
        return theme

    monkeypatch.setattr(desktop, "apply_caption_theme", fake_apply)
    monkeypatch.setattr(desktop, "resolve_hwnd", lambda _window: 4242)
    window = _FakeWindow()
    api = desktop.DesktopApi(theme="day")
    api.bind(window)
    assert window.events.shown.handlers
    assert window.events.loaded.handlers
    window.events.shown.handlers[0]()
    assert applied == [(4242, "day")]
    api.set_theme("night")
    assert applied[-1] == (4242, "night")