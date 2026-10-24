import { useMemo, useRef, useState, type PointerEvent as RPointerEvent, type ReactNode } from "react";
import { Check, Trash2, X } from "lucide-react";
import { useMeta } from "../../meta";
import { useHotkeys } from "../../lib/hotkeys";
import { percent, truncate } from "../../lib/format";
import {
  charIndexAt,
  clientToView,
  invertMatrix,
  lineRects,
  normalizeRect,
  rectHeight,
  rectWidth,
  transformRect,
  viewPointToPage,
  type Matrix,
  type Point,
  type Rect,
} from "../../lib/geometry";
import {
  closesPolygon,
  constrainSquare,
  displayShape,
  ellipseFromRect,
  handlePoint,
  HANDLES,
  polygonArea,
  resizeRect,
  svgPoints,
  viewDragToPageRect,
  viewPolygonToPage,
  type DisplayShape,
  type Handle,
  type PagePoint,
} from "../../lib/shapes";
import { isPicture, PICTURE_SHORT, pictureClass } from "../../lib/pictures";
import type { Box, CharBox, Detection } from "../../types";
import { detectorLabel } from "./detectionUtils";
import { isLightFill, rgbCss, type Tool, type ViewMode } from "./workspace";

export interface OverlayItem {
  det: Detection;
  box: Box;
  /** index of `box` in det.boxes */
  index: number;
  key: string;
}

export type NewShape = { kind: "rect" | "ellipse"; rect: Rect } | { kind: "polygon"; points: PagePoint[]; rect: Rect };

interface Props {
  /** displayed page size, page units */
  pw: number;
  ph: number;
  /** view px per page unit (the rendered size) */
  scale: number;
  matrix: Matrix;
  items: OverlayItem[];
  tool: Tool;
  mode: ViewMode;
  focusedId: string | null;
  readOnly: boolean;
  /** search hits, displayed page units */
  hits: Rect[];
  /** character boxes of the page (text tool) */
  charBoxes: CharBox[];
  /** images: the page image, used to preview blur / pixelate effects */
  effectImage: string | null;
  markAsLabel: string;
  onSelect: (d: Detection | null) => void;
  onToggle: (d: Detection) => void;
  onDelete: (d: Detection) => void;
  onCreate: (s: NewShape) => void;
  onMove: (item: OverlayItem, dx: number, dy: number) => void;
  onResize: (item: OverlayItem, rect: Rect) => void;
  onTextRange: (start: number, end: number) => void;
}

type Draft = { kind: "rect" | "ellipse"; a: Point; b: Point } | null;
interface Drag {
  item: OverlayItem;
  start: Point;
  cur: Point;
  moved: boolean;
  handle: Handle | null;
  shape: DisplayShape;
}

const MIN_DRAW_PX = 4;

function movable(d: Detection, readOnly: boolean): boolean {
  if (readOnly) return false;
  if (d.start >= 0 && d.end > d.start) return false; // text: its boxes follow the characters
  return d.boxes.length === 1;
}

function ShapeEl({ s, className, stroke, fill, dash }: { s: DisplayShape; className?: string; stroke?: string; fill?: string; dash?: boolean }) {
  const common = { className, stroke, fill, strokeDasharray: dash ? "5 3" : undefined };
  if (s.kind === "ellipse") return <ellipse {...common} cx={s.e.cx} cy={s.e.cy} rx={Math.max(s.e.rx, 0.25)} ry={Math.max(s.e.ry, 0.25)} />;
  if (s.kind === "polygon") return <polygon {...common} points={svgPoints(s.pts)} />;
  return <rect {...common} x={s.r.x0} y={s.r.y0} width={Math.max(rectWidth(s.r), 0.5)} height={Math.max(rectHeight(s.r), 0.5)} />;
}

function translateShape(s: DisplayShape, dx: number, dy: number): DisplayShape {
  const r = { x0: s.r.x0 + dx, y0: s.r.y0 + dy, x1: s.r.x1 + dx, y1: s.r.y1 + dy };
  if (s.kind === "ellipse") return { kind: "ellipse", r, e: ellipseFromRect(r) };
  if (s.kind === "polygon") return { kind: "polygon", r, pts: s.pts.map((p) => ({ x: p.x + dx, y: p.y + dy })) };
  return { kind: "rect", r };
}

