/** MCCS-ish short labels for discrete VCP badge text. API keeps raw current/max. */

/** VESA MCCS Input Source Select (0x60) — common codes. Unknown → null. */
const INPUT_SOURCE_LABELS: Record<number, string> = {
  0x01: "VGA",
  0x02: "VGA-2",
  0x03: "DVI",
  0x04: "DVI-2",
  0x05: "复合",
  0x06: "复合-2",
  0x07: "S端子",
  0x08: "S端子-2",
  0x09: "Tuner",
  0x0a: "Tuner-2",
  0x0b: "Tuner-3",
  0x0c: "分量",
  0x0d: "分量-2",
  0x0e: "分量-3",
  0x0f: "DP",
  0x10: "DP-2",
  0x11: "HDMI",
  0x12: "HDMI-2",
  0x13: "HDMI-3",
  0x14: "HDMI-4",
  // Vendor / USB-C adjacent codes seen in the wild (not all MCCS-standard).
  0x17: "USB-C",
  0x18: "USB-C",
  0x19: "USB-C",
  0x1b: "USB-C",
};

/** VESA MCCS Power Mode (0xD6). */
const POWER_MODE_LABELS: Record<number, string> = {
  0x01: "开机",
  0x02: "待机",
  0x03: "休眠",
  0x04: "关机",
  0x05: "软关机",
};

export function inputSourceLabel(code: number): string {
  return INPUT_SOURCE_LABELS[code] ?? `输入 · ${code}`;
}

/** Badge text: known code →「输入 · HDMI」; unknown →「输入 · {n}」. */
export function inputSourceBadge(code: number): string {
  const known = INPUT_SOURCE_LABELS[code];
  if (known) return `输入 · ${known}`;
  return `输入 · ${code}`;
}

export function powerModeLabel(code: number): string {
  return POWER_MODE_LABELS[code] ?? `电源 · ${code}`;
}

/** Badge text: known code →「电源 · 开机」; unknown →「电源 · {n}」. */
export function powerModeBadge(code: number): string {
  const known = POWER_MODE_LABELS[code];
  if (known) return `电源 · ${known}`;
  return `电源 · ${code}`;
}

export function inputSourceKnown(code: number): boolean {
  return Object.prototype.hasOwnProperty.call(INPUT_SOURCE_LABELS, code);
}

export function powerModeKnown(code: number): boolean {
  return Object.prototype.hasOwnProperty.call(POWER_MODE_LABELS, code);
}
