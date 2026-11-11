"""Layout math. No Win32, no brightness writes."""

from pathlib import Path

from fastapi.testclient import TestClient

from displayctl.api import build_app
from displayctl.demo import demo_backend, demo_service
from displayctl.geometry import (
    CANVAS_MAX_HEIGHT,
    CANVAS_MIN_HEIGHT,
    CANVAS_PADDING,
    CANVAS_WIDTH,
    Bounds,
    fit_frame,
    intersects_area,
    normalize_rect,
    place_rect,
    rect_height,
    rect_width,
    suggest_canvas,
    virtual_bounds,
)

# Positions reported from a real extended desktop (L_D): laptop primary at the
# origin, one panel above-left, one above-right. Coordinates are allowed to
# be negative and the panels are different sizes.
LAPTOP = (0, 0, 1646, 1029)
Q24 = (-1088, -1440, 960, -288)
Q27 = (1472, -1440, 4032, 0)
LD_DESK = (LAPTOP, Q24, Q27)

# demo.py desk. Kept here so a future edit cannot stack panels on the origin
# without failing this file.
DEMO_LEFT = (-320, -1440, 2240, 0)
DEMO_RIGHT = (2240, -1440, 4160, 0)
DEMO_SIDE = (1920, 0, 3840, 1080)
DEMO_LAPTOP = (0, 0, 1920, 1080)


def test_width_and_height_helpers():
    assert rect_width(Q24) == 2048
    assert rect_height(Q24) == 1152
    assert rect_width(Q27) == 2560
    assert rect_height(Q27) == 1440
    assert rect_width(LAPTOP) == 1646
    assert rect_height(LAPTOP) == 1029
    assert normalize_rect([0, 0, 10, 20]) == (0, 0, 10, 20)


def test_normalize_rect_rejects_bad_values():
    for value in ((), (0, 0, 1), (0, 0, 1, 2, 3), (True, 0, 1, 1), (0.5, 0, 1, 1)):
        try:
            normalize_rect(value)  # type: ignore[arg-type]
        except ValueError:
            continue
        raise AssertionError(value)


def test_virtual_bounds_include_negative_coordinates():
    bounds = virtual_bounds(LD_DESK)
    assert bounds == Bounds(-1088, -1440, 4032, 1029)
    assert bounds.width == 5120
    assert bounds.height == 2469


def test_non_positive_rects_do_not_move_the_bounds():
    bounds = virtual_bounds([(0, 0, 100, 80), (0, 0, 0, 50), (5, 5, 4, 9), (10, 10, 10, 40)])
    assert bounds == Bounds(0, 0, 100, 80)
    try:
        virtual_bounds([(0, 0, 0, 10), (2, 2, 1, 1)])
    except ValueError:
        return
    raise AssertionError("expected no positive rects")


def test_shared_edge_is_not_an_overlap():
    assert intersects_area((0, 0, 100, 100), (100, 0, 200, 80)) is False
    assert intersects_area((0, 0, 100, 100), (40, -20, 80, 0)) is False
    assert intersects_area((0, 0, 100, 100), (50, 10, 150, 40)) is True
    assert intersects_area((0, 0, 1920, 1080), (0, 0, 2560, 1440)) is True
    assert intersects_area(Q24, LAPTOP) is False
    assert intersects_area(Q27, LAPTOP) is False
    assert intersects_area(Q24, Q27) is False


def test_user_desk_fits_inside_padded_canvas_and_keeps_gaps():
    bounds = virtual_bounds(LD_DESK)
    width, height, padding = suggest_canvas(bounds)
    assert width == CANVAS_WIDTH
    assert padding == CANVAS_PADDING
    assert CANVAS_MIN_HEIGHT <= height <= CANVAS_MAX_HEIGHT
    frame = fit_frame(LD_DESK, width, height, padding)
    laptop, q24, q27 = (place_rect(rect, frame) for rect in LD_DESK)
    for tile in (laptop, q24, q27):
        assert tile.x >= padding - 1e-6
        assert tile.y >= padding - 1e-6
        assert tile.x + tile.width <= width - padding + 1e-6
        assert tile.y + tile.height <= height - padding + 1e-6
        assert tile.width > 0 and tile.height > 0
    assert q24.x < laptop.x
    assert q27.x > laptop.x
    assert q24.y < laptop.y
    assert q27.y < laptop.y
    assert abs((q27.width / laptop.width) - (2560 / 1646)) < 1e-9
    assert abs((q24.height / q27.height) - (1152 / 1440)) < 1e-9
    gap = LAPTOP[1] - Q24[3]
    assert gap == 288
    assert abs((laptop.y - (q24.y + q24.height)) - gap * frame.scale) < 1e-6
    assert abs((q27.y + q27.height) - laptop.y) < 1e-6
    assert q27.x < laptop.x + laptop.width


