import type { Monitor } from "./types";
import { inputSourceBadge, powerModeBadge } from "./vcpLabels";

export function luminanceNow(monitor: Monitor): number | null {
  const cap = monitor.capabilities.luminance;
  if (cap.readable && cap.current !== null) return cap.current;
  return monitor.luminance?.current ?? null;
}

export function canAdjustLuminance(monitor: Monitor): boolean {
  return monitor.capabilities.luminance.writable && luminanceNow(monitor) !== null;
}

export type CapMark = "readable" | "declared" | "absent" | "unknown";
export type ContrastMark = CapMark;

function scalarMark(cap: { declared: boolean; readable: boolean } | null | undefined): CapMark {
  if (!cap) return "unknown";
  if (cap.readable) return "readable";
  if (cap.declared) return "declared";
  return "absent";
}

function scalarVisible(cap: { declared: boolean; readable: boolean } | null | undefined): boolean {
  if (!cap) return false;
  return cap.readable || cap.declared;
}

function scalarView(
  cap: { declared: boolean; readable: boolean; current: number | null; maximum: number | null } | null | undefined,
  readableLabel: (current: number, maximum: number) => { label: string; title: string },
  declaredOnly: { label: string; title: string },
): { label: string; title: string } | null {
  if (!cap || (!cap.readable && !cap.declared)) return null;
  if (cap.readable && cap.current !== null && cap.maximum !== null) {
    return readableLabel(cap.current, cap.maximum);
  }
  return declaredOnly;
}

export function contrastMark(monitor: Monitor): ContrastMark {
  return scalarMark(monitor.capabilities.contrast);
}

export function contrastVisible(monitor: Monitor): boolean {
  return scalarVisible(monitor.capabilities.contrast);
}

export function contrastView(monitor: Monitor): { label: string; title: string } | null {
  return scalarView(
    monitor.capabilities.contrast,
    (current, maximum) => ({
      label: `对比度 · ${current}`,
      title: `GetVCP 读到对比度 ${current}/${maximum}。只读，不写入。`,
    }),
    {
      label: "对比度 · 只读",
      title: "能力字符串声明了对比度。只读，不写入。",
    },
  );
}

export function volumeMark(monitor: Monitor): CapMark {
  return scalarMark(monitor.capabilities.volume);
}

export function volumeVisible(monitor: Monitor): boolean {
  return scalarVisible(monitor.capabilities.volume);
}

export function volumeView(monitor: Monitor): { label: string; title: string } | null {
  return scalarView(
    monitor.capabilities.volume,
    (current, maximum) => ({
      label: `音量 · ${current}`,
      title: `GetVCP 读到音量 ${current}/${maximum}。只读，不写入。`,
    }),
    {
      label: "音量 · 只读",
      title: "能力字符串声明了音量。只读，不写入。",
    },
  );
}

export function rgbMark(monitor: Monitor): CapMark {
  return scalarMark(monitor.capabilities.rgb_gains);
}

export function rgbVisible(monitor: Monitor): boolean {
  return scalarVisible(monitor.capabilities.rgb_gains);
}

export function rgbView(monitor: Monitor): { label: string; title: string } | null {
  const rgb = monitor.capabilities.rgb_gains;
  if (!rgb || (!rgb.readable && !rgb.declared)) return null;
  if (rgb.readable) {
    const parts = [rgb.red, rgb.green, rgb.blue].map((channel) =>
      channel.readable && channel.current !== null ? String(channel.current) : "-",
    );
    const detail = [rgb.red, rgb.green, rgb.blue]
      .map((channel) => {
        if (channel.readable && channel.current !== null && channel.maximum !== null) {
          return `${channel.vcp}=${channel.current}/${channel.maximum}`;
        }
        return `${channel.vcp}=—`;
      })
      .join(" ");
    return {
      label: `RGB · ${parts.join("/")}`,
      title: `GetVCP 读到 RGB 增益 ${detail}。只读，不写入。`,
    };
  }
  return {
    label: "RGB · 只读",
    title: "能力字符串声明了 RGB 增益。只读，不写入。",
  };
}

export function inputSourceMark(monitor: Monitor): CapMark {
  return scalarMark(monitor.capabilities.input_source);
}

export function inputSourceVisible(monitor: Monitor): boolean {
  return scalarVisible(monitor.capabilities.input_source);
}

export function inputSourceView(monitor: Monitor): { label: string; title: string } | null {
  return scalarView(
    monitor.capabilities.input_source,
    (current, maximum) => ({
      label: inputSourceBadge(current),
      title: `GetVCP 读到输入源 ${current}/${maximum}（${inputSourceBadge(current)}）。只读，不写入。`,
    }),
    {
      label: "输入 · 只读",
      title: "能力字符串声明了输入源。只读，不写入。",
    },
  );
}

export function powerModeMark(monitor: Monitor): CapMark {
  return scalarMark(monitor.capabilities.power_mode);
}

export function powerModeVisible(monitor: Monitor): boolean {
  return scalarVisible(monitor.capabilities.power_mode);
}

export function powerModeView(monitor: Monitor): { label: string; title: string } | null {
  return scalarView(
    monitor.capabilities.power_mode,
    (current, maximum) => ({
      label: powerModeBadge(current),
      title: `GetVCP 读到电源模式 ${current}/${maximum}（${powerModeBadge(current)}）。只读，不写入。`,
    }),
    {
      label: "电源 · 只读",
      title: "能力字符串声明了电源模式。只读，不写入。",
    },
  );
}

export function canAdjustContrast(monitor: Monitor): boolean {
  const cap = monitor.capabilities.contrast;
  return Boolean(cap && cap.writable && cap.readable && cap.current !== null && cap.maximum !== null);
}

export function canAdjustVolume(monitor: Monitor): boolean {
  const cap = monitor.capabilities.volume;
  return Boolean(cap && cap.writable && cap.readable && cap.current !== null && cap.maximum !== null);
}

export function contrastNow(monitor: Monitor): number | null {
  const cap = monitor.capabilities.contrast;
  if (cap && cap.readable && cap.current !== null) return cap.current;
  return null;
}

export function volumeNow(monitor: Monitor): number | null {
  const cap = monitor.capabilities.volume;
  if (cap && cap.readable && cap.current !== null) return cap.current;
  return null;
}
