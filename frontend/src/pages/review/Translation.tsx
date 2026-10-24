import { useEffect, useMemo, useState, type RefObject } from "react";
import { Captions, Languages, X } from "lucide-react";
import * as api from "../../api";
import { useJobs } from "../../jobs";
import { languageName, useMeta } from "../../meta";
import { useToast } from "../../components/Toast";
import { Spinner } from "../../components/ui";
import { formatTimecode } from "../../lib/format";
import type { Detection, FileRecord, Transcript, Translation } from "../../types";
import { SpeakerChip, speakerColor, speakerList, wordAt, wordCoverage, wordSpeakers } from "./Transcript";

export interface TranslationKey {
  lang: string;
  redacted: boolean;
}

/** Translation keys ("es:r" redacted, "es:o" original) as listed in file.info.translations (list or map). */
export function parseTranslationKeys(keys: string[] | Record<string, unknown> | null | undefined): TranslationKey[] {
  const list = Array.isArray(keys) ? keys : keys && typeof keys === "object" ? Object.keys(keys) : [];
  return list
    .map((k) => {
      const [lang, flag] = String(k).split(":");
      return lang ? { lang, redacted: flag !== "o" } : null;
    })
    .filter((x): x is TranslationKey => x !== null)
    .sort((a, b) => a.lang.localeCompare(b.lang) || Number(b.redacted) - Number(a.redacted));
}

/** Stored translations from file.info (shown at once), then GET /api/files/{id}/translations. */
export function useTranslationList(file: Pick<FileRecord, "id" | "info">): TranslationKey[] {
  const fromInfo = useMemo(() => parseTranslationKeys(file.info?.translations), [file.info?.translations]);
  const [list, setList] = useState<TranslationKey[] | null>(null);
  const version = JSON.stringify(file.info?.translations ?? null);
  useEffect(() => {
    const ctl = new AbortController();
    api.listTranslations(file.id, ctl.signal).then(
      (r) => setList(parseTranslationKeys(r.map((t) => `${t.lang}:${t.redacted ? "r" : "o"}`))),
      () => setList(null),
    );
    return () => ctl.abort();
  }, [file.id, version]);
  return list ?? fromInfo;
}

/** Segment index playing at time t, or -1. */
export function segmentAt(segs: { start: number; end: number }[], t: number): number {
  for (let i = 0; i < segs.length; i++) if (t >= segs[i].start && t < segs[i].end) return i;
  return -1;
}

interface ToolsProps {
  file: FileRecord;
  transcript: Transcript | null;
  readOnly: boolean;
  /** currently shown translation (or null) */
  shown: TranslationKey | null;
  onShow: (k: TranslationKey | null) => void;
  onFileChanged: () => void;
}

