// Editing detections in place with PATCH /api/files/{id}/detections.
//
// An update names only the fields it changes; for meta fields "" / [] clears the value and shape "rect" clears the
// shape. `applyUpdate` mirrors what the server does (used for optimistic updates) and `inverseUpdate` builds the
// update that puts the previous values back (used by undo). Ids, scores, detectors and reasons never change.

import { detectionShape, polygonBox } from "../../lib/shapes";
import type { Box, Detection, DetectionUpdate, ImageEffect, ShapeKind } from "../../types";

/** A user edit; null removes the value. */
export interface MetaEdit {
  entity?: string;
  exemption?: string;
  partial?: string | null;
  boxes?: Box[];
  label_text?: string | null;
  fill?: [number, number, number] | null;
  effect?: ImageEffect | null;
  note?: string | null;
  shape?: ShapeKind;
  points?: number[][] | null;
}

type MetaKey = "label_text" | "fill" | "effect" | "note" | "shape" | "points" | "image_boxes";
const META_KEYS: MetaKey[] = ["label_text", "fill", "effect", "note", "shape", "points", "image_boxes"];
const CLEAR: Record<MetaKey, string | []> = {
  label_text: "",
  fill: [],
  effect: "",
  note: "",
  shape: "rect",
  points: [],
  image_boxes: [],
};

const isClear = (key: MetaKey, v: unknown) => v === "" || (Array.isArray(v) && v.length === 0) || (key === "shape" && v === "rect");

/** The PATCH update for a user edit of detection `id`. */
export function editToUpdate(id: string, e: MetaEdit): DetectionUpdate {
  const u: DetectionUpdate = { id };
  if (e.entity !== undefined) u.entity = e.entity;
  if (e.exemption !== undefined) u.exemption = e.exemption;
  if (e.partial !== undefined) u.partial = e.partial ?? "";
  if (e.boxes !== undefined) u.boxes = e.boxes.map((b) => ({ ...b }));
  if (e.label_text !== undefined) u.label_text = e.label_text?.trim() ?? "";
  if (e.fill !== undefined) u.fill = e.fill ?? [];
  if (e.effect !== undefined) u.effect = e.effect ?? "";
  if (e.note !== undefined) u.note = e.note?.trim() ?? "";
  if (e.shape !== undefined) u.shape = e.shape;
  if (e.points !== undefined) u.points = e.points ?? [];
  return u;
}

/** `d` after the server applied `u` (mirrors api/files.py _patch_detections). */
export function applyUpdate(d: Detection, u: DetectionUpdate): Detection {
  const out: Detection = { ...d, meta: { ...d.meta } };
  if (u.selected !== undefined) out.selected = u.selected;
  if (u.entity !== undefined) out.entity = u.entity;
  if (u.exemption !== undefined) out.exemption = u.exemption;
  if (u.boxes !== undefined) out.boxes = u.boxes.map((b) => ({ ...b }));
  if (u.partial !== undefined) out.partial = u.partial || null;
  for (const k of META_KEYS) {
    const v = u[k];
    if (v === undefined) continue;
    if (isClear(k, v)) delete out.meta[k];
    else (out.meta as Record<string, unknown>)[k] = v;
  }
  if (u.points && u.points.length && out.meta.shape === "polygon" && u.boxes === undefined) {
    const r = polygonBox(u.points);
    const page = d.boxes[0]?.page ?? d.page;
    out.boxes = [{ page, x0: r.x0, y0: r.y0, x1: r.x1, y1: r.y1 }];
  }
  return out;
}

/** The update that restores `d`'s current values for every field `u` changes. */
export function inverseUpdate(d: Detection, u: DetectionUpdate): DetectionUpdate {
  const back: DetectionUpdate = { id: d.id };
  if (u.selected !== undefined) back.selected = d.selected;
  if (u.entity !== undefined) back.entity = d.entity;
  if (u.exemption !== undefined) back.exemption = d.exemption;
  if (u.partial !== undefined) back.partial = d.partial ?? "";
  if (u.boxes !== undefined) back.boxes = d.boxes.map((b) => ({ ...b }));
  for (const k of META_KEYS) {
    if (u[k] === undefined) continue;
    const prev = (d.meta as Record<string, unknown>)[k];
    (back as unknown as Record<string, unknown>)[k] = prev === undefined || prev === null ? CLEAR[k] : prev;
  }
  // moving a polygon also moved its box: put the exact old box back too
  if (u.points !== undefined && back.boxes === undefined) back.boxes = d.boxes.map((b) => ({ ...b }));
  return back;
}

/** True when the update would change nothing visible on `d`. */
export function isNoop(d: Detection, u: DetectionUpdate): boolean {
  return JSON.stringify(applyUpdate(d, u)) === JSON.stringify(d);
}

export function isManual(d: Pick<Detection, "kind" | "source">): boolean {
  return d.kind === "manual" || (d.source ?? "").startsWith("manual");
}

/** Short name of an operation target, for undo labels (never the detected value). */
export function shapeName(d: Pick<Detection, "meta" | "kind" | "source">): string {
  const s = detectionShape(d);
  if (s === "ellipse") return "ellipse";
  if (s === "polygon") return "polygon";
  return isManual(d) ? "rectangle" : "redaction";
}
