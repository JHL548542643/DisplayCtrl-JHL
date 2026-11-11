import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./api";
import {
  canAdjustContrast,
  canAdjustLuminance,
  canAdjustVolume,
  contrastMark,
  contrastNow,
  contrastView,
  contrastVisible,
  inputSourceView,
  inputSourceVisible,
  luminanceNow,
  powerModeView,
  powerModeVisible,
  rgbView,
  rgbVisible,
  volumeNow,
  volumeView,
  volumeVisible,
} from "./capabilities";
import { chipLabel, displayName } from "./labels";
import { placeMonitors } from "./layout";
import type { CSSProperties } from "react";
import type { Monitor, SetResult } from "./types";

type FeatureName = "luminance" | "contrast" | "volume";

type Draft = {
  pending: number;
  dirty: boolean;
  saving: boolean;
  note: string | null;
  fault: string | null;
};

type CommitResult = SetResult & { notice?: string };

type Props = {
  monitors: Monitor[];
  hoverId: string | null;
  selectedId: string | null;
  onHover: (id: string | null) => void;
  onSelect: (id: string) => void;
  onCommit: (id: string, feature: FeatureName, value: number) => Promise<CommitResult>;
  onBusy: (active: boolean) => void;
};

export function DesktopLayout({
  monitors,
  hoverId,
  selectedId,
  onHover,
  onSelect,
  onCommit,
  onBusy,
}: Props) {
  const placed = placeMonitors(monitors);
  const skipped = monitors.length - (placed?.tiles.length ?? 0);
  const tiles = placed
    ? [...placed.tiles].sort((a, b) => b.width * b.height - a.width * a.height || a.id.localeCompare(b.id))
    : [];
  const byId = new Map(monitors.map((monitor) => [monitor.id, monitor]));
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const reportDraft = useCallback((id: string, draft: Draft) => {
    setDrafts((current) => {
      const previous = current[id];
      if (
        previous &&
        previous.pending === draft.pending &&
        previous.dirty === draft.dirty &&
        previous.saving === draft.saving &&
        previous.note === draft.note &&
        previous.fault === draft.fault
      ) {
        return current;
      }
      return { ...current, [id]: draft };
    });
  }, []);

  const selected = selectedId ? byId.get(selectedId) ?? null : null;
  const selectedDraft = selected ? drafts[selected.id] : undefined;

  return (
    <section className="layout-map" aria-labelledby="desktop-layout-title" data-testid="desktop-layout">
      <div className="layout-map-head">
        <div>
          <h2 id="desktop-layout-title">桌面</h2>
          <p>滑块只改这块屏上的数字，点「应用」才写入。虚线屏不能写。</p>
        </div>
      </div>

      {placed ? (
        <div
          className="layout-stage"
          style={{ aspectRatio: `${placed.width} / ${placed.height}` }}
          role="list"
        >
          {tiles.map((tile) => {
            const monitor = byId.get(tile.id);
            if (!monitor) return null;
            const linked = monitor.id === selectedId ? "selected" : monitor.id === hoverId ? "hover" : null;
            return (
              <MonitorTile
                key={monitor.id}
                monitor={monitor}
                linked={linked}
                style={{
                  left: `${(tile.x / placed.width) * 100}%`,
                  top: `${(tile.y / placed.height) * 100}%`,
                  width: `${(tile.width / placed.width) * 100}%`,
                  height: `${(tile.height / placed.height) * 100}%`,
                }}
                onHover={onHover}
                onSelect={onSelect}
                onCommit={onCommit}
                onBusy={onBusy}
                onDraft={reportDraft}
              />
            );
          })}
        </div>
      ) : (
        <p className="layout-note">这些显示器没有可用的矩形坐标，布局画不出来。</p>
      )}

      {selected ? <DetailLine monitor={selected} draft={selectedDraft} /> : null}
      {skipped > 0 && placed ? <p className="layout-note">{skipped} 台没有坐标，没有画出来。</p> : null}
    </section>
  );
}

