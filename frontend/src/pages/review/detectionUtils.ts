// Pure helpers for the detection list: labels, locations, sorting, grouping and filtering.

import { CATEGORY_ORDER, type MetaHelpers } from "../../meta";
import { formatTimecode } from "../../lib/format";
import { isPicture, pictureClass, pictureMediaName } from "../../lib/pictures";
import { detectionShape } from "../../lib/shapes";
import { isSecondOpinion } from "../../lib/secondOpinion";
import type { Detection } from "../../types";

export type SortMode = "page" | "confidence";

export function detectionLabel(d: Detection, m: MetaHelpers): string {
  if (d.text) return d.text;
  if (isPicture(d)) {
    const name = pictureMediaName(d);
    return `${m.entityLabel(pictureClass(d))}${name ? ` · ${name}` : " (whole picture)"}`;
  }
  if (d.kind === "visual") return `${m.entityLabel(d.entity)} (image region)`;
  if (d.kind === "template") return "Template zone";
  if (d.kind === "audio" && d.meta?.t0 != null) return `Audio ${formatTimecode(d.meta.t0)}–${formatTimecode(d.meta.t1 ?? d.meta.t0)}`;
  if (d.source?.startsWith("manual")) {
    const s = detectionShape(d);
    return s === "ellipse" ? "Drawn ellipse" : s === "polygon" ? "Drawn polygon" : "Drawn box";
  }
  return m.entityLabel(d.entity);
}

export function detectionPage(d: Detection): number {
  return d.boxes[0]?.page ?? d.page;
}

export function detectionLocation(d: Detection): string {
  if (d.kind === "audio" || (d.meta?.t0 != null && !d.boxes.length)) return d.meta?.t0 != null ? formatTimecode(d.meta.t0) : "";
  if (!d.boxes.length && d.meta?.media) return "picture";
  return `p.${detectionPage(d) + 1}`;
}

const DETECTORS: [RegExp, string][] = [
  [/^presidio/, "Second opinion (Presidio)"],
  [/^manual/, "Manual"],
  [/^ner|^ml|^gliner|^spacy|^model/, "AI model"],
  [/^classify/, "Picture classifier"],
  [/^template/, "Zone template"],
  [/^form/, "Form field"],
  [/^(dict|case)/, "Case dictionary"],
  [/^(term|list|search|user)/, "Search term"],
  [/^(rule|regex|pattern|kv|label|valid|checksum)/, "Pattern rule"],
  [/^(face|yolo|vision|plate|scrfd|retina|haar)/, "Vision model"],
];

/** Readable detector family from `source` ("ner:gliner+rule:ssn" → "AI model"). */
export function detectorLabel(source: string | undefined | null): string {
  const s = (source ?? "").toLowerCase().trim();
  if (!s) return "—";
  for (const [re, label] of DETECTORS) if (re.test(s)) return label;
  const head = s.split(/[+:]/)[0];
  return head ? head.charAt(0).toUpperCase() + head.slice(1).replace(/_/g, " ") : "—";
}

function position(d: Detection): number {
  if (d.meta?.t0 != null) return d.meta.t0 * 1000;
  const b = d.boxes[0];
  const page = b?.page ?? d.page;
  return page * 1e6 + (b ? b.y0 * 1000 + b.x0 : Math.max(0, d.start));
}

export function sortDetections(ds: Detection[], mode: SortMode): Detection[] {
  return [...ds].sort((a, b) => (mode === "confidence" ? b.score - a.score || position(a) - position(b) : position(a) - position(b)));
}

export function matchesFilter(d: Detection, q: string, m: MetaHelpers): boolean {
  if (!q) return true;
  const s = q.toLowerCase();
  return (
    d.text.toLowerCase().includes(s) ||
    m.entityLabel(d.entity).toLowerCase().includes(s) ||
    d.entity.toLowerCase().includes(s) ||
    (d.exemption || "").toLowerCase().includes(s) ||
    (d.source || "").toLowerCase().includes(s) ||
    (d.explanation || "").toLowerCase().includes(s)
  );
}

export type StatusFilter = "all" | "selected" | "suggested";

