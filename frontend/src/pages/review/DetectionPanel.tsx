import { memo, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Check, ChevronDown, ChevronRight, ListFilter, Scale, Search, X } from "lucide-react";
import { isSecondOpinion } from "../../lib/secondOpinion";
import { CATEGORY_COLORS, useMeta } from "../../meta";
import { ConfidenceBadge, EmptyState } from "../../components/ui";
import { truncate } from "../../lib/format";
import type { Detection } from "../../types";
import type { DetectionOps } from "./useDetections";
import {
  applyFilter,
  categoryCounts,
  detectionLabel,
  detectionLocation,
  detectorLabel,
  EMPTY_FILTER,
  groupDetections,
  isFilterActive,
  sortDetections,
  type DetectionFilter,
  type SortMode,
} from "./detectionUtils";

// re-exported for older imports / tests
export { detectionLabel, detectionLocation, groupDetections, matchesFilter, sortDetections } from "./detectionUtils";
export type { SortMode } from "./detectionUtils";

// ---- one row ------------------------------------------------------------------------------------------

interface ItemProps {
  d: Detection;
  focused: boolean;
  tabbable: boolean;
  readOnly: boolean;
  onFocus: (d: Detection) => void;
  ops: DetectionOps;
}

const DetectionItem = memo(function DetectionItem({ d, focused, tabbable, readOnly, onFocus, ops }: ItemProps) {
  const m = useMeta();
  const color = m.color(d.entity);
  const label = detectionLabel(d, m);
  return (
    <li className={`det-item ${d.selected ? "is-selected" : "is-suggested"} ${focused ? "is-focused" : ""}`} data-det-id={d.id}>
      <input
        type="checkbox"
        className="det-check"
        checked={d.selected}
        disabled={readOnly}
        onChange={() => ops.toggle(d.id)}
        aria-label={`${d.selected ? "Redacting" : "Suggested"}: ${m.entityLabel(d.entity)} ${detectionLocation(d)}`}
        tabIndex={-1}
      />
      <button className="det-main" data-det-button tabIndex={tabbable ? 0 : -1} onClick={() => onFocus(d)} aria-current={focused ? "true" : undefined}>
        <span className="det-line1">
          <span className={`det-swatch ${d.selected ? "filled" : "dashed"}`} style={{ borderColor: color, background: d.selected ? color : "transparent" }} aria-hidden />
          <span className="det-text">{truncate(label, 70)}</span>
          {isSecondOpinion(d) && (
            <span className="badge badge-info tiny so-badge" title="Suggested by the second opinion (Microsoft Presidio)">
              2nd opinion
            </span>
          )}
          <ConfidenceBadge score={d.score} compact />
        </span>
        <span className="det-line2">
          <span className="det-type">{m.entityLabel(d.entity)}</span>
          <span className="det-sep" aria-hidden>
            ·
          </span>
          <span>{detectionLocation(d)}</span>
          <span className="det-sep" aria-hidden>
            ·
          </span>
          <span title={d.source}>{detectorLabel(d.source)}</span>
          {d.exemption && <span className="det-ex mono">{d.exemption}</span>}
        </span>
        {d.explanation && <span className="det-reason">{truncate(d.explanation, 110)}</span>}
      </button>
    </li>
  );
});

// ---- panel ------------------------------------------------------------------------------------------

interface PanelProps {
  dets: Detection[];
  ops: DetectionOps;
  focusedId: string | null;
  onFocus: (d: Detection) => void;
  showSuggestions: boolean;
  setShowSuggestions: (v: boolean) => void;
  readOnly?: boolean;
  chips?: ReactNode;
  /** paged files: the page shown in the viewer (enables the "this page" filter) */
  currentPage?: number | null;
  pageCount?: number;
  title?: string;
  emptyHint?: ReactNode;
}