function DetailLine({ monitor, draft }: { monitor: Monitor; draft: Draft | undefined }) {
  const name = displayName(monitor.model, monitor.description);
  const reading = luminanceNow(monitor);
  const mark = contrastMark(monitor);
  let text: string;
  if (draft?.fault) text = draft.fault;
  else if (draft?.note) text = draft.note;
  else if (draft?.dirty && reading !== null) {
    text = draft.pending <= 10 ? `${reading} → ${draft.pending}，偏低` : `${reading} → ${draft.pending}`;
  } else if (!canAdjustLuminance(monitor)) text = chipLabel(false, monitor.failure);
  else if (mark === "readable") {
    const view = contrastView(monitor);
    text = view ? view.title.replace("。只读，不写入。", "") : "对比度可读";
  } else if (mark === "declared") text = "对比度已声明，只读";
  else if (mark === "absent") text = "对比度未声明";
  else {
    const volume = volumeView(monitor);
    const rgb = rgbView(monitor);
    if (volume?.label.includes("·") && volume.label !== "音量 · 只读") {
      text = volume.title.replace("。只读，不写入。", "");
    } else if (rgb && rgb.label !== "RGB · 只读") {
      text = rgb.title.replace("。只读，不写入。", "");
    } else text = "亮度可写";
  }

  return (
    <p className="detail" data-monitor-id={monitor.id} data-testid="monitor-detail" aria-live="polite">
      <strong>{name}</strong>
      <span>{text}</span>
    </p>
  );
}

