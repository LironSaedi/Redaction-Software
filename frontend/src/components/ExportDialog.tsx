import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, ClipboardCheck, Download, FileDown, FileSpreadsheet, RotateCcw, ShieldAlert, XCircle } from "lucide-react";
import * as api from "../api";
import { hasRole, useUser } from "../auth";
import { useJobs } from "../jobs";
import { useMeta } from "../meta";
import { useToast } from "./Toast";
import { Field, Modal, ProgressBar, Spinner, Switch } from "./ui";
import { FinalCheckResult } from "./FinalCheck";
import { formatBytes, isTextKind, statusLabel, titleCase } from "../lib/format";
import { isReviewCopy, latestExport as latestReleaseExport, REVIEW_COPY_LABEL } from "../lib/exports";
import type { EnhanceParams, ExportDetail, ExportParams, FileRecord, Verification, VerificationIssue } from "../types";

const ISSUE_TEXT: Record<string, string> = {
  text_under_box: "Text is still extractable under a redaction box",
  value_still_present: "A redacted value still appears in the document",
  pixels_not_destroyed: "Image pixels under a box were not destroyed",
  metadata_present: "Document metadata is still present",
  xmp_present: "XMP metadata is still present",
  embedded_files_present: "Embedded files are still present",
  annotations_present: "Annotations are still present",
  face_visible: "A face is still visible",
  license_plate_visible: "A license plate is still visible",
  marked_copy_not_for_release: "Marked review copy — nothing was removed; not for release",
};

/** Banner for marked review copies (outlines + labels, nothing removed). */
export function ReviewCopyNotice({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`verify verify-review ${compact ? "compact" : ""}`} role="note">
      <ClipboardCheck size={20} aria-hidden />
      <div>
        <strong>{REVIEW_COPY_LABEL}</strong>
        {!compact && (
          <div className="small">
            Every redaction is drawn as an outline with its label, but <strong>nothing is removed</strong>: the original content is
            still readable. Use it for internal QC and supervisor sign-off only — never release it.
          </div>
        )}
      </div>
    </div>
  );
}

export function issueText(i: VerificationIssue): string {
  const base = ISSUE_TEXT[i.type] ?? titleCase(i.type);
  const where: string[] = [];
  if (typeof i.page === "number") where.push(`page ${i.page + 1}`);
  if (typeof i.time === "number") where.push(`at ${i.time.toFixed(2)} s`);
  else if (typeof i.frame === "number") where.push(`frame ${i.frame}`);
  if (i.entity) where.push(titleCase(i.entity));
  return where.length ? `${base} (${where.join(", ")})` : base;
}

