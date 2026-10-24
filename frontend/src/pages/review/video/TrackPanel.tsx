import { useEffect, useState, type ReactNode } from "react";
import { Circle, Film, Scissors, Square, Trash2, X } from "lucide-react";
import { EmptyState, SkeletonList, Switch } from "../../../components/ui";
import { formatTimecode, percent, titleCase } from "../../../lib/format";
import type { Track } from "../../../types";
import type { TrackOps } from "./useTracks";
import { isFullFrame, TRACK_EFFECTS, trackColor, trackShape, type TrackEffect } from "./trackUtils";
import { ShapeToggle } from "./AddTrackCard";

interface Props {
  tracks: Track[] | null;
  selectedId: number | null;
  onSelect: (t: Track | null, frame?: number) => void;
  ops: TrackOps;
  fps: number;
  frame: number;
  seekFrame: (f: number) => void;
  chips?: ReactNode;
  hasTracks: boolean;
  readOnly: boolean;
}

function ShapeIcon({ t }: { t: Track }) {
  if (isFullFrame(t)) return <Film size={12} aria-hidden />;
  return trackShape(t) === "ellipse" ? <Circle size={12} aria-hidden /> : <Square size={12} aria-hidden />;
}

export function TrackPanel({ tracks, selectedId, onSelect, ops, fps, frame, seekFrame, chips, hasTracks, readOnly }: Props) {
  const list = tracks ?? [];
  const sel = list.find((t) => t.id === selectedId) ?? null;
  const [renaming, setRenaming] = useState("");
  useEffect(() => setRenaming(sel?.label ?? ""), [sel?.id, sel?.label]);
  const enabledCount = list.filter((t) => t.enabled).length;

  return (
    <section className="det-panel" aria-label="Visual tracks">
      <div className="det-panel-head">
        <div className="row space">
          <h2>Visual tracks</h2>
          <span className="small muted">
            <strong className="text">{enabledCount}</strong> of {list.length} redacted
          </span>
        </div>
        {chips && <div className="chips">{chips}</div>}
        <p className="small muted">Solid boxes are redacted in the export; dashed ones stay visible (e.g. an officer who may be shown).</p>
      </div>
      {sel && (
        <div className="track-inspector">
          <div className="row gap-sm">
            <span className="cat-dot" style={{ background: trackColor(sel.label) }} aria-hidden />
            <strong className="truncate">
              {isFullFrame(sel) ? "Full-frame effect" : titleCase(sel.label)} #{sel.id}
            </strong>
            <span className="toolbar-spacer" />
            <button className="icon-btn sm" onClick={() => onSelect(null)} aria-label="Close track details">
              <X size={14} />
            </button>
          </div>
          <div className="small muted">
            Frames {sel.first}–{sel.last} ({formatTimecode(sel.first / fps)}–{formatTimecode(sel.last / fps)}) · score {percent(sel.max_score)} ·{" "}
            {sel.source}
          </div>
          {readOnly ? (
            <div className="track-facts">
              <span className="badge badge-neutral">
                <ShapeIcon t={sel} /> {isFullFrame(sel) ? "whole frame" : trackShape(sel)}
              </span>
              <span className="badge badge-neutral">effect: {sel.effect ?? "export setting"}</span>
            </div>
          ) : (
            <div className="row gap-sm wrap track-edit">
              <label className="small row gap-sm">
                Effect
                <select
                  className="select-sm"
                  value={sel.effect ?? ""}
                  onChange={(e) => ops.setEffect(sel, (e.target.value || null) as TrackEffect | null)}
                  aria-label="Effect for this track"
                >
                  <option value="">Export setting</option>
                  {TRACK_EFFECTS.map((ef) => (
                    <option key={ef} value={ef}>
                      {titleCase(ef)}
                    </option>
                  ))}
                </select>
              </label>
              {isFullFrame(sel) ? (
                <span className="badge badge-neutral">
                  <Film size={12} aria-hidden /> whole frame
                </span>
              ) : (
                <ShapeToggle shape={trackShape(sel)} onChange={(sh) => ops.setShape(sel, sh)} />
              )}
            </div>
          )}
          <Switch
            checked={sel.enabled}
            disabled={readOnly}
            onChange={(v) => ops.setEnabled(sel, v)}
            label={<span className="small">Redact this track</span>}
            hint="Off = keep it visible in the export"
          />
          {!readOnly && (
            <>
              <div className="row gap-sm">
                <input className="input-sm grow" aria-label="Track label" value={renaming} onChange={(e) => setRenaming(e.target.value)} />
                <button className="btn btn-xs" disabled={!renaming.trim() || renaming === sel.label} onClick={() => ops.rename(sel, renaming.trim())}>
                  Rename
                </button>
              </div>
              <div className="row gap-sm wrap">
                <button className="btn btn-xs" onClick={() => seekFrame(sel.first)}>
                  Go to start
                </button>
                <button className="btn btn-xs" onClick={() => seekFrame(sel.last)}>
                  Go to end
                </button>
                <button
                  className="btn btn-xs"
                  disabled={frame <= sel.first || frame > sel.last}
                  onClick={() => ops.trim(sel, { trim_start: frame })}
                  data-tip="Remove the boxes before the current frame"
                >
                  <Scissors size={12} aria-hidden /> Trim start
                </button>
                <button
                  className="btn btn-xs"
                  disabled={frame < sel.first || frame >= sel.last}
                  onClick={() => ops.trim(sel, { trim_end: frame })}
                  data-tip="Remove the boxes after the current frame"
                >
                  <Scissors size={12} aria-hidden /> Trim end
                </button>
                <button
                  className="btn btn-xs btn-danger-ghost"
                  onClick={() => {
                    ops.remove(sel);
                    onSelect(null);
                  }}
                >
                  <Trash2 size={12} aria-hidden /> Delete
                </button>
              </div>
            </>
          )}
        </div>
      )}
      <div className="det-list">
        {tracks === null && <SkeletonList rows={6} label="Loading tracks" />}
        {tracks !== null && list.length === 0 && (
          <EmptyState compact title="No tracks">
            {hasTracks ? "All tracks were removed." : "Analyze the video to detect faces, heads and plates, or add a redaction."}
          </EmptyState>
        )}
        <ul className="track-list">
          {list.map((t) => (
            <li key={t.id} className={`track-item ${t.id === selectedId ? "is-focused" : ""}`}>
              <input
                type="checkbox"
                checked={t.enabled}
                disabled={readOnly}
                onChange={(e) => ops.setEnabled(t, e.target.checked)}
                aria-label={`Redact ${t.label} #${t.id}`}
              />
              <button className="det-main" onClick={() => onSelect(t, t.first)}>
                <span className="det-line1">
                  <span
                    className={`det-swatch ${t.enabled ? "filled" : "dashed"} ${trackShape(t) === "ellipse" ? "round" : ""}`}
                    style={{ borderColor: trackColor(t.label), background: t.enabled ? trackColor(t.label) : "transparent" }}
                    aria-hidden
                  />
                  <span className="det-text">
                    {isFullFrame(t) ? "Full frame" : titleCase(t.label)} #{t.id}
                  </span>
                  <span className="det-loc muted mono">
                    {formatTimecode(t.first / fps)}–{formatTimecode(t.last / fps)}
                  </span>
                </span>
                <span className="det-line2">
                  {!t.enabled && <span className="badge badge-outline tiny">visible</span>}
                  {t.source?.startsWith("manual") && <span className="badge badge-info tiny">manual</span>}
                  {t.effect && <span className="badge badge-neutral tiny">{t.effect}</span>}
                  {trackShape(t) === "ellipse" && !isFullFrame(t) && <span className="badge badge-neutral tiny">ellipse</span>}
                  <span>{t.last - t.first + 1} frames</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
