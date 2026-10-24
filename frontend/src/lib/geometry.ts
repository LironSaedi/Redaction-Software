// Screen ↔ page coordinate math for the review workspace.
//
// "Page units" are what the API uses for boxes: PDF points for PDFs, pixels for images,
// video pixels for video tracks. Boxes for rotated PDF pages are in the *unrotated* page space;
// the page's rotation matrix (PyMuPDF `page.rotation_matrix`) maps them to the displayed page.
// "View units" are CSS pixels inside the displayed page image (origin = image top-left).

export interface Point {
  x: number;
  y: number;
}

export interface Rect {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

/** [a, b, c, d, e, f]: x' = a·x + c·y + e, y' = b·x + d·y + f */
export type Matrix = [number, number, number, number, number, number];

export const IDENTITY: Matrix = [1, 0, 0, 1, 0, 0];

export function toMatrix(m: number[] | undefined | null): Matrix {
  if (!m || m.length !== 6 || m.some((v) => !Number.isFinite(v))) return IDENTITY;
  return [m[0], m[1], m[2], m[3], m[4], m[5]];
}

export function isIdentity(m: Matrix): boolean {
  return m[0] === 1 && m[1] === 0 && m[2] === 0 && m[3] === 1 && m[4] === 0 && m[5] === 0;
}

export function applyMatrix(m: Matrix, p: Point): Point {
  return { x: m[0] * p.x + m[2] * p.y + m[4], y: m[1] * p.x + m[3] * p.y + m[5] };
}

export function invertMatrix(m: Matrix): Matrix {
  const [a, b, c, d, e, f] = m;
  const det = a * d - b * c;
  if (Math.abs(det) < 1e-12) return IDENTITY;
  const ia = d / det;
  const ib = -b / det;
  const ic = -c / det;
  const id = a / det;
  const ie = -(ia * e + ic * f);
  const iff = -(ib * e + id * f);
  return [ia, ib, ic, id, ie, iff];
}

/** Rectangle spanned by two arbitrary corners (normalised so x0 ≤ x1, y0 ≤ y1). */
export function normalizeRect(a: Point, b: Point): Rect {
  return { x0: Math.min(a.x, b.x), y0: Math.min(a.y, b.y), x1: Math.max(a.x, b.x), y1: Math.max(a.y, b.y) };
}

export function transformRect(m: Matrix, r: Rect): Rect {
  if (isIdentity(m)) return { ...r };
  const p0 = applyMatrix(m, { x: r.x0, y: r.y0 });
  const p1 = applyMatrix(m, { x: r.x1, y: r.y1 });
  return normalizeRect(p0, p1);
}

export function rectWidth(r: Rect): number {
  return Math.max(0, r.x1 - r.x0);
}

export function rectHeight(r: Rect): number {
  return Math.max(0, r.y1 - r.y0);
}

export function clampRect(r: Rect, width: number, height: number): Rect {
  const cx = (v: number) => Math.min(Math.max(v, 0), width);
  const cy = (v: number) => Math.min(Math.max(v, 0), height);
  return { x0: cx(r.x0), y0: cy(r.y0), x1: cx(r.x1), y1: cy(r.y1) };
}

export function pointInRect(p: Point, r: Rect, tolerance = 0): boolean {
  return p.x >= r.x0 - tolerance && p.x <= r.x1 + tolerance && p.y >= r.y0 - tolerance && p.y <= r.y1 + tolerance;
}

/** Position of a mouse event relative to an element's bounding rect (CSS px). */
export function clientToView(clientX: number, clientY: number, elementRect: { left: number; top: number }): Point {
  return { x: clientX - elementRect.left, y: clientY - elementRect.top };
}

/** Page → view: rotate into display space, then scale (view px per page unit). */
export function pageRectToView(r: Rect, scale: number, matrix: Matrix = IDENTITY): Rect {
  const d = transformRect(matrix, r);
  return { x0: d.x0 * scale, y0: d.y0 * scale, x1: d.x1 * scale, y1: d.y1 * scale };
}

/** View → page for a single point (inverse of pageRectToView). */
export function viewPointToPage(p: Point, scale: number, matrix: Matrix = IDENTITY): Point {
  const s = scale > 0 ? scale : 1;
  const d = { x: p.x / s, y: p.y / s };
  return isIdentity(matrix) ? d : applyMatrix(invertMatrix(matrix), d);
}

/** View → page for a dragged rectangle; the result is clamped to the (unrotated) page. */
export function viewRectToPage(
  r: Rect,
  scale: number,
  matrix: Matrix = IDENTITY,
  pageSize?: { width: number; height: number },
): Rect {
  const a = viewPointToPage({ x: r.x0, y: r.y0 }, scale, matrix);
  const b = viewPointToPage({ x: r.x1, y: r.y1 }, scale, matrix);
  let out = normalizeRect(a, b);
  if (pageSize) {
    // pageSize is the displayed size; the unrotated space swaps w/h for 90° / 270° rotations.
    const swapped = Math.abs(matrix[1]) > 0.5 && Math.abs(matrix[2]) > 0.5;
    out = clampRect(out, swapped ? pageSize.height : pageSize.width, swapped ? pageSize.width : pageSize.height);
  }
  return out;
}

export type FitMode = "width" | "page";

/** View px per page unit so the page fits the container. */
export function fitScale(
  pageWidth: number,
  pageHeight: number,
  containerWidth: number,
  containerHeight: number,
  mode: FitMode = "width",
  padding = 24,
): number {
  if (pageWidth <= 0 || pageHeight <= 0) return 1;
  const w = Math.max(50, containerWidth - padding * 2);
  const h = Math.max(50, containerHeight - padding * 2);
  const sw = w / pageWidth;
  return mode === "width" ? sw : Math.min(sw, h / pageHeight);
}

export const ZOOM_STEPS = [0.25, 0.33, 0.5, 0.67, 0.75, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3, 4];

export function nextZoom(current: number, direction: 1 | -1): number {
  if (direction > 0) return ZOOM_STEPS.find((z) => z > current + 1e-6) ?? ZOOM_STEPS[ZOOM_STEPS.length - 1];
  const smaller = ZOOM_STEPS.filter((z) => z < current - 1e-6);
  return smaller.length ? smaller[smaller.length - 1] : ZOOM_STEPS[0];
}

/**
 * Render resolution for a PDF page shown at `scale` view px per point. Snaps to a few values
 * so the browser cache is reused; the server clamps to 36..220.
 */
export function chooseDpi(scale: number, devicePixelRatio = 1): number {
  const needed = scale * 72 * Math.max(1, devicePixelRatio);
  const steps = [72, 110, 150, 220];
  return steps.find((s) => s >= needed * 0.9) ?? 220;
}

/** Where a `width × height` media element is drawn inside a box with object-fit: contain. */
export function containFit(
  mediaWidth: number,
  mediaHeight: number,
  boxWidth: number,
  boxHeight: number,
): { scale: number; offsetX: number; offsetY: number; width: number; height: number } {
  if (mediaWidth <= 0 || mediaHeight <= 0 || boxWidth <= 0 || boxHeight <= 0) {
    return { scale: 1, offsetX: 0, offsetY: 0, width: boxWidth, height: boxHeight };
  }
  const scale = Math.min(boxWidth / mediaWidth, boxHeight / mediaHeight);
  const width = mediaWidth * scale;
  const height = mediaHeight * scale;
  return { scale, offsetX: (boxWidth - width) / 2, offsetY: (boxHeight - height) / 2, width, height };
}

/** Video pixel box → canvas px (canvas covers the whole element, video drawn with contain). */
export function videoBoxToCanvas(
  box: number[],
  videoWidth: number,
  videoHeight: number,
  canvasWidth: number,
  canvasHeight: number,
): Rect {
  const f = containFit(videoWidth, videoHeight, canvasWidth, canvasHeight);
  return {
    x0: f.offsetX + box[0] * f.scale,
    y0: f.offsetY + box[1] * f.scale,
    x1: f.offsetX + box[2] * f.scale,
    y1: f.offsetY + box[3] * f.scale,
  };
}

/** Canvas px rect → video pixels (clamped to the frame). */
export function canvasRectToVideo(
  r: Rect,
  videoWidth: number,
  videoHeight: number,
  canvasWidth: number,
  canvasHeight: number,
): Rect {
  const f = containFit(videoWidth, videoHeight, canvasWidth, canvasHeight);
  const s = f.scale || 1;
  const out = {
    x0: (r.x0 - f.offsetX) / s,
    y0: (r.y0 - f.offsetY) / s,
    x1: (r.x1 - f.offsetX) / s,
    y1: (r.y1 - f.offsetY) / s,
  };
  return clampRect(normalizeRect({ x: out.x0, y: out.y0 }, { x: out.x1, y: out.y1 }), videoWidth, videoHeight);
}

/** Frame index shown at `time` seconds (frame = round(t · fps)). */
export function frameAt(time: number, fps: number, frameCount?: number): number {
  if (!Number.isFinite(time) || fps <= 0) return 0;
  const f = Math.max(0, Math.round(time * fps));
  return frameCount && frameCount > 0 ? Math.min(f, frameCount - 1) : f;
}

/** Seek target for a frame: the middle of the frame interval avoids landing on the previous frame. */
export function timeOfFrame(frame: number, fps: number): number {
  if (fps <= 0) return 0;
  return Math.max(0, frame / fps + 0.25 / fps);
}

/** Box for a track at `frame`; falls back to the nearest box within `tolerance` frames. */
export function trackBoxAt(boxes: Record<string, number[]> | undefined, frame: number, tolerance = 1): number[] | null {
  if (!boxes) return null;
  const exact = boxes[String(frame)];
  if (exact) return exact;
  for (let d = 1; d <= tolerance; d++) {
    const b = boxes[String(frame - d)] ?? boxes[String(frame + d)];
    if (b) return b;
  }
  return null;
}

/** Index of the character box containing (or nearest to) a page point; -1 if none is close. */
export function charIndexAt(
  boxes: ([number, number, number, number] | null)[],
  p: Point,
  maxDistance = 12,
): number {
  // Like text selection in a document: first the nearest line (vertical distance), then the
  // nearest character on that line (horizontal distance).
  let bestDy = Infinity;
  const dys: number[] = new Array(boxes.length);
  for (let i = 0; i < boxes.length; i++) {
    const b = boxes[i];
    if (!b) {
      dys[i] = Infinity;
      continue;
    }
    const [, y0, , y1] = b;
    const dy = p.y < y0 ? y0 - p.y : p.y > y1 ? p.y - y1 : 0;
    dys[i] = dy;
    if (dy < bestDy) bestDy = dy;
  }
  if (bestDy > maxDistance) return -1;
  let best = -1;
  let bestDx = Infinity;
  for (let i = 0; i < boxes.length; i++) {
    const b = boxes[i];
    if (!b || dys[i] > bestDy + 0.5) continue;
    const [x0, , x1] = b;
    const dx = p.x < x0 ? x0 - p.x : p.x > x1 ? p.x - x1 : 0;
    if (dx < bestDx) {
      bestDx = dx;
      best = i;
    }
  }
  return best;
}

/** Merge adjacent character boxes of a range into one rectangle per line (for highlighting). */
export function lineRects(boxes: ([number, number, number, number] | null)[], start: number, end: number): Rect[] {
  const out: Rect[] = [];
  let cur: Rect | null = null;
  for (let i = Math.max(0, start); i < Math.min(end, boxes.length); i++) {
    const b = boxes[i];
    if (!b) continue;
    const [x0, y0, x1, y1] = b;
    const h = y1 - y0;
    if (cur && Math.abs(y0 - cur.y0) < h * 0.5 && x0 >= cur.x0 - 1) {
      cur.x1 = Math.max(cur.x1, x1);
      cur.y0 = Math.min(cur.y0, y0);
      cur.y1 = Math.max(cur.y1, y1);
    } else {
      if (cur) out.push(cur);
      cur = { x0, y0, x1, y1 };
    }
  }
  if (cur) out.push(cur);
  return out;
}
