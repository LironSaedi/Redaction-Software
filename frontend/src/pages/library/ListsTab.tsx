import { useEffect, useState } from "react";
import { ListChecks, Plus, Save, Trash2 } from "lucide-react";
import * as api from "../../api";
import { entityOptions, useMeta } from "../../meta";
import { useToast } from "../../components/Toast";
import { ConfirmDialog, EmptyState, ErrorState, Field, Loading, Spinner } from "../../components/ui";
import type { TermEntry, TermList, TermListIn } from "../../types";

interface Draft {
  id: number | null;
  name: string;
  kind: "redact" | "allow";
  entity: string;
  exemption: string;
  regex: boolean;
  caseSensitive: boolean;
  wholeWord: boolean;
  text: string;
}

const EMPTY: Draft = {
  id: null,
  name: "",
  kind: "redact",
  entity: "CUSTOM",
  exemption: "",
  regex: false,
  caseSensitive: false,
  wholeWord: true,
  text: "",
};

export function draftToBody(d: Draft): TermListIn {
  const terms: TermEntry[] = d.text
    .split("\n")
    .map((t) => t.trim())
    .filter(Boolean)
    .map((text) => ({ text, regex: d.regex, case_sensitive: d.caseSensitive, whole_word: d.wholeWord }));
  return { name: d.name.trim(), kind: d.kind, entity: d.entity, exemption: d.exemption, terms };
}