function MonitorTile({
  monitor,
  linked,
  style,
  onHover,
  onSelect,
  onCommit,
  onBusy,
  onDraft,
}: {
  monitor: Monitor;
  linked: "selected" | "hover" | null;
  style: CSSProperties;
  onHover: (id: string | null) => void;
  onSelect: (id: string) => void;
  onCommit: (id: string, feature: FeatureName, value: number) => Promise<CommitResult>;
  onBusy: (active: boolean) => void;
  onDraft: (id: string, draft: Draft) => void;
}) {
  const reading = luminanceNow(monitor);
  const adjustable = canAdjustLuminance(monitor);
  const contrastAdjustable = canAdjustContrast(monitor);
  const volumeAdjustable = canAdjustVolume(monitor);
  const mark = contrastMark(monitor);
  const [pending, setPending] = useState(reading ?? 0);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [fault, setFault] = useState<string | null>(null);
  const lock = useRef(false);
  const name = displayName(monitor.model, monitor.description);
  const anyDirty = dirty; // luminance draft drives tile dirty chrome; feature rows have own apply

  useEffect(() => {
    if (!dirty && reading !== null) setPending(reading);
  }, [reading, dirty]);

  useEffect(() => {
    onDraft(monitor.id, { pending, dirty, saving, note, fault });
  }, [monitor.id, pending, dirty, saving, note, fault, onDraft]);

  function changePending(next: number) {
    const value = Math.min(100, Math.max(0, Math.round(next)));
    setPending(value);
    setDirty(reading === null ? false : value !== reading);
    setNote(null);
    setFault(null);
    onSelect(monitor.id);
  }

  function discard() {
    if (reading === null) return;
    setPending(reading);
    setDirty(false);
    setNote(null);
    setFault(null);
  }

  async function apply() {
    if (lock.current || !dirty || !adjustable || saving) return;
    lock.current = true;
    setSaving(true);
    setFault(null);
    setNote(null);
    onSelect(monitor.id);
    onBusy(true);
    try {
      const result = await onCommit(monitor.id, "luminance", pending);
      const verified = result.verified;
      setPending(verified);
      setDirty(false);
      setNote(result.notice ?? (result.noop ? "已经是这个亮度。" : `已回读 ${verified}`));
    } catch (error) {
      setFault(error instanceof ApiError ? error.message : "写入没有完成。");
    } finally {
      lock.current = false;
      setSaving(false);
      onBusy(false);
    }
  }

  const shown = dirty && adjustable ? pending : reading !== null ? reading : null;
  const reason = adjustable ? null : chipLabel(false, monitor.failure);

  return (
    <div
      role="listitem"
      className="layout-tile"
      data-layout-id={monitor.id}
      data-testid="layout-tile"
      data-writable={adjustable || contrastAdjustable || volumeAdjustable ? "true" : "false"}
      data-primary={monitor.primary ? "true" : "false"}
      data-linked={linked ?? "off"}
      data-dirty={anyDirty ? "true" : "false"}
      data-contrast={mark}
      style={style}
      onMouseEnter={() => onHover(monitor.id)}
      onMouseLeave={() => onHover(null)}
      onFocus={() => onHover(monitor.id)}
      onBlur={(event) => {
        const next = event.relatedTarget;
        if (next instanceof Node && event.currentTarget.contains(next)) return;
        onHover(null);
      }}
      onClick={() => onSelect(monitor.id)}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          discard();
        }
        if (
          event.key === "Enter" &&
          event.target instanceof HTMLInputElement &&
          event.target.type === "range"
        ) {
          event.preventDefault();
          void apply();
        }
      }}
    >
      <div className="tile-top">
        <span className="layout-name">{name}</span>
        <span className="tile-badges">
          {monitor.primary ? <em className="tile-badge">主</em> : null}
          {reason ? <em className="tile-badge tile-badge-reason">{reason}</em> : null}
          {!contrastAdjustable && contrastVisible(monitor) ? (
            <em
              className="tile-badge tile-badge-read"
              data-testid="capability-contrast"
              title={contrastView(monitor)?.title}
            >
              {contrastView(monitor)?.label}
            </em>
          ) : null}
          {!volumeAdjustable && volumeVisible(monitor) ? (
            <em
              className="tile-badge tile-badge-read"
              data-testid="capability-volume"
              title={volumeView(monitor)?.title}
            >
              {volumeView(monitor)?.label}
            </em>
          ) : null}
          {rgbVisible(monitor) ? (
            <em
              className="tile-badge tile-badge-read"
              data-testid="capability-rgb"
              title={rgbView(monitor)?.title}
            >
              {rgbView(monitor)?.label}
            </em>
          ) : null}
          {inputSourceVisible(monitor) ? (
            <em
              className="tile-badge tile-badge-read"
              data-testid="capability-input"
              title={inputSourceView(monitor)?.title}
            >
              {inputSourceView(monitor)?.label}
            </em>
          ) : null}
          {powerModeVisible(monitor) ? (
            <em
              className="tile-badge tile-badge-read"
              data-testid="capability-power"
              title={powerModeView(monitor)?.title}
            >
              {powerModeView(monitor)?.label}
            </em>
          ) : null}
        </span>
      </div>

      <p className="tile-value" data-empty={shown === null ? "true" : "false"} data-dirty={dirty ? "true" : "false"}>
        {shown === null ? "—" : shown}
      </p>

      {adjustable ? (
        <div className="tile-control">
          <label className="tile-slider">
            <input
              type="range"
              min={0}
              max={100}
              step={1}
              value={pending}
              disabled={saving}
              aria-label={`${name} 待写入亮度`}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={pending}
              aria-valuetext={dirty ? `${pending}，尚未写入` : `${pending}，与读数一致`}
              style={
                {
                  "--fill": `${pending}%`,
                  "--lo": `${Math.min(pending, reading ?? pending)}%`,
                  "--hi": `${Math.max(pending, reading ?? pending)}%`,
                } as CSSProperties
              }
              onChange={(event) => changePending(Number(event.target.value))}
            />
          </label>
        </div>
      ) : null}
      {adjustable ? (
        <div
          className="tile-commit"
          data-on={dirty ? "true" : "false"}
          data-testid="luminance-commit"
          inert={!dirty}
          aria-hidden={dirty ? undefined : true}
        >
          <span className="tile-commit-note">
            {pending <= 10 ? `已写入 ${reading} · 偏低` : `已写入 ${reading}`}
          </span>
          <button type="button" className="tile-quiet" onClick={discard} disabled={saving || !dirty}>
            撤销
          </button>
          <button
            type="button"
            className="btn primary tile-apply"
            data-testid="apply-brightness"
            onClick={() => void apply()}
            disabled={saving || !dirty}
          >
            {saving ? "写入中" : "应用"}
          </button>
        </div>
      ) : null}

      {contrastAdjustable ? (
        <FeatureSlider
          monitor={monitor}
          feature="contrast"
          label="对比度"
          reading={contrastNow(monitor)}
          testId="contrast"
          onSelect={onSelect}
          onCommit={onCommit}
          onBusy={onBusy}
        />
      ) : null}
      {volumeAdjustable ? (
        <FeatureSlider
          monitor={monitor}
          feature="volume"
          label="音量"
          reading={volumeNow(monitor)}
          testId="volume"
          onSelect={onSelect}
          onCommit={onCommit}
          onBusy={onBusy}
        />
      ) : null}
    </div>
  );
}

