import { useEffect, useState, type FormEvent } from "react";
import { Download, RefreshCw, ShieldAlert, ShieldCheck } from "lucide-react";
import * as api from "../api";
import { useToast } from "../components/Toast";
import { EmptyState, ErrorState, Loading, Spinner } from "../components/ui";
import { AuditTable } from "./case/OtherTabs";
import type { AuditEvent, AuditQuery, AuditVerify, CaseSummary, UserDirectoryEntry } from "../types";

const COMMON_ACTIONS = [
  "login",
  "login_failed",
  "login_locked",
  "logout",
  "password_changed",
  "case_created",
  "case_updated",
  "case_deleted",
  "file_uploaded",
  "file_deleted",
  "analysis_started",
  "detections_reviewed",
  "manual_redaction",
  "search_redaction",
  "redaction_removed",
  "export_started",
  "export_downloaded",
  "original_downloaded",
  "member_added",
  "member_removed",
  "user_created",
  "user_updated",
  "password_reset",
  "audit_exported",
];

const PAGE = 200;

export function AuditPage() {
  const toast = useToast();
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [users, setUsers] = useState<UserDirectoryEntry[]>([]);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [filters, setFilters] = useState<{ action: string; user_id: string; case_id: string; file_id: string }>({
    action: "",
    user_id: "",
    case_id: "",
    file_id: "",
  });
  const [offset, setOffset] = useState(0);
  const [verify, setVerify] = useState<AuditVerify | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [exporting, setExporting] = useState(false);

  const query = (): AuditQuery => ({
    action: filters.action || undefined,
    user_id: filters.user_id ? Number(filters.user_id) : undefined,
    case_id: filters.case_id ? Number(filters.case_id) : undefined,
    file_id: filters.file_id ? Number(filters.file_id) : undefined,
    limit: PAGE,
    offset,
  });

  const load = () => {
    setError(null);
    setEvents(null);
    api.listAudit(query()).then(setEvents, (e) => setError(e instanceof Error ? e.message : "failed"));
  };

  useEffect(() => {
    api.listUsers().then(setUsers, () => setUsers([]));
    api.listCases().then(setCases, () => setCases([]));
  }, []);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [offset]);

  const apply = (e: FormEvent) => {
    e.preventDefault();
    if (offset !== 0) setOffset(0);
    else load();
  };

  const runVerify = async () => {
    setVerifying(true);
    try {
      setVerify(await api.verifyAudit());
    } catch (e) {
      toast.error(e, "Verification failed to run");
    } finally {
      setVerifying(false);
    }
  };

  const exportCsv = async () => {
    setExporting(true);
    try {
      await api.downloadAuditCsv(filters.case_id ? Number(filters.case_id) : undefined);
    } catch (e) {
      toast.error(e, "Export failed");
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Audit log</h1>
          <p className="muted">Tamper-evident record of every sign-in, upload, review decision and export (SHA-256 hash chain).</p>
        </div>
        <div className="row gap">
          <button className="btn" onClick={runVerify} disabled={verifying}>
            {verifying ? <Spinner size={14} /> : <ShieldCheck size={15} aria-hidden />} Verify integrity
          </button>
          <button className="btn" onClick={exportCsv} disabled={exporting}>
            {exporting ? <Spinner size={14} /> : <Download size={15} aria-hidden />} Export CSV
          </button>
        </div>
      </div>
      {verify &&
        (verify.valid ? (
          <div className="verify verify-ok" role="status">
            <ShieldCheck size={20} aria-hidden />
            <div>
              <strong>Audit chain intact</strong>
              <div className="small">
                All {verify.events} events verified. Head hash <span className="mono">{verify.head?.slice(0, 24)}…</span>
              </div>
            </div>
          </div>
        ) : (
          <div className="verify verify-bad" role="alert">
            <ShieldAlert size={20} aria-hidden />
            <div>
              <strong>Audit chain BROKEN at event #{verify.broken_at}</strong>
              <div className="small">
                {verify.reason}. The log may have been altered outside the application; preserve the database and notify your
                security officer.
              </div>
            </div>
          </div>
        ))}
      <form className="toolbar wrap" onSubmit={apply}>
        <select aria-label="Action" value={filters.action} onChange={(e) => setFilters({ ...filters, action: e.target.value })}>
          <option value="">All actions</option>
          {COMMON_ACTIONS.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
        <select aria-label="User" value={filters.user_id} onChange={(e) => setFilters({ ...filters, user_id: e.target.value })}>
          <option value="">All users</option>
          {users.map((u) => (
            <option key={u.id} value={u.id}>
              {u.username}
            </option>
          ))}
        </select>
        <select aria-label="Case" value={filters.case_id} onChange={(e) => setFilters({ ...filters, case_id: e.target.value })}>
          <option value="">All cases</option>
          {cases.map((c) => (
            <option key={c.id} value={c.id}>
              #{c.id} {c.name}
            </option>
          ))}
        </select>
        <input
          aria-label="File id"
          placeholder="File id"
          inputMode="numeric"
          className="input-narrow"
          value={filters.file_id}
          onChange={(e) => setFilters({ ...filters, file_id: e.target.value.replace(/\D/g, "") })}
        />
        <button className="btn btn-primary" type="submit">
          Apply
        </button>
        <button
          className="icon-btn"
          type="button"
          onClick={load}
          aria-label="Refresh"
          title="Refresh"
        >
          <RefreshCw size={15} />
        </button>
      </form>
      {error && <ErrorState message={error} onRetry={load} />}
      {!events && !error && <Loading />}
      {events && events.length === 0 && <EmptyState title="No events match" />}
      {events && events.length > 0 && <AuditTable events={events} showCase />}
      {events && (
        <div className="row gap pager">
          <button className="btn btn-sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
            Newer
          </button>
          <span className="small muted">
            Events {offset + 1}–{offset + events.length}
          </span>
          <button className="btn btn-sm" disabled={events.length < PAGE} onClick={() => setOffset(offset + PAGE)}>
            Older
          </button>
        </div>
      )}
    </div>
  );
}