export function ListsTab() {
  const m = useMeta();
  const toast = useToast();
  const [lists, setLists] = useState<TermList[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadingList, setLoadingList] = useState(false);
  const [toDelete, setToDelete] = useState<TermList | null>(null);

  const load = () => {
    setError(null);
    api.listTermLists().then(setLists, (e) => setError(e instanceof Error ? e.message : "failed"));
  };
  useEffect(load, []);

  const open = async (l: TermList) => {
    setLoadingList(true);
    try {
      const full = await api.getTermList(l.id);
      const terms = full.terms ?? [];
      setDraft({
        id: l.id,
        name: full.name,
        kind: full.kind === "allow" ? "allow" : "redact",
        entity: full.entity || "CUSTOM",
        exemption: full.exemption || "",
        regex: terms.length > 0 && terms.every((t) => t.regex),
        caseSensitive: terms.length > 0 && terms.every((t) => t.case_sensitive),
        wholeWord: terms.length === 0 || terms.every((t) => t.whole_word !== false),
        text: terms.map((t) => t.text).join("\n"),
      });
    } catch (e) {
      toast.error(e, "Could not open list");
    } finally {
      setLoadingList(false);
    }
  };

  const save = async () => {
    if (!draft || !draft.name.trim()) return;
    if (draft.regex) {
      const bad = draft.text
        .split("\n")
        .map((t) => t.trim())
        .filter(Boolean)
        .find((t) => {
          try {
            new RegExp(t);
            return false;
          } catch {
            return true;
          }
        });
      if (bad !== undefined) {
        toast.error("One of the patterns is not a valid regular expression");
        return;
      }
    }
    setBusy(true);
    try {
      const body = draftToBody(draft);
      const saved = draft.id ? await api.updateTermList(draft.id, body) : await api.createTermList(body);
      toast.success("List saved");
      setDraft({ ...draft, id: saved.id });
      load();
    } catch (e) {
      toast.error(e, "Could not save list");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!toDelete) return;
    try {
      await api.deleteTermList(toDelete.id);
      toast.success("List deleted");
      if (draft?.id === toDelete.id) setDraft(null);
      setToDelete(null);
      load();
    } catch (e) {
      toast.error(e, "Could not delete list");
    }
  };

  const count = draft ? draft.text.split("\n").filter((t) => t.trim()).length : 0;

  return (
    <div className="master-detail">
      <div className="master">
        <div className="row space">
          <h2 className="h3">Term lists</h2>
          <button className="btn btn-sm btn-primary" onClick={() => setDraft({ ...EMPTY })}>
            <Plus size={14} aria-hidden /> New list
          </button>
        </div>
        {error && <ErrorState message={error} onRetry={load} />}
        {!lists && !error && <Loading />}
        {lists && lists.length === 0 && (
          <EmptyState icon={<ListChecks size={26} />} title="No lists yet">
            Redact lists always redact their terms; allow lists stop terms from being redacted.
          </EmptyState>
        )}
        <ul className="master-list">
          {lists?.map((l) => (
            <li key={l.id}>
              <button className={`master-item ${draft?.id === l.id ? "active" : ""}`} onClick={() => open(l)}>
                <span className="strong">{l.name}</span>
                <span className="muted small">
                  {l.kind === "allow" ? "Allow list" : `Redact · ${m.entityLabel(l.entity)}`} · {l.count} terms
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div className="detail">
        {loadingList && <Loading />}
        {!draft && !loadingList && <EmptyState title="Select a list or create a new one" />}
        {draft && !loadingList && (
          <div className="card stack">
            <div className="form-grid">
              <Field label="Name" htmlFor="tl-name">
                <input id="tl-name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
              </Field>
              <Field label="Kind" htmlFor="tl-kind">
                <select id="tl-kind" value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value as Draft["kind"] })}>
                  <option value="redact">Redact list — always redact these</option>
                  <option value="allow">Allow list — never redact these</option>
                </select>
              </Field>
              {draft.kind === "redact" && (
                <>
                  <Field label="Mark matches as" htmlFor="tl-entity">
                    <select id="tl-entity" value={draft.entity} onChange={(e) => setDraft({ ...draft, entity: e.target.value })}>
                      {entityOptions(m).map((o) => (
                        <option key={o.key} value={o.key}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label="Exemption code" htmlFor="tl-ex">
                    <select id="tl-ex" value={draft.exemption} onChange={(e) => setDraft({ ...draft, exemption: e.target.value })}>
                      <option value="">Default for the type</option>
                      {m.exemptionCodes.map(([c, d]) => (
                        <option key={c} value={c}>
                          {c} — {d}
                        </option>
                      ))}
                    </select>
                  </Field>
                </>
              )}
            </div>
            <div className="row gap wrap">
              <label className="check inline">
                <input type="checkbox" checked={draft.regex} onChange={(e) => setDraft({ ...draft, regex: e.target.checked })} />
                Terms are regular expressions
              </label>
              <label className="check inline">
                <input type="checkbox" checked={draft.wholeWord} onChange={(e) => setDraft({ ...draft, wholeWord: e.target.checked })} />
                Whole words only
              </label>
              <label className="check inline">
                <input type="checkbox" checked={draft.caseSensitive} onChange={(e) => setDraft({ ...draft, caseSensitive: e.target.checked })} />
                Match case
              </label>
            </div>
            <Field label={`Terms (one per line) — ${count}`} htmlFor="tl-terms">
              <textarea
                id="tl-terms"
                className="mono"
                rows={14}
                value={draft.text}
                onChange={(e) => setDraft({ ...draft, text: e.target.value })}
                spellCheck={false}
              />
            </Field>
            <div className="row gap">
              <button className="btn btn-primary" onClick={save} disabled={busy || !draft.name.trim()}>
                {busy ? <Spinner size={14} /> : <Save size={14} aria-hidden />} Save list
              </button>
              {draft.id && (
                <button className="btn btn-danger-ghost" onClick={() => setToDelete(lists?.find((l) => l.id === draft.id) ?? null)}>
                  <Trash2 size={14} aria-hidden /> Delete
                </button>
              )}
            </div>
          </div>
        )}
      </div>
      {toDelete && (
        <ConfirmDialog
          title="Delete list?"
          danger
          message={`“${toDelete.name}” will no longer be applied to new analyses.`}
          confirmLabel="Delete"
          onConfirm={remove}
          onCancel={() => setToDelete(null)}
        />
      )}
    </div>
  );
}