function FeatureSlider({
  monitor,
  feature,
  label,
  reading,
  testId,
  onSelect,
  onCommit,
  onBusy,
}: {
  monitor: Monitor;
  feature: "contrast" | "volume";
  label: string;
  reading: number | null;
  testId: string;
  onSelect: (id: string) => void;
  onCommit: (id: string, feature: FeatureName, value: number) => Promise<CommitResult>;
  onBusy: (active: boolean) => void;
}) {
  const name = displayName(monitor.model, monitor.description);
  const [pending, setPending] = useState(reading ?? 0);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [fault, setFault] = useState<string | null>(null);
  const lock = useRef(false);

  useEffect(() => {
    if (!dirty && reading !== null) setPending(reading);
  }, [reading, dirty]);

  function changePending(next: number) {
    const value = Math.min(100, Math.max(0, Math.round(next)));
    setPending(value);
    setDirty(reading === null ? false : value !== reading);
    setFault(null);
    onSelect(monitor.id);
  }

  function discard() {
    if (reading === null) return;
    setPending(reading);
    setDirty(false);
    setFault(null);
  }

  async function apply() {
    if (lock.current || !dirty || saving || reading === null) return;
    lock.current = true;
    setSaving(true);
    setFault(null);
    onSelect(monitor.id);
    onBusy(true);
    try {
      const result = await onCommit(monitor.id, feature, pending);
      setPending(result.verified);
      setDirty(false);
    } catch (error) {
      setFault(error instanceof ApiError ? error.message : "写入没有完成。");
    } finally {
      lock.current = false;
      setSaving(false);
      onBusy(false);
    }
  }

  return (
    <div className="tile-feature" data-testid={`feature-${testId}`} data-dirty={dirty ? "true" : "false"}>
      <div className="tile-feature-head">
        <span>{label}</span>
        <strong>{dirty ? pending : reading ?? "—"}</strong>
        {fault ? <em className="tile-feature-fault">{fault}</em> : null}
      </div>
      <div className="tile-control tile-feature-control">
        <label className="tile-slider">
          <input
            type="range"
            min={0}
            max={100}
            step={1}
            value={pending}
            disabled={saving}
            aria-label={`${name} 待写入${label}`}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={pending}
            style={
              {
                "--fill": `${pending}%`,
                "--lo": `${Math.min(pending, reading ?? pending)}%`,
                "--hi": `${Math.max(pending, reading ?? pending)}%`,
              } as CSSProperties
            }
            onChange={(event) => changePending(Number(event.target.value))}
          />
        </label>
        <div
          className="tile-feature-commit"
          data-on={dirty ? "true" : "false"}
          data-testid={`${testId}-commit`}
          inert={!dirty}
          aria-hidden={dirty ? undefined : true}
        >
          <button type="button" className="tile-quiet" onClick={discard} disabled={saving || !dirty}>
            撤销
          </button>
          <button
            type="button"
            className="btn primary tile-apply"
            data-testid={`apply-${testId}`}
            onClick={() => void apply()}
            disabled={saving || !dirty}
          >
            {saving ? "写入中" : "应用"}
          </button>
        </div>
      </div>
    </div>
  );
}
