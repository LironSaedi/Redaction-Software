// Canvas overlay of the video player: track boxes (rectangles / ellipses), labels, and a live preview of the
// export effects (blur / pixelate / blackout) drawn from the video element itself.

import { trackBoxAt, videoBoxToCanvas, type Rect } from "../../../lib/geometry";
import type { Track } from "../../../types";
import { isFullFrame, trackColor, trackShape, type TrackShape } from "./trackUtils";

export interface DrawState {
  video: HTMLVideoElement;
  frame: number;
  tracks: Track[];
  dispW: number;
  dispH: number;
  vw: number;
  vh: number;
  selectedId: number | null;
  livePreview: boolean;
  /** effect for tracks without their own (the export setting) */
  defaultEffect: string;
  pending: { box: number[]; shape: TrackShape } | null;
}

let scratch: HTMLCanvasElement | null = null;

function shapePath(ctx: CanvasRenderingContext2D, r: Rect, shape: TrackShape) {
  ctx.beginPath();
  if (shape === "ellipse") {
    ctx.ellipse((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2, Math.max(0.5, (r.x1 - r.x0) / 2), Math.max(0.5, (r.y1 - r.y0) / 2), 0, 0, Math.PI * 2);
  } else {
    ctx.rect(r.x0, r.y0, r.x1 - r.x0, r.y1 - r.y0);
  }
}

/** Pixel effect inside `r` (canvas px), read from the video element. Falls back to a solid box. */
function drawEffect(ctx: CanvasRenderingContext2D, s: DrawState, r: Rect, shape: TrackShape, effect: string) {
  const v = s.video;
  const w = r.x1 - r.x0;
  const h = r.y1 - r.y0;
  ctx.save();
  shapePath(ctx, r, shape);
  ctx.clip();
  const ready = v.readyState >= 2 && v.videoWidth > 0;
  if (effect === "blackout" || !ready) {
    ctx.fillStyle = "#000";
    ctx.fillRect(r.x0, r.y0, w, h);
  } else if (effect === "blur" && "filter" in ctx) {
    ctx.filter = `blur(${Math.max(6, Math.min(w, h) / 6)}px)`;
    ctx.drawImage(v, 0, 0, s.dispW, s.dispH);
    ctx.filter = "none";
  } else {
    // pixelate (and blur where canvas filters are not supported): down-sample, then scale up without smoothing
    const block = effect === "blur" ? 6 : 10;
    const sw = Math.max(2, Math.round(w / Math.max(4, Math.min(w, h) / block)));
    const sh = Math.max(2, Math.round((sw * h) / Math.max(1, w)));
    scratch = scratch ?? document.createElement("canvas");
    scratch.width = sw;
    scratch.height = sh;
    const sctx = scratch.getContext("2d");
    if (sctx) {
      const kx = v.videoWidth / s.dispW;
      const ky = v.videoHeight / s.dispH;
      sctx.imageSmoothingEnabled = true;
      sctx.drawImage(v, r.x0 * kx, r.y0 * ky, w * kx, h * ky, 0, 0, sw, sh);
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(scratch, 0, 0, sw, sh, r.x0, r.y0, w, h);
      ctx.imageSmoothingEnabled = true;
    } else {
      ctx.fillStyle = "#000";
      ctx.fillRect(r.x0, r.y0, w, h);
    }
  }
  ctx.restore();
}

function tag(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, bg: string, fg: string) {
  ctx.font = "600 11px system-ui, -apple-system, Segoe UI, sans-serif";
  const tw = ctx.measureText(text).width + 10;
  const ty = Math.max(0, y - 17);
  ctx.fillStyle = bg;
  ctx.fillRect(x, ty, tw, 17);
  ctx.fillStyle = fg;
  ctx.fillText(text, x + 5, ty + 12);
}

export function drawOverlay(ctx: CanvasRenderingContext2D, s: DrawState): void {
  const { frame, dispW, dispH, vw, vh } = s;
  ctx.clearRect(0, 0, dispW, dispH);
  for (const t of s.tracks) {
    const b = trackBoxAt(t.boxes, frame, 1);
    if (!b) continue;
    const full = isFullFrame(t);
    const r = full ? { x0: 0, y0: 0, x1: dispW, y1: dispH } : videoBoxToCanvas(b, vw, vh, dispW, dispH);
    const shape = full ? "rect" : trackShape(t);
    const color = trackColor(t.label);
    const sel = t.id === s.selectedId;
    const effect = t.effect || s.defaultEffect;
    if (s.livePreview) {
      if (t.enabled) drawEffect(ctx, s, r, shape, effect);
      continue;
    }
    ctx.lineWidth = sel ? 3 : 2;
    if (full) {
      ctx.setLineDash(t.enabled ? [10, 6] : [4, 4]);
      ctx.strokeStyle = t.enabled ? color : "rgba(255,255,255,0.8)";
      ctx.strokeRect(4, 4, dispW - 8, dispH - 8);
      ctx.setLineDash([]);
      if (t.enabled) {
        ctx.fillStyle = "rgba(0,0,0,0.18)";
        ctx.fillRect(0, 0, dispW, dispH);
      }
      tag(ctx, `Full frame · ${effect}${t.enabled ? "" : " · off"}`, 8, 26, t.enabled ? color : "rgba(40,40,40,0.85)", t.enabled ? "#000" : "#fff");
      continue;
    }
    shapePath(ctx, r, shape);
    if (t.enabled) {
      ctx.setLineDash([]);
      ctx.fillStyle = "rgba(0,0,0,0.32)";
      ctx.fill();
      ctx.strokeStyle = color;
    } else {
      ctx.setLineDash([6, 4]);
      ctx.strokeStyle = "rgba(255,255,255,0.88)";
    }
    ctx.stroke();
    ctx.setLineDash([]);
    if (sel) {
      ctx.lineWidth = 1;
      ctx.strokeStyle = "rgba(255,255,255,0.9)";
      ctx.strokeRect(r.x0 - 3, r.y0 - 3, r.x1 - r.x0 + 6, r.y1 - r.y0 + 6);
    }
    const text = `${t.enabled ? "" : "visible · "}${t.label} #${t.id}${t.effect ? ` · ${t.effect}` : ""}`;
    tag(ctx, text, r.x0, r.y0, t.enabled ? color : "rgba(40,40,40,0.85)", t.enabled ? "#000" : "#fff");
  }
  if (s.pending) {
    const r = videoBoxToCanvas(s.pending.box, vw, vh, dispW, dispH);
    ctx.setLineDash([5, 4]);
    ctx.strokeStyle = "#ffe14d";
    ctx.lineWidth = 2;
    shapePath(ctx, r, s.pending.shape);
    ctx.stroke();
    ctx.setLineDash([]);
  }
}
