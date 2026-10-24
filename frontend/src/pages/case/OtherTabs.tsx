import { CaseExports } from "./CaseExports";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, Printer, Send, Trash2, UserPlus, XCircle } from "lucide-react";
import * as api from "../../api";
import { canSeeOriginals, hasRole, useUser } from "../../auth";
import { CATEGORY_ORDER, useMeta } from "../../meta";
import { useToast } from "../../components/Toast";
import { EmptyState, ErrorState, Loading, Spinner, StatusBadge } from "../../components/ui";
import { formatDate, titleCase } from "../../lib/format";
import type { AuditEvent, CaseDetail, CaseReport, MemberRole, Note, UserDirectoryEntry } from "../../types";

// ---- Members -------------------------------------------------------------------------------------------

export function MembersTab({ caseData, reload }: { caseData: CaseDetail; reload: () => void }) {
  const user = useUser();
  const toast = useToast();
  const [users, setUsers] = useState<UserDirectoryEntry[]>([]);
  const [pick, setPick] = useState("");
  const [role, setRole] = useState<MemberRole>("redactor");
  const [busy, setBusy] = useState(false);
  const canManage = hasRole(user, "redactor");

  useEffect(() => {
    if (canManage) api.listUsers().then(setUsers, () => setUsers([]));
  }, [canManage]);

  const memberIds = new Set(caseData.members.map((m) => m.user_id));
  const candidates = users.filter((u) => !memberIds.has(u.id) && u.is_active !== false);

  const add = async (e: FormEvent) => {
    e.preventDefault();
    if (!pick) return;
    setBusy(true);
    try {
      await api.addCaseMember(caseData.id, Number(pick), role);
      toast.success("Member added");
      setPick("");
      reload();
    } catch (err) {
      toast.error(err, "Could not add member");
    } finally {
      setBusy(false);
    }
  };

  const change = async (uid: number, r: MemberRole) => {
    try {
      await api.addCaseMember(caseData.id, uid, r);
      toast.success("Role updated");
      reload();
    } catch (err) {
      toast.error(err, "Could not change role");
    }
  };

  const remove = async (uid: number) => {
    try {
      await api.removeCaseMember(caseData.id, uid);
      toast.success("Member removed");
      reload();
    } catch (err) {
      toast.error(err, "Could not remove member");
    }
  };

  return (
    <div className="stack">
      {canManage && (
        <form className="card row gap wrap" onSubmit={add}>
          <div className="field grow">
            <label htmlFor="mem-user">Add a member</label>
            <select id="mem-user" value={pick} onChange={(e) => setPick(e.target.value)}>
              <option value="">Choose a user…</option>
              {candidates.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name ? `${u.full_name} (${u.username})` : u.username} — {u.role}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="mem-role">Case role</label>
            <select id="mem-role" value={role} onChange={(e) => setRole(e.target.value as MemberRole)}>
              <option value="redactor">Redactor</option>
              <option value="reviewer">Reviewer (can manage members)</option>
              <option value="viewer">Viewer (redacted exports only)</option>
            </select>
          </div>
          <button className="btn btn-primary align-end" type="submit" disabled={!pick || busy}>
            {busy ? <Spinner size={14} /> : <UserPlus size={15} aria-hidden />} Add
          </button>
        </form>
      )}
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>User</th>
              <th>Username</th>
              <th>Case role</th>
              {canManage && <th className="actions-col">Actions</th>}
            </tr>
          </thead>
          <tbody>
            {caseData.members.map((m) => (
              <tr key={m.user_id}>
                <td>{m.full_name || "—"}</td>
                <td className="mono">{m.username}</td>
                <td>
                  {canManage ? (
                    <select
                      aria-label={`Case role for ${m.username}`}
                      value={m.role}
                      onChange={(e) => change(m.user_id, e.target.value as MemberRole)}
                    >
                      <option value="redactor">Redactor</option>
                      <option value="reviewer">Reviewer</option>
                      <option value="viewer">Viewer</option>
                    </select>
                  ) : (
                    titleCase(m.role)
                  )}
                </td>
                {canManage && (
                  <td className="actions-col">
                    <button className="icon-btn danger" aria-label={`Remove ${m.username}`} data-tip="Remove from the case" onClick={() => remove(m.user_id)}>
                      <Trash2 size={15} />
                    </button>
                  </td>
                )}
              </tr>
            ))}
            {caseData.members.length === 0 && (
              <tr>
                <td colSpan={4} className="muted center">
                  No members. Supervisors and admins can always see every case.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---- Notes ---------------------------------------------------------------------------------------------

export function NotesTab({ caseData }: { caseData: CaseDetail }) {
  const toast = useToast();
  const [notes, setNotes] = useState<Note[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [body, setBody] = useState("");
  const [fileId, setFileId] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => {
    setError(null);
    api.listNotes(caseData.id).then(setNotes, (e) => setError(e instanceof Error ? e.message : "could not load notes"));
  };
  useEffect(load, [caseData.id]);

  const add = async (e: FormEvent) => {
    e.preventDefault();
    if (!body.trim()) return;
    setBusy(true);
    try {
      await api.addNote(caseData.id, body.trim(), fileId ? Number(fileId) : null);
      setBody("");
      load();
    } catch (err) {
      toast.error(err, "Could not add note");
    } finally {
      setBusy(false);
    }
  };

  const fileName = (id: number | null) => (id ? caseData.files.find((f) => f.id === id)?.name ?? `file #${id}` : null);

  return (
    <div className="stack">
      <form className="card stack-sm" onSubmit={add}>
        <label htmlFor="note-body" className="label">
          Add a note
        </label>
        <textarea id="note-body" rows={3} value={body} onChange={(e) => setBody(e.target.value)} maxLength={5000} />
        <div className="row gap">
          <select aria-label="About file" value={fileId} onChange={(e) => setFileId(e.target.value)}>
            <option value="">Whole case</option>
            {caseData.files.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </select>
          <button className="btn btn-primary" type="submit" disabled={busy || !body.trim()}>
            {busy ? <Spinner size={14} /> : <Send size={14} aria-hidden />} Add note
          </button>
        </div>
      </form>
      {error && <ErrorState message={error} onRetry={load} />}
      {!notes && !error && <Loading />}
      {notes && notes.length === 0 && <EmptyState title="No notes yet" />}
      {notes && notes.length > 0 && (
        <ul className="notes">
          {[...notes].reverse().map((n) => (
            <li key={n.id} className="note card">
              <div className="note-head">
                <strong>{n.user}</strong>
                <span className="muted small">{formatDate(n.created_at, true)}</span>
                {n.file_id && (
                  <Link className="small" to={`/files/${n.file_id}`}>
                    {fileName(n.file_id)}
                  </Link>
                )}
              </div>
              <div className="note-body">{n.body}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---- Report --------------------------------------------------------------------------------------------

export function ReportTab({ report, error, onRetry }: { report: CaseReport | null; error: string | null; onRetry: () => void }) {
  const m = useMeta();
  const canReview = canSeeOriginals(useUser());
  const byCategory = useMemo(() => {
    const out = new Map<string, { total: number; types: [string, number][] }>();
    for (const [ent, n] of Object.entries(report?.by_entity ?? {})) {
      const c = m.categoryOf(ent);
      if (!out.has(c)) out.set(c, { total: 0, types: [] });
      const g = out.get(c)!;
      g.total += n;
      g.types.push([ent, n]);
    }
    return Array.from(out.entries()).sort((a, b) => CATEGORY_ORDER.indexOf(a[0]) - CATEGORY_ORDER.indexOf(b[0]));
  }, [report, m]);

  if (error) return <ErrorState message={error} onRetry={onRetry} />;
  if (!report) return <Loading />;
  const codes = m.meta?.exemption_codes ?? {};
  return (
    <div className="stack report">
      <div className="row space">
        <div className="stat-row">
          <div className="stat">
            <div className="stat-num">{report.total_redactions}</div>
            <div className="stat-label">Redactions</div>
          </div>
          <div className="stat">
            <div className="stat-num">{report.files.length}</div>
            <div className="stat-label">Files</div>
          </div>
          <div className="stat">
            <div className="stat-num">{report.files.filter((f) => f.exports > 0).length}</div>
            <div className="stat-label">Exported</div>
          </div>
          <div className="stat">
            <div className="stat-num">{report.files.filter((f) => f.verified === false).length}</div>
            <div className="stat-label">Failed verification</div>
          </div>
        </div>
        <button className="btn no-print" onClick={() => window.print()}>
          <Printer size={15} aria-hidden /> Print
        </button>
      </div>
      <div className="grid-2">
        <section className="card">
          <h3>By category</h3>
          {byCategory.length === 0 && <p className="muted">No redactions selected yet.</p>}
          {byCategory.map(([cat, g]) => (
            <div key={cat} className="report-cat">
              <div className="row space">
                <span className="row gap-sm">
                  <span className="cat-dot" style={{ background: m.color(g.types[0][0]) }} aria-hidden />
                  <strong>{m.categoryLabel(cat)}</strong>
                </span>
                <strong>{g.total}</strong>
              </div>
              <ul className="report-types">
                {g.types
                  .sort((a, b) => b[1] - a[1])
                  .map(([ent, n]) => (
                    <li key={ent} className="row space">
                      <span>{m.entityLabel(ent)}</span>
                      <span className="mono">{n}</span>
                    </li>
                  ))}
              </ul>
            </div>
          ))}
        </section>
        <section className="card">
          <h3>By exemption</h3>
          {Object.keys(report.by_exemption).length === 0 && <p className="muted">No exemption codes applied.</p>}
          <table className="table compact">
            <tbody>
              {Object.entries(report.by_exemption)
                .sort((a, b) => b[1] - a[1])
                .map(([code, n]) => (
                  <tr key={code}>
                    <td className="mono">{code}</td>
                    <td className="small muted">{codes[code] ?? ""}</td>
                    <td className="num">{n}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </section>
      </div>
      <section className="card">
        <h3>Per file</h3>
        <table className="table compact">
          <thead>
            <tr>
              <th>File</th>
              <th>Type</th>
              <th>Status</th>
              <th className="num">Pages</th>
              <th className="num">Redactions</th>
              <th className="num">Exports</th>
              <th>Verified</th>
            </tr>
          </thead>
          <tbody>
            {report.files.map((f) => (
              <tr key={f.file_id}>
                <td>{f.name}</td>
                <td>{f.kind}</td>
                <td>
                  <StatusBadge status={f.status} />
                </td>
                <td className="num">{f.pages || "—"}</td>
                <td className="num">{f.redactions}</td>
                <td className="num">
                  {f.exports}
                  {f.review_copies ? (
                    <span className="badge badge-warn tiny review-count" data-tip="Marked review copies — not for release, not counted as exports">
                      +{f.review_copies} review
                    </span>
                  ) : null}
                </td>
                <td>
                  {f.verified == null ? (
                    <span className="muted">—</span>
                  ) : f.verified ? (
                    <span className="ok-text">
                      <CheckCircle2 size={14} aria-hidden /> yes
                    </span>
                  ) : (
                    <span className="bad-text">
                      <XCircle size={14} aria-hidden /> no
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section className="card no-print-break">
        <h3>Exports and final checks</h3>
        <CaseExports caseId={report.case.id} canReview={canReview} />
      </section>
    </div>
  );
}

// ---- Activity ------------------------------------------------------------------------------------------

export function AuditTable({ events, showCase = false }: { events: AuditEvent[]; showCase?: boolean }) {
  return (
    <div className="table-wrap">
      <table className="table compact audit-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Time</th>
            <th>User</th>
            <th>Action</th>
            <th>Object</th>
            {showCase && <th>Case</th>}
            <th>Details</th>
            <th>IP</th>
            <th>Hash</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr key={e.id}>
              <td className="mono small">{e.id}</td>
              <td className="nowrap small">{formatDate(e.ts, true)}</td>
              <td>{e.user}</td>
              <td>
                <span className="badge badge-neutral">{e.action}</span>
              </td>
              <td className="small">
                {e.object_type}
                {e.object_id ? ` #${e.object_id}` : ""}
              </td>
              {showCase && (
                <td className="small">{e.case_id ? <Link to={`/cases/${e.case_id}`}>#{e.case_id}</Link> : "—"}</td>
              )}
              <td className="small mono details-cell">
                {Object.keys(e.details ?? {}).length
                  ? Object.entries(e.details)
                      .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
                      .join(" ")
                  : ""}
              </td>
              <td className="small mono">{e.ip}</td>
              <td className="small mono muted">{e.hash}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ActivityTab({ caseId }: { caseId: number }) {
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => {
    setError(null);
    api.listAudit({ case_id: caseId, limit: 500 }).then(setEvents, (e) => setError(e instanceof Error ? e.message : "failed"));
  };
  useEffect(load, [caseId]);
  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!events) return <Loading />;
  if (!events.length) return <EmptyState title="No activity recorded yet" />;
  return <AuditTable events={events} />;
}
