# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for DisplayCtl portable preview (Windows).
# Prefer: powershell -File scripts/build_windows.ps1

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None
repo = Path(SPECPATH).resolve().parent
web_dist = repo / "web" / "dist"

if not (web_dist / "index.html").is_file():
    raise SystemExit(
        f"Missing {web_dist / 'index.html'}. Build the UI first "
        "(npm run build in web/) or run scripts/build_windows.ps1."
    )

datas = [(str(web_dist), "web/dist")]
binaries = []
hiddenimports = [
    "displayctl",
    "displayctl.api",
    "displayctl.app_main",
    "displayctl.assemble",
    "displayctl.backend",
    "displayctl.caps_cache",
    "displayctl.cli",
    "displayctl.demo",
    "displayctl.desktop",
    "displayctl.dxva2_win",
    "displayctl.edid_reg",
    "displayctl.errors",
    "displayctl.geometry",
    "displayctl.identity",
    "displayctl.memory",
    "displayctl.models",
    "displayctl.paths",
    "displayctl.policy",
    "displayctl.rate_limit",
    "displayctl.service",
    "displayctl.vcp_probe",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "pystray._win32",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
]

for pkg in (
    "uvicorn",
    "fastapi",
    "starlette",
    "anyio",
    "pydantic",
    "pydantic_core",
    "webview",
    "pystray",
):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

a = Analysis(
    [str(repo / "displayctl" / "app_main.py")],
    pathex=[str(repo)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="DisplayCtl",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    # Windowed: tray + native window are the UI; errors go to MessageBox + log.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
