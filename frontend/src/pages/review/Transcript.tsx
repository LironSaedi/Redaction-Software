import { memo, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import { Check, X } from "lucide-react";
import { entityOptions, useMeta } from "../../meta";
import { formatTimecode } from "../../lib/format";
import type { Detection, Transcript, TranscriptWord } from "../../types";
import type { DetectionOps } from "./useDetections";
import type { FocusRequest } from "./workspace";

/** Detections covering each word: by character offsets when known, else by time range. */
export function wordCoverage(words: TranscriptWord[], dets: Detection[]): Detection[][] {
  const out: Detection[][] = words.map(() => []);
  for (const d of dets) {
    const byChars = d.start >= 0 && d.end > d.start;
    const t0 = d.meta?.t0;
    const t1 = d.meta?.t1;
    for (let i = 0; i < words.length; i++) {
      const w = words[i];
      const hit = byChars
        ? w.char_start < d.end && d.start < w.char_end
        : t0 != null && t1 != null && w.start < t1 && t0 < w.end;
      if (hit) out[i].push(d);
    }
  }
  return out;
}

/** Index of the word being spoken at time t (binary search), or -1. */
export function wordAt(words: TranscriptWord[], t: number): number {
  let lo = 0;
  let hi = words.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const w = words[mid];
    if (t < w.start) hi = mid - 1;
    else if (t >= w.end) lo = mid + 1;
    else return mid;
  }
  return -1;
}

// ---- speakers ----------------------------------------------------------------------------------------
// Labels are anonymous by design ("Speaker 1"); the UI never offers to name them.

const SPEAKER_COLORS = ["#2563eb", "#c026d3", "#059669", "#d97706", "#7c3aed", "#0891b2", "#dc2626", "#4b5563"];

/** Speaker of every word: the word's own label, else the segment it falls in, else null. */
export function wordSpeakers(t: Pick<Transcript, "words" | "segments">): (string | null)[] {
  const segs = (t.segments ?? []).filter((s) => typeof s.speaker === "string" && s.speaker);
  return t.words.map((w) => {
    if (w.speaker) return w.speaker;
    const seg = segs.find((s) => (s.start ?? 0) - 0.05 <= w.start && w.start <= (s.end ?? 0) + 0.05);
    return (seg?.speaker as string | undefined) ?? null;
  });
}

/** Distinct speakers in order of first appearance. */
export function speakerList(speakers: (string | null)[]): string[] {
  const out: string[] = [];
  for (const s of speakers) if (s && !out.includes(s)) out.push(s);
  return out;
}

/** Stable colour per speaker (by order of appearance). */
export function speakerColor(list: string[], speaker: string): string {
  const i = list.indexOf(speaker);
  return SPEAKER_COLORS[(i < 0 ? 0 : i) % SPEAKER_COLORS.length];
}

export function SpeakerChip({ speaker, color }: { speaker: string; color: string }) {
  return (
    <span className="speaker-chip" style={{ ["--spk" as string]: color }} aria-label={speaker}>
      {speaker}
    </span>
  );
}

interface Run {
  det: Detection | null;
  ids: string;
  from: number;
  to: number; // inclusive
}

function buildRuns(cov: Detection[][]): Run[] {
  const runs: Run[] = [];
  cov.forEach((ds, i) => {
    const top = ds.find((d) => d.selected) ?? ds[0] ?? null;
    const last = runs[runs.length - 1];
    if (last && (last.det?.id ?? null) === (top?.id ?? null)) last.to = i;
    else runs.push({ det: top, ids: ds.map((d) => d.id).join(" "), from: i, to: i });
  });
  return runs;
}

interface TranscriptProps {
  transcript: Transcript;
  dets: Detection[];
  ops: DetectionOps;
  media: RefObject<HTMLMediaElement | null>;
  currentTime: number;
  focus: FocusRequest | null;
  onFocus: (d: Detection, source: "viewer") => void;
  preview: boolean;
  showSuggestions: boolean;
  follow: boolean;
  readOnly?: boolean;
}

