import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import * as api from "./api";
import type { EntityMeta, Meta } from "./types";
import { titleCase } from "./lib/format";

// Visual detections (faces, vehicles…) are not in the text entity catalogue.
const VISUAL_LABELS: Record<string, string> = {
  FACE: "Face",
  LICENSE_PLATE: "License plate",
  PERSON_BODY: "Person (body)",
  VEHICLE: "Vehicle",
  SCREEN: "Screen / device",
  DOCUMENT_REGION: "Document / paper",
};

export const CATEGORY_ORDER = ["PII", "PHI", "PCI", "LEGAL", "INDIRECT", "VISUAL", "CUSTOM", "OTHER"];

export const CATEGORY_LABELS_FALLBACK: Record<string, string> = {
  VISUAL: "Faces, plates & visual",
  OTHER: "Other",
};

/** Outline colours per category (also used in the legend). Selected vs suggested also differ by fill/dash. */
export const CATEGORY_COLORS: Record<string, string> = {
  PII: "#2f6fde",
  PHI: "#d0346a",
  PCI: "#1f9d55",
  LEGAL: "#8a4bd6",
  INDIRECT: "#d9822b",
  VISUAL: "#c2a100",
  CUSTOM: "#0f9ba8",
  OTHER: "#6b7280",
};

export interface MetaHelpers {
  meta: Meta | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
  entity: (key: string) => EntityMeta | undefined;
  entityLabel: (key: string) => string;
  categoryOf: (key: string) => string;
  categoryLabel: (cat: string) => string;
  color: (key: string) => string;
  exemptionCodes: [string, string][];
}

const MetaContext = createContext<MetaHelpers | null>(null);

export function MetaProvider({ children }: { children: ReactNode }) {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    api
      .getMeta()
      .then((m) => {
        if (alive) {
          setMeta(m);
          setError(null);
        }
      })
      .catch((e: unknown) => alive && setError(e instanceof Error ? e.message : "could not load settings"))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  const value = useMemo<MetaHelpers>(() => {
    const byKey = new Map((meta?.entities ?? []).map((e) => [e.key, e]));
    const categoryOf = (key: string) => byKey.get(key)?.category ?? (key in VISUAL_LABELS ? "VISUAL" : "OTHER");
    return {
      meta,
      loading,
      error,
      reload,
      entity: (k) => byKey.get(k),
      entityLabel: (k) => byKey.get(k)?.label ?? VISUAL_LABELS[k] ?? titleCase(k),
      categoryOf,
      categoryLabel: (c) => meta?.categories?.[c] ?? CATEGORY_LABELS_FALLBACK[c] ?? titleCase(c),
      color: (k) => CATEGORY_COLORS[categoryOf(k)] ?? CATEGORY_COLORS.OTHER,
      exemptionCodes: Object.entries(meta?.exemption_codes ?? {}),
    };
  }, [meta, loading, error, reload]);

  return <MetaContext.Provider value={value}>{children}</MetaContext.Provider>;
}

export function useMeta(): MetaHelpers {
  const ctx = useContext(MetaContext);
  if (!ctx) throw new Error("useMeta outside MetaProvider");
  return ctx;
}

/** All entity choices for "change type" / manual redaction pickers (text + visual), sorted by category. */
export function entityOptions(m: MetaHelpers): { key: string; label: string; category: string }[] {
  const out = (m.meta?.entities ?? []).map((e) => ({ key: e.key, label: e.label, category: e.category }));
  for (const [k, label] of Object.entries(VISUAL_LABELS)) {
    if (!out.some((o) => o.key === k)) out.push({ key: k, label, category: "VISUAL" });
  }
  return out.sort(
    (a, b) =>
      CATEGORY_ORDER.indexOf(a.category) - CATEGORY_ORDER.indexOf(b.category) || a.label.localeCompare(b.label),
  );
}

/** Entity choices grouped by category (for <optgroup> pickers). */
export function entityGroups(m: MetaHelpers): { category: string; label: string; options: { key: string; label: string }[] }[] {
  const groups = new Map<string, { key: string; label: string }[]>();
  for (const o of entityOptions(m)) {
    if (!groups.has(o.category)) groups.set(o.category, []);
    groups.get(o.category)!.push({ key: o.key, label: o.label });
  }
  return Array.from(groups.entries()).map(([category, options]) => ({ category, label: m.categoryLabel(category), options }));
}

/** Language name for an ISO code from GET /api/meta (falls back to the code). */
export function languageName(m: MetaHelpers, code: string | null | undefined): string {
  if (!code) return "";
  return m.meta?.languages?.codes?.[code] ?? code.toUpperCase();
}

/** Picture class label: meta image_classes first, then the entity catalogue. */
export function pictureClassLabel(m: MetaHelpers, cls: string): string {
  return m.meta?.image_classes?.classes?.[cls] ?? m.entityLabel(cls);
}
