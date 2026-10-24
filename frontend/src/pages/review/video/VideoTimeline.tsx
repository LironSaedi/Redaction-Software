import { memo, type RefObject } from "react";
import { Circle, Film } from "lucide-react";
import { formatTimecode } from "../../../lib/format";
import type { Track } from "../../../types";
import { isFullFrame, trackColor, trackShape } from "./trackUtils";

interface Props {
  tracks: Track[];
  runs: Map<number, [number, number][]>;
  frames: number;
  fps: number;
  selectedId: number | null;
  onSelect: (t: Track, frame?: number) => void;
  seekFrame: (f: number) => void;
  playheadRef: RefObject<HTMLDivElement>;
  inPoint: number | null;
  outPoint: number | null;
  loading: boolean;
  emptyText: string;
}

export const VideoTimeline = memo(function VideoTimeline({
  tracks,
  runs,
  frames,
  fps,
  selectedId,
  onSelect,
  seekFrame,
  playheadRef,
  inPoint,
  outPoint,
  loading,
  emptyText,
}: Props) {
  const span = Math.max(1, frames - 1);
  const pctOf = (f: number) => `${(f / span) * 100}%`;
  const seekAt = (e: React.MouseEvent<HTMLElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    seekFrame(((e.clientX - r.left) / r.width) * span);
  };
  const lo = inPoint != null && outPoint != null ? Math.min(inPoint, outPoint) : null;
  const hi = inPoint != null && outPoint != null ? Math.max(inPoint, outPoint) : null;
  const enabled = tracks.filter((t) => t.enabled).length;

  return (
    <div className="timeline" aria-label="Track timeline">
      <div className="timeline-head">
        <span className="tl-label small muted">
          {tracks.length} tracks · {enabled} redacted
        </span>
        <div className="tl-lane tl-ruler" onClick={seekAt}>
          {lo != null && hi != null && <span className="tl-range" style={{ left: pctOf(lo), width: `${((hi - lo + 1) / Math.max(1, frames)) * 100}%` }} aria-hidden />}
          {inPoint != null && (
            <span className="tl-mark tl-in" style={{ left: pctOf(inPoint) }} data-tip={`In: frame ${inPoint}`}>
              I
            </span>
          )}
          {outPoint != null && (
            <span className="tl-mark tl-out" style={{ left: pctOf(outPoint) }} data-tip={`Out: frame ${outPoint}`}>
              O
            </span>
          )}
          {Array.from({ length: 11 }, (_, i) => (
            <span key={i} className="tl-tick" style={{ left: `${i * 10}%` }}>
              {formatTimecode((span / fps) * (i / 10))}
            </span>
          ))}
        </div>
      </div>
      <div className="timeline-rows">
        <div className="tl-playhead-wrap" aria-hidden>
          {lo != null && hi != null && <span className="tl-range rows" style={{ left: pctOf(lo), width: `${((hi - lo + 1) / Math.max(1, frames)) * 100}%` }} />}
          <div className="tl-playhead" ref={playheadRef} />
        </div>
        {loading && <div className="pad small muted">Loading tracks…</div>}
        {!loading && tracks.length === 0 && <div className="pad small muted">{emptyText}</div>}
        {tracks.map((t) => {
          const color = trackColor(t.label);
          const rr = runs.get(t.id)?.length ? runs.get(t.id)! : [[t.first, t.last] as [number, number]];
          return (
            <div key={t.id} className={`tl-row ${t.id === selectedId ? "selected" : ""} ${t.enabled ? "" : "disabled"}`}>
              <button className="tl-label" onClick={() => onSelect(t, t.first)} data-tip="Select and jump to the start">
                {isFullFrame(t) ? (
                  <Film size={12} aria-hidden className="muted" />
                ) : trackShape(t) === "ellipse" ? (
                  <Circle size={10} aria-hidden style={{ color }} />
                ) : (
                  <span className="cat-dot" style={{ background: color }} aria-hidden />
                )}
                <span className="truncate">
                  {isFullFrame(t) ? "full frame" : t.label} #{t.id}
                </span>
                {t.effect && <span className="tl-effect">{t.effect}</span>}
              </button>
              <div className="tl-lane" onClick={seekAt}>
                {rr.map(([a, b]) => (
                  <span
                    key={a}
                    className="tl-bar"
                    style={{
                      left: pctOf(a),
                      width: `${Math.max(0.3, ((b - a + 1) / Math.max(1, frames)) * 100)}%`,
                      ["--hl" as string]: color,
                    }}
                    onClick={(e) => {
                      e.stopPropagation();
                      const r = e.currentTarget.parentElement!.getBoundingClientRect();
                      const f = ((e.clientX - r.left) / r.width) * span;
                      onSelect(t, Math.max(t.first, Math.min(t.last, f)));
                    }}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
});
