#!/usr/bin/env python3
"""DisplayCtl-JHL: Windows external-monitor brightness via dxva2 VCP 0x10.

Compatibility entry point. Enumeration and the VCP 0x10 read/write calls live
in displayctl.dxva2_win. ``set`` still refuses without ``--yes``, then runs
probe → confirm → one write → readback → one rollback if the read mismatches.

Usage:
  python brightness_vcp.py list
  python brightness_vcp.py get [index]
  python brightness_vcp.py set <index> <0-100>          # refused
  python brightness_vcp.py set <index> <0-100> --yes
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from displayctl.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
