import { memo, useEffect, useRef } from "react";
import * as api from "../../api";
import type { Detection, PageInfo } from "../../types";

export interface PageCount {
  sel: number;
  sug: number;
}

/** Redactions (selected) and suggestions per page. */
export function pageCounts(dets: Detection[]): Map<number, PageCount> {
  const c = new Map<number, PageCount>();
  for (const d of dets) {
    const ps = new Set(d.boxes.map((b) => b.page));
    for (const p of ps) {
      const v = c.get(p) ?? { sel: 0, sug: 0 };
      if (d.selected) v.sel++;
      else v.sug++;
      c.set(p, v);
    }
  }
  return c;
}

interface Props {
  fileId: number;
  pages: PageInfo[];
  current: number;
  onSelect: (n: number) => void;
  counts: Map<number, PageCount>;
}

export const Thumbs = memo(function Thumbs({ fileId, pages, current, onSelect, counts }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.querySelector(`[data-page="${current}"]`)?.scrollIntoView({ block: "nearest" });
  }, [current]);
  return (
    <nav className="thumbs" aria-label="Pages" ref={ref}>
      {pages.map((p) => {
        const c = counts.get(p.page);
        const label = `Page ${p.page + 1}${c?.sel ? `, ${c.sel} redaction${c.sel === 1 ? "" : "s"}` : ""}${c?.sug ? `, ${c.sug} suggestion${c.sug === 1 ? "" : "s"}` : ""}`;
        return (
          <button
            key={p.page}
            data-page={p.page}
            className={`thumb ${p.page === current ? "active" : ""}`}
            onClick={() => onSelect(p.page)}
            aria-current={p.page === current ? "page" : undefined}
            aria-label={label}
          >
            <span className="thumb-img" style={{ aspectRatio: `${p.width} / ${p.height}` }}>
              <img src={api.urls.pageImage(fileId, p.page, 36)} alt="" loading="lazy" draggable={false} />
              {(c?.sel ?? 0) > 0 && (
                <span className="thumb-count" aria-hidden>
                  {c!.sel}
                </span>
              )}
            </span>
            <span className="thumb-foot" aria-hidden>
              <span className="thumb-num">{p.page + 1}</span>
              {c && c.sug > 0 && <span className="thumb-sug" data-tip={`${c.sug} suggestion${c.sug === 1 ? "" : "s"}`}>{c.sug}</span>}
              {p.source && p.source !== "native" && p.source !== "image" && <span className="thumb-ocr">OCR</span>}
            </span>
          </button>
        );
      })}
    </nav>
  );
});
