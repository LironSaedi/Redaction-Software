// Shared review-workspace types.

export type Tool = "select" | "rect" | "ellipse" | "polygon" | "text" | "pan";

export type ViewMode = "edit" | "preview";

export interface FocusRequest {
  id: string;
  nonce: number;
  source: "panel" | "viewer";
}

export const TOOL_KEYS: Record<string, Tool> = { v: "select", r: "rect", d: "rect", e: "ellipse", g: "polygon", t: "text", h: "pan" };

/** Colour swatches for colour-coded redactions (RGB 0..1, as the API stores them). */
export const FILL_SWATCHES: { name: string; rgb: [number, number, number] }[] = [
  { name: "Black", rgb: [0, 0, 0] },
  { name: "White", rgb: [1, 1, 1] },
  { name: "Grey", rgb: [0.45, 0.47, 0.5] },
  { name: "Red", rgb: [0.75, 0.15, 0.18] },
  { name: "Orange", rgb: [0.85, 0.45, 0.1] },
  { name: "Yellow", rgb: [0.95, 0.8, 0.15] },
  { name: "Green", rgb: [0.12, 0.55, 0.3] },
  { name: "Blue", rgb: [0.15, 0.35, 0.75] },
  { name: "Purple", rgb: [0.5, 0.28, 0.75] },
];

export function rgbCss(rgb: number[] | null | undefined, fallback = "#000"): string {
  if (!rgb || rgb.length < 3) return fallback;
  const c = (v: number) => Math.round(Math.min(1, Math.max(0, Number(v))) * 255);
  return `rgb(${c(rgb[0])}, ${c(rgb[1])}, ${c(rgb[2])})`;
}

/** Light fills need dark label text. */
export function isLightFill(rgb: number[] | null | undefined): boolean {
  if (!rgb || rgb.length < 3) return false;
  return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2] > 0.6;
}

export function sameRgb(a: number[] | null | undefined, b: number[] | null | undefined): boolean {
  if (!a || !b) return !a && !b;
  return a.length >= 3 && b.length >= 3 && [0, 1, 2].every((i) => Math.abs(Number(a[i]) - Number(b[i])) < 0.01);
}
