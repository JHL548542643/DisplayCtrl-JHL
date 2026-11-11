import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { apiLabel, getHealth, getMonitors, probeRefusalCopy, setContrast, setLuminance, setVolume } from "./api";
import { MONITOR_PROBE_RETRY_DELAY_MS } from "./probeClient";
import { previewMonitors } from "./demoData";
import { DesktopLayout } from "./DesktopLayout";
import type { Health, Monitor, SetResult } from "./types";
import { syncNativeTitleBar } from "./windowTheme";

type ThemeName = "night" | "graphite" | "day";

type Phase =
  | { name: "loading" }
  | { name: "live"; health: Health; monitors: Monitor[] }
  | { name: "refused"; health: Health; title: string; message: string }
  | { name: "down" }
  | { name: "preview"; monitors: Monitor[] };

const THEMES: { id: ThemeName; label: string }[] = [
  { id: "night", label: "夜航" },
  { id: "graphite", label: "石墨" },
  { id: "day", label: "日间" },
];

function initialTheme(): ThemeName {
  const saved = document.documentElement.dataset.theme;
  if (saved === "graphite" || saved === "day" || saved === "night") return saved;
  return "night";
}

type FeatureName = "luminance" | "contrast" | "volume";

function withReading(monitor: Monitor, feature: FeatureName, current: number): Monitor {
  if (feature === "luminance") {
    return {
      ...monitor,
      luminance: monitor.luminance ? { ...monitor.luminance, current } : monitor.luminance,
      capabilities: {
        ...monitor.capabilities,
        luminance: { ...monitor.capabilities.luminance, current },
      },
    };
  }
  if (feature === "contrast") {
    const contrast = monitor.capabilities.contrast;
    if (!contrast) return monitor;
    return {
      ...monitor,
      capabilities: {
        ...monitor.capabilities,
        contrast: { ...contrast, current },
      },
    };
  }
  const volume = monitor.capabilities.volume;
  if (!volume) return monitor;
  return {
    ...monitor,
    capabilities: {
      ...monitor.capabilities,
      volume: { ...volume, current },
    },
  };
}