export const TranscriptView = memo(function TranscriptView({
  transcript,
  dets,
  ops,
  media,
  currentTime,
  focus,
  onFocus,
  preview,
  showSuggestions,
  follow,
  readOnly = false,
}: TranscriptProps) {
  const m = useMeta();
  const rootRef = useRef<HTMLDivElement>(null);
  const prevWord = useRef(-1);
  const [pending, setPending] = useState<{ i0: number; i1: number; x: number; y: number } | null>(null);
  const [markAs, setMarkAs] = useState("CUSTOM");
  const [only, setOnly] = useState<string[]>([]);
  const words = transcript.words;
  const speakers = useMemo(() => wordSpeakers(transcript), [transcript]);
  const speakerNames = useMemo(() => speakerList(speakers), [speakers]);
  const filtering = only.length > 0;
  const hiddenWords = filtering ? speakers.filter((sp) => !sp || !only.includes(sp)).length : 0;

  const shown = useMemo(() => dets.filter((d) => d.selected || (showSuggestions && !preview)), [dets, showSuggestions, preview]);
  const runs = useMemo(() => buildRuns(wordCoverage(words, shown)), [words, shown]);

  // highlight the spoken word without re-rendering the transcript
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const i = wordAt(words, currentTime);
    if (i === prevWord.current) return;
    root.querySelector(`[data-i="${prevWord.current}"]`)?.classList.remove("w-now");
    prevWord.current = i;
    if (i >= 0) {
      const el = root.querySelector(`[data-i="${i}"]`);
      el?.classList.add("w-now");
      if (follow && el && media.current && !media.current.paused) el.scrollIntoView({ block: "nearest" });
    }
  }, [currentTime, words, follow, media, runs]);

  useEffect(() => {
    if (!focus || focus.source !== "panel" || !rootRef.current) return;
    rootRef.current.querySelector(`[data-ids~="${CSS.escape(focus.id)}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [focus]);

  const seek = (t: number) => {
    if (media.current) media.current.currentTime = Math.max(0, t);
  };

  const onMouseUp = () => {
    const root = rootRef.current;
    const sel = window.getSelection();
    if (!root || !sel || sel.isCollapsed || sel.rangeCount === 0 || readOnly) {
      setPending(null);
      return;
    }
    const range = sel.getRangeAt(0);
    if (!root.contains(range.commonAncestorContainer)) return;
    const idx = (n: Node) => {
      const el = (n.nodeType === Node.TEXT_NODE ? n.parentElement : (n as HTMLElement))?.closest<HTMLElement>("[data-i]");
      return el ? Number(el.dataset.i) : null;
    };
    let i0 = idx(range.startContainer);
    let i1 = idx(range.endContainer);
    if (i0 == null || i1 == null) {
      // selection boundary on whitespace: use the words fully inside the range
      const inside = Array.from(root.querySelectorAll<HTMLElement>("[data-i]")).filter((el) => range.intersectsNode(el));
      if (!inside.length) return;
      i0 = Number(inside[0].dataset.i);
      i1 = Number(inside[inside.length - 1].dataset.i);
    }
    if (i1 < i0) [i0, i1] = [i1, i0];
    const r = range.getBoundingClientRect();
    const box = root.getBoundingClientRect();
    setPending({ i0, i1, x: r.left - box.left, y: r.bottom - box.top + root.scrollTop + 6 });
  };

  const confirm = async () => {
    if (!pending) return;
    const w0 = words[pending.i0];
    const w1 = words[pending.i1];
    setPending(null);
    window.getSelection()?.removeAllRanges();
    if (!w0 || !w1) return;
    const d = await ops.add({ entity: markAs, t0: Math.max(0, w0.start - 0.05), t1: w1.end + 0.05, note: "marked in transcript" }, "Redact words");
    if (d) onFocus(d, "viewer");
  };

  if (!words.length) {
    return <div className="muted pad">The transcript is empty (no speech was recognised).</div>;
  }

  return (
    <div className="transcript-wrap">
      {(!readOnly || speakerNames.length > 0) && (
        <div className="row gap-sm small transcript-tools">
          {!readOnly && (
            <>
              <span className="muted">Click a word to jump there · select words to redact them as</span>
              <select className="select-sm" aria-label="Mark selected words as" value={markAs} onChange={(e) => setMarkAs(e.target.value)}>
                {entityOptions(m).map((o) => (
                  <option key={o.key} value={o.key}>
                    {o.label}
                  </option>
                ))}
              </select>
            </>
          )}
          {speakerNames.length > 0 && (
            <div className="speaker-filter" role="group" aria-label="Show speakers">
              <span className="muted">Speakers</span>
              <button type="button" className={`filter-chip ${!filtering ? "active" : ""}`} aria-pressed={!filtering} onClick={() => setOnly([])}>
                All
              </button>
              {speakerNames.map((sp) => {
                const on = only.includes(sp);
                return (
                  <button
                    key={sp}
                    type="button"
                    className={`filter-chip speaker-toggle ${on ? "active" : ""}`}
                    aria-pressed={on}
                    style={{ ["--spk" as string]: speakerColor(speakerNames, sp) }}
                    onClick={() => setOnly((cur) => (cur.includes(sp) ? cur.filter((x) => x !== sp) : [...cur, sp]))}
                  >
                    <span className="speaker-dot" aria-hidden /> {sp}
                  </button>
                );
              })}
              {filtering && (
                <span className="muted tiny" role="status">
                  {hiddenWords} word{hiddenWords === 1 ? "" : "s"} of other speakers hidden
                </span>
              )}
            </div>
          )}
        </div>
      )}
      <div className="transcript" ref={rootRef} onPointerUp={() => setTimeout(onMouseUp, 0)} onKeyUp={(e) => e.shiftKey && onMouseUp()} aria-label="Transcript">
        {runs.map((run) => {
          const ws: ReactNode[] = [];
          for (let i = run.from; i <= run.to; i++) {
            const w = words[i];
            const sp = speakers[i];
            if (filtering && (!sp || !only.includes(sp))) continue;
            // a new speaker turn starts here (or the first word shown after hidden words)
            if (sp && (i === 0 || speakers[i - 1] !== sp || (filtering && !only.includes(speakers[i - 1] ?? "")))) {
              ws.push(<SpeakerChip key={`spk${i}`} speaker={sp} color={speakerColor(speakerNames, sp)} />);
            }
            const txt = preview && run.det?.selected ? w.text.replace(/[^\s]/g, "█") : w.text;
            ws.push(
              <span key={i} data-i={i} className="w" onClick={() => seek(w.start)} title={formatTimecode(w.start)}>
                {txt}
              </span>,
            );
            ws.push(<span key={`s${i}`}> </span>);
          }
          if (!ws.length) return null;
          if (!run.det) return <span key={run.from}>{ws}</span>;
          const d = run.det;
          const focused = focus?.id === d.id;
          return (
            <span
              key={run.from}
              data-ids={run.ids}
              className={`tr-run ${d.selected ? "hl-selected" : "hl-suggested"} ${focused ? "hl-focused" : ""}`}
              style={{ ["--hl" as string]: m.color(d.entity) }}
            >
              {ws}
              {!preview && !readOnly && (
                <button
                  className="tr-toggle"
                  onClick={() => {
                    ops.toggle(d.id);
                    onFocus(d, "viewer");
                  }}
                  data-tip={`${m.entityLabel(d.entity)} · ${d.selected ? "keep audible" : "redact"}`}
                  aria-label={`${d.selected ? "Un-select" : "Redact"} ${m.entityLabel(d.entity)} at ${formatTimecode(d.meta?.t0 ?? 0)}`}
                >
                  {d.selected ? <X size={11} aria-hidden /> : <Check size={11} aria-hidden />}
                </button>
              )}
            </span>
          );
        })}
        {pending && (
          <div className="float-bar" style={{ left: Math.max(0, pending.x), top: pending.y }}>
            <span className="small">
              Redact {pending.i1 - pending.i0 + 1} word{pending.i1 > pending.i0 ? "s" : ""} ({formatTimecode(words[pending.i0]?.start ?? 0)}–
              {formatTimecode(words[pending.i1]?.end ?? 0)})
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
  );
});

/** Horizontal strip of redacted time ranges with a playhead; click to seek. */
export function TimeStrip({
  duration,
  dets,
  currentTime,
  onSeek,
  showSuggestions,
}: {
  duration: number;
  dets: Detection[];
  currentTime: number;
  onSeek: (t: number) => void;
  showSuggestions: boolean;
}) {
  const m = useMeta();
  if (!duration || duration <= 0) return null;
  const ranges = dets.filter((d) => d.meta?.t0 != null && d.meta?.t1 != null && (d.selected || showSuggestions));
  return (
    <div
      className="time-strip"
      role="slider"
      tabIndex={0}
      aria-label="Redacted time ranges; click to seek"
      aria-valuemin={0}
      aria-valuemax={Math.round(duration)}
      aria-valuenow={Math.round(currentTime)}
      aria-valuetext={formatTimecode(currentTime)}
      onClick={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        onSeek(((e.clientX - r.left) / r.width) * duration);
      }}
      onKeyDown={(e) => {
        if (e.key === "ArrowLeft") onSeek(Math.max(0, currentTime - 1));
        if (e.key === "ArrowRight") onSeek(Math.min(duration, currentTime + 1));
      }}
    >
      {ranges.map((d) => (
        <span
          key={d.id}
          className={`ts-range ${d.selected ? "sel" : "sug"}`}
          style={{
            left: `${((d.meta.t0 ?? 0) / duration) * 100}%`,
            width: `${Math.max(0.4, (((d.meta.t1 ?? 0) - (d.meta.t0 ?? 0)) / duration) * 100)}%`,
            ["--hl" as string]: m.color(d.entity),
          }}
          title={`${m.entityLabel(d.entity)} ${formatTimecode(d.meta.t0 ?? 0)}–${formatTimecode(d.meta.t1 ?? 0)}`}
        />
      ))}
      <span className="ts-head" style={{ left: `${Math.min(100, (currentTime / duration) * 100)}%` }} aria-hidden />
    </div>
  );
}

export function useMediaTime(media: RefObject<HTMLMediaElement | null>, deps: unknown[] = []): number {
  const [t, setT] = useState(0);
  useEffect(() => {
    const el = media.current;
    if (!el) return;
    const on = () => setT(el.currentTime);
    el.addEventListener("timeupdate", on);
    el.addEventListener("seeked", on);
    el.addEventListener("loadedmetadata", on);
    return () => {
      el.removeEventListener("timeupdate", on);
      el.removeEventListener("seeked", on);
      el.removeEventListener("loadedmetadata", on);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [media, ...deps]);
  return t;
}
