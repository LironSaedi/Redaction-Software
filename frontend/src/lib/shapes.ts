// Shape geometry for manual redactions: rectangles, ellipses and free polygons.
//
// Page units (PDF points / image pixels) are what the API stores. Boxes and polygon points of rotated
// PDF pages live in the *unrotated* page space; the page matrix maps them to the displayed page.
// View units are CSS pixels inside the displayed page (origin = top-left of the page image).

import {
  applyMatrix,
  clampRect,
  IDENTITY,
  normalizeRect,
  transformRect,
  viewPointToPage,
  type Matrix,
  type Point,
  type Rect,
} from "./geometry";
import type { Detection, ShapeKind } from "../types";

export type PagePoint = [number, number];

export const SHAPES: ShapeKind[] = ["rect", "ellipse", "polygon"];

export interface Ellipse {
  cx: number;
  cy: number;
  rx: number;
  ry: number;
}

/** The ellipse inscribed in a rectangle. */
export function ellipseFromRect(r: Rect): Ellipse {
  return { cx: (r.x0 + r.x1) / 2, cy: (r.y0 + r.y1) / 2, rx: Math.abs(r.x1 - r.x0) / 2, ry: Math.abs(r.y1 - r.y0) / 2 };
}

export function pointInEllipse(p: Point, r: Rect): boolean {
  const e = ellipseFromRect(r);
  if (e.rx <= 0 || e.ry <= 0) return false;
  const dx = (p.x - e.cx) / e.rx;
  const dy = (p.y - e.cy) / e.ry;
  return dx * dx + dy * dy <= 1;
}

/** Even-odd ray casting. */
export function pointInPolygon(p: Point, pts: Point[]): boolean {
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const a = pts[i];
    const b = pts[j];
    if (a.y > p.y !== b.y > p.y && p.x < ((b.x - a.x) * (p.y - a.y)) / (b.y - a.y || 1e-12) + a.x) inside = !inside;
  }
  return inside;
}

export function polygonBounds(pts: Point[]): Rect {
  if (!pts.length) return { x0: 0, y0: 0, x1: 0, y1: 0 };
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  for (const p of pts) {
    x0 = Math.min(x0, p.x);
    y0 = Math.min(y0, p.y);
    x1 = Math.max(x1, p.x);
    y1 = Math.max(y1, p.y);
  }
  return { x0, y0, x1, y1 };
}

/** Shoelace area (absolute). */
export function polygonArea(pts: Point[]): number {
  let s = 0;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) s += (pts[j].x + pts[i].x) * (pts[j].y - pts[i].y);
  return Math.abs(s) / 2;
}

export const toPoint = (p: PagePoint | number[]): Point => ({ x: Number(p[0]), y: Number(p[1]) });
export const fromPoint = (p: Point): PagePoint => [p.x, p.y];

/** SVG `points` attribute. */
export function svgPoints(pts: Point[]): string {
  return pts.map((p) => `${round(p.x, 3)},${round(p.y, 3)}`).join(" ");
}

function round(v: number, digits = 2): number {
  const f = 10 ** digits;
  return Math.round(v * f) / f;
}

/** View polygon (CSS px) → page polygon, clamped to the unrotated page. */
export function viewPolygonToPage(
  pts: Point[],
  scale: number,
  matrix: Matrix = IDENTITY,
  pageSize?: { width: number; height: number },
): PagePoint[] {
  const swapped = Math.abs(matrix[1]) > 0.5 && Math.abs(matrix[2]) > 0.5;
  const w = pageSize ? (swapped ? pageSize.height : pageSize.width) : Infinity;
  const h = pageSize ? (swapped ? pageSize.width : pageSize.height) : Infinity;
  return pts.map((p) => {
    const q = viewPointToPage(p, scale, matrix);
    return [round(Math.min(Math.max(q.x, 0), w)), round(Math.min(Math.max(q.y, 0), h))];
  });
}

/** Page polygon → displayed page units (rotation applied, not scaled). */
export function pagePolygonToDisplay(pts: (PagePoint | number[])[], matrix: Matrix = IDENTITY): Point[] {
  return pts.map((p) => applyMatrix(matrix, toPoint(p)));
}

/** Page polygon → view px (rotation applied, then scaled). */
export function pagePolygonToView(pts: (PagePoint | number[])[], scale: number, matrix: Matrix = IDENTITY): Point[] {
  return pagePolygonToDisplay(pts, matrix).map((p) => ({ x: p.x * scale, y: p.y * scale }));
}

/** Bounding box of a page polygon, as an API box (page units). */
export function polygonBox(pts: (PagePoint | number[])[]): Rect {
  return polygonBounds(pts.map(toPoint));
}

