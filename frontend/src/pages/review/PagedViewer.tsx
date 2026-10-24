import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent } from "react";
import { ChevronLeft, ChevronRight, Eye, EyeOff, Maximize2, MoveHorizontal, PencilLine, ZoomIn, ZoomOut } from "lucide-react";
import * as api from "../../api";
import { useMeta } from "../../meta";
import { Spinner } from "../../components/ui";
import { useHotkeys, useKeyHeld } from "../../lib/hotkeys";
import { percent } from "../../lib/format";
import { chooseDpi, clampRect, fitScale, nextZoom, toMatrix, transformRect, type Rect } from "../../lib/geometry";
import { detectionPoints, detectionShape, translatePolygon, translateRect } from "../../lib/shapes";
import type { Detection, FileRecord, ManualDetectionIn, PageInfo, PageText } from "../../types";
import type { DetectionOps } from "./useDetections";
import { PageOverlay, type NewShape, type OverlayItem } from "./PageOverlay";
import { pageCounts, Thumbs } from "./Thumbs";
import { TOOL_HINTS, ToolPalette } from "./ToolPalette";
import { TOOL_KEYS, type FocusRequest, type Tool, type ViewMode } from "./workspace";

export type { FocusRequest } from "./workspace";

/** Settings applied to new shapes (edited in the properties panel while nothing is selected). */
export interface DrawDefaults {
  entity: string;
  exemption: string;
  effect: string;
  fill: [number, number, number] | null;
  label_text: string;
}

type ZoomState = { mode: "width" } | { mode: "page" } | { mode: "custom"; pct: number };

interface Props {
  file: FileRecord;
  pages: PageInfo[];
  page: number;
  setPage: (n: number) => void;
  dets: Detection[];
  ops: DetectionOps;
  focus: FocusRequest | null;
  onFocus: (d: Detection | null, source: "viewer") => void;
  mode: ViewMode;
  setMode: (m: ViewMode) => void;
  showSuggestions: boolean;
  setShowSuggestions: (v: boolean) => void;
  searchMatches: Detection[];
  analyzed: boolean;
  readOnly: boolean;
  defaults: DrawDefaults;
}

const MIN_PCT = 0.1;
const MAX_PCT = 6;

