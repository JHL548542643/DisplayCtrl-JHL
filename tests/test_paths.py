"""Resource path helpers for source and frozen layouts."""

from __future__ import annotations

from pathlib import Path

from displayctl import paths


def test_package_root_is_repo_in_source() -> None:
    root = paths.package_root()
    assert (root / "displayctl").is_dir()
    assert (root / "pyproject.toml").is_file()


def test_web_dist_dir_none_without_build(tmp_path, monkeypatch) -> None:
    # Point package_root at an empty tree so web/dist is missing.
    monkeypatch.setattr(paths, "package_root", lambda: tmp_path)
    assert paths.web_dist_dir() is None


def test_web_dist_dir_finds_index(tmp_path, monkeypatch) -> None:
    dist = tmp_path / "web" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(paths, "package_root", lambda: tmp_path)
    found = paths.web_dist_dir()
    assert found == dist


def test_is_frozen_false_in_tests() -> None:
    assert paths.is_frozen() is False