export function PageOverlay(props: Props) {
  const { pw, ph, scale, matrix, items, tool, mode, focusedId, readOnly, hits, charBoxes, effectImage } = props;
  const m = useMeta();
  const svgRef = useRef<SVGSVGElement>(null);
  const [draft, setDraft] = useState<Draft>(null);
  const [shift, setShift] = useState(false);
  const [poly, setPolyState] = useState<{ pts: Point[]; cursor: Point | null } | null>(null);
  // mirror of `poly`, so quick successive clicks never work on a stale copy
  const polyRef = useRef<{ pts: Point[]; cursor: Point | null } | null>(null);
  const setPoly = (v: { pts: Point[]; cursor: Point | null } | null | ((p: { pts: Point[]; cursor: Point | null } | null) => { pts: Point[]; cursor: Point | null } | null)) => {
    const next = typeof v === "function" ? v(polyRef.current) : v;
    polyRef.current = next;
    setPolyState(next);
  };
  const [drag, setDrag] = useState<Drag | null>(null);
  const [textSel, setTextSel] = useState<{ a: number; b: number; done: boolean } | null>(null);
  const [hover, setHover] = useState<{ item: OverlayItem; x: number; y: number } | null>(null);
  const preview = mode === "preview";
  const locked = readOnly || preview;
  const inv = useMemo(() => invertMatrix(matrix), [matrix]);
  const unit = 1 / (scale || 1); // page units per screen px

  const shapes = useMemo(() => items.map((it) => ({ it, s: displayShape(it.det, it.box, matrix) })), [items, matrix]);

  // ---- coordinates ------------------------------------------------------------------------------------
  const measured = () => {
    const r = svgRef.current?.getBoundingClientRect();
    return r && r.width > 0 ? r.width / pw : scale;
  };
  const viewPt = (e: { clientX: number; clientY: number }): Point => {
    const r = svgRef.current!.getBoundingClientRect();
    return clientToView(e.clientX, e.clientY, r);
  };
  /** displayed page units */
  const dpu = (p: Point): Point => {
    const s = measured();
    return { x: p.x / s, y: p.y / s };
  };
  const pageSize = { width: pw, height: ph };

  const itemAt = (target: EventTarget | null): OverlayItem | null => {
    const el = (target as Element | null)?.closest?.("[data-key]");
    const key = el?.getAttribute("data-key");
    return key ? (items.find((i) => i.key === key) ?? null) : null;
  };

  // ---- polygon ----------------------------------------------------------------------------------------
  const finishPolygon = () => {
    const cur = polyRef.current;
    if (!cur || cur.pts.length < 3) {
      setPoly(null);
      return;
    }
    const s = measured();
    const pts = cur.pts;
    setPoly(null);
    if (polygonArea(pts) < 16) return; // a stray double-click, not a shape
    const pagePts = viewPolygonToPage(pts, s, matrix, pageSize);
    const xs = pagePts.map((p) => p[0]);
    const ys = pagePts.map((p) => p[1]);
    props.onCreate({
      kind: "polygon",
      points: pagePts,
      rect: { x0: Math.min(...xs), y0: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys) },
    });
  };

  useHotkeys(
    {
      Enter: (e) => {
        if (polyRef.current) {
          e.preventDefault();
          finishPolygon();
        } else if (textSel?.done) {
          e.preventDefault();
          confirmText();
        }
      },
      Escape: (e) => {
        e.preventDefault();
        setPoly(null);
        setDraft(null);
        setDrag(null);
        setTextSel(null);
      },
      Backspace: (e) => {
        if (polyRef.current) {
          e.preventDefault();
          setPoly((p) => (p && p.pts.length > 1 ? { ...p, pts: p.pts.slice(0, -1) } : null));
        }
      },
    },
    !!poly || !!draft || !!drag || !!textSel,
    { capture: true },
  );

  const confirmText = () => {
    if (!textSel) return;
    const start = Math.min(textSel.a, textSel.b);
    const end = Math.max(textSel.a, textSel.b) + 1;
    setTextSel(null);
    props.onTextRange(start, end);
  };

  // ---- pointer handling -------------------------------------------------------------------------------
  const onPointerDown = (e: RPointerEvent<SVGSVGElement>) => {
    if (e.button !== 0) return;
    const p = viewPt(e);
    setShift(e.shiftKey);
    if (tool === "rect" || tool === "ellipse") {
      if (readOnly) return;
      e.preventDefault();
      e.currentTarget.setPointerCapture(e.pointerId);
      setDraft({ kind: tool, a: p, b: p });
      return;
    }
    if (tool === "polygon") {
      if (readOnly) return;
      e.preventDefault();
      const cur = polyRef.current;
      if (!cur) {
        setPoly({ pts: [p], cursor: p });
        return;
      }
      if (closesPolygon(cur.pts, p, 8)) {
        finishPolygon();
        return;
      }
      const last = cur.pts[cur.pts.length - 1];
      if (Math.hypot(last.x - p.x, last.y - p.y) < 3) return; // second click of a double-click
      setPoly({ ...cur, pts: [...cur.pts, p] });
      return;
    }
    if (tool === "text") {
      if (readOnly || !charBoxes.length) return;
      e.preventDefault();
      e.currentTarget.setPointerCapture(e.pointerId);
      const i = charIndexAt(charBoxes, viewPointToPage(p, measured(), matrix), 14);
      setTextSel(i >= 0 ? { a: i, b: i, done: false } : null);
      return;
    }
    if (tool !== "select") return;
    const handle = (e.target as Element).getAttribute?.("data-handle") as Handle | null;
    const item = itemAt(e.target);
    if (!item) {
      props.onSelect(null);
      return;
    }
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    const s = shapes.find((x) => x.it.key === item.key)?.s ?? displayShape(item.det, item.box, matrix);
    setDrag({ item, start: p, cur: p, moved: false, handle, shape: s });
  };

  const onPointerMove = (e: RPointerEvent<SVGSVGElement>) => {
    if (draft) {
      setShift(e.shiftKey);
      setDraft({ ...draft, b: viewPt(e) });
    } else if (polyRef.current) {
      setPoly({ ...polyRef.current, cursor: viewPt(e) });
    } else if (drag) {
      const cur = viewPt(e);
      const moved = drag.moved || Math.hypot(cur.x - drag.start.x, cur.y - drag.start.y) > 3;
      setDrag({ ...drag, cur, moved });
      setHover(null);
    } else if (textSel && !textSel.done) {
      const i = charIndexAt(charBoxes, viewPointToPage(viewPt(e), measured(), matrix), 30);
      if (i >= 0 && i !== textSel.b) setTextSel({ ...textSel, b: i });
    }
  };

  const onPointerUp = (e: RPointerEvent<SVGSVGElement>) => {
    // use the release position itself: a fast drag can end before React has rendered the last move
    const end = viewPt(e);
    if (draft) {
      const b0 = Math.hypot(end.x - draft.a.x, end.y - draft.a.y) > 0 ? end : draft.b;
      const b = e.shiftKey ? constrainSquare(draft.a, b0) : b0;
      const vr = normalizeRect(draft.a, b);
      const kind = draft.kind;
      setDraft(null);
      if (rectWidth(vr) < MIN_DRAW_PX || rectHeight(vr) < MIN_DRAW_PX) return;
      props.onCreate({ kind, rect: viewDragToPageRect(draft.a, b, measured(), matrix, pageSize) });
      return;
    }
    if (drag) {
      const d = { ...drag, cur: end, moved: drag.moved || Math.hypot(end.x - drag.start.x, end.y - drag.start.y) > 3 };
      setDrag(null);
      if (!d.moved || !movable(d.item.det, locked)) {
        props.onSelect(d.item.det);
        return;
      }
      const s = measured();
      if (d.handle) {
        const r = resizeRect(d.shape.r, d.handle, dpu(d.cur), 2 * unit);
        props.onResize(d.item, transformRect(inv, r));
      } else {
        const a = viewPointToPage(d.start, s, matrix);
        const b = viewPointToPage(d.cur, s, matrix);
        props.onMove(d.item, b.x - a.x, b.y - a.y);
      }
      return;
    }
    if (textSel && !textSel.done) {
      const i = charIndexAt(charBoxes, viewPointToPage(end, measured(), matrix), 30);
      setTextSel({ ...textSel, b: i >= 0 ? i : textSel.b, done: true });
    }
  };

  const onDoubleClick = (e: React.MouseEvent<SVGSVGElement>) => {
    if (tool === "polygon") {
      e.preventDefault();
      finishPolygon();
      return;
    }
    if (tool === "select" && !locked) {
      const item = itemAt(e.target);
      if (item) props.onToggle(item.det);
    }
  };

  // ---- derived drawing --------------------------------------------------------------------------------
  const textRects = useMemo(() => {
    if (!textSel) return [];
    const a = Math.min(textSel.a, textSel.b);
    const b = Math.max(textSel.a, textSel.b) + 1;
    return lineRects(charBoxes, a, b).map((r) => transformRect(matrix, r));
  }, [textSel, charBoxes, matrix]);

  const draftShape = (() => {
    if (!draft) return null;
    const b = shift ? constrainSquare(draft.a, draft.b) : draft.b;
    const r = normalizeRect(dpu(draft.a), dpu(b));
    return draft.kind === "ellipse" ? ({ kind: "ellipse", r, e: ellipseFromRect(r) } as DisplayShape) : ({ kind: "rect", r } as DisplayShape);
  })();

  const dragShape = (() => {
    if (!drag || !drag.moved || !movable(drag.item.det, locked)) return null;
    if (drag.handle) {
      const r = resizeRect(drag.shape.r, drag.handle, dpu(drag.cur), 2 * unit);
      return drag.shape.kind === "ellipse" ? ({ kind: "ellipse", r, e: ellipseFromRect(r) } as DisplayShape) : ({ kind: "rect", r } as DisplayShape);
    }
    const a = dpu(drag.start);
    const b = dpu(drag.cur);
    return translateShape(drag.shape, b.x - a.x, b.y - a.y);
  })();

  const focusedShape = shapes.find((x) => x.it.det.id === focusedId);
  const baseFont = Math.max(pw, ph) / 80;
  const uid = useMemo(() => Math.random().toString(36).slice(2, 8), []);

  // ---- render -----------------------------------------------------------------------------------------
  const label = (d: Detection) => (typeof d.meta?.label_text === "string" && d.meta.label_text) || d.exemption || "";
  const effectOf = (d: Detection) => (typeof d.meta?.effect === "string" ? d.meta.effect : null);

  const renderItem = ({ it, s }: { it: OverlayItem; s: DisplayShape }): ReactNode => {
    const d = it.det;
    const color = m.color(d.entity);
    const focused = d.id === focusedId;
    const dragging = !!dragShape && drag?.item.key === it.key;
    if (preview) {
      if (!d.selected) return null;
      const eff = effectOf(d);
      const fill = Array.isArray(d.meta?.fill) ? (d.meta.fill as number[]) : null;
      if (effectImage && (eff === "blur" || eff === "pixelate")) {
        return (
          <g key={it.key} data-key={it.key} className="box box-preview">
            <clipPath id={`clip-${uid}-${it.key.replace(/[^a-z0-9]/gi, "")}`}>
              <ShapeEl s={s} />
            </clipPath>
            <image
              href={effectImage}
              x={0}
              y={0}
              width={pw}
              height={ph}
              preserveAspectRatio="none"
              clipPath={`url(#clip-${uid}-${it.key.replace(/[^a-z0-9]/gi, "")})`}
              filter={`url(#fx-${eff}-${uid})`}
            />
          </g>
        );
      }
      const solid = eff === "whiteout" ? "#fff" : fill ? rgbCss(fill) : "#000";
      const light = eff === "whiteout" || isLightFill(fill);
      const text = label(d);
      const rh = rectHeight(s.r);
      const rw = rectWidth(s.r);
      const fs = Math.max(unit * 6, Math.min(rh * 0.62, baseFont));
      const estW = text.length * fs * 0.56;
      return (
        <g key={it.key} data-key={it.key} className="box box-preview">
          <ShapeEl s={s} fill={solid} className="preview-fill" />
          {text && rh > unit * 7 && rw > unit * 14 && (
            <text
              x={(s.r.x0 + s.r.x1) / 2}
              y={(s.r.y0 + s.r.y1) / 2}
              fontSize={fs}
              className="box-label"
              fill={light ? "#111" : "#fff"}
              textAnchor="middle"
              dominantBaseline="central"
              textLength={estW > rw * 0.92 ? rw * 0.92 : undefined}
              lengthAdjust="spacingAndGlyphs"
            >
              {text}
            </text>
          )}
        </g>
      );
    }
    const picture = isPicture(d);
    const tag = picture ? (PICTURE_SHORT[pictureClass(d)] ?? m.entityLabel(pictureClass(d))) : null;
    return (
      <g
        key={it.key}
        data-key={it.key}
        className={`box ${d.selected ? "box-selected" : "box-suggested"} ${focused ? "box-focused" : ""} ${dragging ? "box-dragging" : ""} ${movable(d, locked) ? "box-movable" : ""}`}
        onPointerEnter={(e) => {
          if (drag || tool !== "select") return;
          const fr = svgRef.current?.getBoundingClientRect();
          if (fr) setHover({ item: it, x: e.clientX - fr.left, y: e.clientY - fr.top });
        }}
        onPointerLeave={() => setHover((h) => (h?.item.key === it.key ? null : h))}
      >
        <ShapeEl s={s} className="shape" stroke={color} dash={!d.selected} />
        {tag && (
          <g className="pic-tag" pointerEvents="none">
            <rect x={s.r.x0} y={s.r.y0} width={(tag.length * 6.2 + 10) * unit} height={15 * unit} fill={color} />
            <text x={s.r.x0 + 5 * unit} y={s.r.y0 + 11 * unit} fontSize={10 * unit} fill="#111">
              {tag}
            </text>
          </g>
        )}
      </g>
    );
  };

  const hoverDet = hover ? items.find((i) => i.key === hover.item.key)?.det ?? null : null;
  const viewW = pw * scale;
  const viewH = ph * scale;
  const fr = focusedShape?.s.r;

  return (
    <>
      <svg
        ref={svgRef}
        className={`overlay mode-${mode} tool-${tool}`}
        viewBox={`0 0 ${pw} ${ph}`}
        width={viewW}
        height={viewH}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onDoubleClick={onDoubleClick}
        onPointerLeave={() => {
          setHover(null);
          if (polyRef.current) setPoly({ ...polyRef.current, cursor: null });
        }}
        role="group"
        aria-label="Redaction boxes"
      >
        <defs>
          <filter id={`fx-blur-${uid}`} x="0" y="0" width={pw} height={ph} filterUnits="userSpaceOnUse">
            <feGaussianBlur stdDeviation={Math.max(4, Math.max(pw, ph) / 140)} />
          </filter>
          {(() => {
            const b = Math.max(6, Math.round(Math.max(pw, ph) / 90));
            return (
              <filter id={`fx-pixelate-${uid}`} x="0" y="0" width={pw} height={ph} filterUnits="userSpaceOnUse" primitiveUnits="userSpaceOnUse">
                <feFlood x={b / 2 - 1} y={b / 2 - 1} height={2} width={2} />
                <feComposite width={b} height={b} />
                <feTile result="a" />
                <feComposite in="SourceGraphic" in2="a" operator="in" />
                <feMorphology operator="dilate" radius={b / 2} />
              </filter>
            );
          })()}
        </defs>
        {hits.map((h, i) => (
          <rect key={`h${i}`} className="search-hit" x={h.x0} y={h.y0} width={rectWidth(h)} height={rectHeight(h)} />
        ))}
        {shapes.map(renderItem)}
        {!preview && focusedShape && !dragShape && (
          <g className="focus-layer" pointerEvents="none">
            <ShapeEl s={focusedShape.s} className="focus-ring" />
          </g>
        )}
        {!preview && focusedShape && !dragShape && tool === "select" && movable(focusedShape.it.det, locked) && focusedShape.s.kind !== "polygon" && (
          <g className="handles">
            {HANDLES.map((h) => {
              const p = handlePoint(focusedShape.s.r, h);
              const sz = 8 * unit;
              return (
                <rect
                  key={h}
                  data-key={focusedShape.it.key}
                  data-handle={h}
                  className={`handle handle-${h}`}
                  x={p.x - sz / 2}
                  y={p.y - sz / 2}
                  width={sz}
                  height={sz}
                />
              );
            })}
          </g>
        )}
        {dragShape && <ShapeEl s={dragShape} className="drag-ghost" />}
        {textRects.map((r, i) => (
          <rect key={`ts${i}`} className="text-sel" x={r.x0} y={r.y0} width={rectWidth(r)} height={rectHeight(r)} />
        ))}
        {draftShape && <ShapeEl s={draftShape} className="draw-shape" />}
        {poly && (
          <g className="poly-draft" pointerEvents="none">
            <polyline points={svgPoints([...poly.pts, ...(poly.cursor ? [poly.cursor] : [])].map(dpu))} className="draw-shape open" />
            {poly.pts.map((p, i) => {
              const q = dpu(p);
              return <circle key={i} cx={q.x} cy={q.y} r={(i === 0 && poly.pts.length >= 3 ? 5 : 3.5) * unit} className={i === 0 ? "vertex first" : "vertex"} />;
            })}
          </g>
        )}
      </svg>
      {hover && hoverDet && tool === "select" && !drag && !preview && (
        <div
          className="box-tooltip"
          role="tooltip"
          style={{ left: Math.min(hover.x + 14, viewW - 260), top: Math.min(hover.y + 18, Math.max(0, viewH - 140)) }}
        >
          <div className="row gap-sm">
            <span className="cat-dot" style={{ background: m.color(hoverDet.entity) }} aria-hidden />
            <strong>{m.entityLabel(hoverDet.entity)}</strong>
            <span className={`badge tiny ${hoverDet.selected ? "badge-dark" : "badge-outline"}`}>{hoverDet.selected ? "Redacting" : "Suggestion"}</span>
          </div>
          <div className="small">
            {percent(hoverDet.score)} confidence · {detectorLabel(hoverDet.source)}
          </div>
          {hoverDet.exemption && (
            <div className="small">
              <span className="mono">{hoverDet.exemption}</span> {truncate(m.meta?.exemption_codes[hoverDet.exemption] ?? "", 60)}
            </div>
          )}
          {hoverDet.explanation && <div className="small muted">{truncate(hoverDet.explanation, 140)}</div>}
          <div className="tiny muted">Click to select · double-click to {hoverDet.selected ? "un-redact" : "redact"}</div>
        </div>
      )}
      {!preview && !readOnly && focusedShape && fr && tool === "select" && !drag && (
        <div
          className="box-actions"
          style={{
            left: Math.max(0, Math.min(fr.x0 * scale, viewW - 200)),
            top: fr.y0 * scale > 40 ? fr.y0 * scale - 36 : Math.min(fr.y1 * scale + 6, viewH - 34),
          }}
          onPointerDown={(e) => e.stopPropagation()}
        >
          <button
            className={`btn btn-xs ${focusedShape.it.det.selected ? "" : "btn-primary"}`}
            onClick={() => props.onToggle(focusedShape.it.det)}
            data-tip={focusedShape.it.det.selected ? "Keep visible (Enter)" : "Redact (Enter)"}
          >
            {focusedShape.it.det.selected ? <X size={12} aria-hidden /> : <Check size={12} aria-hidden />}
            {focusedShape.it.det.selected ? "Un-redact" : "Redact"}
          </button>
          <button className="icon-btn sm danger" aria-label="Delete redaction" data-tip="Delete (Del)" onClick={() => props.onDelete(focusedShape.it.det)}>
            <Trash2 size={13} />
          </button>
        </div>
      )}
      {textSel?.done && textRects.length > 0 && (
        <div
          className="float-bar"
          style={{
            left: Math.max(0, Math.min(textRects[textRects.length - 1].x0 * scale, viewW - 280)),
            top: Math.min(textRects[textRects.length - 1].y1 * scale + 6, viewH - 40),
          }}
          onPointerDown={(e) => e.stopPropagation()}
        >
          <span className="small">
            {Math.abs(textSel.b - textSel.a) + 1} characters as <strong>{props.markAsLabel}</strong>
          </span>
          <button
            className="btn btn-xs btn-primary"
            onClick={confirmText}
          >
            Redact
          </button>
          <button className="btn btn-xs" onClick={() => setTextSel(null)}>
            Cancel
          </button>
        </div>
      )}
      {poly && (
        <div className="draw-hint" role="status">
          {poly.pts.length < 3
            ? `Polygon: ${poly.pts.length} point${poly.pts.length === 1 ? "" : "s"} — keep clicking`
            : `${poly.pts.length} points — double-click, Enter or click the first point to close`}{" "}
          · ⌫ undo point · Esc cancel
        </div>
      )}
    </>
  );
}
