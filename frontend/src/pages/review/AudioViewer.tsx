import { useEffect, useRef, useState } from "react";
import { Eye, PencilLine } from "lucide-react";
import * as api from "../../api";
import { EmptyState, Loading } from "../../components/ui";
import { useHotkeys } from "../../lib/hotkeys";
import type { Detection, FileRecord, Transcript } from "../../types";
import type { DetectionOps } from "./useDetections";
import type { FocusRequest } from "./workspace";
import type { JumpRequest } from "./ReviewPage";
import { TimeStrip, TranscriptView, useMediaTime } from "./Transcript";
import { TranscriptTools, TranslationView, useTranslation, type TranslationKey } from "./Translation";

export function useTranscript(file: FileRecord) {
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!file.has_transcript) return;
    const ctl = new AbortController();
    api.getTranscript(file.id, ctl.signal).then(setTranscript, (e: unknown) => {
      if (!(e instanceof DOMException)) setError(e instanceof Error ? e.message : "could not load transcript");
    });
    return () => ctl.abort();
  }, [file.id, file.has_transcript, file.analyzed_at]);
  return { transcript, error };
}

interface Props {
  file: FileRecord;
  dets: Detection[];
  ops: DetectionOps;
  focus: FocusRequest | null;
  onFocus: (d: Detection, source: "viewer") => void;
  preview: boolean;
  setPreview: (v: boolean) => void;
  showSuggestions: boolean;
  jump: JumpRequest | null;
  readOnly: boolean;
  onFileChanged: () => void;
}

export function AudioViewer({ file, dets, ops, focus, onFocus, preview, setPreview, showSuggestions, jump, readOnly, onFileChanged }: Props) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const t = useMediaTime(audioRef);
  const { transcript, error } = useTranscript(file);
  const [follow, setFollow] = useState(true);
  const [mediaError, setMediaError] = useState(false);
  const [shown, setShown] = useState<TranslationKey | null>(null);
  const tr = useTranslation(file.id, shown, JSON.stringify(file.info?.translations ?? {}));
  const duration = transcript?.duration || file.duration;

  useEffect(() => {
    if (!focus || focus.source !== "panel") return;
    const d = dets.find((x) => x.id === focus.id);
    if (d?.meta?.t0 != null && audioRef.current) audioRef.current.currentTime = Math.max(0, d.meta.t0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus?.nonce]);

  useEffect(() => {
    const t0 = jump?.match.meta?.t0;
    if (typeof t0 === "number" && audioRef.current) audioRef.current.currentTime = Math.max(0, t0);
  }, [jump]);

  useHotkeys({
    p: () => setPreview(!preview),
    " ": (e) => {
      e.preventDefault();
      const a = audioRef.current;
      if (a) (a.paused ? a.play() : Promise.resolve(a.pause())).catch(() => undefined);
    },
  });

  return (
    <div className="viewer-col audio-viewer">
      <div className="viewer-toolbar" role="toolbar" aria-label="Audio tools">
        <div className="seg seg-sm" role="radiogroup" aria-label="View mode">
          <button type="button" role="radio" aria-checked={!preview} className={`seg-item ${!preview ? "active" : ""}`} onClick={() => setPreview(false)}>
            <PencilLine size={14} aria-hidden /> Edit
          </button>
          <button type="button" role="radio" aria-checked={preview} className={`seg-item ${preview ? "active" : ""}`} onClick={() => setPreview(true)} data-tip="Preview the redacted transcript (P)">
            <Eye size={14} aria-hidden /> Preview redacted
          </button>
        </div>
        <span className="toolbar-spacer" />
        <label className="check inline small">
          <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> Follow playback
        </label>
      </div>
      <div className="viewer-scroll audio-scroll">
        <div className="audio-player card">
          <audio
            ref={audioRef}
            src={api.urls.media(file.id)}
            controls
            preload="metadata"
            className="audio-el"
            onError={() => setMediaError(true)}
            onLoadedMetadata={() => setMediaError(false)}
          >
            Your browser cannot play this audio.
          </audio>
          {mediaError && (
            <div className="notice notice-info small media-error" role="status">
              This browser cannot play the original .{file.ext} audio. The transcript, redaction review and export still work; the
              redacted export is a standard audio file.
            </div>
          )}
          <TimeStrip
            duration={duration}
            dets={dets}
            currentTime={t}
            showSuggestions={showSuggestions}
            onSeek={(s) => audioRef.current && (audioRef.current.currentTime = s)}
          />
          <div className="small muted">Shaded ranges are bleeped / muted in the export.</div>
          {file.has_transcript && (
            <TranscriptTools file={file} transcript={transcript} readOnly={readOnly} shown={shown} onShow={setShown} onFileChanged={onFileChanged} />
          )}
        </div>
        {shown && transcript && tr.data && (
          <TranslationView
            transcript={transcript}
            translation={tr.data}
            tkey={shown}
            dets={dets}
            media={audioRef}
            currentTime={t}
            onClose={() => setShown(null)}
          />
        )}
        {shown && tr.error && <div className="notice notice-error small transcript-card">{tr.error}</div>}
        <div className="card transcript-card">
          <h3>Transcript</h3>
          {!file.has_transcript && (
            <EmptyState title="Not transcribed yet">Analyze the file to transcribe speech and find spoken PII.</EmptyState>
          )}
          {file.has_transcript && !transcript && !error && <Loading label="Loading transcript…" />}
          {error && <div className="text-bad">{error}</div>}
          {transcript && (
            <TranscriptView
              transcript={transcript}
              dets={dets}
              ops={ops}
              media={audioRef}
              currentTime={t}
              focus={focus}
              onFocus={onFocus}
              preview={preview}
              showSuggestions={showSuggestions}
              follow={follow}
              readOnly={readOnly}
            />
          )}
        </div>
      </div>
    </div>
  );
}
