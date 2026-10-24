import { Link } from "react-router-dom";
import { CircleAlert, ScanSearch, ShieldCheck } from "lucide-react";
import { useMeta } from "../meta";
import { finalCheckHeadline, finalCheckState } from "../lib/secondOpinion";
import type { SecondOpinionReport } from "../types";

interface Props {
  report: SecondOpinionReport | null | undefined;
  /** link back to the review workspace (omit for viewers) */
  fileId?: number;
  compact?: boolean;
}

/**
 * The export's final check by Microsoft Presidio (report.second_opinion): either "passed", or the items that still
 * look personal in the released file. The found text is shown here for the reviewer only — never in notifications.
 */
export function FinalCheckResult({ report, fileId, compact = false }: Props) {
  const m = useMeta();
  const s = finalCheckState(report);
  if (!s) return null;
  if (s.state === "unchecked")
    return (
      <div className="final-check final-check-muted small" role="note">
        <ShieldCheck size={15} aria-hidden /> Final check not run: {s.reason}
      </div>
    );
  if (s.state === "passed")
    return (
      <div className="final-check final-check-ok" role="status">
        <ShieldCheck size={18} aria-hidden />
        <div>
          <strong>{finalCheckHeadline(s)}</strong>
          {!compact && (
            <div className="small">
              {s.engine} re-read the released file{s.reviewed ? `; ${s.reviewed} item${s.reviewed === 1 ? " was" : "s were"} left visible on purpose` : ""}.
            </div>
          )}
        </div>
      </div>
    );
  // viewers do not receive the found text: the table then has page and type only
  const withText = s.findings.some((f) => typeof f.text === "string" && f.text !== "");
  return (
    <div className="final-check final-check-open" role="alert">
      <CircleAlert size={18} aria-hidden />
      <div className="grow">
        <div className="row gap-sm wrap">
          <strong>{finalCheckHeadline(s)}</strong>
          <span className="small">— {s.engine} still recognises them in the released file.</span>
        </div>
        {!compact && (
          <table className="table compact final-check-table">
            <thead>
              <tr>
                <th>Page</th>
                <th>Type</th>
                {withText && <th>Text</th>}
                <th />
              </tr>
            </thead>
            <tbody>
              {s.findings.slice(0, 100).map((f, i) => (
                <tr key={i} className={f.reviewed ? "row-muted" : ""}>
                  <td className="num">{f.page + 1}</td>
                  <td>{m.entityLabel(f.entity)}</td>
                  {withText && <td className="mono small">{f.text ?? ""}</td>}
                  <td>
                    {f.reviewed ? (
                      <span className="badge badge-neutral tiny" title="The reviewer left this unredacted on purpose">
                        reviewed
                      </span>
                    ) : (
                      <span className="tiny muted">{Math.round(f.score * 100)}%</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {fileId != null && (
          <Link className="btn btn-sm final-check-link" to={`/files/${fileId}`}>
            <ScanSearch size={14} aria-hidden /> Review the file
          </Link>
        )}
      </div>
    </div>
  );
}
