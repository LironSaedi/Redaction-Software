import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent, type ReactNode } from "react";
import { Eye, EyeOff, Film, Image as ImageIcon, Pause, Play, Plus, SkipBack, SkipForward, Volume2, VolumeX, X } from "lucide-react";
import * as api from "../../api";
import { useMeta } from "../../meta";
import { useToast } from "../../components/Toast";
import { Tabs } from "../../components/ui";
import { useHotkeys } from "../../lib/hotkeys";
import { formatTimecode, titleCase } from "../../lib/format";
import type { OpHistory } from "../../lib/history";
import { constrainSquare } from "../../lib/shapes";
import { canvasRectToVideo, containFit, frameAt, normalizeRect, rectHeight, rectWidth, timeOfFrame, trackBoxAt, videoBoxToCanvas, type Point } from "../../lib/geometry";
import type { Detection, FileRecord, ManualTrackIn, Track } from "../../types";
import type { DetectionOps } from "./useDetections";
import type { FocusRequest } from "./workspace";
import type { JumpRequest } from "./ReviewPage";
import { DetectionPanel } from "./DetectionPanel";
import { FindRedactPanel } from "./FindRedactPanel";
import { PropertiesPanel } from "./PropertiesPanel";
import { TranscriptView } from "./Transcript";
import { useTranscript } from "./AudioViewer";
import { TranscriptTools, TranslationView, useTranslation, type TranslationKey } from "./Translation";
import { useTracks } from "./video/useTracks";
import { drawOverlay } from "./video/videoDraw";
import { VideoTimeline } from "./video/VideoTimeline";
import { TrackPanel } from "./video/TrackPanel";
import { AddTrackCard, FullFrameCard, type AddMode, type Pending } from "./video/AddTrackCard";
import { trackRuns, type TrackShape } from "./video/trackUtils";

// kept here for older imports / tests
export { normalizeTrack, trackColor, trackRuns } from "./video/trackUtils";

interface Props {
  file: FileRecord;
  dets: Detection[];
  ops: DetectionOps;
  focus: FocusRequest | null;
  onFocus: (d: Detection | null, source: "viewer" | "panel") => void;
  showSuggestions: boolean;
  setShowSuggestions: (v: boolean) => void;
  chips: ReactNode;
  history: OpHistory;
  readOnly: boolean;
  jump: JumpRequest | null;
  onJump: (m: Detection) => void;
  onSearchPreview: (m: Detection[]) => void;
  onFileChanged: () => void;
}

type RightTab = "tracks" | "audio" | "find";