export function PagedViewer({
  file,
  pages,
  page,
  setPage,
  dets,
  ops,
  focus,
  onFocus,
  mode,
  setMode,
  showSuggestions,
  setShowSuggestions,
  searchMatches,
  analyzed,
  readOnly,
  defaults,
}: Props) {
  const m = useMeta();
  const isImage = file.kind === "image";
  const [zoom, setZoom] = useState<ZoomState>({ mode: "width" });
  const [tool, setToolState] = useState<Tool>("select");
  const [spacePan, setSpacePan] = useState(false);
  const [panning, setPanning] = useState(false);
  const [container, setContainer] = useState({ w: 800, h: 600 });
  const [loadedUrl, setLoadedUrl] = useState<string | null>(null);
  const [imgError, setImgError] = useState(false);
  const [texts, setTexts] = useState<Record<number, PageText | { error: string }>>({});
  const scrollRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const pendingScroll = useRef<string | null>(null);
  const zoomAnchor = useRef<{ px: number; py: number; ox: number; oy: number } | null>(null);
  const panRef = useRef<{ x: number; y: number; sl: number; st: number; id: number } | null>(null);

  const info = pages.find((p) => p.page === page) ?? pages[0];
  const pw = info?.width || 1;
  const ph = info?.height || 1;
  const matrix = useMemo(() => toMatrix(info?.matrix), [info]);
  const base = isImage ? 1 : 96 / 72;
  const textDisabled = isImage ? "not available for images" : !analyzed ? "analyze the file first" : undefined;

  const setTool = useCallback(
    (t: Tool) => {
      if (readOnly && t !== "select" && t !== "pan") return;
      if (t === "text" && textDisabled) return;
      setToolState(t);
    },
    [readOnly, textDisabled],
  );
  useKeyHeld(" ", setSpacePan);
  const effTool: Tool = spacePan ? "pan" : tool;

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setContainer({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setContainer({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  const scale =
    zoom.mode === "custom" ? zoom.pct * base : fitScale(pw, ph, container.w, container.h, zoom.mode === "width" ? "width" : "page", 24);
  const pct = scale / base;
  const dpi = isImage ? 110 : chooseDpi(scale, window.devicePixelRatio || 1);
  const url = api.urls.pageImage(file.id, page, dpi);
  const viewW = pw * scale;
  const viewH = ph * scale;

  useEffect(() => setImgError(false), [url]);

  const zoomTo = useCallback(
    (nextPct: number, anchor?: { clientX: number; clientY: number }) => {
      const p = Math.min(MAX_PCT, Math.max(MIN_PCT, nextPct));
      const sc = scrollRef.current;
      const fr = frameRef.current;
      if (sc && fr) {
        const sr = sc.getBoundingClientRect();
        const ox = anchor ? anchor.clientX - sr.left : sc.clientWidth / 2;
        const oy = anchor ? anchor.clientY - sr.top : sc.clientHeight / 2;
        // page point under the anchor, so it stays there after the zoom
        zoomAnchor.current = { px: (sc.scrollLeft + ox - fr.offsetLeft) / scale, py: (sc.scrollTop + oy - fr.offsetTop) / scale, ox, oy };
      }
      setZoom({ mode: "custom", pct: p });
    },
    [scale],
  );

  useLayoutEffect(() => {
    const a = zoomAnchor.current;
    const sc = scrollRef.current;
    const fr = frameRef.current;
    if (!a || !sc || !fr) return;
    zoomAnchor.current = null;
    sc.scrollLeft = fr.offsetLeft + a.px * scale - a.ox;
    sc.scrollTop = fr.offsetTop + a.py * scale - a.oy;
  }, [scale]);

  // Ctrl / ⌘ + wheel zooms at the pointer (non-passive listener, so the browser zoom is suppressed)
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      const factor = Math.exp(-Math.max(-60, Math.min(60, e.deltaY)) * 0.006);
      zoomTo(pct * factor, e);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [pct, zoomTo]);

  const counts = useMemo(() => pageCounts(dets), [dets]);

  const items = useMemo(() => {
    const out: OverlayItem[] = [];
    for (const d of dets) {
      if (!d.selected && (!showSuggestions || mode === "preview")) continue;
      d.boxes.forEach((b, i) => {
        if (b.page === page) out.push({ det: d, box: b, index: i, key: `${d.id}:${i}` });
      });
    }
    // suggestions under selected boxes, the focused one on top
    return out.sort((a, b) => Number(a.det.selected) - Number(b.det.selected) || Number(a.det.id === focus?.id) - Number(b.det.id === focus?.id));
  }, [dets, page, showSuggestions, mode, focus?.id]);

  const hits = useMemo(
    () => searchMatches.flatMap((d) => d.boxes.filter((b) => b.page === page).map((b) => transformRect(matrix, b))),
    [searchMatches, page, matrix],
  );

  const goto = useCallback(
    (n: number) => {
      const max = pages.length - 1;
      setPage(Math.max(0, Math.min(max, n)));
    },
    [pages.length, setPage],
  );

  // ---- focus requests from the panel: go to the page, then scroll (and zoom) the box into view -------
  useEffect(() => {
    if (!focus) return;
    const d = dets.find((x) => x.id === focus.id);
    if (!d) return;
    const p = d.boxes[0]?.page ?? d.page;
    if (focus.source === "panel") pendingScroll.current = d.id;
    if (p !== page && p >= 0 && p < pages.length) goto(p);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus?.nonce]);

  useEffect(() => {
    const id = pendingScroll.current;
    if (!id || !scrollRef.current || !frameRef.current) return;
    const d = dets.find((x) => x.id === id);
    const b = d?.boxes.find((x) => x.page === page);
    if (!b) return;
    const r = transformRect(matrix, b);
    // tiny boxes (a date, initials) are hard to see at "fit page": zoom in a little
    if ((r.y1 - r.y0) * scale < 9 && pct < 1.5) {
      setZoom({ mode: "custom", pct: 1.5 });
      return;
    }
    pendingScroll.current = null;
    const sc = scrollRef.current;
    const cx = frameRef.current.offsetLeft + ((r.x0 + r.x1) / 2) * scale;
    const cy = frameRef.current.offsetTop + ((r.y0 + r.y1) / 2) * scale;
    sc.scrollTo({ left: Math.max(0, cx - sc.clientWidth / 2), top: Math.max(0, cy - sc.clientHeight / 2), behavior: "smooth" });
  }, [page, scale, dets, matrix, focus?.nonce, pct]);

  // ---- text layer (text tool) ------------------------------------------------------------------------
  useEffect(() => {
    if (tool !== "text" || texts[page] || !analyzed) return;
    let alive = true;
    api.getPageText(file.id, page).then(
      (t) => alive && setTexts((x) => ({ ...x, [page]: t })),
      (e) => alive && setTexts((x) => ({ ...x, [page]: { error: e instanceof Error ? e.message : "no text" } })),
    );
    return () => {
      alive = false;
    };
  }, [tool, page, file.id, texts, analyzed]);
  const pageText = texts[page];
  const charBoxes = pageText && "boxes" in pageText ? (pageText.boxes ?? []) : [];

  // ---- edits from the overlay ------------------------------------------------------------------------
  const swapped = Math.abs(matrix[1]) > 0.5 && Math.abs(matrix[2]) > 0.5;
  const unrot = { w: swapped ? ph : pw, h: swapped ? pw : ph };

  const newBody = (extra: ManualDetectionIn): ManualDetectionIn => {
    const body: ManualDetectionIn = { entity: defaults.entity, page, ...extra };
    if (defaults.exemption) body.exemption = defaults.exemption;
    if (defaults.label_text.trim()) body.label_text = defaults.label_text.trim();
    if (defaults.fill) body.fill = defaults.fill;
    if (isImage && defaults.effect) body.effect = defaults.effect as ManualDetectionIn["effect"];
    return body;
  };

  const onCreate = async (s: NewShape) => {
    const box = { x0: s.rect.x0, y0: s.rect.y0, x1: s.rect.x1, y1: s.rect.y1 };
    const body =
      s.kind === "polygon"
        ? newBody({ boxes: [box], shape: "polygon", points: s.points })
        : newBody({ boxes: [box], ...(s.kind === "ellipse" ? { shape: "ellipse" as const } : {}) });
    const d = await ops.add(body, s.kind === "rect" ? "Add rectangle" : s.kind === "ellipse" ? "Add ellipse" : "Add polygon");
    if (d) onFocus(d, "viewer");
  };

  const clampBox = (r: Rect): Rect => {
    // keep the size; slide back inside the page
    const w = r.x1 - r.x0;
    const h = r.y1 - r.y0;
    const x0 = Math.min(Math.max(r.x0, 0), Math.max(0, unrot.w - w));
    const y0 = Math.min(Math.max(r.y0, 0), Math.max(0, unrot.h - h));
    return { x0, y0, x1: x0 + w, y1: y0 + h };
  };

  const onMove = (it: OverlayItem, dx: number, dy: number) => {
    const d = it.det;
    const moved = clampBox(translateRect(it.box, dx, dy));
    const ddx = moved.x0 - it.box.x0;
    const ddy = moved.y0 - it.box.y0;
    if (Math.abs(ddx) < 0.01 && Math.abs(ddy) < 0.01) return;
    if (detectionShape(d) === "polygon") {
      const pts = detectionPoints(d);
      if (pts) {
        // the server moves the polygon's locating box with its points
        void ops.edit(d.id, { points: translatePolygon(pts, ddx, ddy) }, "Move polygon");
        return;
      }
    }
    const boxes = d.boxes.map((b, i) => (i === it.index ? { ...b, ...round(moved) } : b));
    ops.update(d.id, { boxes }, "Move");
  };

  const onResize = (it: OverlayItem, r: Rect) => {
    const c = clampRect(r, unrot.w, unrot.h);
    if (c.x1 - c.x0 < 1 || c.y1 - c.y0 < 1) return;
    const boxes = it.det.boxes.map((b, i) => (i === it.index ? { ...b, ...round(c) } : b));
    ops.update(it.det.id, { boxes }, "Resize");
  };

  const onTextRange = async (start: number, end: number) => {
    const body: ManualDetectionIn = { entity: defaults.entity, page, start, end };
    if (defaults.exemption) body.exemption = defaults.exemption;
    const d = await ops.add(body, "Redact selected text");
    if (d) onFocus(d, "viewer");
  };

  const focusedDet = focus ? (dets.find((d) => d.id === focus.id) ?? null) : null;

  // ---- panning (hand tool / Space) -------------------------------------------------------------------
  const onPanDown = (e: RPointerEvent<HTMLDivElement>) => {
    if (effTool !== "pan" || e.button !== 0) return;
    const sc = scrollRef.current;
    if (!sc) return;
    e.preventDefault();
    sc.setPointerCapture(e.pointerId);
    panRef.current = { x: e.clientX, y: e.clientY, sl: sc.scrollLeft, st: sc.scrollTop, id: e.pointerId };
    setPanning(true);
  };
  const onPanMove = (e: RPointerEvent<HTMLDivElement>) => {
    const p = panRef.current;
    const sc = scrollRef.current;
    if (!p || !sc) return;
    sc.scrollLeft = p.sl - (e.clientX - p.x);
    sc.scrollTop = p.st - (e.clientY - p.y);
  };
  const onPanUp = () => {
    panRef.current = null;
    setPanning(false);
  };

  // ---- shortcuts ---------------------------------------------------------------------------------------
  const toolKeys = Object.fromEntries(Object.entries(TOOL_KEYS).map(([k, t]) => [k, () => setTool(t)]));
  useHotkeys({
    ...toolKeys,
    ArrowLeft: (e) => {
      e.preventDefault();
      goto(page - 1);
    },
    ArrowRight: (e) => {
      e.preventDefault();
      goto(page + 1);
    },
    PageUp: () => goto(page - 1),
    PageDown: () => goto(page + 1),
    Home: () => goto(0),
    End: () => goto(pages.length - 1),
    Escape: () => {
      if (focusedDet) onFocus(null, "viewer");
      else setTool("select");
    },
    Enter: (e) => {
      if (focusedDet && !readOnly) {
        e.preventDefault();
        ops.toggle(focusedDet.id);
      }
    },
    Delete: () => focusedDet && !readOnly && ops.remove(focusedDet.id),
    Backspace: (e) => {
      if (focusedDet && !readOnly) {
        e.preventDefault();
        ops.remove(focusedDet.id);
      }
    },
    p: () => setMode(mode === "preview" ? "edit" : "preview"),
    s: () => setShowSuggestions(!showSuggestions),
    "+": () => zoomTo(nextZoom(pct, 1)),
    "=": () => zoomTo(nextZoom(pct, 1)),
    "-": () => zoomTo(nextZoom(pct, -1)),
    "0": () => setZoom({ mode: "width" }),
    f: () => setZoom({ mode: "page" }),
  });

  const loaded = loadedUrl === url;
  const textUnavailable = tool === "text" && (!analyzed || (pageText && "error" in pageText) || (pageText && "boxes" in pageText && !charBoxes.length));
  const pageCount = counts.get(page);

  return (
    <div className="paged-viewer">
      {pages.length > 1 && <Thumbs fileId={file.id} pages={pages} current={page} onSelect={goto} counts={counts} />}
      {!readOnly && (
        <ToolPalette
          tool={effTool}
          onChange={setTool}
          disabled={textDisabled ? { text: textDisabled } : {}}
          hidden={isImage ? ["text"] : []}
        />
      )}
      <div className="viewer-col">
        <div className="viewer-toolbar" role="toolbar" aria-label="Viewer">
          <div className="seg seg-sm" role="radiogroup" aria-label="View mode">
            <button
              type="button"
              role="radio"
              aria-checked={mode === "edit"}
              className={`seg-item ${mode === "edit" ? "active" : ""}`}
              onClick={() => setMode("edit")}
              data-tip="Boxes outlined and see-through, so the content stays readable (P)"
            >
              <PencilLine size={14} aria-hidden /> Edit
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={mode === "preview"}
              className={`seg-item ${mode === "preview" ? "active" : ""}`}
              onClick={() => setMode("preview")}
              data-tip="Solid boxes with labels, as in the export (P)"
            >
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
          <div className="tool-group" aria-label="Zoom">
            <button className="icon-btn" onClick={() => zoomTo(nextZoom(pct, -1))} aria-label="Zoom out" data-tip="Zoom out (−)">
              <ZoomOut size={16} />
            </button>
            <button className="zoom-label mono small" onClick={() => setZoom({ mode: "custom", pct: 1 })} data-tip="Actual size" aria-label={`Zoom ${percent(pct)}, reset to 100%`}>
              {percent(pct)}
            </button>
            <button className="icon-btn" onClick={() => zoomTo(nextZoom(pct, 1))} aria-label="Zoom in" data-tip="Zoom in (+)">
              <ZoomIn size={16} />
            </button>
            <button
              className={`icon-btn ${zoom.mode === "width" ? "active" : ""}`}
              onClick={() => setZoom({ mode: "width" })}
              aria-label="Fit width"
              aria-pressed={zoom.mode === "width"}
              data-tip="Fit width (0)"
            >
              <MoveHorizontal size={16} />
            </button>
            <button
              className={`icon-btn ${zoom.mode === "page" ? "active" : ""}`}
              onClick={() => setZoom({ mode: "page" })}
              aria-label="Fit page"
              aria-pressed={zoom.mode === "page"}
              data-tip="Fit page (F)"
            >
              <Maximize2 size={16} />
            </button>
          </div>
          {pages.length > 1 && (
            <div className="tool-group page-nav" aria-label="Page navigation">
              <button className="icon-btn" onClick={() => goto(page - 1)} disabled={page <= 0} aria-label="Previous page" data-tip="Previous page (←)">
                <ChevronLeft size={16} />
              </button>
              <label className="small row gap-xs">
                <span className="sr-only">Go to page</span>
                <input
                  className="page-input"
                  type="number"
                  min={1}
                  max={pages.length}
                  value={page + 1}
                  onChange={(e) => {
                    const v = Number(e.target.value);
                    if (v >= 1 && v <= pages.length) goto(v - 1);
                  }}
                />
                <span className="muted">of {pages.length}</span>
              </label>
              <button
                className="icon-btn"
                onClick={() => goto(page + 1)}
                disabled={page >= pages.length - 1}
                aria-label="Next page"
                data-tip="Next page (→)"
              >
                <ChevronRight size={16} />
              </button>
            </div>
          )}
        </div>
        <div
          className={`viewer-scroll tool-${effTool} ${panning ? "panning" : ""}`}
          ref={scrollRef}
          onPointerDown={onPanDown}
          onPointerMove={onPanMove}
          onPointerUp={onPanUp}
          onPointerCancel={onPanUp}
        >
          <div className="page-frame" ref={frameRef} style={{ width: viewW, height: viewH }}>
            <img
              key={url}
              src={url}
              width={viewW}
              height={viewH}
              alt={`Page ${page + 1} of ${file.name}`}
              draggable={false}
              onLoad={() => setLoadedUrl(url)}
              onError={() => setImgError(true)}
              className="page-img"
            />
            {!loaded && !imgError && (
              <div className="page-loading">
                <span className="skeleton skeleton-page" aria-hidden />
                <Spinner size={22} label="Rendering page" />
              </div>
            )}
            {imgError && <div className="page-loading text-bad">This page could not be rendered.</div>}
            <PageOverlay
              pw={pw}
              ph={ph}
              scale={scale}
              matrix={matrix}
              items={items}
              tool={effTool}
              mode={mode}
              focusedId={focus?.id ?? null}
              readOnly={readOnly}
              hits={hits}
              charBoxes={charBoxes}
              effectImage={isImage ? url : null}
              markAsLabel={m.entityLabel(defaults.entity)}
              onSelect={(d) => onFocus(d, "viewer")}
              onToggle={(d) => ops.toggle(d.id)}
              onDelete={(d) => ops.remove(d.id)}
              onCreate={onCreate}
              onMove={onMove}
              onResize={onResize}
              onTextRange={onTextRange}
            />
          </div>
        </div>
        <div className="viewer-status small">
          <span className="status-tool" role="status">
            {effTool === "text" && textUnavailable
              ? !analyzed
                ? "Analyze the file to enable text selection"
                : "No selectable text on this page"
              : TOOL_HINTS[effTool]}
            {effTool !== "select" && effTool !== "pan" && !readOnly && (
              <>
                {" "}
                · new: <strong>{m.entityLabel(defaults.entity)}</strong>
              </>
            )}
          </span>
          <span className="toolbar-spacer" />
          {(info?.source === "ocr" || info?.source === "hybrid") && (
            <span className="muted">
              Text from {info.source.toUpperCase()}
              {info.ocr_conf ? ` (${Math.round(info.ocr_conf)}% confidence)` : ""}
            </span>
          )}
          <span className="muted">
            <strong className="text">{pageCount?.sel ?? 0}</strong> redacted
            {pageCount?.sug ? ` · ${pageCount.sug} suggested` : ""} on this page
          </span>
          <span className="muted mono">
            {pw.toFixed(0)}×{ph.toFixed(0)} {isImage ? "px" : "pt"}
          </span>
        </div>
      </div>
    </div>
  );
}

function round(r: Rect): Rect {
  const f = (v: number) => Math.round(v * 100) / 100;
  return { x0: f(r.x0), y0: f(r.y0), x1: f(r.x1), y1: f(r.y1) };
}
