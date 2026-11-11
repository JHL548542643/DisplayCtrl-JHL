"""Virtual-desktop geometry for the read-only layout map.

Pure arithmetic. Nothing here talks to Win32 or the brightness write path.
``web/src/layout.ts`` repeats this fit: bounding box, uniform scale, padding,
and letterboxing. The canvas constants must stay in sync with that file.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

Rect = tuple[int, int, int, int]

CANVAS_WIDTH = 1000
CANVAS_MIN_HEIGHT = 220
CANVAS_MAX_HEIGHT = 520
CANVAS_PADDING = 28


def normalize_rect(value: Sequence[int]) -> Rect:
    if len(value) != 4:
        raise ValueError("rect must be left, top, right, bottom")
    left, top, right, bottom = value
    parts = (left, top, right, bottom)
    if any(isinstance(part, bool) or not isinstance(part, int) for part in parts):
        raise ValueError("rect values must be integers")
    return left, top, right, bottom


def rect_width(rect: Rect) -> int:
    return rect[2] - rect[0]


def rect_height(rect: Rect) -> int:
    return rect[3] - rect[1]


def rect_positive(rect: Rect) -> bool:
    return rect_width(rect) > 0 and rect_height(rect) > 0


@dataclass(frozen=True)
class Bounds:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


def virtual_bounds(rects: Sequence[Rect]) -> Bounds:
    """Bounding box of every positive rect. Empty and inverted rects are skipped."""
    usable = [rect for rect in rects if rect_positive(rect)]
    if not usable:
        raise ValueError("no positive rects")
    return Bounds(
        left=min(rect[0] for rect in usable),
        top=min(rect[1] for rect in usable),
        right=max(rect[2] for rect in usable),
        bottom=max(rect[3] for rect in usable),
    )


def intersects_area(left: Rect, right: Rect) -> bool:
    """True when the interiors overlap. A shared edge is not an overlap."""
    return left[0] < right[2] and right[0] < left[2] and left[1] < right[3] and right[1] < left[3]


def suggest_canvas(
    bounds: Bounds,
    *,
    width: float = CANVAS_WIDTH,
    padding: float = CANVAS_PADDING,
    min_height: float = CANVAS_MIN_HEIGHT,
    max_height: float = CANVAS_MAX_HEIGHT,
) -> tuple[float, float, float]:
    """Nominal canvas size. Height follows the desktop aspect, then clamps."""
    if bounds.width <= 0 or bounds.height <= 0:
        raise ValueError("empty desktop")
    if width <= 2 * padding:
        raise ValueError("canvas smaller than padding")
    inner_width = width - 2 * padding
    natural = bounds.height * (inner_width / bounds.width) + 2 * padding
    height = min(max_height, max(min_height, natural))
    return width, height, padding


@dataclass(frozen=True)
class Frame:
    canvas_width: float
    canvas_height: float
    scale: float
    origin_x: float
    origin_y: float
    bounds: Bounds


@dataclass(frozen=True)
class Tile:
    x: float
    y: float
    width: float
    height: float


def fit_frame(
    rects: Sequence[Rect],
    canvas_width: float,
    canvas_height: float,
    padding: float,
) -> Frame:
    if padding < 0:
        raise ValueError("padding must be >= 0")
    if canvas_width <= 2 * padding or canvas_height <= 2 * padding:
        raise ValueError("canvas smaller than padding")
    bounds = virtual_bounds(rects)
    if bounds.width <= 0 or bounds.height <= 0:
        raise ValueError("empty desktop")
    inner_width = canvas_width - 2 * padding
    inner_height = canvas_height - 2 * padding
    scale = min(inner_width / bounds.width, inner_height / bounds.height)
    used_width = bounds.width * scale
    used_height = bounds.height * scale
    return Frame(
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        scale=scale,
        origin_x=padding + (inner_width - used_width) / 2,
        origin_y=padding + (inner_height - used_height) / 2,
        bounds=bounds,
    )


def place_rect(rect: Rect, frame: Frame) -> Tile:
    bounds = frame.bounds
    return Tile(
        x=frame.origin_x + (rect[0] - bounds.left) * frame.scale,
        y=frame.origin_y + (rect[1] - bounds.top) * frame.scale,
        width=rect_width(rect) * frame.scale,
        height=rect_height(rect) * frame.scale,
    )
