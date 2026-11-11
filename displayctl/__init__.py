"""Safety-first external-monitor control for luminance, contrast, and volume.

The public write paths are ``set_luminance_safe``, ``set_contrast_safe``, and
``set_volume_safe``. Each refuses unless a fresh probe says the target VCP is
writable on a single identified panel, and ``confirm=True`` is required.
"""

from displayctl.service import (
    enumerate_monitors,
    get_luminance,
    probe,
    set_contrast_safe,
    set_luminance_safe,
    set_volume_safe,
)

__version__ = "0.3.1"

enumerate = enumerate_monitors

__all__ = [
    "enumerate",
    "enumerate_monitors",
    "get_luminance",
    "probe",
    "set_contrast_safe",
    "set_luminance_safe",
    "set_volume_safe",
    "__version__",
]