/** Detected language, translation and caption downloads for a transcript. */
export function TranscriptTools({ file, transcript, readOnly, shown, onShow, onFileChanged }: ToolsProps) {
  const m = useMeta();
  const toast = useToast();
  const jobs = useJobs();
  const langs = m.meta?.languages;
  const codes = useMemo(() => Object.entries(langs?.codes ?? {}).sort((a, b) => a[1].localeCompare(b[1])), [langs]);
  const available = useTranslationList(file);
  const source = transcript?.language || "";
  const [targetPick, setTarget] = useState<string | null>(null);
  // default: English, or Spanish when the recording is in English
  const target = targetPick && targetPick !== source ? targetPick : source === "en" ? "es" : "en";
  const [redacted, setRedacted] = useState(true);
  const [running, setRunning] = useState<number | null>(null);
  const [capLang, setCapLang] = useState<string>("");
  const [busy, setBusy] = useState<string | null>(null);
  const canTranslate = langs?.translation_available !== false;
  const job = running ? jobs.job(running) : undefined;

  const translate = async () => {
    try {
      const { job_id } = await api.translateTranscript(file.id, target, redacted);
      setRunning(job_id);
      const key = { lang: target, redacted };
      jobs.track(job_id, {
        label: `Translation into ${languageName(m, target)}`,
        fileId: file.id,
        kind: "translate",
        onDone: (j) => {
          setRunning(null);
          if (j.status === "done") {
            onFileChanged();
            onShow(key);
          }
        },
      });
    } catch (e) {
      toast.error(e, "Could not start the translation");
    }
  };

  const download = async (fmt: "srt" | "vtt") => {
    const k = capLang ? available.find((a) => `${a.lang}:${a.redacted ? "r" : "o"}` === capLang) : null;
    setBusy(fmt);
    try {
      await api.downloadCaptions(file.id, fmt, k ? { lang: k.lang, redacted: k.redacted } : { redacted: true });
    } catch (e) {
      toast.error(e, "Download failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="transcript-tools-bar">
      <div className="tt-group">
        <span className="tt-label">Spoken language</span>
        {source ? (
          <span className="badge badge-info" data-tip={`Detected by the speech model${transcript?.model ? ` (${transcript.model})` : ""}`}>
            {languageName(m, source)} <span className="mono tiny">{source}</span>
          </span>
        ) : (
          <span className="muted small">unknown</span>
        )}
      </div>
      {!readOnly && (
        <div className="tt-group">
          <Languages size={15} aria-hidden className="muted" />
          <label className="sr-only" htmlFor="tt-target">
            Translate into
          </label>
          <select id="tt-target" className="select-sm" value={target} onChange={(e) => setTarget(e.target.value)} disabled={!canTranslate || !!running}>
            {codes
              .filter(([c]) => c !== source)
              .map(([c, name]) => (
                <option key={c} value={c}>
                  {name}
                </option>
              ))}
          </select>
          <label className="check inline small" data-tip="Redact the source first, so no redacted word can reach the translation">
            <input type="checkbox" checked={redacted} onChange={(e) => setRedacted(e.target.checked)} disabled={!canTranslate || !!running} />
            Redacted
          </label>
          <button
            className="btn btn-xs"
            onClick={translate}
            disabled={!canTranslate || !!running || !transcript}
            data-tip={canTranslate ? "Translate on this server (no data leaves it)" : "The translation model is not installed on this server"}
          >
            {running ? <Spinner size={12} /> : null} {running ? `Translating ${Math.round((job?.progress ?? 0) * 100)}%` : "Translate"}
          </button>
          {!canTranslate && <span className="tiny muted">Translation model not installed (ask an administrator to run scripts/download_models.py).</span>}
        </div>
      )}
      {available.length > 0 && (
        <div className="tt-group" role="group" aria-label="Translations">
          <span className="tt-label">Translations</span>
          {available.map((a) => {
            const on = shown?.lang === a.lang && shown.redacted === a.redacted;
            return (
              <button
                key={`${a.lang}:${a.redacted}`}
                className={`filter-chip ${on ? "active" : ""}`}
                aria-pressed={on}
                onClick={() => onShow(on ? null : a)}
              >
                {languageName(m, a.lang)}
                {!a.redacted && <span className="tiny warn-text"> · unredacted</span>}
              </button>
            );
          })}
        </div>
      )}
      <div className="tt-group">
        <Captions size={15} aria-hidden className="muted" />
        <label className="sr-only" htmlFor="tt-cap">
          Captions language
        </label>
        <select id="tt-cap" className="select-sm" value={capLang} onChange={(e) => setCapLang(e.target.value)}>
          <option value="">Transcript ({source ? languageName(m, source) : "original"}), redacted</option>
          {available.map((a) => (
            <option key={`${a.lang}:${a.redacted}`} value={`${a.lang}:${a.redacted ? "r" : "o"}`}>
              {languageName(m, a.lang)}
              {a.redacted ? ", redacted" : ", unredacted"}
            </option>
          ))}
        </select>
        <button className="btn btn-xs" onClick={() => download("srt")} disabled={busy !== null} data-tip="Download captions (SubRip)">
          {busy === "srt" && <Spinner size={11} />} SRT
        </button>
        <button className="btn btn-xs" onClick={() => download("vtt")} disabled={busy !== null} data-tip="Download captions (WebVTT)">
          {busy === "vtt" && <Spinner size={11} />} VTT
        </button>
      </div>
    </div>
  );
}

export function useTranslation(fileId: number, key: TranslationKey | null, version: string) {
  const [data, setData] = useState<Translation | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setData(null);
    setError(null);
    if (!key) return;
    const ctl = new AbortController();
    api.getTranslation(fileId, key.lang, key.redacted, ctl.signal).then(setData, (e: unknown) => {
      if (!(e instanceof DOMException)) setError(e instanceof Error ? e.message : "could not load the translation");
    });
    return () => ctl.abort();
  }, [fileId, key?.lang, key?.redacted, version]); // eslint-disable-line react-hooks/exhaustive-deps
  return { data, error };
}