export function translatePolygon(pts: (PagePoint | number[])[], dx: number, dy: number): PagePoint[] {
  return pts.map((p) => [round(Number(p[0]) + dx), round(Number(p[1]) + dy)]);
}

export function translateRect(r: Rect, dx: number, dy: number): Rect {
  return { x0: r.x0 + dx, y0: r.y0 + dy, x1: r.x1 + dx, y1: r.y1 + dy };
}

export type Handle = "n" | "s" | "e" | "w" | "ne" | "nw" | "se" | "sw";
export const HANDLES: Handle[] = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];

/** Rectangle after dragging one of its handles to `p` (all in the same units); never inverted. */
export function resizeRect(r: Rect, handle: Handle, p: Point, minSize = 2): Rect {
  let { x0, y0, x1, y1 } = r;
  if (handle.includes("w")) x0 = Math.min(p.x, x1 - minSize);
  if (handle.includes("e")) x1 = Math.max(p.x, x0 + minSize);
  if (handle.includes("n")) y0 = Math.min(p.y, y1 - minSize);
  if (handle.includes("s")) y1 = Math.max(p.y, y0 + minSize);
  return { x0, y0, x1, y1 };
}

/** Handle anchor points of a rectangle. */
export function handlePoint(r: Rect, h: Handle): Point {
  const cx = (r.x0 + r.x1) / 2;
  const cy = (r.y0 + r.y1) / 2;
  return {
    x: h.includes("w") ? r.x0 : h.includes("e") ? r.x1 : cx,
    y: h.includes("n") ? r.y0 : h.includes("s") ? r.y1 : cy,
  };
}

/** A square / circle constraint while drawing with Shift held. */
export function constrainSquare(a: Point, b: Point): Point {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const s = Math.max(Math.abs(dx), Math.abs(dy));
  return { x: a.x + Math.sign(dx || 1) * s, y: a.y + Math.sign(dy || 1) * s };
}

/** True when a click at `p` should close the polygon (near its first vertex). */
export function closesPolygon(pts: Point[], p: Point, tolerance = 8): boolean {
  if (pts.length < 3) return false;
  const f = pts[0];
  return Math.hypot(f.x - p.x, f.y - p.y) <= tolerance;
}

// ---- detections --------------------------------------------------------------------------------

export function detectionShape(d: Pick<Detection, "meta">): ShapeKind {
  const s = d.meta?.shape;
  return s === "ellipse" || s === "polygon" ? s : "rect";
}

/** Polygon vertices (unrotated page units) of a polygon detection, or null. */
export function detectionPoints(d: Pick<Detection, "meta">): PagePoint[] | null {
  if (detectionShape(d) !== "polygon") return null;
  const pts = d.meta?.points;
  if (!Array.isArray(pts) || pts.length < 3) return null;
  const out: PagePoint[] = [];
  for (const p of pts) {
    if (Array.isArray(p) && p.length >= 2 && Number.isFinite(Number(p[0])) && Number.isFinite(Number(p[1]))) {
      out.push([Number(p[0]), Number(p[1])]);
    }
  }
  return out.length >= 3 ? out : null;
}

/** Geometry of one detection box as drawn on the displayed page (page units, rotation applied). */
export type DisplayShape =
  | { kind: "rect"; r: Rect }
  | { kind: "ellipse"; r: Rect; e: Ellipse }
  | { kind: "polygon"; r: Rect; pts: Point[] };

export function displayShape(d: Pick<Detection, "meta">, box: Rect, matrix: Matrix = IDENTITY): DisplayShape {
  const r = transformRect(matrix, box);
  const shape = detectionShape(d);
  if (shape === "ellipse") return { kind: "ellipse", r, e: ellipseFromRect(r) };
  if (shape === "polygon") {
    const pts = detectionPoints(d);
    if (pts) {
      const dp = pagePolygonToDisplay(pts, matrix);
      return { kind: "polygon", r: polygonBounds(dp), pts: dp };
    }
  }
  return { kind: "rect", r };
}

/** A rectangle drawn in view px → page rect (clamped). Thin re-export kept next to the other shapes. */
export function viewDragToPageRect(
  a: Point,
  b: Point,
  scale: number,
  matrix: Matrix,
  page: { width: number; height: number },
): Rect {
  const vr = normalizeRect(a, b);
  const p0 = viewPointToPage({ x: vr.x0, y: vr.y0 }, scale, matrix);
  const p1 = viewPointToPage({ x: vr.x1, y: vr.y1 }, scale, matrix);
  const swapped = Math.abs(matrix[1]) > 0.5 && Math.abs(matrix[2]) > 0.5;
  const r = normalizeRect(p0, p1);
  const c = clampRect(r, swapped ? page.height : page.width, swapped ? page.width : page.height);
  return { x0: round(c.x0), y0: round(c.y0), x1: round(c.x1), y1: round(c.y1) };
}
