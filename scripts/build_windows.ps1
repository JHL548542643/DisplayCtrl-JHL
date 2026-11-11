<#
.SYNOPSIS
  Build a portable DisplayCtl Windows preview EXE (API + Vite UI).

.DESCRIPTION
  1) npm ci + npm run build in web/
  2) pip install -e ".[pack]" (PyInstaller)
  3) PyInstaller onefile -> release/DisplayCtl.exe

.PARAMETER SkipWeb
  Reuse an existing web/dist instead of rebuilding.

.PARAMETER SkipInstall
  Skip pip install -e ".[pack]" (assume deps already present).

.PARAMETER OutDir
  Output directory for the EXE (default: release).
#>
[CmdletBinding()]
param(
  [switch]$SkipWeb,
  [switch]$SkipInstall,
  [string]$OutDir = "release"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "== DisplayCtl Windows preview build ==" -ForegroundColor Cyan
Write-Host "Repo: $RepoRoot"

if (-not $SkipWeb) {
  Write-Host "`n[1/3] Building Vite production assets..." -ForegroundColor Cyan
  Push-Location (Join-Path $RepoRoot "web")
  try {
    if (-not (Test-Path "node_modules")) {
      npm ci
    } else {
      # Prefer lockfile-consistent install when present
      if (Test-Path "package-lock.json") { npm ci } else { npm install }
    }
    npm run build
  } finally {
    Pop-Location
  }
} else {
  Write-Host "`n[1/3] Skipping web build (SkipWeb)" -ForegroundColor Yellow
}

$index = Join-Path $RepoRoot "web\dist\index.html"
if (-not (Test-Path $index)) {
  throw "web/dist/index.html missing. Run without -SkipWeb, or build the UI first."
}

if (-not $SkipInstall) {
  Write-Host "`n[2/3] Installing package + PyInstaller..." -ForegroundColor Cyan
  python -m pip install -e ".[pack]"
} else {
  Write-Host "`n[2/3] Skipping pip install (SkipInstall)" -ForegroundColor Yellow
}

$outAbs = Join-Path $RepoRoot $OutDir
New-Item -ItemType Directory -Force -Path $outAbs | Out-Null
$workDir = Join-Path $RepoRoot "build\pyinstaller"
New-Item -ItemType Directory -Force -Path $workDir | Out-Null

Write-Host "`n[3/3] PyInstaller onefile..." -ForegroundColor Cyan
$spec = Join-Path $RepoRoot "scripts\displayctl.spec"
if (Test-Path $spec) {
  python -m PyInstaller --noconfirm --clean --distpath $outAbs --workpath $workDir $spec
} else {
  # Fallback args if .spec is absent
  python -m PyInstaller `
    --noconfirm --clean --onefile --windowed `
    --name DisplayCtl `
    --distpath $outAbs `
    --workpath $workDir `
    --paths $RepoRoot `
    --collect-all uvicorn `
    --collect-all fastapi `
    --collect-all starlette `
    --collect-all anyio `
    --collect-submodules pydantic `
    --hidden-import displayctl `
    --hidden-import displayctl.api `
    --hidden-import displayctl.app_main `
    --hidden-import displayctl.demo `
    --hidden-import displayctl.service `
    --hidden-import displayctl.dxva2 `
    --add-data "web\dist;web\dist" `
    (Join-Path $RepoRoot "displayctl\app_main.py")
}

$exe = Join-Path $outAbs "DisplayCtl.exe"
if (-not (Test-Path $exe)) {
  throw "Build finished but $exe was not produced."
}
$sizeMb = [math]::Round((Get-Item $exe).Length / 1MB, 2)
Write-Host "`nOK: $exe ($sizeMb MB)" -ForegroundColor Green
Write-Host "Smoke tip: .\release\DisplayCtl.exe --demo --port 8877 --no-gui --no-browser"
Write-Host "Then: curl http://127.0.0.1:8877/api/health"