import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  CheckCircle2,
  Combine,
  CornerDownRight,
  Download,
  Eye,
  FileDown,
  FolderUp,
  ScanSearch,
  Trash2,
  Upload,
  XCircle,
} from "lucide-react";
import * as api from "../../api";
import { canSeeOriginals, hasRole, useUser } from "../../auth";
import { useJobs } from "../../jobs";
import { useToast } from "../../components/Toast";
import { AnalyzeDialog } from "../../components/AnalyzeDialog";
import { ExportDialog } from "../../components/ExportDialog";
import { isReviewCopy, latestExport, latestReviewCopy, releasedExports, REVIEW_COPY_LABEL } from "../../lib/exports";
import { ConfirmDialog, EmptyState, KindIcon, Modal, ProgressBar, Spinner, StatusBadge } from "../../components/ui";
import { KIND_LABELS, formatBytes, formatDate, formatDuration } from "../../lib/format";
import type { CaseDetail, CaseReport, FileRecord, UploadResult } from "../../types";

/** Supported formats, shown in the drop zone. Mailboxes (MBOX / PST / OST) become one email file per message. */
export const SUPPORTED_FORMATS_HINT =
  "PDF, Office (Word, PowerPoint, Excel), Email & mailboxes (EML, MSG, MBOX, PST), images & scans, video and audio.";

const ACCEPT =
  ".pdf,.png,.jpg,.jpeg,.webp,.bmp,.heic,.tif,.tiff,.gif,.mp4,.mov,.avi,.mkv,.m4v,.wmv,.webm,.mpg,.mpeg,.ts,.3gp,.wav,.mp3,.m4a,.aac,.flac,.ogg,.wma,.aiff,.aif,.opus,.docx,.docm,.pptx,.xlsx,.xlsm,.eml,.msg,.mbox,.mbx,.pst,.ost,.txt,.csv,.md,.json,.log,.html,.htm,.xml,.rtf,.tsv";

/** Parents first, each followed by its attachments (parent_id), keeping upload order. */
export function orderFileTree(files: FileRecord[]): { file: FileRecord; depth: number }[] {
  const byParent = new Map<number, FileRecord[]>();
  const ids = new Set(files.map((f) => f.id));
  const roots: FileRecord[] = [];
  for (const f of files) {
    if (f.parent_id != null && ids.has(f.parent_id)) {
      if (!byParent.has(f.parent_id)) byParent.set(f.parent_id, []);
      byParent.get(f.parent_id)!.push(f);
    } else roots.push(f);
  }
  const out: { file: FileRecord; depth: number }[] = [];
  const walk = (f: FileRecord, depth: number) => {
    out.push({ file: f, depth });
    for (const c of byParent.get(f.id) ?? []) walk(c, depth + 1);
  };
  roots.forEach((r) => walk(r, 0));
  return out;
}

function sizeCell(f: FileRecord): string {
  if (f.kind === "video" || f.kind === "audio") return f.duration > 0 ? formatDuration(f.duration) : formatBytes(f.size);
  if (f.page_count) return `${f.page_count} page${f.page_count === 1 ? "" : "s"}`;
  return formatBytes(f.size);
}

