import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { CheckCircle2, ChevronLeft, ChevronRight, Download, Eye, ShieldAlert, ZoomIn, ZoomOut } from "lucide-react";
import * as api from "../api";
import { useToast } from "../components/Toast";
import { EmptyState, ErrorState, KindIcon, Loading, Spinner } from "../components/ui";
import { ExportDownloads, ReviewCopyNotice, VerificationResult } from "../components/ExportDialog";
import { isReviewCopy, releasedExports } from "../lib/exports";
import { FinalCheckResult } from "../components/FinalCheck";
import { canSeeOriginals, useUser } from "../auth";
import { useHotkeys } from "../lib/hotkeys";
import { formatBytes, formatDate } from "../lib/format";
import type { ExportDetail, FileRecord } from "../types";

/** What a viewer sees for a file: its redacted exports only. */
export function ViewerFileView({ file }: { file: FileRecord }) {
  const toast = useToast();
  // review copies show the original content: never offered to viewers
  const exports = releasedExports(file.exports).sort((a, b) => b.id - a.id);
  return (
    <div className="page">
      <Link to={`/cases/${file.case_id}`} className="back-link">
        <ChevronLeft size={15} aria-hidden /> Case
      </Link>
      <div className="page-header">
        <div className="row gap-sm">
          <KindIcon kind={file.kind} size={20} />
          <h1>{file.name}</h1>
        </div>
      </div>
      <p className="muted">Your role can see redacted exports only. Originals and detection lists are not available.</p>
      {exports.length === 0 ? (
        <EmptyState title="No redacted export yet" />
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Export</th>
                <th>Verified</th>
                <th>Size</th>
                <th>Created</th>
                <th className="actions-col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {exports.map((e) => (
                <tr key={e.id}>
                  <td className="mono small">{e.name}</td>
                  <td>{e.verified ? <span className="ok-text">Verified</span> : <span className="bad-text">Failed</span>}</td>
                  <td>{formatBytes(e.size)}</td>
                  <td>{formatDate(e.created_at, true)}</td>
                  <td className="actions-col">
                    {e.name.toLowerCase().endsWith(".pdf") && (
                      <Link className="btn btn-sm" to={`/exports/${e.id}`}>
                        <Eye size={14} aria-hidden /> View
                      </Link>
                    )}
                    <button className="btn btn-sm" onClick={() => api.downloadExport(e.id, e.name).catch((er) => toast.error(er, "Download failed"))}>
                      <Download size={14} aria-hidden /> Download
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** Page-by-page view of a redacted PDF export (`GET /api/exports/{id}/pages/{n}.png`). */
export function ExportViewerPage() {
  const params = useParams();
  const exportId = Number(params.exportId);
  const canReview = canSeeOriginals(useUser());
  const [exp, setExp] = useState<ExportDetail | null>(null);
  const [file, setFile] = useState<FileRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [width, setWidth] = useState(820);
  const [loaded, setLoaded] = useState<string | null>(null);
  const [imgError, setImgError] = useState(false);

  useEffect(() => {
    api.getExport(exportId).then(
      (e) => {
        setExp(e);
        api.getFile(e.file_id).then(setFile, () => undefined);
      },
      (e) => setError(e instanceof Error ? e.message : "could not load export"),
    );
  }, [exportId]);

  useEffect(() => setImgError(false), [page, exportId]);

  const isPdf = !!exp?.name.toLowerCase().endsWith(".pdf");
  const pageCount = (exp?.report?.verification?.pages as number | undefined) ?? (exp?.report?.pages as number | undefined) ?? 0;
  const protectedPdf = !!exp?.settings?.password_protected;

  useHotkeys({
    ArrowLeft: () => setPage((p) => Math.max(0, p - 1)),
    ArrowRight: () => setPage((p) => (pageCount ? Math.min(pageCount - 1, p + 1) : p + 1)),
  });

  if (error)
    return (
      <div className="page">
        <ErrorState message={error} />
      </div>
    );
  if (!exp) return <Loading label="Loading export…" />;
  const url = api.urls.exportPage(exp.id, page, 110);

  return (
    <div className="page export-viewer">
      <Link to={file ? `/cases/${file.case_id}` : "/cases"} className="back-link">
        <ChevronLeft size={15} aria-hidden /> {file ? "Case" : "Cases"}
      </Link>
      <div className="page-header">
        <div>
          <h1 className="row gap-sm">
            {isReviewCopy(exp) ? null : exp.verified ? (
              <CheckCircle2 className="ok-text" size={20} aria-hidden />
            ) : (
              <ShieldAlert className="bad-text" size={20} aria-hidden />
            )}
            {exp.name}
          </h1>
          <p className="muted small">
            {isReviewCopy(exp) ? "Review copy — not for release" : "Redacted export"} · {formatBytes(exp.size)} · {formatDate(exp.created_at, true)} · SHA-256 <span className="mono">{exp.sha256.slice(0, 16)}…</span>
          </p>
        </div>
        <ExportDownloads exp={exp} file={file ?? undefined} />
      </div>
      {isReviewCopy(exp) ? (
        <ReviewCopyNotice />
      ) : (
        <>
          <VerificationResult verification={exp.report?.verification} verified={exp.verified} />
          <FinalCheckResult report={exp.report?.second_opinion} fileId={canReview ? exp.file_id : undefined} />
        </>
      )}
      {!isPdf && <EmptyState title="Preview is available for PDF exports">Download the file to view it.</EmptyState>}
      {isPdf && protectedPdf && <EmptyState title="Password-protected export">Download the file and open it with its password.</EmptyState>}
      {isPdf && !protectedPdf && (
        <div className="export-pages">
          <div className="viewer-toolbar" role="toolbar" aria-label="Page navigation">
            <button className="icon-btn" disabled={page === 0} onClick={() => setPage(page - 1)} aria-label="Previous page">
              <ChevronLeft size={16} />
            </button>
            <span className="small">
              Page {page + 1}
              {pageCount ? ` of ${pageCount}` : ""}
            </span>
            <button
              className="icon-btn"
              disabled={pageCount > 0 && page >= pageCount - 1}
              onClick={() => setPage(page + 1)}
              aria-label="Next page"
            >
              <ChevronRight size={16} />
            </button>
            <span className="toolbar-spacer" />
            <button className="icon-btn" onClick={() => setWidth((w) => Math.max(400, w - 120))} aria-label="Zoom out">
              <ZoomOut size={16} />
            </button>
            <button className="icon-btn" onClick={() => setWidth((w) => Math.min(1800, w + 120))} aria-label="Zoom in">
              <ZoomIn size={16} />
            </button>
          </div>
          <div className="export-page-frame">
            {loaded !== url && !imgError && (
              <div className="page-loading">
                <Spinner size={22} label="Rendering page" />
              </div>
            )}
            {imgError ? (
              <div className="pad text-bad">This page could not be displayed.</div>
            ) : (
              <img
                key={url}
                src={url}
                alt={`Redacted page ${page + 1}`}
                style={{ width }}
                onLoad={() => setLoaded(url)}
                onError={() => setImgError(true)}
                draggable={false}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