def test_matching_aspect_uses_the_full_inner_box():
    bounds = virtual_bounds(LD_DESK)
    padding = 10
    frame = fit_frame(LD_DESK, bounds.width + 2 * padding, bounds.height + 2 * padding, padding)
    assert abs(frame.scale - 1) < 1e-9
    q24 = place_rect(Q24, frame)
    laptop = place_rect(LAPTOP, frame)
    assert abs(q24.x - padding) < 1e-6
    assert abs(q24.y - padding) < 1e-6
    assert abs(laptop.x - (padding + (LAPTOP[0] - bounds.left))) < 1e-6
    assert abs(laptop.y - (padding + (LAPTOP[1] - bounds.top))) < 1e-6


def test_short_canvas_letterboxes_a_wide_desktop():
    frame = fit_frame(LD_DESK, 1000, 220, 16)
    tiles = [place_rect(rect, frame) for rect in LD_DESK]
    left = min(tile.x for tile in tiles)
    right = max(tile.x + tile.width for tile in tiles)
    top = min(tile.y for tile in tiles)
    bottom = max(tile.y + tile.height for tile in tiles)
    assert left > 16 + 1
    assert 1000 - right > 16 + 1
    assert abs(top - 16) < 1e-6
    assert abs(bottom - (220 - 16)) < 1e-6
    assert abs(tiles[0].width / rect_width(LAPTOP) - tiles[1].width / rect_width(Q24)) < 1e-9


def test_suggest_canvas_clamps_extreme_aspects():
    wide, wide_height, pad = suggest_canvas(Bounds(0, 0, 10000, 100))
    tall, tall_height, _pad = suggest_canvas(Bounds(0, 0, 100, 8000))
    assert (wide, pad) == (CANVAS_WIDTH, CANVAS_PADDING)
    assert wide_height == CANVAS_MIN_HEIGHT
    assert tall_height == CANVAS_MAX_HEIGHT
    try:
        fit_frame([LAPTOP], 30, 30, 20)
    except ValueError:
        return
    raise AssertionError("expected canvas smaller than padding")


def test_demo_desk_is_split_and_not_stacked_at_the_origin():
    monitors = {monitor.device: monitor for monitor in demo_backend().monitors}
    assert monitors[r"\\.\DISPLAY2"].rect == DEMO_LEFT
    assert monitors[r"\\.\DISPLAY3"].rect == DEMO_RIGHT
    assert monitors[r"\\.\DISPLAY4"].rect == DEMO_SIDE
    assert monitors[r"\\.\DISPLAY1"].rect == DEMO_LAPTOP
    assert monitors[r"\\.\DISPLAY1"].primary is True
    assert monitors[r"\\.\DISPLAY2"].primary is False
    rects = [monitor.rect for monitor in monitors.values()]
    for index, left in enumerate(rects):
        for right in rects[index + 1 :]:
            assert intersects_area(left, right) is False
    bounds = virtual_bounds(rects)
    assert bounds.left < 0 and bounds.top < 0
    frame = fit_frame(rects, 1000, 480, CANVAS_PADDING)
    left = place_rect(DEMO_LEFT, frame)
    right = place_rect(DEMO_RIGHT, frame)
    laptop = place_rect(DEMO_LAPTOP, frame)
    side = place_rect(DEMO_SIDE, frame)
    assert left.x < right.x
    assert left.y < laptop.y and right.y < laptop.y
    assert side.x >= laptop.x + laptop.width - 1e-6
    assert abs(side.y - laptop.y) < 1e-6


def test_api_passes_demo_rects_through_unchanged():
    client = TestClient(build_app(demo_service()))
    payload = client.get("/api/monitors").json()["monitors"]
    listed = {monitor["device"]: tuple(monitor["rect"]) for monitor in payload}
    backend = {monitor.device: monitor.rect for monitor in demo_backend().monitors}
    assert listed == backend
    assert all(len(monitor["rect"]) == 4 for monitor in payload)


def test_preview_sample_uses_the_same_desk():
    text = Path("web/src/demoData.ts").read_text(encoding="utf-8")
    for rect in (DEMO_LEFT, DEMO_RIGHT, DEMO_SIDE, DEMO_LAPTOP):
        assert f"rect: [{', '.join(str(part) for part in rect)}]" in text


def test_frontend_canvas_constants_match_python():
    text = Path("web/src/layout.ts").read_text(encoding="utf-8")
    assert f"CANVAS_WIDTH = {CANVAS_WIDTH}" in text
    assert f"CANVAS_MIN_HEIGHT = {CANVAS_MIN_HEIGHT}" in text
    assert f"CANVAS_MAX_HEIGHT = {CANVAS_MAX_HEIGHT}" in text
    assert f"CANVAS_PADDING = {CANVAS_PADDING}" in text
    assert "setLuminance" not in text
    desktop = Path("web/src/DesktopLayout.tsx").read_text(encoding="utf-8")
    assert "setLuminance" not in desktop
    assert "confirm" not in desktop


def test_geometry_module_does_not_touch_writes():
    source = Path("displayctl/geometry.py").read_text(encoding="utf-8")
    for needle in ("SetVCP", "dxva2", "set_luminance", "ctypes"):
        assert needle not in source
