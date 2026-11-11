"""Resolve resource paths for source installs and frozen (PyInstaller) builds."""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"))


def package_root() -> Path:
    """Repo root in source installs; PyInstaller extract dir when frozen."""
    if is_frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[1]


def web_dist_dir() -> Path | None:
    """Return web/dist if index.html exists, else None."""
    candidate = package_root() / "web" / "dist"
    if (candidate / "index.html").is_file():
        return candidate
    return None