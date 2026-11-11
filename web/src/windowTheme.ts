export type ThemeName = "night" | "graphite" | "day";

export function isThemeName(value: string | null | undefined): value is ThemeName {
  return value === "night" || value === "graphite" || value === "day";
}

type NativeApi = {
  set_theme?: (theme: ThemeName) => Promise<unknown> | unknown;
};

export type PyWindow = {
  pywebview?: { api?: NativeApi };
};

export function syncNativeTitleBar(theme: ThemeName, win: PyWindow = window as PyWindow): void {
  const api = win.pywebview?.api;
  if (api?.set_theme) {
    void api.set_theme(theme);
  }
}