export function VideoWorkspace({
  file,
  dets,
  ops,
  focus,
  onFocus,
  showSuggestions,
  setShowSuggestions,
  chips,
  history,
  readOnly,
  jump,
  onJump,
  onSearchPreview,
  onFileChanged,
}: Props) {
  const m = useMeta();
  const toast = useToast();
  const info = file.info ?? {};
  const fps = info.fps && info.fps > 0 ? info.fps : 30;
  const frames = info.frames && info.frames > 0 ? info.frames : Math.max(1, Math.round((file.duration || 1) * fps));
  const vw = info.width || 1280;
  const vh = info.height || 720;
  const { tracks, ops: tops } = useTracks(file.id, file.has_tracks, history);
  const { transcript } = useTranscript(file);

  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const playheadRef = useRef<HTMLDivElement>(null);
  const [stage, setStage] = useState({ w: 800, h: 450 });
  const [frame, setFrame] = useState(0);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);
  const [rate, setRate] = useState(1);
  const [selectedTrack, setSelectedTrack] = useState<number | null>(null);
  const [livePreview, setLivePreview] = useState(false);
  const [serverPreview, setServerPreview] = useState<string | null>(null);
  const [previewEffect, setPreviewEffect] = useState("blur");
  const [adding, setAdding] = useState(false);
  const [drag, setDrag] = useState<{ a: Point; b: Point; square: boolean } | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [addMode, setAddMode] = useState<AddMode>("track");
  const [addLabel, setAddLabel] = useState("manual");
  const [addShape, setAddShape] = useState<TrackShape>("rect");
  const [addEffect, setAddEffect] = useState("");
  const [endFrame, setEndFrame] = useState<number>(0);
  const [submitting, setSubmitting] = useState(false);
  const [rightTab, setRightTab] = useState<RightTab>("tracks");
  const [inPoint, setInPoint] = useState<number | null>(null);
  const [outPoint, setOutPoint] = useState<number | null>(null);
  const [fullFrame, setFullFrame] = useState(false);
  const [fullEffect, setFullEffect] = useState("blur");
  const [shownTr, setShownTr] = useState<TranslationKey | null>(null);
  const tr = useTranslation(file.id, shownTr, JSON.stringify(file.info?.translations ?? {}));
  const lastFrameUpdate = useRef(0);

  useLayoutEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setStage({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setStage({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  const fit = containFit(vw, vh, stage.w, stage.h);
  const dispW = Math.max(1, Math.floor(fit.width));
  const dispH = Math.max(1, Math.floor(fit.height));
  const sortedTracks = useMemo(() => [...(tracks ?? [])].sort((a, b) => a.first - b.first || a.id - b.id), [tracks]);
  const runs = useMemo(() => new Map(sortedTracks.map((t) => [t.id, trackRuns(t.boxes, Math.max(1, Math.round(fps / 4)))])), [sortedTracks, fps]);

  // ---- drawing ---------------------------------------------------------------------------------------
  const draw = useCallback(() => {
    const v = videoRef.current;
    const c = canvasRef.current;
    if (!v || !c) return;
    const dpr = window.devicePixelRatio || 1;
    if (c.width !== Math.round(dispW * dpr) || c.height !== Math.round(dispH * dpr)) {
      c.width = Math.round(dispW * dpr);
      c.height = Math.round(dispH * dpr);
    }
    const ctx = c.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const f = frameAt(v.currentTime, fps, frames);
    const now = performance.now();
    if (v.paused || now - lastFrameUpdate.current >= 120) {
      // throttle React updates while playing; the playhead moves imperatively
      lastFrameUpdate.current = now;
      setFrame(f);
      setTime(v.currentTime);
    }
    if (playheadRef.current) playheadRef.current.style.left = `${(f / Math.max(1, frames - 1)) * 100}%`;
    const pend = pending ? (pending.keyframes[String(f)] ?? (pending.frame === f ? pending.box : null)) : null;
    drawOverlay(ctx, {
      video: v,
      frame: f,
      tracks: sortedTracks,
      dispW,
      dispH,
      vw,
      vh,
      selectedId: selectedTrack,
      livePreview,
      defaultEffect: previewEffect,
      pending: pend ? { box: pend, shape: addShape } : null,
    });
  }, [dispW, dispH, fps, frames, sortedTracks, selectedTrack, livePreview, vw, vh, pending, previewEffect, addShape]);

  useEffect(() => {
    draw();
  }, [draw]);

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    let handle = 0;
    let stopped = false;
    type RVFC = (cb: () => void) => number;
    const rvfc = (v as HTMLVideoElement & { requestVideoFrameCallback?: RVFC }).requestVideoFrameCallback?.bind(v);
    const tick = () => {
      if (stopped) return;
      draw();
      if (!v.paused) handle = rvfc ? rvfc(tick) : requestAnimationFrame(tick);
    };
    const onPlay = () => {
      setPlaying(true);
      setServerPreview(null);
      tick();
    };
    const onPause = () => {
      setPlaying(false);
      draw();
    };
    const onSeeked = () => draw();
    v.addEventListener("play", onPlay);
    v.addEventListener("pause", onPause);
    v.addEventListener("seeked", onSeeked);
    v.addEventListener("loadeddata", onSeeked);
    v.addEventListener("timeupdate", onSeeked);
    return () => {
      stopped = true;
      cancelAnimationFrame(handle);
      v.removeEventListener("play", onPlay);
      v.removeEventListener("pause", onPause);
      v.removeEventListener("seeked", onSeeked);
      v.removeEventListener("loadeddata", onSeeked);
      v.removeEventListener("timeupdate", onSeeked);
    };
  }, [draw]);

  // ---- transport -------------------------------------------------------------------------------------
  const seekFrame = useCallback(
    (f: number) => {
      const v = videoRef.current;
      if (!v) return;
      const clamped = Math.max(0, Math.min(frames - 1, Math.round(f)));
      v.currentTime = timeOfFrame(clamped, fps);
      setFrame(clamped);
      setServerPreview(null);
    },
    [frames, fps],
  );
  const togglePlay = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) v.play().catch(() => undefined);
    else v.pause();
  };
  const pause = () => videoRef.current?.pause();
  const step = (n: number) => {
    pause();
    // from the element itself, so quick repeated presses never use a stale frame
    const v = videoRef.current;
    seekFrame((v ? frameAt(v.currentTime, fps, frames) : frame) + n);
  };

  // audio detections / transcript focus and Find & Redact jumps
  useEffect(() => {
    if (!focus || focus.source !== "panel") return;
    const d = dets.find((x) => x.id === focus.id);
    if (d?.meta?.t0 != null && videoRef.current) videoRef.current.currentTime = Math.max(0, d.meta.t0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus?.nonce]);
  useEffect(() => {
    const t0 = jump?.match.meta?.t0;
    if (typeof t0 === "number" && videoRef.current) videoRef.current.currentTime = Math.max(0, t0);
  }, [jump]);

  // ---- add redaction ---------------------------------------------------------------------------------
  const startAdd = () => {
    if (readOnly) return;
    pause();
    setServerPreview(null);
    setFullFrame(false);
    setAdding(true);
    setPending(null);
    setSelectedTrack(null);
  };
  const cancelAdd = () => {
    setAdding(false);
    setPending(null);
    setDrag(null);
  };

  const canvasPoint = (e: RPointerEvent<HTMLCanvasElement>): Point => {
    const r = e.currentTarget.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };

  const onPointerDown = (e: RPointerEvent<HTMLCanvasElement>) => {
    if (e.button !== 0) return;
    const p = canvasPoint(e);
    if (adding) {
      e.currentTarget.setPointerCapture(e.pointerId);
      setDrag({ a: p, b: p, square: e.shiftKey });
      return;
    }
    const hit = [...sortedTracks].reverse().find((t) => {
      const b = trackBoxAt(t.boxes, frame, 1);
      if (!b) return false;
      const r = videoBoxToCanvas(b, vw, vh, dispW, dispH);
      return p.x >= r.x0 && p.x <= r.x1 && p.y >= r.y0 && p.y <= r.y1;
    });
    setSelectedTrack(hit ? hit.id : null);
    if (hit) setRightTab("tracks");
  };
  const onPointerMove = (e: RPointerEvent<HTMLCanvasElement>) => {
    if (drag) setDrag({ a: drag.a, b: canvasPoint(e), square: e.shiftKey });
  };
  const onPointerUp = () => {
    if (!drag) return;
    const b = drag.square ? constrainSquare(drag.a, drag.b) : drag.b;
    const r = normalizeRect(drag.a, b);
    setDrag(null);
    if (rectWidth(r) < 5 || rectHeight(r) < 5) return;
    const vr = canvasRectToVideo(r, vw, vh, dispW, dispH);
    const box = [vr.x0, vr.y0, vr.x1, vr.y1].map((v) => Math.round(v * 10) / 10);
    setPending((p) => {
      if (!p || addMode !== "keyframes") return { frame, box, keyframes: { [String(frame)]: box } };
      const keyframes = { ...p.keyframes, [String(frame)]: box };
      const first = Math.min(...Object.keys(keyframes).map(Number));
      return { frame: first, box: keyframes[String(first)], keyframes };
    });
    setEndFrame((ef) => (ef > frame ? ef : Math.min(frames - 1, frame + Math.round(fps * 3))));
  };

  const submitAdd = async () => {
    if (!pending) return;
    const keys = Object.keys(pending.keyframes).map(Number);
    if (addMode === "keyframes" && keys.length < 2) {
      toast.error("Add at least two keyframes: move to another frame and draw the box again.");
      return;
    }
    const body: ManualTrackIn = {
      frame: pending.frame,
      box: pending.box,
      label: addLabel.trim() || "manual",
      mode: addMode,
      end_frame: addMode === "static" ? endFrame : addMode === "track" ? (endFrame > pending.frame ? endFrame : null) : null,
      keyframes: addMode === "keyframes" ? pending.keyframes : null,
      effect: addEffect || null,
      shape: addShape === "ellipse" ? "ellipse" : null,
    };
    setSubmitting(true);
    const t = await tops.add(body, addShape === "ellipse" ? "Add ellipse track" : "Add box track");
    setSubmitting(false);
    if (t) {
      toast.success(`Redaction added (${t.last - t.first + 1} frames)`);
      setSelectedTrack(t.id);
      cancelAdd();
    }
  };

  const submitFullFrame = async () => {
    if (inPoint == null || outPoint == null) return;
    const lo = Math.min(inPoint, outPoint);
    const hi = Math.max(inPoint, outPoint);
    setSubmitting(true);
    const t = await tops.add({ frame: lo, end_frame: hi, box: [0, 0, 0, 0], label: "full_frame", mode: "full_frame", effect: fullEffect }, "Full-frame effect");
    setSubmitting(false);
    if (t) {
      toast.success(`Full-frame ${fullEffect} added (${hi - lo + 1} frames)`);
      setFullFrame(false);
      setSelectedTrack(t.id);
    }
  };

  const sel = sortedTracks.find((t) => t.id === selectedTrack) ?? null;
  const selectTrack = (t: Track | null, f?: number) => {
    setSelectedTrack(t ? t.id : null);
    if (t) setRightTab("tracks");
    if (f != null) seekFrame(f);
  };

  useHotkeys({
    " ": (e) => {
      e.preventDefault();
      togglePlay();
    },
    ArrowLeft: (e) => {
      e.preventDefault();
      step(-1);
    },
    ArrowRight: (e) => {
      e.preventDefault();
      step(1);
    },
    ",": () => step(-1),
    ".": () => step(1),
    "shift+ArrowLeft": (e) => {
      e.preventDefault();
      seekFrame(frame - Math.round(fps));
    },
    "shift+ArrowRight": (e) => {
      e.preventDefault();
      seekFrame(frame + Math.round(fps));
    },
    a: () => (adding ? cancelAdd() : startAdd()),
    d: () => (adding ? cancelAdd() : startAdd()),
    r: () => adding && setAddShape("rect"),
    e: () => {
      if (adding) setAddShape("ellipse");
      else if (sel && !readOnly) tops.setEnabled(sel, !sel.enabled);
    },
    x: () => sel && !readOnly && tops.setEnabled(sel, !sel.enabled),
    i: () => setInPoint(frame),
    o: () => setOutPoint(frame),
    f: () => {
      if (readOnly) return;
      cancelAdd();
      setFullFrame(true);
      if (inPoint == null) setInPoint(frame);
    },
    p: () => setLivePreview((v) => !v),
    Escape: () => {
      if (adding) cancelAdd();
      else if (fullFrame) setFullFrame(false);
      else if (serverPreview) setServerPreview(null);
      else {
        setInPoint(null);
        setOutPoint(null);
      }
    },
  });

  const audioDets = dets;
  const focusedDet = focus ? (dets.find((d) => d.id === focus.id) ?? null) : null;
  const effects = (m.meta?.effects ?? ["blur", "pixelate", "blackout"]).filter((e) => e !== "whiteout");

  return (
    <div className="review-body">
      <div className="viewer-col video-viewer">
        <div className="viewer-toolbar" role="toolbar" aria-label="Video tools">
          {!readOnly &&
            (!adding ? (
              <button className="tool-btn" onClick={startAdd} data-tip="Draw a box or ellipse on the current frame (A)">
                <Plus size={15} aria-hidden /> <span>Add redaction</span>
              </button>
            ) : (
              <button className="tool-btn active" onClick={cancelAdd} data-tip="Cancel (Esc)">
                <X size={15} aria-hidden /> <span>Cancel adding</span>
              </button>
            ))}
          {!readOnly && (
            <button
              className={`tool-btn ${fullFrame ? "active" : ""}`}
              onClick={() => {
                cancelAdd();
                setFullFrame((v) => !v);
                if (inPoint == null) setInPoint(frame);
              }}
              data-tip="Blur / black out the whole frame between in and out points (F)"
            >
              <Film size={15} aria-hidden /> <span>Full-frame effect</span>
            </button>
          )}
          <button
            className={`tool-btn ${livePreview ? "active" : ""}`}
            aria-pressed={livePreview}
            onClick={() => setLivePreview((v) => !v)}
            data-tip="Show the redaction effects while playing (P)"
          >
            {livePreview ? <EyeOff size={15} aria-hidden /> : <Eye size={15} aria-hidden />} <span>Live preview</span>
          </button>
          <span className="toolbar-spacer" />
          <label className="row gap-sm small">
            <span className="muted">Default effect</span>
            <select className="select-sm" value={previewEffect} onChange={(e) => setPreviewEffect(e.target.value)} aria-label="Default preview effect">
              {effects.map((ef) => (
                <option key={ef} value={ef}>
                  {titleCase(ef)}
                </option>
              ))}
            </select>
          </label>
          <button
            className={`tool-btn ${serverPreview ? "active" : ""}`}
            onClick={() => {
              if (serverPreview) {
                setServerPreview(null);
                return;
              }
              pause();
              setServerPreview(api.urls.videoFrame(file.id, frame, true, previewEffect));
            }}
            data-tip="Render this frame exactly as the export will (each track's own effect and shape)"
          >
            <ImageIcon size={15} aria-hidden /> <span>{serverPreview ? "Close frame preview" : "Preview frame"}</span>
          </button>
        </div>
        {adding && (
          <AddTrackCard
            frame={frame}
            frames={frames}
            pending={pending}
            mode={addMode}
            setMode={setAddMode}
            label={addLabel}
            setLabel={setAddLabel}
            endFrame={endFrame}
            setEndFrame={setEndFrame}
            shape={addShape}
            setShape={setAddShape}
            effect={addEffect}
            setEffect={setAddEffect}
            submitting={submitting}
            onSubmit={submitAdd}
          />
        )}
        {fullFrame && (
          <FullFrameCard
            frame={frame}
            fps={fps}
            inPoint={inPoint}
            outPoint={outPoint}
            setIn={setInPoint}
            setOut={setOutPoint}
            effect={fullEffect}
            setEffect={setFullEffect}
            submitting={submitting}
            onSubmit={submitFullFrame}
            onCancel={() => setFullFrame(false)}
          />
        )}
        <div className="video-stage" ref={stageRef}>
          <div className="video-box" style={{ width: dispW, height: dispH }}>
            <video
              ref={videoRef}
              src={api.urls.media(file.id)}
              width={dispW}
              height={dispH}
              preload="auto"
              muted={muted}
              playsInline
              onRateChange={(e) => setRate(e.currentTarget.playbackRate)}
              aria-label={`Video ${file.name}`}
            />
            <canvas
              ref={canvasRef}
              className={`video-overlay ${adding ? "adding" : ""}`}
              style={{ width: dispW, height: dispH }}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              aria-label="Redaction overlay. Click a box to select its track."
            />
            {drag &&
              (() => {
                const b = drag.square ? constrainSquare(drag.a, drag.b) : drag.b;
                return (
                  <div
                    className={`draw-rect-div ${addShape === "ellipse" ? "ellipse" : ""}`}
                    style={{ left: Math.min(drag.a.x, b.x), top: Math.min(drag.a.y, b.y), width: Math.abs(b.x - drag.a.x), height: Math.abs(b.y - drag.a.y) }}
                  />
                );
              })()}
            {serverPreview && <img className="server-preview" src={serverPreview} alt={`Frame ${frame} as exported`} width={dispW} height={dispH} />}
          </div>
        </div>
        <div className="transport" role="group" aria-label="Playback">
          <button className="icon-btn" onClick={() => step(-1)} aria-label="Previous frame" data-tip="Previous frame (← or ,)">
            <SkipBack size={16} />
          </button>
          <button className="icon-btn big" onClick={togglePlay} aria-label={playing ? "Pause" : "Play"} data-tip="Play / pause (Space)">
            {playing ? <Pause size={18} /> : <Play size={18} />}
          </button>
          <button className="icon-btn" onClick={() => step(1)} aria-label="Next frame" data-tip="Next frame (→ or .)">
            <SkipForward size={16} />
          </button>
          <input
            className="seek"
            type="range"
            min={0}
            max={frames - 1}
            step={1}
            value={frame}
            onChange={(e) => seekFrame(Number(e.target.value))}
            aria-label="Seek"
            aria-valuetext={`${formatTimecode(time)}, frame ${frame}`}
          />
          <span className="mono small nowrap">
            {formatTimecode(time)} / {formatTimecode(info.duration ?? file.duration)} · f{frame}
          </span>
          <button className="btn btn-xs" onClick={() => setInPoint(frame)} data-tip="Set the in point (I)">
            In
          </button>
          <button className="btn btn-xs" onClick={() => setOutPoint(frame)} data-tip="Set the out point (O)">
            Out
          </button>
          <select
            className="select-sm"
            aria-label="Playback speed"
            value={rate}
            onChange={(e) => {
              const r = Number(e.target.value);
              if (videoRef.current) videoRef.current.playbackRate = r;
              setRate(r);
            }}
          >
            {[0.25, 0.5, 1, 1.5, 2].map((r) => (
              <option key={r} value={r}>
                {r}×
              </option>
            ))}
          </select>
          <button className="icon-btn" onClick={() => setMuted((x) => !x)} aria-label={muted ? "Unmute" : "Mute"}>
            {muted ? <VolumeX size={16} /> : <Volume2 size={16} />}
          </button>
        </div>
        <VideoTimeline
          tracks={sortedTracks}
          runs={runs}
          frames={frames}
          fps={fps}
          selectedId={selectedTrack}
          onSelect={selectTrack}
          seekFrame={seekFrame}
          playheadRef={playheadRef}
          inPoint={inPoint}
          outPoint={outPoint}
          loading={tracks === null}
          emptyText={file.has_tracks ? "No tracks." : "No tracks yet — analyze the video, or add a redaction manually."}
        />
        {transcript && (
          <details className="card video-transcript" open={transcript.words.length > 0}>
            <summary>Audio transcript ({audioDets.filter((d) => d.selected).length} spoken redactions)</summary>
            <TranscriptTools file={file} transcript={transcript} readOnly={readOnly} shown={shownTr} onShow={setShownTr} onFileChanged={onFileChanged} />
            {shownTr && tr.data && (
              <TranslationView
                transcript={transcript}
                translation={tr.data}
                tkey={shownTr}
                dets={audioDets}
                media={videoRef}
                currentTime={time}
                onClose={() => setShownTr(null)}
              />
            )}
            <TranscriptView
              transcript={transcript}
              dets={audioDets}
              ops={ops}
              media={videoRef}
              currentTime={time}
              focus={focus}
              onFocus={onFocus}
              preview={livePreview}
              showSuggestions={showSuggestions}
              follow={false}
              readOnly={readOnly}
            />
          </details>
        )}
      </div>
      <aside className="side-col review-side" aria-label="Review panel">
        <Tabs<RightTab>
          label="Redaction lists"
          idPrefix="vside"
          className="side-tabs"
          active={rightTab}
          onChange={setRightTab}
          tabs={[
            { key: "tracks", label: `Tracks (${sortedTracks.length})` },
            { key: "audio", label: `Spoken PII (${audioDets.length})`, hidden: !file.has_transcript },
            { key: "find", label: "Find", hidden: !file.has_transcript || readOnly },
          ]}
        />
        <div className="side-main">
          {rightTab === "audio" && file.has_transcript ? (
            <DetectionPanel
              dets={audioDets}
              ops={ops}
              focusedId={focus?.id ?? null}
              onFocus={(d) => onFocus(d, "panel")}
              showSuggestions={showSuggestions}
              setShowSuggestions={setShowSuggestions}
              chips={chips}
              readOnly={readOnly}
              title="Spoken PII"
              emptyHint="Select words in the transcript to redact them."
            />
          ) : rightTab === "find" && file.has_transcript ? (
            <FindRedactPanel fileId={file.id} dets={dets} ops={ops} onPreview={onSearchPreview} onJump={onJump} caseId={file.case_id} />
          ) : (
            <TrackPanel
              tracks={tracks === null ? null : sortedTracks}
              selectedId={selectedTrack}
              onSelect={selectTrack}
              ops={tops}
              fps={fps}
              frame={frame}
              seekFrame={seekFrame}
              chips={chips}
              hasTracks={file.has_tracks}
              readOnly={readOnly}
            />
          )}
        </div>
        {rightTab === "audio" && focusedDet && (
          <div className="side-props open">
            <div className="side-props-body">
              <PropertiesPanel
                det={focusedDet}
                fileKind={file.kind}
                ops={ops}
                readOnly={readOnly}
                defaults={{ entity: "CUSTOM", exemption: "", effect: "", fill: null, label_text: "" }}
                setDefaults={() => undefined}
                onClose={() => onFocus(null, "panel")}
              />
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}
