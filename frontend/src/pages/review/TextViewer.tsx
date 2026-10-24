import { useEffect, useMemo, useRef, useState } from "react";
import { Eye, EyeOff, PencilLine } from "lucide-react";
import { useMeta } from "../../meta";
import { useHotkeys } from "../../lib/hotkeys";
import type { Detection } from "../../types";
import type { DetectionOps } from "./useDetections";
import type { FocusRequest } from "./workspace";
import type { JumpRequest } from "./ReviewPage";
import { EntitySelect } from "./PropertiesPanel";

export interface Segment {
  start: number;
  end: number;
  /** detections covering the whole segment (shortest first) */
  dets: Detection[];
}

/** Split `text` at every detection boundary; each piece lists the detections covering it. */
export function buildSegments(textLength: number, dets: Detection[]): Segment[] {
  const spans = dets.filter((d) => d.start >= 0 && d.end > d.start && d.start < textLength);
  const cuts = new Set<number>([0, textLength]);
  for (const d of spans) {
    cuts.add(Math.max(0, d.start));
    cuts.add(Math.min(textLength, d.end));
  }
  const points = Array.from(cuts).sort((a, b) => a - b);
  const byStart = [...spans].sort((a, b) => a.start - b.start);
  const out: Segment[] = [];
  let active: Detection[] = [];
  let k = 0;
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i];
    const b = points[i + 1];
    while (k < byStart.length && byStart[k].start <= a) active.push(byStart[k++]);
    active = active.filter((d) => d.end > a);
    const covering = active.filter((d) => d.start <= a && d.end >= b).sort((x, y) => x.end - x.start - (y.end - y.start));
    out.push({ start: a, end: b, dets: covering });
  }
  return out;
}

/** Map a DOM selection inside the text view back to character offsets. */
function selectionOffsets(root: HTMLElement): { start: number; end: number; rect: DOMRect } | null {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null;
  const range = sel.getRangeAt(0);
  if (!root.contains(range.commonAncestorContainer)) return null;
  const offsetOf = (node: Node, off: number): number | null => {
    const el = (node.nodeType === Node.TEXT_NODE ? node.parentElement : (node as HTMLElement))?.closest<HTMLElement>("[data-s]");
    if (!el) return null;
    const base = Number(el.dataset.s);
    if (node.nodeType === Node.TEXT_NODE) return base + off;
    return base + (off > 0 ? (el.textContent ?? "").length : 0);
  };
  const a = offsetOf(range.startContainer, range.startOffset);
  const b = offsetOf(range.endContainer, range.endOffset);
  if (a == null || b == null || b <= a) return null;
  return { start: a, end: b, rect: range.getBoundingClientRect() };
}

interface Props {
  text: string;
  dets: Detection[];
  ops: DetectionOps;
  focus: FocusRequest | null;
  onFocus: (d: Detection, source: "viewer") => void;
  preview: boolean;
  setPreview: (v: boolean) => void;
  showSuggestions: boolean;
  setShowSuggestions: (v: boolean) => void;
  searchMatches: Detection[];
  jump: JumpRequest | null;
  readOnly: boolean;
}

