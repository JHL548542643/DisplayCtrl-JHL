/** Port of displayctl/geometry.py. Pytest locks this fit; keep the constants identical. */

export const CANVAS_WIDTH = 1000;
export const CANVAS_MIN_HEIGHT = 220;
export const CANVAS_MAX_HEIGHT = 520;
export const CANVAS_PADDING = 28;

export type Rect = readonly [number, number, number, number];

export type Bounds = {
  left: number;
  top: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
};

export type Frame = {
  canvasWidth: number;
  canvasHeight: number;
  scale: number;
  originX: number;
  originY: number;
  bounds: Bounds;
};

export type PlacedTile = {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
};

export function rectWidth(rect: Rect): number {
  return rect[2] - rect[0];
}

export function rectHeight(rect: Rect): number {
  return rect[3] - rect[1];
}

export function asRect(value: readonly number[] | null | undefined): Rect | null {
  if (!value || value.length !== 4) return null;
  const [left, top, right, bottom] = value;
  if (![left, top, right, bottom].every((part) => typeof part === "number" && Number.isFinite(part))) {
    return null;
  }
  return [left, top, right, bottom];
}

export function virtualBounds(rects: readonly Rect[]): Bounds | null {
  const usable = rects.filter((rect) => rectWidth(rect) > 0 && rectHeight(rect) > 0);
  if (usable.length === 0) return null;
  const left = Math.min(...usable.map((rect) => rect[0]));
  const top = Math.min(...usable.map((rect) => rect[1]));
  const right = Math.max(...usable.map((rect) => rect[2]));
  const bottom = Math.max(...usable.map((rect) => rect[3]));
  return { left, top, right, bottom, width: right - left, height: bottom - top };
}

export function suggestCanvas(bounds: Bounds): { width: number; height: number; padding: number } {
  const padding = CANVAS_PADDING;
  const innerWidth = CANVAS_WIDTH - 2 * padding;
  const natural = bounds.height * (innerWidth / bounds.width) + 2 * padding;
  const height = Math.min(CANVAS_MAX_HEIGHT, Math.max(CANVAS_MIN_HEIGHT, natural));
  return { width: CANVAS_WIDTH, height, padding };
}

export function fitFrame(
  rects: readonly Rect[],
  canvasWidth: number,
  canvasHeight: number,
  padding: number,
): Frame | null {
  if (padding < 0 || canvasWidth <= 2 * padding || canvasHeight <= 2 * padding) return null;
  const bounds = virtualBounds(rects);
  if (!bounds || bounds.width <= 0 || bounds.height <= 0) return null;
  const innerWidth = canvasWidth - 2 * padding;
  const innerHeight = canvasHeight - 2 * padding;
  const scale = Math.min(innerWidth / bounds.width, innerHeight / bounds.height);
  const usedWidth = bounds.width * scale;
  const usedHeight = bounds.height * scale;
  return {
    canvasWidth,
    canvasHeight,
    scale,
    originX: padding + (innerWidth - usedWidth) / 2,
    originY: padding + (innerHeight - usedHeight) / 2,
    bounds,
  };
}

export function placeRect(rect: Rect, frame: Frame): { x: number; y: number; width: number; height: number } {
  return {
    x: frame.originX + (rect[0] - frame.bounds.left) * frame.scale,
    y: frame.originY + (rect[1] - frame.bounds.top) * frame.scale,
    width: rectWidth(rect) * frame.scale,
    height: rectHeight(rect) * frame.scale,
  };
}

export function placeMonitors(monitors: readonly { id: string; rect: readonly number[] }[]): {
  width: number;
  height: number;
  bounds: Bounds;
  tiles: PlacedTile[];
} | null {
  const usable: { id: string; rect: Rect }[] = [];
  for (const monitor of monitors) {
    const rect = asRect(monitor.rect);
    if (!rect || rectWidth(rect) <= 0 || rectHeight(rect) <= 0) continue;
    usable.push({ id: monitor.id, rect });
  }
  const bounds = virtualBounds(usable.map((item) => item.rect));
  if (!bounds) return null;
  const canvas = suggestCanvas(bounds);
  const frame = fitFrame(
    usable.map((item) => item.rect),
    canvas.width,
    canvas.height,
    canvas.padding,
  );
  if (!frame) return null;
  return {
    width: canvas.width,
    height: canvas.height,
    bounds,
    tiles: usable.map((item) => ({ id: item.id, ...placeRect(item.rect, frame) })),
  };
}