export function VerificationResult({ verification, verified }: { verification?: Verification; verified: boolean }) {
  const issues = verification?.issues ?? [];
  if (verified) {
    return (
      <div className="verify verify-ok" role="status">
        <CheckCircle2 size={20} aria-hidden />
        <div>
          <strong>Verification passed</strong>
          <div className="small">
            The exported file was re-read independently and no redacted content was found
            {verification?.checks ? ` (${verification.checks.length} checks)` : ""}
            {verification?.frames_checked ? ` (${verification.frames_checked} frames checked)` : ""}.
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="verify verify-bad" role="alert">
      <ShieldAlert size={22} aria-hidden />
      <div>
        <strong>Verification FAILED — do not release this file</strong>
        <div className="small">
          The independent check found possible leaks. Downloads of this export are blocked for redactors; a supervisor must
          review it. Fix the redactions (or add boxes over the reported areas) and export again.
        </div>
        {issues.length > 0 && (
          <ul className="issue-list">
            {issues.slice(0, 30).map((i, n) => (
              <li key={n}>
                <XCircle size={14} aria-hidden /> {issueText(i)}
              </li>
            ))}
            {issues.length > 30 && <li className="muted">…and {issues.length - 30} more</li>}
          </ul>
        )}
      </div>
    </div>
  );
}

export function ExportDownloads({
  exp,
  file,
}: {
  exp: Pick<ExportDetail, "id" | "name" | "verified" | "size"> & { settings?: Record<string, unknown> | null };
  file?: FileRecord;
}) {
  const toast = useToast();
  const user = useUser();
  const [busy, setBusy] = useState<string | null>(null);
  const run = async (what: string, fn: () => Promise<void>) => {
    setBusy(what);
    try {
      await fn();
    } catch (e) {
      toast.error(e, "Download failed");
    } finally {
      setBusy(null);
    }
  };
  const review = isReviewCopy(exp);
  const blocked = !review && !exp.verified && !hasRole(user, "supervisor");
  return (
    <div className="row gap wrap">
      <button
        className={review ? "btn btn-warn" : "btn btn-primary"}
        disabled={blocked || busy !== null}
        data-tip={blocked ? "Blocked: verification failed" : review ? REVIEW_COPY_LABEL : undefined}
        onClick={() => run("file", () => api.downloadExport(exp.id, exp.name))}
      >
        {busy === "file" ? <Spinner size={14} /> : <Download size={15} aria-hidden />} {review ? "Review copy (not for release)" : "Redacted file"}
        {exp.size ? <span className="muted small"> ({formatBytes(exp.size)})</span> : null}
      </button>
      <button className="btn" disabled={busy !== null} onClick={() => run("log", () => api.downloadExportLog(exp.id))}>
        {busy === "log" ? <Spinner size={14} /> : <FileSpreadsheet size={15} aria-hidden />} Redaction log (CSV)
      </button>
      {file && (file.kind === "audio" || file.kind === "video") && file.has_transcript && (
        <button className="btn" disabled={busy !== null} onClick={() => run("srt", () => api.downloadCaptions(file.id, "srt"))}>
          {busy === "srt" ? <Spinner size={14} /> : <FileDown size={15} aria-hidden />} Redacted captions (SRT)
        </button>
      )}
    </div>
  );
}

function defaultParams(kinds: Set<string>): ExportParams {
  return {
    style: { label: "none", custom_text: "REDACTED" },
    text_style: "block",
    effect: kinds.size === 1 && kinds.has("video") ? "blur" : "blackout",
    face_effect: null,
    audio_effect: "bleep",
    voice_disguise: false,
    mute_audio: false,
    bates_prefix: "",
    bates_start: 1,
    bates_digits: 6,
    watermark: "",
    password: "",
    flatten: false,
    padding: 0,
    marked_copy: false,
    enhance: null,
    burn_captions: false,
    second_opinion: true,
  };
}

export const DEFAULT_ENHANCE: EnhanceParams = { brightness: 0, contrast: 1, sharpen: 0, gamma: 1, denoise: false };

export function isDefaultEnhance(e: EnhanceParams | null | undefined): boolean {
  if (!e) return true;
  return (
    Math.abs(e.brightness - DEFAULT_ENHANCE.brightness) < 1e-6 &&
    Math.abs(e.contrast - DEFAULT_ENHANCE.contrast) < 1e-6 &&
    Math.abs(e.sharpen - DEFAULT_ENHANCE.sharpen) < 1e-6 &&
    Math.abs(e.gamma - DEFAULT_ENHANCE.gamma) < 1e-6 &&
    !e.denoise
  );
}

/** Strip empty optional values so the server applies its defaults. */
export function cleanExportParams(p: ExportParams, kinds: Set<string>): ExportParams {
  const out: ExportParams = { ...p };
  if (!out.bates_prefix) {
    out.bates_prefix = null;
  }
  if (!out.watermark) out.watermark = null;
  if (!out.password) out.password = null;
  if (!out.face_effect) out.face_effect = null;
  // a video-only export without an explicit effect choice keeps the server's "blur" default
  if (kinds.size === 1 && kinds.has("video") && !out.effect) delete out.effect;
  out.padding = Math.max(0, Math.min(10, Number(out.padding) || 0));
  // enhancement is sent only when something was changed
  if (isDefaultEnhance(out.enhance)) delete out.enhance;
  // a review copy exists for PDFs and images only
  const markable = Array.from(kinds).every((k) => k === "pdf" || k === "image");
  if (!out.marked_copy || !markable) delete out.marked_copy;
  if (!out.burn_captions || !kinds.has("video")) delete out.burn_captions;
  // a review copy is never released, so it gets no final check
  if (out.marked_copy) out.second_opinion = false;
  return out;
}

interface ExportDialogProps {
  caseId: number;
  files: FileRecord[];
  onClose: () => void;
  onDone?: () => void;
}

interface Outcome {
  fileId: number;
  jobId: number;
  status: string;
  message?: string;
  exp?: ExportDetail;
}

export function ExportDialog({ caseId, files, onClose, onDone }: ExportDialogProps) {
  const meta = useMeta().meta;
  const so = meta?.second_opinion;
  const toast = useToast();
  const jobs = useJobs();
  const kinds = useMemo(() => new Set(files.map((f) => f.kind)), [files]);
  const [p, setP] = useState<ExportParams>(() => defaultParams(kinds));
  const [busy, setBusy] = useState(false);
  const [outcomes, setOutcomes] = useState<Outcome[]>([]);

  const set = <K extends keyof ExportParams>(k: K, v: ExportParams[K]) => setP((x) => ({ ...x, [k]: v }));
  const hasPdf = kinds.has("pdf") || kinds.has("email");
  const hasImage = kinds.has("image");
  const hasVideo = kinds.has("video");
  const hasAudio = kinds.has("audio") || hasVideo;
  const hasText = Array.from(kinds).some(isTextKind);
  const effects = meta?.effects ?? ["blackout", "pixelate", "blur", "whiteout"];
  const audioEffects = meta?.audio_effects ?? ["bleep", "mute", "noise"];
  const markable = Array.from(kinds).every((k) => k === "pdf" || k === "image");
  const marked = !!p.marked_copy && markable;
  const enhance = p.enhance ?? DEFAULT_ENHANCE;
  const setEnhance = (patch: Partial<EnhanceParams>) => set("enhance", { ...enhance, ...patch });
  const videoTranscript = files.some((f) => f.kind === "video" && f.has_transcript);

  const start = async () => {
    setBusy(true);
    try {
      const params = cleanExportParams(p, kinds);
      let ids: number[];
      if (files.length === 1) ids = [(await api.exportFile(files[0].id, params)).job_id];
      else ids = (await api.bulkExport(caseId, files.map((f) => f.id), params)).jobs;
      const initial: Outcome[] = ids.map((jobId, i) => ({ fileId: files[i]?.id ?? 0, jobId, status: "queued" }));
      setOutcomes(initial);
      let remaining = ids.length;
      ids.forEach((jobId, i) =>
        jobs.track(jobId, {
          label: files.length === 1 ? `Export of ${files[0].name}` : "Export",
          fileId: files[i]?.id,
          kind: "export",
          notify: false,
          onDone: async (j) => {
            let exp: ExportDetail | undefined;
            const exportId = j.result?.export_id;
            if (j.status === "done" && typeof exportId === "number") {
              exp = await api.getExport(exportId).catch(() => undefined);
            }
            setOutcomes((os) =>
              os.map((o) => (o.jobId === jobId ? { ...o, status: j.status, message: j.message, exp } : o)),
            );
            if (j.status === "error") toast.error(j.message || "export failed", `Export of ${files[i]?.name ?? "file"}`);
            else if (j.status === "done" && exp && isReviewCopy(exp)) toast.info(`Review copy of ${files[i]?.name ?? "file"} created — not for release`);
            else if (j.status === "done" && typeof j.result?.second_opinion_open === "number" && j.result.second_opinion_open > 0)
              // counts only: the found text itself is shown in the dialog, never in a notification
              toast.info(`${j.result.second_opinion_open} possible item(s) still readable in the export of ${files[i]?.name ?? "file"}`);
            else if (j.status === "done" && exp && !exp.verified)
              toast.error("verification failed — a supervisor must review", `Export of ${files[i]?.name ?? "file"}`);
            else if (j.status === "done") toast.success(`Export of ${files[i]?.name ?? "file"} verified`);
            remaining -= 1;
            if (remaining === 0) onDone?.();
          },
        }),
      );
    } catch (e) {
      toast.error(e, "Could not start export");
    } finally {
      setBusy(false);
    }
  };

  const started = outcomes.length > 0;
  const finishedAll = started && outcomes.every((o) => ["done", "error", "cancelled"].includes(o.status));

  return (
    <Modal
      title={files.length === 1 ? `Export “${files[0].name}”` : `Export ${files.length} files`}
      onClose={onClose}
      size="lg"
      busy={busy}
      footer={
        started ? (
          <button className="btn btn-primary" onClick={onClose}>
            {finishedAll ? "Close" : "Continue in background"}
          </button>
        ) : (
          <>
            <button className="btn" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button className={marked ? "btn btn-warn" : "btn btn-primary"} onClick={start} disabled={busy}>
              {busy ? <Spinner size={14} /> : marked ? <ClipboardCheck size={15} aria-hidden /> : <FileDown size={15} aria-hidden />}{" "}
              {marked ? "Create review copy" : "Export & verify"}
            </button>
          </>
        )
      }
    >
      {!started && (
        <div className="export-form">
          <p className="muted small">
            Redactions are applied permanently to a new copy (the original is kept), metadata is removed, and the result is
            independently re-checked for leaks before it can be released.
          </p>
          {(hasPdf || hasImage || hasVideo) && (
            <fieldset className="fieldset">
              <legend>All redactions</legend>
              <div className="form-grid">
                <Field
                  label={`Extra margin around redactions: ${Number(p.padding ?? 0).toFixed(1)} ${hasPdf && !hasImage && !hasVideo ? "pt" : hasPdf ? "pt / px" : "px"}`}
                  htmlFor="ex-pad"
                  hint="Grows every box so letter edges and anti-aliasing are covered. PDF points / image pixels."
                >
                  <div className="row gap-sm">
                    <input
                      id="ex-pad"
                      type="range"
                      min={0}
                      max={10}
                      step={0.5}
                      value={p.padding ?? 0}
                      onChange={(e) => set("padding", Number(e.target.value))}
                    />
                    <input
                      className="input-sm num-input"
                      type="number"
                      min={0}
                      max={10}
                      step={0.5}
                      aria-label="Extra margin"
                      value={p.padding ?? 0}
                      onChange={(e) => set("padding", Math.max(0, Math.min(10, Number(e.target.value) || 0)))}
                    />
                  </div>
                </Field>
                {markable && (
                  <div className="field">
                    <Switch
                      checked={marked}
                      onChange={(v) => set("marked_copy", v)}
                      label={<strong>Marked review copy</strong>}
                      hint="Outlines + labels, nothing removed — internal QC only. This is NOT a redacted release copy."
                    />
                  </div>
                )}
              </div>
              {marked && <ReviewCopyNotice />}
            </fieldset>
          )}
          {!marked && (
            <fieldset className="fieldset">
              <legend>Final check</legend>
              <Switch
                checked={!!p.second_opinion && so?.available !== false}
                disabled={so?.available === false}
                onChange={(v) => set("second_opinion", v)}
                label={<strong>Final check with Microsoft Presidio</strong>}
                hint={
                  so?.available === false
                    ? `Not available on this server${so.reason ? ` (${so.reason})` : ""}.`
                    : "Re-reads the released file with an independent detector (running locally) and lists anything that still looks personal."
                }
              />
            </fieldset>
          )}
          {hasPdf && !marked && (
            <fieldset className="fieldset">
              <legend>PDF</legend>
              <div className="form-grid">
                <Field label="Box label" htmlFor="ex-label">
                  <select
                    id="ex-label"
                    value={p.style?.label ?? "none"}
                    onChange={(e) => set("style", { ...p.style, label: e.target.value as "none" })}
                  >
                    <option value="none">None (solid box)</option>
                    <option value="entity">Type (e.g. “SSN”)</option>
                    <option value="exemption">Exemption code (e.g. “(b)(6)”)</option>
                    <option value="custom">Custom text</option>
                  </select>
                </Field>
                {p.style?.label === "custom" && (
                  <Field label="Custom label text" htmlFor="ex-custom">
                    <input
                      id="ex-custom"
                      value={p.style?.custom_text ?? ""}
                      onChange={(e) => set("style", { ...p.style, custom_text: e.target.value })}
                    />
                  </Field>
                )}
                <Field label="Bates prefix" htmlFor="ex-bates" hint="Leave empty for no Bates numbering.">
                  <input id="ex-bates" value={p.bates_prefix ?? ""} onChange={(e) => set("bates_prefix", e.target.value)} placeholder="e.g. SMITH-" />
                </Field>
                <Field label="Bates start number" htmlFor="ex-bates-start">
                  <input
                    id="ex-bates-start"
                    type="number"
                    min={1}
                    value={p.bates_start ?? 1}
                    onChange={(e) => set("bates_start", Math.max(1, Number(e.target.value) || 1))}
                    disabled={!p.bates_prefix}
                  />
                </Field>
                <Field label="Watermark" htmlFor="ex-wm">
                  <input id="ex-wm" value={p.watermark ?? ""} onChange={(e) => set("watermark", e.target.value)} placeholder="e.g. CONFIDENTIAL" />
                </Field>
                <Field label="Open password (optional)" htmlFor="ex-pw" hint="Not stored. Share it separately.">
                  <input id="ex-pw" type="password" autoComplete="new-password" value={p.password ?? ""} onChange={(e) => set("password", e.target.value)} />
                </Field>
                <label className="check span-2">
                  <input type="checkbox" checked={!!p.flatten} onChange={(e) => set("flatten", e.target.checked)} />
                  <span>Flatten pages to images (no selectable text remains anywhere)</span>
                </label>
              </div>
            </fieldset>
          )}
          {(hasImage || hasVideo) && !marked && (
            <fieldset className="fieldset">
              <legend>Images &amp; video</legend>
              <div className="form-grid">
                <Field label="Redaction effect" htmlFor="ex-effect">
                  <select id="ex-effect" value={p.effect} onChange={(e) => set("effect", e.target.value)}>
                    {effects.map((e) => (
                      <option key={e} value={e}>
                        {titleCase(e)}
                      </option>
                    ))}
                  </select>
                </Field>
                {hasImage && (
                  <Field label="Faces effect" htmlFor="ex-face" hint="Optional different effect for faces.">
                    <select id="ex-face" value={p.face_effect ?? ""} onChange={(e) => set("face_effect", e.target.value || null)}>
                      <option value="">Same as above</option>
                      {effects.map((e) => (
                        <option key={e} value={e}>
                          {titleCase(e)}
                        </option>
                      ))}
                    </select>
                  </Field>
                )}
                {hasVideo && (
                  <label className="check span-2">
                    <input type="checkbox" checked={!!p.burn_captions} onChange={(e) => set("burn_captions", e.target.checked)} />
                    <span>
                      Burn redacted captions into the video
                      <span className="field-hint block">
                        {videoTranscript ? "The redacted transcript is drawn as subtitles." : "Needs a transcript (analyze the video with audio on)."}
                      </span>
                    </span>
                  </label>
                )}
              </div>
              <details className="enhance" open={!isDefaultEnhance(p.enhance)}>
                <summary>
                  Enhance (dark or blurry footage / photos){!isDefaultEnhance(p.enhance) && <span className="badge badge-info tiny">changed</span>}
                </summary>
                <div className="enhance-grid">
                  <EnhanceSlider id="en-b" label="Brightness" min={-1} max={1} step={0.05} value={enhance.brightness} onChange={(v) => setEnhance({ brightness: v })} />
                  <EnhanceSlider id="en-c" label="Contrast" min={0.5} max={2} step={0.05} value={enhance.contrast} onChange={(v) => setEnhance({ contrast: v })} />
                  <EnhanceSlider id="en-s" label="Sharpen" min={0} max={2} step={0.1} value={enhance.sharpen} onChange={(v) => setEnhance({ sharpen: v })} />
                  <EnhanceSlider id="en-g" label="Gamma" min={0.3} max={3} step={0.05} value={enhance.gamma} onChange={(v) => setEnhance({ gamma: v })} />
                  <label className="check">
                    <input type="checkbox" checked={enhance.denoise} onChange={(e) => setEnhance({ denoise: e.target.checked })} />
                    <span>Reduce noise (slower)</span>
                  </label>
                  <button type="button" className="btn btn-xs btn-ghost" disabled={isDefaultEnhance(p.enhance)} onClick={() => set("enhance", null)}>
                    <RotateCcw size={12} aria-hidden /> Reset
                  </button>
                </div>
              </details>
            </fieldset>
          )}
          {hasAudio && (
            <fieldset className="fieldset">
              <legend>Audio</legend>
              <div className="form-grid">
                <Field label="Spoken PII effect" htmlFor="ex-aeffect">
                  <select id="ex-aeffect" value={p.audio_effect} onChange={(e) => set("audio_effect", e.target.value)}>
                    {audioEffects.map((e) => (
                      <option key={e} value={e}>
                        {titleCase(e)}
                      </option>
                    ))}
                  </select>
                </Field>
                <label className="check">
                  <input type="checkbox" checked={!!p.voice_disguise} onChange={(e) => set("voice_disguise", e.target.checked)} />
                  <span>Disguise voices</span>
                </label>
                {hasVideo && (
                  <label className="check">
                    <input type="checkbox" checked={!!p.mute_audio} onChange={(e) => set("mute_audio", e.target.checked)} />
                    <span>Remove the video's audio entirely</span>
                  </label>
                )}
              </div>
            </fieldset>
          )}
          {hasText && (
            <fieldset className="fieldset">
              <legend>Office &amp; text documents</legend>
              <Field label="Replacement text" htmlFor="ex-tstyle">
                <select id="ex-tstyle" value={p.text_style} onChange={(e) => set("text_style", e.target.value as "block")}>
                  <option value="block">Blocks (█████)</option>
                  <option value="entity">[TYPE] label</option>
                  <option value="exemption">[EXEMPTION] code</option>
                </select>
              </Field>
            </fieldset>
          )}
        </div>
      )}
      {started && (
        <div className="job-progress-list">
          {outcomes.map((o) => {
            const f = files.find((x) => x.id === o.fileId);
            const live = jobs.job(o.jobId);
            const status = o.status !== "queued" ? o.status : (live?.status ?? "queued");
            return (
              <div key={o.jobId} className="job-progress">
                <div className="row space">
                  <span className="strong">{f?.name ?? `File ${o.fileId}`}</span>
                  <span className="muted small">{statusLabel(status)}</span>
                </div>
                {!["done", "error", "cancelled"].includes(o.status) && (
                  <>
                    <ProgressBar value={live?.progress ?? 0} indeterminate={!live || live.status === "queued"} />
                    {live?.message && <div className="muted small">{live.message}</div>}
                  </>
                )}
                {o.status === "error" && <div className="notice notice-error">{o.message || "Export failed"}</div>}
                {o.exp && (
                  <>
                    {isReviewCopy(o.exp) ? (
                      <ReviewCopyNotice />
                    ) : (
                      <>
                        <VerificationResult verification={o.exp.report?.verification} verified={o.exp.verified} />
                        <FinalCheckResult report={o.exp.report?.second_opinion} fileId={o.fileId} />
                      </>
                    )}
                    <ExportDownloads exp={o.exp} file={f} />
                    <div className="muted tiny mono">SHA-256 {o.exp.sha256}</div>
                  </>
                )}
              </div>
            );
          })}
        </div>
      )}
    </Modal>
  );
}

/** Latest release export of a file (review copies are skipped; see lib/exports). */
export const latestExport = latestReleaseExport;

function EnhanceSlider({
  id,
  label,
  min,
  max,
  step,
  value,
  onChange,
}: {
  id: string;
  label: string;
  min: number;
  max: number;
  step: number;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="enhance-row" htmlFor={id}>
      <span>{label}</span>
      <input id={id} type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
      <span className="mono tiny">{value.toFixed(2)}</span>
    </label>
  );
}

export function useExportDetail(exportId: number | undefined) {
  const [exp, setExp] = useState<ExportDetail | null>(null);
  useEffect(() => {
    if (!exportId) return;
    let alive = true;
    api.getExport(exportId).then((e) => alive && setExp(e), () => alive && setExp(null));
    return () => {
      alive = false;
    };
  }, [exportId]);
  return exp;
}
