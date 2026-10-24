import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Briefcase, Plus, Search } from "lucide-react";
import * as api from "../api";
import { hasRole, useUser } from "../auth";
import { useMeta } from "../meta";
import { useToast } from "../components/Toast";
import { EmptyState, ErrorState, Field, Loading, Modal, Spinner, StatusBadge } from "../components/ui";
import { CASE_STATUSES, REQUEST_TYPES, formatDate, fromDateInput, isOverdue, statusLabel } from "../lib/format";
import type { CaseSummary } from "../types";

export function NewCaseDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (c: CaseSummary) => void }) {
  const { meta } = useMeta();
  const toast = useToast();
  const [name, setName] = useState("");
  const [number, setNumber] = useState("");
  const [requestType, setRequestType] = useState("FOIA");
  const [due, setDue] = useState("");
  const [profile, setProfile] = useState("standard");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    try {
      const c = await api.createCase({
        name: name.trim(),
        number: number.trim(),
        request_type: requestType,
        due_date: fromDateInput(due),
        default_profile: profile,
        description,
      });
      toast.success("Case created");
      onCreated(c);
    } catch (err) {
      toast.error(err, "Could not create case");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="New case"
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <button className="btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className="btn btn-primary" type="submit" form="new-case-form" disabled={busy || !name.trim()}>
            {busy && <Spinner size={14} />} Create case
          </button>
        </>
      }
    >
      <form id="new-case-form" className="form-grid" onSubmit={submit}>
        <Field label="Case name" htmlFor="nc-name" className="span-2">
          <input id="nc-name" value={name} onChange={(e) => setName(e.target.value)} required autoFocus />
        </Field>
        <Field label="Case / request number" htmlFor="nc-number">
          <input id="nc-number" value={number} onChange={(e) => setNumber(e.target.value)} />
        </Field>
        <Field label="Request type" htmlFor="nc-type">
          <select id="nc-type" value={requestType} onChange={(e) => setRequestType(e.target.value)}>
            {REQUEST_TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </Field>
        <Field label="Due date" htmlFor="nc-due">
          <input id="nc-due" type="date" value={due} onChange={(e) => setDue(e.target.value)} />
        </Field>
        <Field label="Default detection profile" htmlFor="nc-profile">
          <select id="nc-profile" value={profile} onChange={(e) => setProfile(e.target.value)}>
            {(meta?.profiles ?? [{ key: "standard", label: "Standard PII" }]).map((p) => (
              <option key={p.key} value={p.key}>
                {p.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Description (optional)" htmlFor="nc-desc" className="span-2">
          <textarea id="nc-desc" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
      </form>
    </Modal>
  );
}

export function CasesPage() {
  const user = useUser();
  const navigate = useNavigate();
  const [cases, setCases] = useState<CaseSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [showNew, setShowNew] = useState(false);

  const load = () => {
    setError(null);
    api
      .listCases()
      .then(setCases)
      .catch((e) => setError(e instanceof Error ? e.message : "could not load cases"));
  };
  useEffect(load, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (cases ?? []).filter(
      (c) =>
        (!statusFilter || c.status === statusFilter) &&
        (!q ||
          c.name.toLowerCase().includes(q) ||
          (c.number || "").toLowerCase().includes(q) ||
          (c.request_type || "").toLowerCase().includes(q)),
    );
  }, [cases, query, statusFilter]);

  const canCreate = hasRole(user, "redactor");

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Cases</h1>
          <p className="muted">Requests, productions and records releases you have access to.</p>
        </div>
        {canCreate && (
          <button className="btn btn-primary" onClick={() => setShowNew(true)}>
            <Plus size={16} aria-hidden /> New case
          </button>
        )}
      </div>
      <div className="toolbar">
        <div className="search-input">
          <Search size={15} aria-hidden />
          <input
            type="search"
            placeholder="Search by name, number or type"
            aria-label="Search cases"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <select aria-label="Filter by status" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">All statuses</option>
          {CASE_STATUSES.map((s) => (
            <option key={s} value={s}>
              {statusLabel(s)}
            </option>
          ))}
        </select>
        <span className="muted small">{cases ? `${filtered.length} of ${cases.length}` : ""}</span>
      </div>
      {error && <ErrorState message={error} onRetry={load} />}
      {!cases && !error && <Loading label="Loading cases…" />}
      {cases && cases.length === 0 && (
        <EmptyState icon={<Briefcase size={32} />} title="No cases yet">
          {canCreate ? (
            <>
              Create a case to upload files for review.{" "}
              <button className="btn btn-sm btn-primary" onClick={() => setShowNew(true)}>
                <Plus size={14} aria-hidden /> New case
              </button>
            </>
          ) : (
            "You have not been added to any case."
          )}
        </EmptyState>
      )}
      {cases && cases.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Number</th>
                <th>Request type</th>
                <th>Status</th>
                <th>Due</th>
                <th className="num">Files</th>
                <th className="num">Exported</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((c) => (
                <tr key={c.id} className="row-link" onClick={() => navigate(`/cases/${c.id}`)}>
                  <td>
                    <Link to={`/cases/${c.id}`} className="strong" onClick={(e) => e.stopPropagation()}>
                      {c.name}
                    </Link>
                  </td>
                  <td className="mono">{c.number || "—"}</td>
                  <td>{c.request_type || "—"}</td>
                  <td>
                    <StatusBadge status={c.status} />
                  </td>
                  <td className={isOverdue(c.due_date, c.status) ? "overdue" : ""}>
                    {formatDate(c.due_date)}
                    {isOverdue(c.due_date, c.status) && <span className="sr-only"> (overdue)</span>}
                    {isOverdue(c.due_date, c.status) && <span className="badge badge-bad tiny">overdue</span>}
                  </td>
                  <td className="num">{c.file_count ?? 0}</td>
                  <td className="num">{c.exported ?? 0}</td>
                  <td className="muted">{formatDate(c.updated_at)}</td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={8} className="muted center">
                    No cases match the filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {showNew && (
        <NewCaseDialog
          onClose={() => setShowNew(false)}
          onCreated={(c) => {
            setShowNew(false);
            navigate(`/cases/${c.id}`);
          }}
        />
      )}
    </div>
  );
}
