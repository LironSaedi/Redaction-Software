import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, ClipboardCheck, Download, XCircle } from "lucide-react";
import * as api from "../../api";
import { useToast } from "../../components/Toast";
import { FinalCheckResult } from "../../components/FinalCheck";
import { useExportDetail } from "../../components/ExportDialog";
import { EmptyState, SkeletonList } from "../../components/ui";
import { formatBytes, formatDate } from "../../lib/format";
import { REVIEW_COPY_LABEL } from "../../lib/exports";
import type { CaseExport } from "../../types";

/** Final-check cell from the list's own `second_opinion_open` (no request per row). */
export function FinalCheckCell({ e, open, onToggle }: { e: Pick<CaseExport, "marked_copy" | "second_opinion_open">; open: boolean; onToggle: () => void }) {
  if (e.marked_copy) return <span className="muted small">—</span>;
  const n = e.second_opinion_open;
  if (n === undefined || n === null) return <span className="muted small">not checked</span>;
  if (n === 0)
    return (
      <span className="ok-text small">
        <CheckCircle2 size={14} aria-hidden /> passed
      </span>
    );
  return (
    <button className="link-btn small warn-text" onClick={onToggle} aria-expanded={open}>
      {n} possible item{n === 1 ? "" : "s"} still readable
    </button>
  );
}

/** The full findings, fetched only when a row is expanded. */
function FinalCheckDetail({ e, canReview }: { e: CaseExport; canReview: boolean }) {
  const exp = useExportDetail(e.id);
  if (!exp) return <span className="skeleton" style={{ width: 220, height: 14 }} aria-hidden />;
  return <FinalCheckResult report={exp.report?.second_opinion} fileId={canReview ? e.file_id : undefined} />;
}

/** Every export of the case, with verification and the Microsoft Presidio final check. */
export function CaseExports({ caseId, canReview }: { caseId: number; canReview: boolean }) {
  const toast = useToast();
  const [list, setList] = useState<CaseExport[] | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => {
    api.listCaseExports(caseId).then(setList, () => setList([]));
  }, [caseId]);
  if (!list) return <SkeletonList rows={3} label="Loading exports" />;
  if (!list.length) return <EmptyState compact title="No exports yet" />;
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>File</th>
            <th>Export</th>
            <th>Verified</th>
            <th>Final check</th>
            <th>Created</th>
            <th className="actions-col" />
          </tr>
        </thead>
        <tbody>
          {list.slice(0, 200).flatMap((e) => {
            const rows = [
              <tr key={e.id}>
                <td>
                  <Link to={`/files/${e.file_id}`}>{e.file_name}</Link>
                </td>
                <td className="mono small">{e.name}</td>
                <td>
                  {e.marked_copy ? (
                    <span className="badge badge-warn tiny">
                      <ClipboardCheck size={11} aria-hidden /> {REVIEW_COPY_LABEL}
                    </span>
                  ) : e.verified ? (
                    <span className="ok-text small">
                      <CheckCircle2 size={14} aria-hidden /> verified
                    </span>
                  ) : (
                    <span className="bad-text small">
                      <XCircle size={14} aria-hidden /> failed
                    </span>
                  )}
                </td>
                <td>
                  <FinalCheckCell e={e} open={open === e.id} onToggle={() => setOpen(open === e.id ? null : e.id)} />
                </td>
                <td className="small">{formatDate(e.created_at, true)}</td>
                <td className="actions-col">
                  <button
                    className="icon-btn"
                    aria-label={`Download ${e.name} (${formatBytes(e.size)})`}
                    data-tip={`Download (${formatBytes(e.size)})`}
                    onClick={() => api.downloadExport(e.id, e.name).catch((er) => toast.error(er, "Download failed"))}
                  >
                    <Download size={15} />
                  </button>
                </td>
              </tr>,
            ];
            if (open === e.id)
              rows.push(
                <tr key={`${e.id}-detail`} className="detail-row">
                  <td colSpan={6}>
                    <FinalCheckDetail e={e} canReview={canReview} />
                  </td>
                </tr>,
              );
            return rows;
          })}
        </tbody>
      </table>
    </div>
  );
}
