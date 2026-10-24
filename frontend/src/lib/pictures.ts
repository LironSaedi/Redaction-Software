// Pictures inside documents (photos, exhibits, charts, ID cards, signatures…) are classified by the analysis
// and listed as one "region" detection each; selecting it redacts the whole picture.

import type { Rect } from "./geometry";
import type { Detection } from "../types";

export const PICTURE_CLASSES = [
  "IMAGE_ID_CARD",
  "IMAGE_SIGNATURE",
  "IMAGE_PHOTO_PERSON",
  "IMAGE_PHOTO",
  "IMAGE_MEDICAL",
  "IMAGE_CHART",
  "IMAGE_TABLE",
  "IMAGE_SCREENSHOT",
  "IMAGE_DOCUMENT",
  "IMAGE_GRAPHIC",
] as const;

/** Fallback labels (GET /api/meta → image_classes.classes is preferred). */
export const PICTURE_LABELS: Record<string, string> = {
  IMAGE_ID_CARD: "ID / licence / insurance card",
  IMAGE_PHOTO_PERSON: "Photo of a person",
  IMAGE_PHOTO: "Photo (scene / property / injury)",
  IMAGE_SIGNATURE: "Handwritten signature",
  IMAGE_MEDICAL: "Medical image",
  IMAGE_CHART: "Chart / graph",
  IMAGE_TABLE: "Table / form image",
  IMAGE_SCREENSHOT: "Screenshot",
  IMAGE_DOCUMENT: "Picture of a document",
  IMAGE_GRAPHIC: "Logo / graphic / stamp",
};

/** Short badge text drawn on a picture's box in the viewer. */
export const PICTURE_SHORT: Record<string, string> = {
  IMAGE_ID_CARD: "ID card",
  IMAGE_PHOTO_PERSON: "Person photo",
  IMAGE_PHOTO: "Photo",
  IMAGE_SIGNATURE: "Signature",
  IMAGE_MEDICAL: "Medical",
  IMAGE_CHART: "Chart",
  IMAGE_TABLE: "Table",
  IMAGE_SCREENSHOT: "Screenshot",
  IMAGE_DOCUMENT: "Document",
  IMAGE_GRAPHIC: "Graphic",
};

export function isPictureClass(entity: string): boolean {
  return entity.startsWith("IMAGE_");
}

/** A whole-picture item: kind "region" with an IMAGE_* type (or the classifier's meta.class). */
export function isPicture(d: Pick<Detection, "kind" | "entity" | "meta">): boolean {
  if (d.kind !== "region") return false;
  return isPictureClass(d.entity) || (typeof d.meta?.class === "string" && isPictureClass(d.meta.class));
}

/** Current class of a picture: the reviewer may have re-typed it, so the entity wins over meta.class. */
export function pictureClass(d: Pick<Detection, "entity" | "meta">): string {
  if (isPictureClass(d.entity)) return d.entity;
  return typeof d.meta?.class === "string" ? d.meta.class : d.entity;
}

/** Office pictures have no page boxes; they name the media part (e.g. "word/media/image3.png"). */
export function pictureMediaName(d: Pick<Detection, "meta">): string | null {
  const m = d.meta?.media;
  if (typeof m !== "string" || !m) return null;
  const parts = m.split("/");
  return parts[parts.length - 1] || m;
}

export function hasPageBox(d: Pick<Detection, "boxes">): boolean {
  return d.boxes.length > 0;
}

export type PictureStatus = "all" | "redacted" | "kept";

export interface PictureFilter {
  /** empty = every class */
  classes?: Set<string> | string[];
  status?: PictureStatus;
}

export function filterPictures(dets: Detection[], f: PictureFilter = {}): Detection[] {
  const classes = f.classes ? new Set(f.classes) : null;
  return dets.filter((d) => {
    if (!isPicture(d)) return false;
    if (classes && classes.size && !classes.has(pictureClass(d))) return false;
    if (f.status === "redacted" && !d.selected) return false;
    if (f.status === "kept" && d.selected) return false;
    return true;
  });
}

/** Count per class (only classes that occur), in the canonical class order. */
export function pictureCounts(dets: Detection[]): { cls: string; total: number; selected: number }[] {
  const m = new Map<string, { total: number; selected: number }>();
  for (const d of dets) {
    if (!isPicture(d)) continue;
    const c = pictureClass(d);
    const v = m.get(c) ?? { total: 0, selected: 0 };
    v.total += 1;
    if (d.selected) v.selected += 1;
    m.set(c, v);
  }
  const order = (c: string) => {
    const i = (PICTURE_CLASSES as readonly string[]).indexOf(c);
    return i < 0 ? 99 : i;
  };
  return Array.from(m.entries())
    .sort((a, b) => order(a[0]) - order(b[0]) || a[0].localeCompare(b[0]))
    .map(([cls, v]) => ({ cls, ...v }));
}

/** Sort pictures in reading order: page, then top-to-bottom, left-to-right; office pictures by part name. */
export function sortPictures(dets: Detection[]): Detection[] {
  return [...dets].sort((a, b) => {
    const pa = a.boxes[0]?.page ?? a.page;
    const pb = b.boxes[0]?.page ?? b.page;
    if (pa !== pb) return pa - pb;
    const ya = a.boxes[0]?.y0 ?? 0;
    const yb = b.boxes[0]?.y0 ?? 0;
    if (ya !== yb) return ya - yb;
    const xa = a.boxes[0]?.x0 ?? 0;
    const xb = b.boxes[0]?.x0 ?? 0;
    if (xa !== xb) return xa - xb;
    return String(a.meta?.media ?? "").localeCompare(String(b.meta?.media ?? ""));
  });
}

export interface CropLayout {
  /** px per page unit */
  scale: number;
  /** size of the full page image when drawn at that scale */
  imgWidth: number;
  imgHeight: number;
  /** offset of the page image inside the frame */
  left: number;
  top: number;
}

/**
 * How to draw a page image inside a `frame` so that `box` (displayed page units) is centred and fits.
 * `pad` adds a margin around the picture as a fraction of its size.
 */
export function cropLayout(box: Rect, page: { width: number; height: number }, frame: { w: number; h: number }, pad = 0.04): CropLayout {
  const bw0 = Math.max(1e-6, box.x1 - box.x0);
  const bh0 = Math.max(1e-6, box.y1 - box.y0);
  const x0 = box.x0 - bw0 * pad;
  const y0 = box.y0 - bh0 * pad;
  const bw = bw0 * (1 + 2 * pad);
  const bh = bh0 * (1 + 2 * pad);
  const scale = Math.min(frame.w / bw, frame.h / bh);
  return {
    scale,
    imgWidth: page.width * scale,
    imgHeight: page.height * scale,
    left: (frame.w - bw * scale) / 2 - x0 * scale,
    top: (frame.h - bh * scale) / 2 - y0 * scale,
  };
}