export interface DetectionFilter {
  text: string;
  /** empty = every category */
  categories: string[];
  /** "" = every type */
  entity: string;
  /** "all", "current" or a 0-based page */
  page: "all" | "current" | number;
  status: StatusFilter;
  /** 0..1 */
  minScore: number;
  /** only Microsoft Presidio second-opinion suggestions */
  secondOpinion: boolean;
}

export const EMPTY_FILTER: DetectionFilter = {
  text: "",
  categories: [],
  entity: "",
  page: "all",
  status: "all",
  minScore: 0,
  secondOpinion: false,
};

export function isFilterActive(f: DetectionFilter): boolean {
  return (
    !!f.text || f.categories.length > 0 || !!f.entity || f.page !== "all" || f.status !== "all" || f.minScore > 0 || f.secondOpinion
  );
}

/** Detections shown in the list. `showSuggestions` false hides unselected items whatever the status filter says. */
export function applyFilter(
  dets: Detection[],
  f: DetectionFilter,
  ctx: { m: MetaHelpers; currentPage?: number; showSuggestions?: boolean },
): Detection[] {
  const cats = new Set(f.categories);
  const page = f.page === "current" ? (ctx.currentPage ?? 0) : f.page;
  return dets.filter((d) => {
    if (ctx.showSuggestions === false && !d.selected) return false;
    if (f.status === "selected" && !d.selected) return false;
    if (f.status === "suggested" && d.selected) return false;
    if (cats.size && !cats.has(ctx.m.categoryOf(d.entity))) return false;
    if (f.entity && d.entity !== f.entity) return false;
    if (page !== "all" && !(d.boxes.some((b) => b.page === page) || (!d.boxes.length && d.page === page && d.meta?.t0 == null))) return false;
    if (f.minScore > 0 && d.score < f.minScore - 1e-9) return false;
    if (f.secondOpinion && !isSecondOpinion(d)) return false;
    return matchesFilter(d, f.text, ctx.m);
  });
}

export interface Group {
  category: string;
  types: { entity: string; items: Detection[]; total: number; selected: number }[];
  total: number;
  selected: number;
}

export function groupDetections(all: Detection[], visible: Detection[], m: MetaHelpers): Group[] {
  const totals = new Map<string, { total: number; selected: number }>();
  for (const d of all) {
    const t = totals.get(d.entity) ?? { total: 0, selected: 0 };
    t.total += 1;
    if (d.selected) t.selected += 1;
    totals.set(d.entity, t);
  }
  const cats = new Map<string, Map<string, Detection[]>>();
  for (const d of visible) {
    const c = m.categoryOf(d.entity);
    if (!cats.has(c)) cats.set(c, new Map());
    const types = cats.get(c)!;
    if (!types.has(d.entity)) types.set(d.entity, []);
    types.get(d.entity)!.push(d);
  }
  return Array.from(cats.entries())
    .sort((a, b) => CATEGORY_ORDER.indexOf(a[0]) - CATEGORY_ORDER.indexOf(b[0]))
    .map(([category, types]) => {
      const ts = Array.from(types.entries())
        .map(([entity, items]) => ({ entity, items, ...(totals.get(entity) ?? { total: items.length, selected: 0 }) }))
        .sort((a, b) => m.entityLabel(a.entity).localeCompare(m.entityLabel(b.entity)));
      return {
        category,
        types: ts,
        total: ts.reduce((n, t) => n + t.total, 0),
        selected: ts.reduce((n, t) => n + t.selected, 0),
      };
    });
}

/** Counts per category over all detections (for the legend / category chips). */
export function categoryCounts(all: Detection[], m: MetaHelpers): { category: string; total: number; selected: number }[] {
  const c = new Map<string, { total: number; selected: number }>();
  for (const d of all) {
    const k = m.categoryOf(d.entity);
    const v = c.get(k) ?? { total: 0, selected: 0 };
    v.total += 1;
    if (d.selected) v.selected += 1;
    c.set(k, v);
  }
  return Array.from(c.entries())
    .sort((a, b) => CATEGORY_ORDER.indexOf(a[0]) - CATEGORY_ORDER.indexOf(b[0]))
    .map(([category, v]) => ({ category, ...v }));
}