interface ViewProps {
  transcript: Transcript;
  translation: Translation;
  tkey: TranslationKey;
  dets: Detection[];
  media: RefObject<HTMLMediaElement | null>;
  currentTime: number;
  onClose: () => void;
}

/** Original speech and its translation, segment by segment; click a row to play from there. */
export function TranslationView({ transcript, translation, tkey, dets, media, currentTime, onClose }: ViewProps) {
  const m = useMeta();
  const words = transcript.words;
  const redactedWords = useMemo(() => {
    const cov = wordCoverage(words, dets.filter((d) => d.selected));
    return new Set(cov.map((c, i) => (c.length ? i : -1)).filter((i) => i >= 0));
  }, [words, dets]);
  const speakers = useMemo(() => wordSpeakers(transcript), [transcript]);
  const segs = translation.segments;
  const speakerNames = useMemo(() => speakerList([...speakers, ...segs.map((x) => x.speaker ?? null)]), [speakers, segs]);
  const now = segmentAt(segs, currentTime);
  const nowWord = wordAt(words, currentTime);

  return (
    <section className="card translation-card" aria-label="Translation">
      <header className="row space">
        <h3>
          Side by side: {languageName(m, transcript.language) || "original"} → {languageName(m, tkey.lang)}
          {tkey.redacted ? <span className="badge badge-ok tiny">redacted</span> : <span className="badge badge-warn tiny">unredacted</span>}
        </h3>
        <button className="icon-btn sm" onClick={onClose} aria-label="Close the translation">
          <X size={14} />
        </button>
      </header>
      {segs.length === 0 ? (
        <p className="muted small">The translation is empty.</p>
      ) : (
        <div className="tl-table" role="table" aria-label="Transcript and translation">
          <div className="tl-tr tl-th" role="row">
            <span role="columnheader">Time</span>
            <span role="columnheader">Original</span>
            <span role="columnheader">{languageName(m, tkey.lang)}</span>
          </div>
          {segs.map((s, i) => {
            const idx: number[] = [];
            for (let w = 0; w < words.length; w++) if (words[w].start < s.end && words[w].end > s.start) idx.push(w);
            return (
              <button
                key={i}
                role="row"
                className={`tl-tr ${i === now ? "is-now" : ""}`}
                onClick={() => {
                  if (media.current) media.current.currentTime = Math.max(0, s.start);
                }}
              >
                <span role="cell" className="mono tiny muted">
                  {formatTimecode(s.start)}
                </span>
                <span role="cell" className="tl-orig">
                  {(() => {
                    const sp = s.speaker || (idx.length > 0 ? speakers[idx[0]] : null);
                    return sp ? <SpeakerChip speaker={sp} color={speakerColor(speakerNames, sp)} /> : null;
                  })()}
                  {idx.map((w) => (
                    <span key={w} className={`${redactedWords.has(w) ? "w-red" : ""} ${w === nowWord ? "w-now" : ""}`}>
                      {words[w].text}{" "}
                    </span>
                  ))}
                </span>
                <span role="cell" className="tl-trans">
                  {s.text}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}