function UploadZone({ caseId, onUploaded }: { caseId: number; onUploaded: (r: UploadResult) => void }) {
  const toast = useToast();
  const inputRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [errors, setErrors] = useState<UploadResult["errors"]>([]);

  const upload = async (list: FileList | File[]) => {
    const files = Array.from(list);
    if (!files.length) return;
    setProgress(0);
    setErrors([]);
    try {
      const r = await api.uploadFiles(caseId, files, setProgress);
      setErrors(r.errors);
      if (r.files.length) toast.success(`${r.files.length} file${r.files.length > 1 ? "s" : ""} added to the case`);
      if (r.errors.length) toast.error(`${r.errors.length} file${r.errors.length > 1 ? "s were" : " was"} rejected — see the details below`);
      onUploaded(r);
    } catch (e) {
      // e.g. a PST mailbox when the server lacks `readpst`: the server's explanation is shown verbatim
      if (e instanceof api.ApiError && e.status >= 400 && e.status < 500 && e.status !== 401 && e.detail) {
        setErrors([{ name: files.length === 1 ? files[0].name : `${files.length} files`, error: e.detail }]);
        toast.error("The upload was rejected — see the details below");
      } else toast.error(e, "Upload failed");
    } finally {
      setProgress(null);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    if (progress !== null) return;
    upload(e.dataTransfer.files);
  };

  return (
    <div>
      <div
        className={`dropzone ${over ? "over" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
      >
        {progress === null ? (
          <>
            <FolderUp size={22} aria-hidden />
            <div>
              <strong>Drop files here</strong> or{" "}
              <button className="link-btn" onClick={() => inputRef.current?.click()}>
                choose files
              </button>
              <div className="muted small">{SUPPORTED_FORMATS_HINT} Files are encrypted at rest.</div>
            </div>
          </>
        ) : (
          <div className="upload-progress">
            <div className="row gap-sm">
              <Spinner size={15} /> {progress < 1 ? `Uploading… ${Math.round(progress * 100)}%` : "Processing on the server…"}
            </div>
            <ProgressBar value={progress} label="Upload progress" indeterminate={progress >= 1} />
          </div>
        )}
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPT}
          className="sr-only"
          aria-label="Choose files to upload"
          onChange={(e) => e.target.files && upload(e.target.files)}
        />
      </div>
      {errors.length > 0 && (
        <div className="notice notice-error" role="alert">
          <strong>Some files were not accepted:</strong>
          <ul>
            {errors.map((er, i) => (
              <li key={i}>
                {er.name}: {er.error}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function ViewerFiles({ files }: { files: FileRecord[] }) {
  const toast = useToast();
  // viewers only receive verified release exports (the server refuses the others; review copies show originals)
  const withExports = files
    .map((f) => ({ ...f, exports: releasedExports(f.exports) }))
    .filter((f) => f.exports.length);
  const pending = files.filter((f) => f.exports.some((e) => !isReviewCopy(e)) && !releasedExports(f.exports).length).length;
  if (!withExports.length)
    return (
      <EmptyState icon={<FileDown size={30} />} title="No released files yet">
        Redacted exports appear here once the review team has produced and verified them.
        {pending > 0 && ` ${pending} file(s) are awaiting supervisor review.`}
      </EmptyState>
    );
  return (
    <>
    {pending > 0 && (
      <div className="notice notice-info small">
        {pending} file(s) have exports awaiting supervisor review and are not released yet.
      </div>
    )}
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>File</th>
            <th>Redacted export</th>
            <th>Verified</th>
            <th>Created</th>
            <th className="actions-col">Actions</th>
          </tr>
        </thead>
        <tbody>
          {withExports.flatMap((f) =>
            [...f.exports]
              .sort((a, b) => b.id - a.id)
              .map((e, i) => (
                <tr key={e.id}>
                  <td>
                    {i === 0 ? (
                      <span className="row gap-sm">
                        <KindIcon kind={f.kind} /> {f.name}
                      </span>
                    ) : (
                      <span className="muted small">earlier export</span>
                    )}
                  </td>
                  <td className="mono small">{e.name}</td>
                  <td>
                    {e.verified ? (
                      <span className="ok-text">
                        <CheckCircle2 size={15} aria-hidden /> Verified
                      </span>
                    ) : (
                      <span className="bad-text">
                        <XCircle size={15} aria-hidden /> Failed
                      </span>
                    )}
                  </td>
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
              )),
          )}
        </tbody>
      </table>
    </div>
    </>
  );
}

interface Props {
  caseData: CaseDetail;
  report: CaseReport | null;
  reload: () => void;
}

export function FilesTab({ caseData, report, reload }: Props) {
  const user = useUser();
  const toast = useToast();
  const jobs = useJobs();
  const navigate = useNavigate();
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [analyzeFiles, setAnalyzeFiles] = useState<FileRecord[] | null>(null);
  const [exportFiles, setExportFiles] = useState<FileRecord[] | null>(null);
  const [toDelete, setToDelete] = useState<FileRecord | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [merge, setMerge] = useState<FileRecord[] | null>(null);
  const [mergeName, setMergeName] = useState("merged.pdf");
  const [merging, setMerging] = useState(false);

  const files = caseData.files;
  const tree = useMemo(() => orderFileTree(files), [files]);
  const redactions = useMemo(() => new Map((report?.files ?? []).map((r) => [r.file_id, r.redactions])), [report]);
  const caseJobs = jobs.active.filter((j) => j.case_id === caseData.id);
  const activeKey = caseJobs.map((j) => j.id).join(",");
  const prevKey = useRef(activeKey);

  // a job for this case left the active list (possibly started elsewhere): refresh statuses
  useEffect(() => {
    const before = prevKey.current.split(",").filter(Boolean);
    const now = new Set(activeKey.split(",").filter(Boolean));
    prevKey.current = activeKey;
    if (before.some((id) => !now.has(id))) reload();
  }, [activeKey, reload]);

  useEffect(() => {
    setSelected((s) => new Set(Array.from(s).filter((id) => files.some((f) => f.id === id))));
  }, [files]);

  if (!canSeeOriginals(user)) return <ViewerFiles files={files} />;

  const redactor = hasRole(user, "redactor");
  const supervisor = hasRole(user, "supervisor");
  const selFiles = files.filter((f) => selected.has(f.id));
  const allSelected = files.length > 0 && selected.size === files.length;
  const exportable = (f: FileRecord) => f.has_detections || f.kind === "video";

  const download = (f: FileRecord) => {
    const e = latestExport(f);
    if (e) api.downloadExport(e.id, e.name).catch((er) => toast.error(er, "Download failed"));
  };

  const doDelete = async () => {
    if (!toDelete) return;
    setDeleting(true);
    try {
      await api.deleteFile(toDelete.id);
      toast.success("File and all its working copies were destroyed");
      setToDelete(null);
      reload();
    } catch (e) {
      toast.error(e, "Delete failed");
    } finally {
      setDeleting(false);
    }
  };

  const doMerge = async () => {
    if (!merge) return;
    setMerging(true);
    try {
      await api.mergePdfs(caseData.id, merge.map((f) => f.id), mergeName.trim() || "merged.pdf");
      toast.success("Merged PDF added to the case");
      setMerge(null);
      setSelected(new Set());
      reload();
    } catch (e) {
      toast.error(e, "Merge failed");
    } finally {
      setMerging(false);
    }
  };

  return (
    <div className="files-tab">
      {redactor && <UploadZone caseId={caseData.id} onUploaded={() => reload()} />}

      {selected.size > 0 && (
        <div className="bulk-bar" role="region" aria-label="Bulk actions">
          <strong>{selected.size} selected</strong>
          <button className="btn btn-sm btn-primary" onClick={() => setAnalyzeFiles(selFiles)}>
            <ScanSearch size={14} aria-hidden /> Analyze selected
          </button>
          <button
            className="btn btn-sm"
            onClick={() => {
              const ok = selFiles.filter(exportable);
              if (!ok.length) toast.error("Analyze the selected files before exporting");
              else setExportFiles(ok);
            }}
          >
            <FileDown size={14} aria-hidden /> Export selected
          </button>
          {selFiles.filter((f) => f.kind === "pdf").length >= 2 && (
            <button className="btn btn-sm" onClick={() => setMerge(selFiles.filter((f) => f.kind === "pdf"))}>
              <Combine size={14} aria-hidden /> Merge PDFs
            </button>
          )}
          <button className="btn btn-sm btn-ghost" onClick={() => setSelected(new Set())}>
            Clear selection
          </button>
        </div>
      )}

      {files.length === 0 ? (
        <EmptyState icon={<Upload size={30} />} title="No files in this case">
          Upload documents, images, video or audio to start reviewing.
        </EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="table files-table">
            <thead>
              <tr>
                <th className="check-col">
                  <input
                    type="checkbox"
                    aria-label="Select all files"
                    checked={allSelected}
                    onChange={(e) => setSelected(e.target.checked ? new Set(files.map((f) => f.id)) : new Set())}
                  />
                </th>
                <th>Name</th>
                <th>Type</th>
                <th>Length</th>
                <th>Status</th>
                <th className="num">Redactions</th>
                <th>Last export</th>
                <th className="actions-col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {tree.map(({ file: f, depth }) => {
                const job = jobs.jobForFile(f.id);
                const exp = latestExport(f);
                return (
                  <tr key={f.id} className={selected.has(f.id) ? "selected" : ""}>
                    <td className="check-col">
                      <input
                        type="checkbox"
                        aria-label={`Select ${f.name}`}
                        checked={selected.has(f.id)}
                        onChange={(e) => {
                          const s = new Set(selected);
                          if (e.target.checked) s.add(f.id);
                          else s.delete(f.id);
                          setSelected(s);
                        }}
                      />
                    </td>
                    <td>
                      <div className="file-name" style={{ paddingLeft: depth * 22 }}>
                        {depth > 0 && <CornerDownRight size={14} className="muted" aria-label="attachment of" />}
                        <KindIcon kind={f.kind} />
                        <Link to={`/files/${f.id}`} className="strong">
                          {f.name}
                        </Link>
                      </div>
                      {f.status === "error" && f.error && <div className="small text-bad">{f.error}</div>}
                    </td>
                    <td>{KIND_LABELS[f.kind] ?? f.kind}</td>
                    <td className="muted">{sizeCell(f)}</td>
                    <td className="status-cell">
                      {job ? (
                        <div className="inline-job" title={job.message}>
                          <span className="small">{job.kind === "export" ? "Exporting" : "Analyzing"}</span>
                          <ProgressBar value={job.progress} label={`${job.kind} progress`} indeterminate={job.status === "queued"} />
                        </div>
                      ) : f.status === "analyzing" ? (
                        <span
                          className="badge badge-warn"
                          title="No analysis is running for this file any more — the last run probably failed. Analyze it again."
                        >
                          Analysis interrupted
                        </span>
                      ) : (
                        <StatusBadge status={f.status} />
                      )}
                    </td>
                    <td className="num">{f.has_detections ? (redactions.get(f.id) ?? "—") : "—"}</td>
                    <td>
                      {exp ? (
                        <span className={exp.verified ? "ok-text" : "bad-text"} data-tip={exp.verified ? "Verified" : "Verification failed"}>
                          {exp.verified ? <CheckCircle2 size={15} aria-hidden /> : <XCircle size={15} aria-hidden />}
                          <span className="sr-only">{exp.verified ? "verified" : "verification failed"}</span>{" "}
                          {formatDate(exp.created_at)}
                          {typeof exp.second_opinion_open === "number" && exp.second_opinion_open > 0 && (
                            <span className="badge badge-warn tiny" data-tip="Final check (Microsoft Presidio): possible personal items still readable — see the case report">
                              {exp.second_opinion_open} still readable
                            </span>
                          )}
                        </span>
                      ) : (
                        !latestReviewCopy(f) && <span className="muted">—</span>
                      )}
                      {(() => {
                        const rc = latestReviewCopy(f);
                        return rc && (!exp || rc.id > exp.id) ? (
                          <span className="badge badge-warn tiny block-badge" data-tip={`${REVIEW_COPY_LABEL} · ${formatDate(rc.created_at)}`}>
                            {REVIEW_COPY_LABEL}
                          </span>
                        ) : null;
                      })()}
                    </td>
                    <td className="actions-col">
                      <div className="row-actions">
                        <button className="btn btn-sm" onClick={() => navigate(`/files/${f.id}`)} title="Open the review workspace">
                          <Eye size={14} aria-hidden /> Review
                        </button>
                        {redactor && (
                          <button
                            className="icon-btn"
                            data-tip="Analyze"
                            aria-label={`Analyze ${f.name}`}
                            disabled={!!job}
                            onClick={() => setAnalyzeFiles([f])}
                          >
                            <ScanSearch size={16} />
                          </button>
                        )}
                        {redactor && (
                          <button
                            className="icon-btn"
                            data-tip={exportable(f) ? "Export" : "Analyze first"}
                            aria-label={`Export ${f.name}`}
                            disabled={!exportable(f) || !!job}
                            onClick={() => setExportFiles([f])}
                          >
                            <FileDown size={16} />
                          </button>
                        )}
                        <button
                          className="icon-btn"
                          data-tip={exp ? "Download the latest redacted export" : latestReviewCopy(f) ? "No release export yet (only a review copy)" : "No export yet"}
                          aria-label={`Download latest export of ${f.name}`}
                          disabled={!exp}
                          onClick={() => download(f)}
                        >
                          <Download size={16} />
                        </button>
                        {supervisor && (
                          <button className="icon-btn danger" data-tip="Delete" aria-label={`Delete ${f.name}`} onClick={() => setToDelete(f)}>
                            <Trash2 size={16} />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {analyzeFiles && (
        <AnalyzeDialog
          caseId={caseData.id}
          files={analyzeFiles}
          defaultProfile={caseData.default_profile}
          onClose={() => {
            setAnalyzeFiles(null);
            reload();
          }}
          onDone={reload}
        />
      )}
      {exportFiles && (
        <ExportDialog
          caseId={caseData.id}
          files={exportFiles}
          onClose={() => {
            setExportFiles(null);
            reload();
          }}
          onDone={reload}
        />
      )}
      {toDelete && (
        <ConfirmDialog
          title="Delete file?"
          danger
          busy={deleting}
          confirmLabel="Delete permanently"
          message={
            <>
              <p>
                <strong>{toDelete.name}</strong>, its working copies, detections and all {toDelete.exports.length} export(s) will
                be destroyed. This cannot be undone; the deletion is recorded in the audit log.
              </p>
            </>
          }
          onConfirm={doDelete}
          onCancel={() => setToDelete(null)}
        />
      )}
      {merge && (
        <Modal
          title={`Merge ${merge.length} PDFs`}
          onClose={() => setMerge(null)}
          busy={merging}
          size="sm"
          footer={
            <>
              <button className="btn" onClick={() => setMerge(null)} disabled={merging}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={doMerge} disabled={merging}>
                {merging && <Spinner size={14} />} Merge
              </button>
            </>
          }
        >
          <p className="small muted">A new PDF is added to the case; the originals are kept. Order:</p>
          <ol className="small">
            {merge.map((f) => (
              <li key={f.id}>{f.name}</li>
            ))}
          </ol>
          <div className="field">
            <label htmlFor="merge-name">File name</label>
            <input id="merge-name" value={mergeName} onChange={(e) => setMergeName(e.target.value)} />
          </div>
        </Modal>
      )}
    </div>
  );
}
