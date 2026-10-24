import { Circle, Film, Square } from "lucide-react";
import { Spinner } from "../../../components/ui";
import { formatTimecode, titleCase } from "../../../lib/format";
import type { TrackMode } from "../../../types";
import { TRACK_EFFECTS, type TrackShape } from "./trackUtils";

export type AddMode = Exclude<TrackMode, "full_frame">;

export interface Pending {
  frame: number;
  box: number[];
  keyframes: Record<string, number[]>;
}

function EffectSelect({ id, value, onChange }: { id: string; value: string; onChange: (v: string) => void }) {
  return (
    <select id={id} className="select-sm" value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">Export setting</option>
      {TRACK_EFFECTS.map((e) => (
        <option key={e} value={e}>
          {titleCase(e)}
        </option>
      ))}
    </select>
  );
}

export function ShapeToggle({ shape, onChange }: { shape: TrackShape; onChange: (s: TrackShape) => void }) {
  return (
    <div className="seg seg-xs" role="radiogroup" aria-label="Shape">
      <button type="button" role="radio" aria-checked={shape === "rect"} className={`seg-item ${shape === "rect" ? "active" : ""}`} onClick={() => onChange("rect")} data-tip="Rectangle (R)">
        <Square size={12} aria-hidden /> Rect
      </button>
      <button
        type="button"
        role="radio"
        aria-checked={shape === "ellipse"}
        className={`seg-item ${shape === "ellipse" ? "active" : ""}`}
        onClick={() => onChange("ellipse")}
        data-tip="Ellipse (E)"
      >
        <Circle size={12} aria-hidden /> Ellipse
      </button>
    </div>
  );
}

interface AddProps {
  frame: number;
  frames: number;
  pending: Pending | null;
  mode: AddMode;
  setMode: (m: AddMode) => void;
  label: string;
  setLabel: (v: string) => void;
  endFrame: number;
  setEndFrame: (v: number) => void;
  shape: TrackShape;
  setShape: (s: TrackShape) => void;
  effect: string;
  setEffect: (e: string) => void;
  submitting: boolean;
  onSubmit: () => void;
}

export function AddTrackCard(p: AddProps) {
  return (
    <div className="add-card" role="region" aria-label="New video redaction">
      <div className="row gap wrap">
        <span className="small">
          {!p.pending ? (
            <>
              <strong>Draw a {p.shape === "ellipse" ? "ellipse" : "box"}</strong> around the object on frame {p.frame} (←/→ to pick the frame)
            </>
          ) : (
            <>
              Box at frame <strong>{p.pending.frame}</strong>
              {p.mode === "keyframes" && ` · ${Object.keys(p.pending.keyframes).length} keyframe(s) — move and draw again to add more`}
            </>
          )}
        </span>
        <ShapeToggle shape={p.shape} onChange={p.setShape} />
        <label className="small row gap-sm">
          Effect
          <EffectSelect id="add-effect" value={p.effect} onChange={p.setEffect} />
        </label>
      </div>
      {p.pending && (
        <div className="row gap wrap">
          <label className="small row gap-sm">
            Label
            <input className="input-sm" value={p.label} onChange={(e) => p.setLabel(e.target.value)} />
          </label>
          <div className="seg seg-xs" role="radiogroup" aria-label="How to follow the object">
            {(
              [
                ["track", "Track automatically"],
                ["static", "Static for a range"],
                ["keyframes", "Keyframes"],
              ] as [AddMode, string][]
            ).map(([k, l]) => (
              <button key={k} type="button" role="radio" aria-checked={p.mode === k} className={`seg-item ${p.mode === k ? "active" : ""}`} onClick={() => p.setMode(k)}>
                {l}
              </button>
            ))}
          </div>
          {p.mode !== "keyframes" && (
            <label className="small row gap-sm">
              {p.mode === "static" ? "Until frame" : "Stop at frame"}
              <input
                className="input-sm num-input"
                type="number"
                min={p.pending.frame}
                max={p.frames - 1}
                value={p.endFrame}
                onChange={(e) => p.setEndFrame(Math.max(p.pending!.frame, Math.min(p.frames - 1, Number(e.target.value) || 0)))}
              />
              <button type="button" className="link-btn small" onClick={() => p.setEndFrame(p.frame)}>
                current
              </button>
              <button type="button" className="link-btn small" onClick={() => p.setEndFrame(p.frames - 1)}>
                end
              </button>
            </label>
          )}
          <button className="btn btn-sm btn-primary" onClick={p.onSubmit} disabled={p.submitting}>
            {p.submitting && <Spinner size={13} />} {p.mode === "track" && p.submitting ? "Tracking…" : "Add redaction"}
          </button>
        </div>
      )}
    </div>
  );
}

interface FullProps {
  frame: number;
  fps: number;
  inPoint: number | null;
  outPoint: number | null;
  setIn: (f: number | null) => void;
  setOut: (f: number | null) => void;
  effect: string;
  setEffect: (e: string) => void;
  submitting: boolean;
  onSubmit: () => void;
  onCancel: () => void;
}

export function FullFrameCard(p: FullProps) {
  const ok = p.inPoint != null && p.outPoint != null;
  const lo = ok ? Math.min(p.inPoint!, p.outPoint!) : 0;
  const hi = ok ? Math.max(p.inPoint!, p.outPoint!) : 0;
  return (
    <div className="add-card full-frame-card" role="region" aria-label="Full-frame effect">
      <div className="row gap wrap">
        <Film size={15} aria-hidden />
        <strong className="small">Full-frame effect</strong>
        <span className="small muted">Blur or black out the whole picture between the in and out points (I / O).</span>
      </div>
      <div className="row gap wrap">
        <span className="small">
          In <strong className="mono">{p.inPoint ?? "—"}</strong>{" "}
          <button className="link-btn small" onClick={() => p.setIn(p.frame)}>
            set to current
          </button>
        </span>
        <span className="small">
          Out <strong className="mono">{p.outPoint ?? "—"}</strong>{" "}
          <button className="link-btn small" onClick={() => p.setOut(p.frame)}>
            set to current
          </button>
        </span>
        {ok && (
          <span className="small muted">
            {hi - lo + 1} frames · {formatTimecode(lo / p.fps)}–{formatTimecode(hi / p.fps)}
          </span>
        )}
        <label className="small row gap-sm">
          Effect
          <select className="select-sm" value={p.effect} onChange={(e) => p.setEffect(e.target.value)}>
            {TRACK_EFFECTS.map((e) => (
              <option key={e} value={e}>
                {titleCase(e)}
              </option>
            ))}
          </select>
        </label>
        <button className="btn btn-sm btn-primary" disabled={!ok || p.submitting} onClick={p.onSubmit}>
          {p.submitting && <Spinner size={13} />} Apply to {ok ? hi - lo + 1 : 0} frames
        </button>
        <button className="btn btn-sm btn-ghost" onClick={p.onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
