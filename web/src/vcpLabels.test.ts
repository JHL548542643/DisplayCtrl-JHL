import assert from "node:assert/strict";
import test from "node:test";
import {
  inputSourceBadge,
  inputSourceKnown,
  inputSourceLabel,
  powerModeBadge,
  powerModeKnown,
  powerModeLabel,
} from "./vcpLabels.ts";

test("input source maps common MCCS codes to short labels", () => {
  assert.equal(inputSourceLabel(0x01), "VGA");
  assert.equal(inputSourceLabel(0x03), "DVI");
  assert.equal(inputSourceLabel(0x0f), "DP");
  assert.equal(inputSourceLabel(0x11), "HDMI");
  assert.equal(inputSourceLabel(0x12), "HDMI-2");
  assert.equal(inputSourceLabel(0x17), "USB-C");
  assert.equal(inputSourceBadge(0x11), "输入 · HDMI");
  assert.equal(inputSourceBadge(0x0f), "输入 · DP");
  assert.equal(inputSourceKnown(0x11), true);
});

test("input source unknown codes keep 输入 · {n} fallback", () => {
  assert.equal(inputSourceBadge(8), "输入 · S端子-2"); // 0x08 is mapped
  assert.equal(inputSourceBadge(50), "输入 · 50");
  assert.equal(inputSourceBadge(99), "输入 · 99");
  assert.equal(inputSourceKnown(50), false);
  assert.equal(inputSourceLabel(50), "输入 · 50");
});

test("power mode maps DPM codes to Chinese short labels", () => {
  assert.equal(powerModeLabel(1), "开机");
  assert.equal(powerModeLabel(2), "待机");
  assert.equal(powerModeLabel(3), "休眠");
  assert.equal(powerModeLabel(4), "关机");
  assert.equal(powerModeLabel(5), "软关机");
  assert.equal(powerModeBadge(1), "电源 · 开机");
  assert.equal(powerModeBadge(2), "电源 · 待机");
  assert.equal(powerModeKnown(1), true);
});

test("power mode unknown codes keep 电源 · {n} fallback", () => {
  assert.equal(powerModeBadge(9), "电源 · 9");
  assert.equal(powerModeLabel(9), "电源 · 9");
  assert.equal(powerModeKnown(9), false);
});

test("badge text for mapped, DisplayPort, and unmapped input codes", () => {
  // 0x08 S-Video-2, 0x0F DisplayPort, 50 unmapped; power 1 = on
  assert.equal(inputSourceBadge(8), "输入 · S端子-2");
  assert.equal(inputSourceBadge(15), "输入 · DP");
  assert.equal(inputSourceBadge(50), "输入 · 50");
  assert.equal(powerModeBadge(1), "电源 · 开机");
});
