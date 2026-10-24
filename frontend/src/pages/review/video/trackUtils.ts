import type { Track } from "../../../types";

const LABEL_COLORS: Record<string, string> = {
  face: "#e4572e",
  head: "#f3a712",
  license_plate: "#2f6fde",
  person: "#8a4bd6",
  vehicle: "#1f9d55",
  screen: "#0f9ba8",
  document: "#a0522d",
  text: "#d0346a",
  full_frame: "#9aa4b5",
  manual: "#e0e000",
};

export function trackColor(label: string): string {
  return LABEL_COLORS[label] ?? LABEL_COLORS.manual;
}

export const TRACK_EFFECTS = ["blur", "pixelate", "blackout"] as const;
export type TrackEffect = (typeof TRACK_EFFECTS)[number];
export type TrackShape = "rect" | "ellipse";

export function trackShape(t: Pick<Track, "shape">): TrackShape {
  return t.shape === "ellipse" ? "ellipse" : "rect";
}

export function isFullFrame(t: Pick<Track, "label" | "source">): boolean {
  return t.label === "full_frame" || (t.source ?? "").endsWith(":full_frame");
}

/** Contiguous frame runs of a track (for drawing gaps on the timeline). */
export function trackRuns(boxes: Record<string, number[]> | undefined, gap = 1): [number, number][] {
  if (!boxes) return [];
  const frames = Object.keys(boxes)
    .map(Number)
    .filter((n) => Number.isFinite(n))
    .sort((a, b) => a - b);
  const runs: [number, number][] = [];
  for (const f of frames) {
    const last = runs[runs.length - 1];
    if (last && f - last[1] <= gap + 1) last[1] = f;
    else runs.push([f, f]);
  }
  return runs;
}

/** first/last from the boxes themselves (the server keeps stale first/last after a trim). */
export function normalizeTrack(t: Track): Track {
  if (!t.boxes) return t;
  const frames = Object.keys(t.boxes).map(Number).filter(Number.isFinite);
  if (!frames.length) return t;
  return { ...t, first: Math.min(...frames), last: Math.max(...frames) };
}
