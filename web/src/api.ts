import type { Health, Monitor, SetResult } from "./types";
import {
  ApiError,
  HEALTH_TIMEOUT_MS,
  LUMINANCE_TIMEOUT_MS,
  MONITORS_TIMEOUT_MS,
  shareInflight,
} from "./probeClient";

export { ApiError, HEALTH_TIMEOUT_MS, LUMINANCE_TIMEOUT_MS, MONITORS_TIMEOUT_MS, probeRefusalCopy } from "./probeClient";

const DEFAULT_API = "http://127.0.0.1:8765";

function configuredApi(): string {
  const fromEnv = import.meta.env.VITE_API_BASE?.trim();
  if (fromEnv) return fromEnv.replace(/\/$/, "");
  return DEFAULT_API;
}

// 开发服务器端口会变。请求留在当前源，由 Vite 把 /api 转到 VITE_API_BASE（默认 8765）。
// 构建后的页面才用绝对地址：有 VITE_API_BASE 用它，否则与提供页面的 API 同源。
export function apiBase(): string {
  if (import.meta.env.DEV) return "";
  const fromEnv = import.meta.env.VITE_API_BASE?.trim();
  if (fromEnv) return fromEnv.replace(/\/$/, "");
  if (typeof window !== "undefined") return window.location.origin;
  return DEFAULT_API;
}

export function apiLabel(): string {
  const absolute = import.meta.env.DEV ? configuredApi() : apiBase() || configuredApi();
  return absolute.replace(/^https?:\/\//, "");
}

async function readError(response: Response): Promise<ApiError> {
  try {
    const payload = (await response.json()) as { error?: { kind: string; message: string; retryable: boolean } };
    if (payload.error?.message) return new ApiError(payload.error);
  } catch {
    /* 非 JSON 错误也要能显示 */
  }
  return new ApiError({
    kind: "probe_failed",
    message: `控制服务返回 ${response.status}`,
    retryable: false,
  });
}

async function getJson<T>(path: string, timeoutMs: number): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, {
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!response.ok) throw await readError(response);
  return (await response.json()) as T;
}

export function getHealth(): Promise<Health> {
  return getJson<Health>("/api/health", HEALTH_TIMEOUT_MS);
}

const monitorsInflight: { current: Promise<Monitor[]> | null } = { current: null };

export function getMonitors(): Promise<Monitor[]> {
  return shareInflight(monitorsInflight, async () => {
    const payload = await getJson<{ ok: boolean; monitors: Monitor[] }>("/api/monitors", MONITORS_TIMEOUT_MS);
    return payload.monitors;
  });
}

export async function setLuminance(monitorId: string, value: number): Promise<SetResult> {
  return setFeature(monitorId, "luminance", value);
}

export async function setContrast(monitorId: string, value: number): Promise<SetResult> {
  return setFeature(monitorId, "contrast", value);
}

export async function setVolume(monitorId: string, value: number): Promise<SetResult> {
  return setFeature(monitorId, "volume", value);
}

async function setFeature(
  monitorId: string,
  feature: "luminance" | "contrast" | "volume",
  value: number,
): Promise<SetResult> {
  const response = await fetch(`${apiBase()}/api/monitors/${encodeURIComponent(monitorId)}/${feature}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ value, confirm: true }),
    signal: AbortSignal.timeout(LUMINANCE_TIMEOUT_MS),
  });
  if (!response.ok) throw await readError(response);
  const payload = (await response.json()) as { result: SetResult };
  return payload.result;
}