export function App() {
  const [theme, setTheme] = useState<ThemeName>(initialTheme);
  const [phase, setPhase] = useState<Phase>({ name: "loading" });
  const [refreshing, setRefreshing] = useState(false);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const phaseRef = useRef(phase);
  const loadGen = useRef(0);
  const busy = useRef(0);
  phaseRef.current = phase;

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("displayctl.theme", theme);
    } catch {
      /* 隐私模式不影响控制 */
    }
    syncNativeTitleBar(theme);
    const onReady = () => syncNativeTitleBar(theme);
    window.addEventListener("pywebviewready", onReady);
    return () => window.removeEventListener("pywebviewready", onReady);
  }, [theme]);

  const load = useCallback(async (manual: boolean) => {
    const gen = ++loadGen.current;
    const stale = () => loadGen.current !== gen;
    // 已经在看实况时，后台轮询失败就保持原列表，不必再排队一趟 DDC。
    const retryList = manual || phaseRef.current.name !== "live";
    if (manual) setRefreshing(true);
    try {
      const health = await getHealth();
      if (stale()) return;
      try {
        const monitors = await loadMonitorList(retryList, stale);
        if (stale()) return;
        setPhase({ name: "live", health, monitors });
      } catch (error) {
        if (stale()) return;
        const copy = probeRefusalCopy(error);
        setPhase((current) => {
          if (!manual && current.name === "live") return current;
          return { name: "refused", health, title: copy.title, message: copy.message };
        });
      }
    } catch {
      if (stale()) return;
      setPhase((current) => {
        if (current.name === "preview") return current;
        if (!manual && current.name === "live") return current;
        return { name: "down" };
      });
    } finally {
      if (loadGen.current === gen) setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load(false);
    // 卸载时作废这一代，避免把过期结果写回界面。
    // 不 abort 在途的列表请求：浏览器断开后，服务端那趟 dxva2 仍会占着锁。
    // 新的一次 load 会通过 getMonitors 的 in-flight 合并接上同一次探测。
    return () => {
      loadGen.current += 1;
    };
  }, [load]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.hidden || busy.current > 0) return;
      if (phaseRef.current.name !== "live") return;
      void load(false);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [load]);

    async function commit(
    id: string,
    feature: FeatureName,
    value: number,
  ): Promise<SetResult & { notice?: string }> {
    if (phase.name === "preview") {
      await new Promise((resolve) => window.setTimeout(resolve, 280));
      setPhase({
        name: "preview",
        monitors: phase.monitors.map((monitor) =>
          monitor.id === id ? withReading(monitor, feature, value) : monitor,
        ),
      });
      return {
        monitor_id: id,
        requested: value,
        previous: value,
        verified: value,
        noop: false,
        rolled_back: false,
        notice: "演示回读，没有发送到本机服务。",
      };
    }
    const writer = feature === "luminance" ? setLuminance : feature === "contrast" ? setContrast : setVolume;
    const result = await writer(id, value);
    setPhase((current) => {
      if (current.name !== "live") return current;
      return {
        ...current,
        monitors: current.monitors.map((monitor) =>
          monitor.id === id ? withReading(monitor, feature, result.verified) : monitor,
        ),
      };
    });
    return result;
  }


  const monitors = phase.name === "live" ? phase.monitors : phase.name === "preview" ? phase.monitors : [];

  useEffect(() => {
    if (selectedId && !monitors.some((monitor) => monitor.id === selectedId)) setSelectedId(null);
    if (hoverId && !monitors.some((monitor) => monitor.id === hoverId)) setHoverId(null);
  }, [monitors, selectedId, hoverId]);

  const writable = monitors.filter((monitor) => monitor.capabilities.luminance.writable).length;
  const health = phase.name === "live" || phase.name === "refused" ? phase.health : null;
  const demoBanner =
    phase.name === "preview"
      ? "离线界面演示 · 不会发送写入"
      : health?.demo
        ? "演示后端 · 写入只改本进程里的假数据"
        : null;
  const link =
    health == null
      ? "未连接"
      : health.demo
        ? `${health.backend} · 演示`
        : `${health.backend} · 本机`;

  return (
    <div className="app">
      <div className="bezel">
        <header className="topbar">
          <div className="brand">
            <svg className="mark" viewBox="0 0 32 32" aria-hidden="true">
              <rect x="2" y="4" width="18" height="12" rx="2.5" />
              <rect x="12" y="15" width="18" height="12" rx="2.5" />
            </svg>
            <div>
              <strong>DisplayCtl</strong>
              <span>外接显示控制台</span>
            </div>
          </div>
          <div className="top-actions">
            <p className="link-pill" data-state={health ? (health.demo ? "demo" : "live") : "down"}>
              <i />
              {link}
              <span>{apiLabel()}</span>
            </p>
            <div className="themes" role="group" aria-label="主题">
              {THEMES.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  aria-pressed={theme === item.id}
                  onClick={() => setTheme(item.id)}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <button type="button" className="btn" onClick={() => void load(true)} disabled={refreshing}>
              {refreshing ? "探测中" : "重新探测"}
            </button>
          </div>
        </header>

        {demoBanner ? <div className="banner">{demoBanner}</div> : null}

        <main>
          <section className="bridge" aria-label="摘要">
            <div>
              <span>在册</span>
              <strong>{phase.name === "loading" ? "—" : monitors.length}</strong>
            </div>
            <div>
              <span>可写</span>
              <strong>{phase.name === "loading" ? "—" : writable}</strong>
            </div>
          </section>

          {phase.name === "loading" ? <div className="skeleton stage-skeleton" aria-busy="true" /> : null}

          {phase.name === "down" ? (
            <StatePanel
              testId="offline-state"
              kicker="Loopback"
              title="控制服务未连接"
              body="界面只访问本机 127.0.0.1:8765。先在这台机器上启动 API，不要把端口转到局域网。"
            >
              <button type="button" className="btn primary" onClick={() => void load(true)}>
                重试
              </button>
              <button
                type="button"
                className="btn"
                onClick={() => setPhase({ name: "preview", monitors: previewMonitors.map((item) => ({ ...item, capabilities: structuredClone(item.capabilities) })) })}
              >
                查看界面演示
              </button>
            </StatePanel>
          ) : null}

          {phase.name === "refused" ? (
            <StatePanel testId="refused-state" kicker={phase.health.platform} title={phase.title} body={phase.message}>
              <button type="button" className="btn primary" onClick={() => void load(true)}>
                重试
              </button>
              <button
                type="button"
                className="btn"
                onClick={() => setPhase({ name: "preview", monitors: previewMonitors.map((item) => ({ ...item, capabilities: structuredClone(item.capabilities) })) })}
              >
                查看界面演示
              </button>
            </StatePanel>
          ) : null}

          {phase.name !== "loading" && phase.name !== "down" && phase.name !== "refused" && monitors.length === 0 ? (
            <StatePanel
              testId="empty-state"
              kicker="dxva2"
              title="没有发现物理显示器"
              body="接上外接显示器并打开扩展模式后，再探测一次。"
            >
              <button type="button" className="btn primary" onClick={() => void load(true)}>
                重新探测
              </button>
            </StatePanel>
          ) : null}

          {monitors.length > 0 ? (
            <DesktopLayout
              monitors={monitors}
              hoverId={hoverId}
              selectedId={selectedId}
              onHover={setHoverId}
              onSelect={setSelectedId}
              onCommit={commit}
              onBusy={(active) => {
                busy.current += active ? 1 : -1;
              }}
            />
          ) : null}
        </main>
      </div>
    </div>
  );
}

async function loadMonitorList(retry: boolean, stale: () => boolean): Promise<Monitor[]> {
  try {
    return await getMonitors();
  } catch (error) {
    if (!retry || stale() || !probeRefusalCopy(error).retryList) throw error;
    await new Promise((resolve) => window.setTimeout(resolve, MONITOR_PROBE_RETRY_DELAY_MS));
    if (stale()) throw error;
    return await getMonitors();
  }
}

function StatePanel({
  kicker,
  title,
  body,
  testId,
  children,
}: {
  kicker: string;
  title: string;
  body: string;
  testId: string;
  children: ReactNode;
}) {
  return (
    <section className="state" data-testid={testId}>
      <MonitorGlyph />
      <p className="kicker">{kicker}</p>
      <h2>{title}</h2>
      <p>{body}</p>
      <div className="actions">{children}</div>
    </section>
  );
}

function MonitorGlyph() {
  return (
    <svg className="glyph" viewBox="0 0 80 64" aria-hidden="true">
      <rect x="6" y="6" width="68" height="42" rx="6" />
      <path d="M28 54h24M40 48v6" />
      <path className="slash" d="M24 18l32 24" />
    </svg>
  );
}