export function TextViewer({
  text,
  dets,
  ops,
  focus,
  onFocus,
  preview,
  setPreview,
  showSuggestions,
  setShowSuggestions,
  searchMatches,
  jump,
  readOnly,
}: Props) {
  const m = useMeta();
  const rootRef = useRef<HTMLDivElement>(null);
  const [pending, setPending] = useState<{ start: number; end: number; x: number; y: number } | null>(null);
  const [markAs, setMarkAs] = useState("CUSTOM");

  const shown = useMemo(() => dets.filter((d) => d.selected || (showSuggestions && !preview)), [dets, showSuggestions, preview]);
  const all = useMemo(() => [...shown, ...searchMatches.map((d) => ({ ...d, id: `hit-${d.id}`, kind: "hit" }))], [shown, searchMatches]);
  const segments = useMemo(() => buildSegments(text.length, all), [text.length, all]);

  useHotkeys({ p: () => setPreview(!preview), s: () => setShowSuggestions(!showSuggestions) });

  // scroll to a Find & Redact match
  useEffect(() => {
    if (!jump || !rootRef.current) return;
    const el = rootRef.current.querySelector(`[data-ids~="${CSS.escape(`hit-${jump.match.id}`)}"]`);
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [jump]);

  // scroll to a detection chosen in the panel
  useEffect(() => {
    if (!focus || focus.source !== "panel" || !rootRef.current) return;
    const el = rootRef.current.querySelector(`[data-ids~="${CSS.escape(focus.id)}"]`);
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [focus]);

  const onMouseUp = () => {
    const root = rootRef.current;
    if (!root || readOnly) return;
    const s = selectionOffsets(root);
    if (!s) {
      setPending(null);
      return;
    }
    const box = root.getBoundingClientRect();
    setPending({ start: s.start, end: s.end, x: s.rect.left - box.left + root.scrollLeft, y: s.rect.bottom - box.top + root.scrollTop + 6 });
  };

  const confirm = async () => {
    if (!pending) return;
    const { start, end } = pending;
    setPending(null);
    window.getSelection()?.removeAllRanges();
    const d = await ops.add({ entity: markAs, page: 0, start, end }, "Redact selected text");
    if (d) onFocus(d, "viewer");
  };

  return (
    <div className="viewer-col text-viewer">
      <div className="viewer-toolbar" role="toolbar" aria-label="Viewer tools">
        <div className="seg seg-sm" role="radiogroup" aria-label="View mode">
          <button type="button" role="radio" aria-checked={!preview} className={`seg-item ${!preview ? "active" : ""}`} onClick={() => setPreview(false)}>
            <PencilLine size={14} aria-hidden /> Edit
          </button>
          <button type="button" role="radio" aria-checked={preview} className={`seg-item ${preview ? "active" : ""}`} onClick={() => setPreview(true)} data-tip="Preview redacted (P)">
            <Eye size={14} aria-hidden /> Preview redacted
          </button>
        </div>
        <button
          type="button"
          className={`tool-btn ${!showSuggestions ? "active" : ""}`}
          aria-pressed={!showSuggestions}
          onClick={() => setShowSuggestions(!showSuggestions)}
          data-tip="Show or hide unselected suggestions (S)"
        >
          {showSuggestions ? <Eye size={14} aria-hidden /> : <EyeOff size={14} aria-hidden />}
          <span>{showSuggestions ? "Suggestions shown" : "Suggestions hidden"}</span>
        </button>
        <span className="toolbar-spacer" />
        {!readOnly && (
          <label className="row gap-sm small mark-as">
            <span className="muted">Select text to redact as</span>
            <span className="select-sm-wrap">
              <EntitySelect id="tv-mark" value={markAs} onChange={setMarkAs} />
            </span>
          </label>
        )}
      </div>
      <div className="viewer-scroll">
        <div className="text-doc" ref={rootRef} onPointerUp={() => setTimeout(onMouseUp, 0)} onKeyUp={(e) => e.shiftKey && onMouseUp()}>
          {segments.map((seg) => {
            const piece = text.slice(seg.start, seg.end);
            if (!seg.dets.length) {
              return (
                <span key={seg.start} data-s={seg.start}>
                  {piece}
                </span>
              );
            }
            const real = seg.dets.filter((d) => d.kind !== "hit");
            const top = real.find((d) => d.selected) ?? real[0];
            const hitIds = seg.dets.filter((d) => d.kind === "hit").map((d) => d.id).join(" ");
            if (!top) {
              return (
                <mark key={seg.start} data-s={seg.start} data-ids={hitIds} className="search-hit-text">
                  {piece}
                </mark>
              );
            }
            const color = m.color(top.entity);
            if (preview && top.selected) {
              return (
                <span key={seg.start} data-s={seg.start} className="redacted-text" data-ids={real.map((d) => d.id).join(" ")}>
                  {piece.replace(/[^\s]/g, "█")}
                </span>
              );
            }
            const focused = real.some((d) => d.id === focus?.id);
            return (
              <mark
                key={seg.start}
                data-s={seg.start}
                data-ids={[...real.map((d) => d.id), hitIds].join(" ")}
                className={`hl ${top.selected ? "hl-selected" : "hl-suggested"} ${focused ? "hl-focused" : ""}`}
                style={{ ["--hl" as string]: color }}
                title={`${m.entityLabel(top.entity)} · ${Math.round(top.score * 100)}%${top.exemption ? ` · ${top.exemption}` : ""} — click to select, double-click to ${top.selected ? "un-redact" : "redact"}`}
                onClick={() => {
                  const s = window.getSelection();
                  if (s && !s.isCollapsed) return;
                  onFocus(top, "viewer");
                }}
                onDoubleClick={() => {
                  // a double-click also selects the word: drop that selection, it is not a new redaction
                  window.getSelection()?.removeAllRanges();
                  setPending(null);
                  if (!readOnly) ops.toggle(top.id);
                }}
              >
                {piece}
              </mark>
            );
          })}
          {pending && (
            <div className="float-bar" style={{ left: Math.max(0, pending.x), top: pending.y }}>
              <span className="small">
                Redact {pending.end - pending.start} characters as <strong>{m.entityLabel(markAs)}</strong>
              </span>
              <button className="btn btn-xs btn-primary" onMouseDown={(e) => e.preventDefault()} onClick={confirm}>
                Redact
              </button>
              <button className="btn btn-xs" onMouseDown={(e) => e.preventDefault()} onClick={() => setPending(null)}>
                Cancel
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