export function DetectionPanel({
  dets,
  ops,
  focusedId,
  onFocus,
  showSuggestions,
  setShowSuggestions,
  readOnly = false,
  chips,
  currentPage = null,
  pageCount = 0,
  title = "Detections",
  emptyHint,
}: PanelProps) {
  const m = useMeta();
  const [filter, setFilter] = useState<DetectionFilter>(EMPTY_FILTER);
  const [showFilters, setShowFilters] = useState(false);
  const [sort, setSort] = useState<SortMode>("page");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [limits, setLimits] = useState<Record<string, number>>({});
  const listRef = useRef<HTMLDivElement>(null);

  const visible = useMemo(
    () => sortDetections(applyFilter(dets, filter, { m, currentPage: currentPage ?? 0, showSuggestions }), sort),
    [dets, filter, m, currentPage, showSuggestions, sort],
  );
  const groups = useMemo(() => groupDetections(dets, visible, m), [dets, visible, m]);
  const cats = useMemo(() => categoryCounts(dets, m), [dets, m]);
  const types = useMemo(() => {
    const s = new Map<string, number>();
    for (const d of dets) s.set(d.entity, (s.get(d.entity) ?? 0) + 1);
    return Array.from(s.entries()).sort((a, b) => m.entityLabel(a[0]).localeCompare(m.entityLabel(b[0])));
  }, [dets, m]);
  const selectedCount = useMemo(() => dets.filter((d) => d.selected).length, [dets]);
  const active = isFilterActive(filter);
  const second = useMemo(() => dets.filter(isSecondOpinion), [dets]);
  const secondOpen = second.filter((d) => !d.selected);
  const shownSuggested = visible.filter((d) => !d.selected).length;
  const shownSelected = visible.length - shownSuggested;

  useEffect(() => {
    if (!focusedId || !listRef.current) return;
    listRef.current.querySelector(`[data-det-id="${CSS.escape(focusedId)}"]`)?.scrollIntoView({ block: "nearest" });
  }, [focusedId]);

  const toggleCollapsed = (k: string) =>
    setCollapsed((s) => {
      const n = new Set(s);
      if (n.has(k)) n.delete(k);
      else n.add(k);
      return n;
    });

  const toggleCategory = (c: string) =>
    setFilter((f) => ({ ...f, categories: f.categories.includes(c) ? f.categories.filter((x) => x !== c) : [...f.categories, c] }));

  // roving focus with ↑/↓; Space toggles
  const onListKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    if (!target.matches("[data-det-button]")) return;
    const buttons = Array.from(listRef.current?.querySelectorAll<HTMLButtonElement>("[data-det-button]") ?? []);
    const i = buttons.indexOf(target as HTMLButtonElement);
    const id = target.closest<HTMLElement>("[data-det-id]")?.dataset.detId;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const next = buttons[Math.max(0, Math.min(buttons.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)))];
      const nid = next?.closest<HTMLElement>("[data-det-id]")?.dataset.detId;
      const d = dets.find((x) => x.id === nid);
      if (d) onFocus(d);
      next?.focus();
    } else if (e.key === " " && id && !readOnly) {
      e.preventDefault();
      ops.toggle(id);
    }
  };

  const firstId = visible[0]?.id;
  const pct = dets.length ? selectedCount / dets.length : 0;

  return (
    <section className="det-panel" aria-label={title}>
      <div className="det-panel-head">
        <div className="row space">
          <h2>{title}</h2>
          <span className="small muted" aria-live="polite">
            <strong className="text">{selectedCount}</strong> of {dets.length} redacted
          </span>
        </div>
        <div className="mini-progress" aria-hidden>
          <span style={{ width: `${pct * 100}%` }} />
        </div>
        {chips && <div className="chips">{chips}</div>}
        {cats.length > 0 && (
          <div className="legend" role="group" aria-label="Categories (click to filter)">
            {cats.map((c) => {
              const on = filter.categories.includes(c.category);
              return (
                <button
                  key={c.category}
                  type="button"
                  className={`legend-chip ${on ? "active" : ""}`}
                  aria-pressed={on}
                  onClick={() => toggleCategory(c.category)}
                  data-tip={`${m.categoryLabel(c.category)}: ${c.selected} of ${c.total} redacted`}
                >
                  <span className="cat-dot" style={{ background: CATEGORY_COLORS[c.category] ?? CATEGORY_COLORS.OTHER }} aria-hidden />
                  <span className="legend-name">{shortCategory(c.category, m.categoryLabel(c.category))}</span>
                  <span className="legend-count">{c.total}</span>
                </button>
              );
            })}
          </div>
        )}
        {second.length > 0 && (
          <div className="so-callout" role="group" aria-label="Second opinion">
            <Scale size={15} aria-hidden />
            <div className="grow">
              <div className="small">
                <strong>Second opinion</strong> — Microsoft Presidio suggests {second.length} more item{second.length === 1 ? "" : "s"}
                {secondOpen.length !== second.length ? ` (${secondOpen.length} still open)` : ""}.
              </div>
              <div className="row gap-xs wrap">
                <button
                  type="button"
                  className={`filter-chip ${filter.secondOpinion ? "active" : ""}`}
                  aria-pressed={filter.secondOpinion}
                  onClick={() => setFilter({ ...filter, secondOpinion: !filter.secondOpinion })}
                >
                  Second opinion <span className="filter-count">{second.length}</span>
                </button>
                {!readOnly && secondOpen.length > 0 && (
                  <>
                    <button
                      className="btn btn-xs"
                      onClick={() => ops.setSelected(secondOpen.map((d) => d.id), true, `Redact ${secondOpen.length} second-opinion items`)}
                      data-tip="Redact every open second-opinion suggestion"
                    >
                      <Check size={12} aria-hidden /> Redact all
                    </button>
                    <button
                      className="btn btn-xs"
                      onClick={() => ops.removeMany(secondOpen.map((d) => d.id), `Dismiss ${secondOpen.length} second-opinion items`)}
                      data-tip="Remove every open second-opinion suggestion (Undo brings them back)"
                    >
                      <X size={12} aria-hidden /> Dismiss all
                    </button>
                  </>
                )}
              </div>
            </div>
          </div>
        )}
        <div className="row gap-sm">
          <div className="search-input grow">
            <Search size={14} aria-hidden />
            <input
              aria-label="Filter detections"
              placeholder="Filter by text, type, code…"
              value={filter.text}
              onChange={(e) => setFilter({ ...filter, text: e.target.value })}
            />
            {filter.text && (
              <button className="icon-btn xs" onClick={() => setFilter({ ...filter, text: "" })} aria-label="Clear the text filter">
                <X size={12} />
              </button>
            )}
          </div>
          <button
            className={`icon-btn ${showFilters || active ? "active" : ""}`}
            aria-expanded={showFilters}
            aria-label="More filters"
            data-tip="Filters: type, page, status, confidence"
            onClick={() => setShowFilters((v) => !v)}
          >
            <ListFilter size={16} />
          </button>
        </div>
        {showFilters && (
          <div className="det-filters">
            <label className="field-inline">
              <span>Type</span>
              <select className="select-sm" value={filter.entity} onChange={(e) => setFilter({ ...filter, entity: e.target.value })}>
                <option value="">All types</option>
                {types.map(([k, n]) => (
                  <option key={k} value={k}>
                    {m.entityLabel(k)} ({n})
                  </option>
                ))}
              </select>
            </label>
            {currentPage != null && (
              <label className="field-inline">
                <span>Page</span>
                <select
                  className="select-sm"
                  value={String(filter.page)}
                  onChange={(e) => {
                    const v = e.target.value;
                    setFilter({ ...filter, page: v === "all" || v === "current" ? v : Number(v) });
                  }}
                >
                  <option value="all">All pages</option>
                  <option value="current">This page ({currentPage + 1})</option>
                  {Array.from({ length: Math.min(pageCount, 500) }, (_, i) => (
                    <option key={i} value={i}>
                      Page {i + 1}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <div className="field-inline">
              <span>Show</span>
              <div className="seg seg-xs" role="radiogroup" aria-label="Status">
                {(
                  [
                    ["all", "All"],
                    ["selected", "Redacting"],
                    ["suggested", "Suggestions"],
                  ] as const
                ).map(([k, l]) => (
                  <button
                    key={k}
                    type="button"
                    role="radio"
                    aria-checked={filter.status === k}
                    className={`seg-item ${filter.status === k ? "active" : ""}`}
                    onClick={() => setFilter({ ...filter, status: k })}
                  >
                    {l}
                  </button>
                ))}
              </div>
            </div>
            <label className="field-inline">
              <span>Sort by</span>
              <select className="select-sm" value={sort} onChange={(e) => setSort(e.target.value as SortMode)}>
                <option value="page">Position in the document</option>
                <option value="confidence">Confidence (highest first)</option>
              </select>
            </label>
            <label className="field-inline">
              <span>Min. confidence</span>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={filter.minScore}
                onChange={(e) => setFilter({ ...filter, minScore: Number(e.target.value) })}
                aria-valuetext={`${Math.round(filter.minScore * 100)}%`}
              />
              <span className="mono tiny conf-value">{Math.round(filter.minScore * 100)}%</span>
            </label>
            <div className="row space">
              <label className="check inline small">
                <input type="checkbox" checked={showSuggestions} onChange={(e) => setShowSuggestions(e.target.checked)} />
                Show unselected suggestions
              </label>
              <button className="link-btn small" onClick={() => setFilter(EMPTY_FILTER)} disabled={!active}>
                Clear filters
              </button>
            </div>
          </div>
        )}
        <div className="bulk-row">
          <span className="small muted">
            {visible.length === dets.length ? `${visible.length} items` : `${visible.length} of ${dets.length}`}
          </span>
          <span className="toolbar-spacer" />
          {!readOnly && visible.length > 0 && (
            <>
              <button
                className="btn btn-xs"
                disabled={shownSuggested === 0}
                onClick={() => ops.setSelected(visible.map((d) => d.id), true, `Accept ${shownSuggested} shown`)}
                data-tip="Accept (redact) every item shown in the list, as filtered"
              >
                <Check size={12} aria-hidden /> Accept all shown
              </button>
              <button
                className="btn btn-xs"
                disabled={shownSelected === 0}
                onClick={() => ops.setSelected(visible.map((d) => d.id), false, `Reject ${shownSelected} shown`)}
                data-tip="Reject (keep visible) every item shown in the list, as filtered"
              >
                <X size={12} aria-hidden /> Reject all shown
              </button>
            </>
          )}
        </div>
      </div>
      <div className="det-list" ref={listRef} onKeyDown={onListKey}>
        {dets.length === 0 && (
          <EmptyState compact title="Nothing detected yet">
            {emptyHint ?? "Draw a shape or select text to add a redaction."}
          </EmptyState>
        )}
        {dets.length > 0 && visible.length === 0 && (
          <EmptyState compact title="No detections match">
            <button className="link-btn" onClick={() => setFilter(EMPTY_FILTER)}>
              Clear the filters
            </button>
            {!showSuggestions && " — suggestions are hidden."}
          </EmptyState>
        )}
        {groups.map((g) => {
          const ck = `c:${g.category}`;
          const catCollapsed = collapsed.has(ck);
          return (
            <section key={g.category} className="det-cat">
              <div className="det-cat-head">
                <button className="det-collapse" onClick={() => toggleCollapsed(ck)} aria-expanded={!catCollapsed}>
                  {catCollapsed ? <ChevronRight size={14} aria-hidden /> : <ChevronDown size={14} aria-hidden />}
                  <span className="cat-dot" style={{ background: CATEGORY_COLORS[g.category] ?? CATEGORY_COLORS.OTHER }} aria-hidden />
                  <span className="strong truncate">{m.categoryLabel(g.category)}</span>
                  <span className="count-pill">
                    {g.selected}/{g.total}
                  </span>
                </button>
                {!readOnly && (
                  <span className="group-actions">
                    <button
                      className="icon-btn sm"
                      data-tip="Accept the whole category"
                      aria-label={`Accept all ${m.categoryLabel(g.category)}`}
                      onClick={() => ops.selectEntities(Object.fromEntries(g.types.map((t) => [t.entity, true])))}
                    >
                      <Check size={14} />
                    </button>
                    <button
                      className="icon-btn sm"
                      data-tip="Reject the whole category"
                      aria-label={`Reject all ${m.categoryLabel(g.category)}`}
                      onClick={() => ops.selectEntities(Object.fromEntries(g.types.map((t) => [t.entity, false])))}
                    >
                      <X size={14} />
                    </button>
                  </span>
                )}
              </div>
              {!catCollapsed &&
                g.types.map((t) => {
                  const tk = `t:${t.entity}`;
                  const tCollapsed = collapsed.has(tk);
                  const limit = limits[t.entity] ?? 150;
                  return (
                    <div key={t.entity} className="det-type">
                      <div className="det-type-head">
                        <button className="det-collapse" onClick={() => toggleCollapsed(tk)} aria-expanded={!tCollapsed}>
                          {tCollapsed ? <ChevronRight size={13} aria-hidden /> : <ChevronDown size={13} aria-hidden />}
                          <span className="truncate">{m.entityLabel(t.entity)}</span>
                          <span className="count-pill subtle">
                            {t.selected}/{t.total}
                          </span>
                        </button>
                        {!readOnly && (
                          <span className="group-actions">
                            <button
                              className="icon-btn xs"
                              onClick={() => ops.selectEntities({ [t.entity]: true })}
                              data-tip={`Accept all ${t.total}`}
                              aria-label={`Accept all ${t.total} ${m.entityLabel(t.entity)}`}
                            >
                              <Check size={13} />
                            </button>
                            <button
                              className="icon-btn xs"
                              onClick={() => ops.selectEntities({ [t.entity]: false })}
                              data-tip={`Reject all ${t.total}`}
                              aria-label={`Reject all ${t.total} ${m.entityLabel(t.entity)}`}
                            >
                              <X size={13} />
                            </button>
                          </span>
                        )}
                      </div>
                      {!tCollapsed && (
                        <ul className="det-items">
                          {t.items.slice(0, limit).map((d) => (
                            <DetectionItem
                              key={d.id}
                              d={d}
                              focused={focusedId === d.id}
                              tabbable={focusedId ? focusedId === d.id : d.id === firstId}
                              readOnly={readOnly}
                              onFocus={onFocus}
                              ops={ops}
                            />
                          ))}
                          {t.items.length > limit && (
                            <li>
                              <button className="link-btn small pad" onClick={() => setLimits((l) => ({ ...l, [t.entity]: limit + 300 }))}>
                                Show {Math.min(300, t.items.length - limit)} more of {t.items.length - limit}
                              </button>
                            </li>
                          )}
                        </ul>
                      )}
                    </div>
                  );
                })}
            </section>
          );
        })}
      </div>
    </section>
  );
}

const SHORT_CATEGORY: Record<string, string> = {
  PII: "Personal",
  PHI: "Health",
  PCI: "Financial",
  LEGAL: "Legal",
  INDIRECT: "Indirect",
  VISUAL: "Visual",
  CUSTOM: "Custom",
  OTHER: "Other",
};

function shortCategory(cat: string, label: string): string {
  if (SHORT_CATEGORY[cat]) return SHORT_CATEGORY[cat];
  const s = label.split(/[:(—]/)[0].trim();
  return s.length > 16 ? s.slice(0, 15) + "…" : s;
}
