export const FAILURE_LABEL: Record<string, string> = {
  ddc_off: "DDC 关闭",
  cable: "链路异常",
  internal_panel: "内置屏",
  transient: "瞬时失败",
  unsupported: "不支持亮度",
  unsupported_scale: "刻度不明",
  probe_failed: "探测失败",
  identity_ambiguous: "身份冲突",
  identity_unstable: "身份不足",
  platform_unsupported: "无后端",
};

export const QUALITY_LABEL: Record<string, string> = {
  strong: "序列号",
  model: "型号 · 当前唯一",
  unstable: "不足",
  ambiguous: "冲突",
};

export function chipLabel(writable: boolean, failure: string | null): string {
  if (writable) return "可写";
  if (!failure) return "不可写";
  return FAILURE_LABEL[failure] ?? "不可写";
}

export function chipTone(writable: boolean, failure: string | null): "ok" | "warn" | "danger" | "neutral" {
  if (writable) return "ok";
  if (failure === "internal_panel" || failure === "platform_unsupported") return "neutral";
  if (failure === "identity_ambiguous" || failure === "identity_unstable" || failure === "rollback_failed") {
    return "danger";
  }
  return "warn";
}

export function displayName(model: string | null, description: string): string {
  return model || description || "未命名显示器";
}

export function shortDevice(device: string): string {
  return device.replace(/^\\\\\.\\/, "") || device;
}
