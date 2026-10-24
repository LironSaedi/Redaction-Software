import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ChevronLeft, Pencil, Trash2 } from "lucide-react";
import * as api from "../api";
import { canSeeOriginals, hasRole, useUser } from "../auth";
import { useMeta } from "../meta";
import { useToast } from "../components/Toast";
import { ConfirmDialog, ErrorState, Field, Loading, Spinner, StatusBadge, Tabs } from "../components/ui";
import { CASE_STATUSES, REQUEST_TYPES, formatDate, fromDateInput, isOverdue, statusLabel, toDateInput } from "../lib/format";
import { FilesTab } from "./case/FilesTab";
import { ActivityTab, MembersTab, NotesTab, ReportTab } from "./case/OtherTabs";
import { RedactTextTab } from "./case/RedactTextTab";
import type { CaseDetail, CaseReport } from "../types";

type TabKey = "files" | "redact" | "members" | "notes" | "report" | "activity";
const TABS: TabKey[] = ["files", "redact", "members", "notes", "report", "activity"];

function CaseHeaderEdit({ c, onSaved, onCancel }: { c: CaseDetail; onSaved: () => void; onCancel: () => void }) {
  const user = useUser();
  const { meta } = useMeta();
  const toast = useToast();
  const [name, setName] = useState(c.name);
  const [number, setNumber] = useState(c.number);
  const [requestType, setRequestType] = useState(c.request_type);
  const [due, setDue] = useState(toDateInput(c.due_date));
  const [profile, setProfile] = useState(c.default_profile);
  const [description, setDescription] = useState(c.description);
  const [status, setStatus] = useState(c.status);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.updateCase(c.id, {
        name: name.trim() || c.name,
        number,
        request_type: requestType,
        due_date: fromDateInput(due),
        default_profile: profile,
        description,
        status,
      });
      toast.success("Case updated");
      onSaved();
    } catch (err) {
      toast.error(err, "Could not save");
    } finally {
      setBusy(false);
    }
  };

  const types = REQUEST_TYPES.includes(requestType) || !requestType ? REQUEST_TYPES : [requestType, ...REQUEST_TYPES];
  return (
    <form className="card form-grid case-edit" onSubmit={submit}>
      <Field label="Case name" htmlFor="ce-name" className="span-2">
        <input id="ce-name" value={name} onChange={(e) => setName(e.target.value)} required />
      </Field>
      <Field label="Number" htmlFor="ce-num">
        <input id="ce-num" value={number} onChange={(e) => setNumber(e.target.value)} />
      </Field>
      <Field label="Request type" htmlFor="ce-type">
        <select id="ce-type" value={requestType} onChange={(e) => setRequestType(e.target.value)}>
          <option value="">—</option>
          {types.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
      </Field>
      <Field label="Status" htmlFor="ce-status">
        <select id="ce-status" value={status} onChange={(e) => setStatus(e.target.value)}>
          {CASE_STATUSES.map((s) => (
            <option key={s} value={s} disabled={s === "closed" && !hasRole(user, "supervisor")}>
              {statusLabel(s)}
              {s === "closed" && !hasRole(user, "supervisor") ? " (supervisors)" : ""}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Due date" htmlFor="ce-due">
        <input id="ce-due" type="date" value={due} onChange={(e) => setDue(e.target.value)} />
      </Field>
      <Field label="Default profile" htmlFor="ce-prof">
        <select id="ce-prof" value={profile} onChange={(e) => setProfile(e.target.value)}>
          {(meta?.profiles ?? []).map((p) => (
            <option key={p.key} value={p.key}>
              {p.label}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Description" htmlFor="ce-desc" className="span-2">
        <textarea id="ce-desc" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
      </Field>
      <div className="row gap span-2">
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy && <Spinner size={14} />} Save
        </button>
        <button className="btn" type="button" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export function CaseDetailPage() {
  const params = useParams();
  const caseId = Number(params.caseId);
  const user0 = useUser();
  const requested = (TABS.includes(params.tab as TabKey) ? params.tab : "files") as TabKey;
  // viewers never get the redaction tab (the API refuses it too)
  const tab: TabKey = requested === "redact" && !hasRole(user0, "redactor") ? "files" : requested;
  const navigate = useNavigate();
  const user = useUser();
  const toast = useToast();
  const { meta } = useMeta();
  const [c, setC] = useState<CaseDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<CaseReport | null>(null);
  const [reportError, setReportError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(() => {
    if (!Number.isFinite(caseId)) return;
    api.getCase(caseId).then(
      (d) => {
        setC(d);
        setError(null);
      },
      (e) => setError(e instanceof Error ? e.message : "could not load case"),
    );
    api.caseReport(caseId).then(
      (r) => {
        setReport(r);
        setReportError(null);
      },
      (e) => setReportError(e instanceof Error ? e.message : "could not load report"),
    );
  }, [caseId]);

  useEffect(() => {
    setC(null);
    setReport(null);
    load();
  }, [load]);

  if (error)
    return (
      <div className="page">
        <ErrorState message={error} onRetry={load} />
      </div>
    );
  if (!c) return <Loading label="Loading case…" />;

  const profileLabel = meta?.profiles.find((p) => p.key === c.default_profile)?.label ?? c.default_profile;
  const canEdit = hasRole(user, "redactor");
  const originals = canSeeOriginals(user);

  const doDelete = async () => {
    setDeleting(true);
    try {
      await api.deleteCase(c.id);
      toast.success("Case and all its files were destroyed");
      navigate("/cases", { replace: true });
    } catch (e) {
      toast.error(e, "Delete failed");
      setDeleting(false);
    }
  };

  return (
    <div className="page">
      <Link to="/cases" className="back-link">
        <ChevronLeft size={15} aria-hidden /> Cases
      </Link>
      {editing ? (
        <CaseHeaderEdit
          c={c}
          onCancel={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            load();
          }}
        />
      ) : (
        <div className="case-header">
          <div>
            <div className="row gap-sm wrap">
              <h1>{c.name}</h1>
              <StatusBadge status={c.status} />
            </div>
            <dl className="meta-list">
              <div>
                <dt>Number</dt>
                <dd className="mono">{c.number || "—"}</dd>
              </div>
              <div>
                <dt>Request type</dt>
                <dd>{c.request_type || "—"}</dd>
              </div>
              <div>
                <dt>Due</dt>
                <dd className={isOverdue(c.due_date, c.status) ? "overdue" : ""}>
                  {formatDate(c.due_date)}
                  {isOverdue(c.due_date, c.status) ? " (overdue)" : ""}
                </dd>
              </div>
              <div>
                <dt>Default profile</dt>
                <dd>{profileLabel}</dd>
              </div>
              <div>
                <dt>Files</dt>
                <dd>
                  {c.file_count ?? c.files.length} · {c.exported ?? 0} exported
                </dd>
              </div>
            </dl>
            {c.description && <p className="case-desc">{c.description}</p>}
          </div>
          <div className="row gap">
            {canEdit && (
              <button className="btn" onClick={() => setEditing(true)}>
                <Pencil size={14} aria-hidden /> Edit
              </button>
            )}
            {hasRole(user, "supervisor") && (
              <button className="btn btn-danger-ghost" onClick={() => setConfirmDelete(true)}>
                <Trash2 size={14} aria-hidden /> Delete case
              </button>
            )}
          </div>
        </div>
      )}

      <Tabs<TabKey>
        label="Case sections"
        active={tab}
        onChange={(k) => navigate(k === "files" ? `/cases/${c.id}` : `/cases/${c.id}/${k}`, { replace: true })}
        tabs={[
          { key: "files", label: originals ? `Files (${c.files.length})` : "Released files" },
          { key: "redact", label: "Redact text", hidden: !canEdit },
          { key: "members", label: `Members (${c.members.length})` },
          { key: "notes", label: "Notes" },
          { key: "report", label: "Report" },
          { key: "activity", label: "Activity" },
        ]}
      />
      <div className="tab-panel" role="tabpanel" aria-labelledby={`tab-${tab}`}>
        {tab === "files" && <FilesTab caseData={c} report={report} reload={load} />}
        {tab === "redact" && canEdit && <RedactTextTab caseData={c} onChanged={load} />}
        {tab === "members" && <MembersTab caseData={c} reload={load} />}
        {tab === "notes" && <NotesTab caseData={c} />}
        {tab === "report" && <ReportTab report={report} error={reportError} onRetry={load} />}
        {tab === "activity" && <ActivityTab caseId={c.id} />}
      </div>

      {confirmDelete && (
        <ConfirmDialog
          title="Delete this case?"
          danger
          busy={deleting}
          confirmLabel="Destroy case and files"
          message={
            <p>
              Every file in <strong>{c.name}</strong> ({c.files.length}), all working copies, detections and exports will be
              destroyed permanently. The deletion is recorded in the audit log.
            </p>
          }
          onConfirm={doDelete}
          onCancel={() => setConfirmDelete(false)}
        />
      )}
    </div>
  );
}
