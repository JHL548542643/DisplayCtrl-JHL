"""Fixed panels for UI development. Nothing here touches a real display.

The rectangles are one extended desktop, not four panels stacked at the
origin. ``web/src/demoData.ts`` repeats the same coordinates for the offline
preview.

```
-320           0        1920     2240      3840           5760
-1440 [======== 27G2 =========][======== DELL ========]
   0            [ laptop ][ generic ][ GW2480 ]
 1080
```

27G2 declares luminance, contrast, volume, RGB gains, input source, and power mode, and returns GetVCP samples.
GW2480 declares luminance only.
The Dell, the generic panel, and the laptop have no DDC capability string.
"""

from __future__ import annotations

from displayctl.identity import encode_edid
from displayctl.memory import MemoryBackend, MemoryMonitor
from displayctl.models import VcpSample
from displayctl.policy import (
    CONTRAST_VCP,
    INPUT_SOURCE_VCP,
    POWER_MODE_VCP,
    RGB_GAIN_B_VCP,
    RGB_GAIN_G_VCP,
    RGB_GAIN_R_VCP,
    VOLUME_VCP,
)
from displayctl.service import DisplayService

# left, top, right, bottom. Negative values are normal on an extended desktop.
_LEFT = (-320, -1440, 2240, 0)  # 2560×1440, above and slightly left
_RIGHT = (2240, -1440, 4160, 0)  # 1920×1440, above-right
_SIDE = (1920, 0, 3840, 1080)  # right of the laptop
_LAPTOP = (0, 0, 1920, 1080)  # primary, origin
_BENQ = (3840, 0, 5760, 1080)  # luminance only, right of the generic panel


def demo_backend() -> MemoryBackend:
    lg = encode_edid("GSM", 0x5B05, serial_text="K1A92")
    dell = encode_edid("DEL", 0x414C, serial_text="CN0U2720")
    benq = encode_edid("BNQ", 0x2480, serial_text="K8GW2480", name="GW2480")
    return MemoryBackend(
        [
            MemoryMonitor(
                device=r"\\.\DISPLAY2",
                description="Generic PnP Monitor",
                rect=_LEFT,
                primary=False,
                edid=lg,
                caps="(prot(monitor)type(LCD)model(27G2)vcp(10 12 16 18 1A 60 62 D6))",
                vcp_ok=True,
                current=42,
                maximum=100,
                winerr=None,
                reads=(
                    VcpSample(code=CONTRAST_VCP, current=55, maximum=100),
                    VcpSample(code=VOLUME_VCP, current=30, maximum=100),
                    VcpSample(code=RGB_GAIN_R_VCP, current=50, maximum=100),
                    VcpSample(code=RGB_GAIN_G_VCP, current=52, maximum=100),
                    VcpSample(code=RGB_GAIN_B_VCP, current=48, maximum=100),
                    VcpSample(code=INPUT_SOURCE_VCP, current=15, maximum=22),
                    VcpSample(code=POWER_MODE_VCP, current=1, maximum=4),
                ),
            ),
            MemoryMonitor(
                device=r"\\.\DISPLAY3",
                description="DELL U2720Q",
                rect=_RIGHT,
                primary=False,
                edid=dell,
                caps=None,
                vcp_ok=False,
                current=None,
                maximum=None,
                winerr=31,
            ),
            MemoryMonitor(
                device=r"\\.\DISPLAY4",
                description="Generic PnP Monitor",
                rect=_SIDE,
                primary=False,
                edid=None,
                caps=None,
                vcp_ok=False,
                current=None,
                maximum=None,
                winerr=31,
            ),
            MemoryMonitor(
                device=r"\\.\DISPLAY1",
                description="Integrated Panel",
                rect=_LAPTOP,
                primary=True,
                edid=None,
                caps=None,
                vcp_ok=False,
                current=None,
                maximum=None,
                winerr=31,
            ),
            MemoryMonitor(
                device=r"\\.\DISPLAY5",
                description="BenQ GW2480",
                rect=_BENQ,
                primary=False,
                edid=benq,
                caps="(prot(monitor)type(LCD)model(GW2480)vcp(10))",
                vcp_ok=True,
                current=28,
                maximum=100,
                winerr=None,
            ),
        ]
    )


def demo_service() -> DisplayService:
    return DisplayService(demo_backend(), sleep=lambda _seconds: None, demo=True)
