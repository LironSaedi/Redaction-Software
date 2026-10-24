import { useState } from "react";
import { Link } from "react-router-dom";
import {
  BadgeCheck,
  CheckCircle2,
  ChevronLeft,
  ClipboardCheck,
  Download,
  FileDown,
  FileSpreadsheet,
  Keyboard,
  Redo2,
  ScanSearch,
  Undo2,
  XCircle,
} from "lucide-react";
import * as api from "../../api";
import { useToast } from "../../components/Toast";
import { KindIcon, ProgressBar, Spinner, StatusBadge } from "../../components/ui";
import { formatDate, KIND_LABELS } from "../../lib/format";
import { latestExport, latestReviewCopy, REVIEW_COPY_LABEL } from "../../lib/exports";
import type { HistorySnapshot } from "../../lib/history";
import type { FileRecord, Job } from "../../types";

const MOD = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl+";

interface Props {
  file: FileRecord;
  caseName: string | null;
  job: Job | undefined;
  history: HistorySnapshot;
  onUndo: () => void;
  onRedo: () => void;
  onHelp: () => void;
  onAnalyze: () => void;
  onApprove: () => void;
  onExport: () => void;
  analyzed: boolean;
  canExport: boolean;
  redactor: boolean;
  supervisor: boolean;
}

function jobVerb(kind: string): string {
  if (kind === "export") return "Exporting";
  if (kind === "translate") return "Translating";
  return "Analyzing";
}

export function ReviewHeader(p: Props) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const { file, job } = p;
  const exp = latestExport(file);
  const review = latestReviewCopy(file);
  const showReview = review && (!exp || review.id > exp.id);

  const download = async (what: string, fn: () => Promise<void>) => {
    setBusy(what);
    try {
      await fn();
    } catch (e) {
      toast.error(e, "Download failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <header className="review-header">
      <div className="review-title">
        <Link to={`/cases/${file.case_id}`} className="back-link" data-tip="Back to the case">
          <ChevronLeft size={15} aria-hidden /> <span className="truncate">{p.caseName ?? "Case"}</span>
        </Link>
        <div className="row gap-sm">
          <KindIcon kind={file.kind} size={18} />
          <h1 className="truncate" title={file.name}>
            {file.name}
          </h1>
          <StatusBadge status={file.status} />
          <span className="muted small nowrap">{KIND_LABELS[file.kind] ?? file.kind}</span>
        </div>
      </div>
      {job && (
        <div className="review-job" role="status">
          <span className="small truncate">
            {jobVerb(job.kind)}: {job.message || "queued"}
          </span>
          <ProgressBar value={job.progress} indeterminate={job.status === "queued"} label="Job progress" />
        </div>
      )}
      <div className="review-actions">
        {p.redactor && (
          <div className="btn-group" role="group" aria-label="History">
            <button
              className="icon-btn"
              onClick={p.onUndo}
              disabled={!p.history.canUndo}
              aria-label={p.history.undoLabel ? `Undo ${p.history.undoLabel}` : "Undo"}
              data-tip={p.history.undoLabel ? `Undo: ${p.history.undoLabel} (${MOD}Z)` : `Nothing to undo (${MOD}Z)`}
            >
              {p.history.busy ? <Spinner size={15} /> : <Undo2 size={17} />}
            </button>
            <button
              className="icon-btn"
              onClick={p.onRedo}
              disabled={!p.history.canRedo}
              aria-label={p.history.redoLabel ? `Redo ${p.history.redoLabel}` : "Redo"}
              data-tip={p.history.redoLabel ? `Redo: ${p.history.redoLabel} (${MOD}⇧Z)` : `Nothing to redo (${MOD}⇧Z)`}
            >
              <Redo2 size={17} />
            </button>
          </div>
        )}
        <button className="icon-btn" onClick={p.onHelp} aria-label="Keyboard shortcuts" data-tip="Keyboard shortcuts (?)">
          <Keyboard size={17} />
        </button>
        <span className="divider-v" aria-hidden />
        {p.redactor && p.analyzed && (
          <button
            className="btn btn-sm btn-ghost"
            aria-label="Download AI confidence report (CSV)"
            onClick={() => download("conf", () => api.downloadConfidenceReport(file.id))}
            disabled={busy !== null}
            data-tip="Every finding with its type, confidence, detector, decision and reason (CSV, no values)"
          >
            {busy === "conf" ? <Spinner size={14} /> : <FileSpreadsheet size={14} aria-hidden />}
            <span className="hide-narrow">Confidence report</span>
          </button>
        )}
        {p.redactor && (
          <button className="btn btn-sm" onClick={p.onAnalyze} disabled={!!job} aria-label={p.analyzed ? "Re-analyze" : "Analyze"}>
            <ScanSearch size={14} aria-hidden /> <span className="hide-narrow">{p.analyzed ? "Re-analyze" : "Analyze"}</span>
          </button>
        )}
        {p.supervisor && file.status !== "approved" && p.analyzed && (
          <button className="btn btn-sm" onClick={p.onApprove} data-tip="Mark as approved for release" aria-label="Approve for release">
            <BadgeCheck size={14} aria-hidden /> <span className="hide-narrow">Approve</span>
          </button>
        )}
        {showReview && review && (
          <button
            className="btn btn-sm btn-warn-ghost"
            aria-label={`Download the review copy (${REVIEW_COPY_LABEL})`}
            onClick={() => download("review", () => api.downloadExport(review.id, review.name))}
            disabled={busy !== null}
            data-tip={`${REVIEW_COPY_LABEL}: outlines and labels only, nothing removed (${formatDate(review.created_at, true)})`}
          >
            {busy === "review" ? <Spinner size={14} /> : <ClipboardCheck size={14} aria-hidden />}
            <span className="hide-narrow">Review copy</span>
          </button>
        )}
        {exp && (
          <button
            className="btn btn-sm"
            aria-label={`Download the latest export (${exp.verified ? "verified" : "verification failed"})`}
            onClick={() => download("exp", () => api.downloadExport(exp.id, exp.name))}
            disabled={busy !== null}
            data-tip={`Latest redacted export, ${formatDate(exp.created_at, true)} — ${exp.verified ? "verified" : "verification FAILED"}${
              typeof exp.second_opinion_open === "number"
                ? exp.second_opinion_open
                  ? `; final check: ${exp.second_opinion_open} possible item(s) still readable`
                  : "; final check passed"
                : ""
            }`}
          >
            {busy === "exp" ? (
              <Spinner size={14} />
            ) : exp.verified ? (
              <CheckCircle2 size={14} className="ok-text" aria-label="verified" />
            ) : (
              <XCircle size={14} className="bad-text" aria-label="verification failed" />
            )}
            <Download size={14} aria-hidden /> <span className="hide-narrow">Latest export</span>
          </button>
        )}
        {p.redactor && (
          <button className="btn btn-sm btn-primary" onClick={p.onExport} disabled={!p.canExport || !!job} data-tip={p.canExport ? "Export & verify" : "Analyze first"}>
            <FileDown size={14} aria-hidden /> Export
          </button>
        )}
      </div>
    </header>
  );
}
