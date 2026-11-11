"""Native window + system tray shell for the packaged DisplayCtl preview."""

from __future__ import annotations

import os
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

LogFn = Callable[[str], None]

DEFAULT_THEME = "night"

# Match web/src/styles.css so the OS caption blends into the in-app chrome.
THEME_CHROME: dict[str, dict[str, Any]] = {
    "night": {"bg": "#10140f", "text": "#f3f6ea", "dark": True},
    "graphite": {"bg": "#101317", "text": "#e8eef6", "dark": True},
    "day": {"bg": "#e5e1d4", "text": "#1c2118", "dark": False},
}

# DWM window attributes (Windows 11+ for caption/text/border colors).
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_USE_IMMERSIVE_DARK_MODE_LEGACY = 19
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMSBT_NONE = 1


def normalize_theme(name: str | None) -> str:
    if name in THEME_CHROME:
        return str(name)
    return DEFAULT_THEME


def chrome_for(name: str | None) -> dict[str, Any]:
    return THEME_CHROME[normalize_theme(name)]


def colorref(hex_color: str) -> int:
    """Pack #RRGGBB into a Win32 COLORREF (0x00BBGGRR)."""
    text = hex_color.strip().lstrip("#")
    if len(text) != 6:
        raise ValueError(f"invalid color: {hex_color}")
    red = int(text[0:2], 16)
    green = int(text[2:4], 16)
    blue = int(text[4:6], 16)
    return red | (green << 8) | (blue << 16)


def theme_state_path() -> Path:
    override = os.environ.get("DISPLAYCTL_THEME_FILE")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "DisplayCtl" / "theme.txt"


def load_saved_theme() -> str:
    try:
        text = theme_state_path().read_text(encoding="utf-8").strip()
    except OSError:
        return DEFAULT_THEME
    return normalize_theme(text)


def save_theme(name: str) -> None:
    path = theme_state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(normalize_theme(name) + "\n", encoding="utf-8")
    except OSError:
        pass


def resolve_hwnd(window: Any) -> int | None:
    native = getattr(window, "native", None)
    if native is None:
        return None
    handle = getattr(native, "Handle", None)
    if handle is None:
        return None
    try:
        if hasattr(handle, "ToInt32"):
            return int(handle.ToInt32())
        return int(handle)
    except (TypeError, ValueError, OverflowError, AttributeError):
        try:
            return int(handle.ToInt64())
        except (TypeError, ValueError, OverflowError, AttributeError):
            return None


def _dwm_set(hwnd: int, attr: int, value: int) -> bool:
    try:
        import ctypes

        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            attr,
            ctypes.byref(ctypes.c_int(value)),
            ctypes.sizeof(ctypes.c_int),
        )
        return int(result) == 0
    except Exception:  # noqa: BLE001
        return False


def _frame_changed(hwnd: int) -> None:
    try:
        import ctypes

        # SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020)
    except Exception:  # noqa: BLE001
        pass


def apply_caption_theme(hwnd: int | None, theme: str | None) -> str:
    """Color the native Windows caption to the in-app theme. No-op off Windows."""
    name = normalize_theme(theme)
    if hwnd is None or sys.platform != "win32":
        return name
    chrome = chrome_for(name)
    dark = 1 if chrome["dark"] else 0
    if not _dwm_set(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, dark):
        _dwm_set(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE_LEGACY, dark)
    # Disable Mica so caption/border colors are not washed out.
    _dwm_set(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_NONE)
    background = colorref(str(chrome["bg"]))
    text = colorref(str(chrome["text"]))
    _dwm_set(hwnd, DWMWA_CAPTION_COLOR, background)
    _dwm_set(hwnd, DWMWA_TEXT_COLOR, text)
    _dwm_set(hwnd, DWMWA_BORDER_COLOR, background)
    _frame_changed(hwnd)
    return name


def window_settings(theme: str | None = None) -> dict[str, Any]:
    """Arguments for webview.create_window (url/js_api filled in by the caller)."""
    name = normalize_theme(theme or load_saved_theme())
    return {
        "title": "DisplayCtl",
        "width": 1180,
        "height": 800,
        "min_size": (880, 600),
        "confirm_close": False,
        "background_color": chrome_for(name)["bg"],
    }


