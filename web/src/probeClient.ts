import type { ApiErrorBody } from "./types";

/**
 * `/api/health` 不枚举显示器。保持原来的 8 秒，离线时尽快落到「未连接」。
 * 列表和亮度要等 dxva2。能力字符串已缓存、或 0x10 失败而跳过时，列表大体是
 * 枚举加每台屏一次 GetVCP，大约 1 秒这一量级；第一次仍可能为每台外接屏读一次
 * 能力字符串。30 秒盖住这一趟。服务端列表探测是 singleflight，重叠的 GET
 * 不会再各排一串 DDC。时限只决定浏览器何时放弃等待，不放宽确认、单次写入、回读或回滚。
 */
export const HEALTH_TIMEOUT_MS = 8_000;
export const MONITORS_TIMEOUT_MS = 30_000;
export const LUMINANCE_TIMEOUT_MS = 30_000;

/**
 * 列表失败后只自动再要一次。间隔短，是为了赶上服务端刚填上的枚举缓存；
 * 写入路径不使用这个间隔，也不会因此再发 POST。
 */
export const MONITOR_PROBE_RETRY_DELAY_MS = 1_000;

export class ApiError extends Error {
  kind: string;
  retryable: boolean;

  constructor(body: ApiErrorBody) {
    super(body.message);
    this.kind = body.kind;
    this.retryable = body.retryable;
  }
}

export type ProbeRefusalCopy = {
  title: string;
  message: string;
  /** 只用于再拉一次显示器列表，绝不用于亮度写入。 */
  retryList: boolean;
};

const REFUSED_TITLE = "这块机器现在不能写显示器";
const INCOMPLETE_TITLE = "这次没有完成显示器探测";

export function probeRefusalCopy(error: unknown): ProbeRefusalCopy {
  if (error instanceof ApiError) {
    return {
      title: REFUSED_TITLE,
      message: error.message,
      retryList: error.retryable,
    };
  }
  if (isClientTimeout(error)) {
    return {
      title: INCOMPLETE_TITLE,
      message: "探测超时。多屏 dxva2 枚举可能要十几秒，界面已自动重试一次。若仍是这页，请再点「重试」。",
      retryList: true,
    };
  }
  if (error instanceof TypeError) {
    return {
      title: INCOMPLETE_TITLE,
      message: "探测失败。控制服务在线，但这次没有拿到显示器列表。界面已自动重试一次，请再点「重试」。",
      retryList: true,
    };
  }
  return {
    title: INCOMPLETE_TITLE,
    message: "探测失败。控制服务在线，但这次没有拿到显示器列表，请点「重试」。",
    retryList: false,
  };
}

function isClientTimeout(error: unknown): boolean {
  // AbortSignal.timeout() 规范上是 TimeoutError。部分浏览器仍报 AbortError，
  // 而列表请求上唯一的 AbortSignal 就是这个时限。
  return hasName(error, "TimeoutError") || hasName(error, "AbortError");
}

function hasName(error: unknown, name: string): boolean {
  return typeof error === "object" && error !== null && (error as { name?: unknown }).name === name;
}

/**
 * 重叠的相同列表探测共用一个 Promise，避免发出第二笔 HTTP。
 * 服务端也会把同时进来的列表探测合成一趟 DDC。取消前一个 fetch 停不掉
 * 已经开始的枚举。`start` 不应再入同一个 slot。
 */
export function shareInflight<T>(slot: { current: Promise<T> | null }, start: () => Promise<T>): Promise<T> {
  if (slot.current) return slot.current;
  const flight = start().finally(() => {
    if (slot.current === flight) slot.current = null;
  });
  slot.current = flight;
  return flight;
}