class DesktopApi:
    """JS bridge: the UI calls set_theme() whenever 夜航/石墨/日间 changes."""

    def __init__(self, theme: str | None = None, log: LogFn | None = None) -> None:
        self.window: Any = None
        self.theme = normalize_theme(theme or load_saved_theme())
        self._log = log or (lambda _m: None)

    def bind(self, window: Any) -> None:
        self.window = window
        self._hook_shown()
        self._override_system_theme_hook()

    def set_theme(self, name: str) -> str:
        self.theme = normalize_theme(name)
        save_theme(self.theme)
        hwnd = resolve_hwnd(self.window)
        apply_caption_theme(hwnd, self.theme)
        self._log(f"caption theme {self.theme}")
        return self.theme

    def apply_current(self) -> str:
        return self.set_theme(self.theme)

    def _hook_shown(self) -> None:
        window = self.window
        if window is None:
            return

        def _apply(*_args: Any, **_kwargs: Any) -> None:
            self.apply_current()

        try:
            window.events.shown += _apply
        except Exception:  # noqa: BLE001 — older pywebview
            pass
        try:
            window.events.loaded += _apply
        except Exception:  # noqa: BLE001
            pass

    def _override_system_theme_hook(self) -> None:
        """Stop pywebview from resetting the caption to the Windows system theme."""
        native = getattr(self.window, "native", None)
        if native is None or not hasattr(native, "update_title_bar_theme"):
            return

        def _ours(*_args: Any, **_kwargs: Any) -> None:
            self.apply_current()

        try:
            native.update_title_bar_theme = _ours
        except Exception:  # noqa: BLE001
            pass


def _make_icon_image():
    """Small generated tray icon (no external asset required)."""
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Rounded tile — deep blue with a bright bar (brightness metaphor).
    draw.rounded_rectangle((4, 4, 60, 60), radius=12, fill=(30, 64, 175, 255))
    draw.rounded_rectangle((14, 28, 50, 40), radius=4, fill=(191, 219, 254, 255))
    return img


def run_desktop(url: str, *, server: Any, log: LogFn | None = None) -> int:
    """Show a pywebview window + pystray Quit, blocking until the user quits.

    ``server`` is a uvicorn.Server whose ``should_exit`` flag we set on Quit.
    """
    import webview

    try:
        import pystray
        from pystray import MenuItem
    except ImportError as exc:  # pragma: no cover - pack extra
        raise RuntimeError("pystray is required for the tray shell") from exc

    _log = log or (lambda _m: None)
    window_holder: dict[str, Any] = {"window": None}
    icon_holder: dict[str, Any] = {"icon": None}
    stop_once = threading.Event()
    api = DesktopApi(log=_log)

    def _request_stop() -> None:
        if stop_once.is_set():
            return
        stop_once.set()
        _log("desktop quit requested")
        try:
            server.should_exit = True
        except Exception:  # noqa: BLE001
            pass
        window = window_holder.get("window")
        if window is not None:
            try:
                window.destroy()
            except Exception:  # noqa: BLE001
                pass
        icon = icon_holder.get("icon")
        if icon is not None:
            try:
                icon.stop()
            except Exception:  # noqa: BLE001
                pass

    def on_show(_icon=None, _item=None) -> None:
        window = window_holder.get("window")
        if window is None:
            return
        try:
            window.show()
            window.restore()
        except Exception as exc:  # noqa: BLE001
            _log(f"show window failed: {exc}")

    def on_quit(_icon=None, _item=None) -> None:
        _request_stop()

    def on_closing() -> bool:
        # Hide to tray instead of quitting when the user closes the window.
        window = window_holder.get("window")
        if window is not None:
            try:
                window.hide()
            except Exception:  # noqa: BLE001
                return True
        return False

    window = webview.create_window(
        url=url,
        js_api=api,
        **window_settings(api.theme),
    )
    window_holder["window"] = window
    api.bind(window)
    try:
        window.events.closing += on_closing
    except Exception:  # noqa: BLE001 — older pywebview
        pass

    def _run_tray() -> None:
        menu = pystray.Menu(
            MenuItem("Show DisplayCtl", on_show, default=True),
            MenuItem("Quit", on_quit),
        )
        icon = pystray.Icon("DisplayCtl", _make_icon_image(), "DisplayCtl", menu)
        icon_holder["icon"] = icon
        _log("tray started")
        try:
            icon.run()
        except Exception as exc:  # noqa: BLE001
            _log(f"tray error: {exc}")

    tray_thread = threading.Thread(target=_run_tray, name="displayctl-tray", daemon=True)
    tray_thread.start()

    _log(f"webview start {url}")
    # Blocks until window.destroy(); private_mode avoids leftover cookies between runs.
    webview.start(private_mode=True)
    _request_stop()
    return 0