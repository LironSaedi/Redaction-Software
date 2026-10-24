import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Eye, Redo2, Replace, Trash2, Undo2 } from "lucide-react";
import * as api from "../../api";
import { useMeta } from "../../meta";
import { useToast } from "../../components/Toast";
import { EmptyState, Spinner, Switch } from "../../components/ui";
import { parseTerms, termFlags } from "../../lib/redactText";
import { changeCount, changesOf, redoCaseRedaction, undoCaseRedaction, type CaseSnapshots } from "../../lib/caseRedaction";
import { EntitySelect, ExemptionSelect } from "../review/PropertiesPanel";
import type { CaseDetail, ExtraTerm, RedactTextOut } from "../../types";

/** The result of a preview / redaction run, one row per file (counts only — never the matched text). */
export function RedactTextResults({ res, action }: { res: RedactTextOut; action?: React.ReactNode }) {
  const reexport = res.files.filter((f) => f.needs_reexport);
  return (
    <div className="stack-sm">
      <div className={`notice ${res.preview ? "notice-info" : "notice-ok"}`} role="status">
        {res.preview ? (
          <>
            <Eye size={15} aria-hidden /> Preview: {res.total_matches} match{res.total_matches === 1 ? "" : "es"} in{" "}
            {res.files.filter((f) => f.matches > 0).length} file(s). Nothing was changed yet.
          </>
        ) : (
          <>
            <CheckCircle2 size={15} aria-hidden />
            <span className="grow">
              {res.total_added} redaction{res.total_added === 1 ? "" : "s"} added ({res.total_matches} match
              {res.total_matches === 1 ? "" : "es"}).{res.remembered ? " These entries will also be redacted in files added later." : ""}
            </span>
            {action}
          </>
        )}
      </div>
      {reexport.length > 0 && (
        <div className="notice notice-warn" role="alert">
          <AlertTriangle size={15} aria-hidden /> {reexport.length} file(s) were already approved or exported — export them again so the
          released copy includes the new redactions.
        </div>
      )}
      <div className="table-wrap">
        <table className="table compact">
          <thead>
            <tr>
              <th>File</th>
              <th className="num">Matches</th>
              {!res.preview && <th className="num">Added</th>}
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {res.files.map((f) => (
              <tr key={f.file_id} className={f.skipped ? "row-muted" : ""}>
                <td>
                  <Link to={`/files/${f.file_id}`}>{f.name}</Link>
                </td>
                <td className="num">{f.skipped ? "—" : f.matches}</td>
                {!res.preview && <td className="num">{f.skipped ? "—" : f.added}</td>}
                <td className="small">
                  {f.skipped ? (
                    <span className="muted">Skipped: {f.skipped}</span>
                  ) : f.needs_reexport ? (
                    <span className="warn-text">
                      <AlertTriangle size={13} aria-hidden /> Export again
                    </span>
                  ) : f.matches === 0 ? (
                    <span className="muted">No matches</span>
                  ) : res.preview ? (
                    <span>Will be redacted</span>
                  ) : f.added ? (
                    <span className="ok-text">
                      <CheckCircle2 size={13} aria-hidden /> Redacted
                    </span>
                  ) : (
                    <span className="muted">Already redacted</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Case tab: redact additional words, names, numbers or phrases in every file of the case. */
export function RedactTextTab({ caseData, onChanged }: { caseData: CaseDetail; onChanged: () => void }) {
  const m = useMeta();
  const toast = useToast();
  const [text, setText] = useState("");
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [wholeWord, setWholeWord] = useState(true);
  const [regex, setRegex] = useState(false);
  const [entity, setEntity] = useState("CUSTOM");
  const [exemption, setExemption] = useState("");
  const [remember, setRemember] = useState(true);
  const [busy, setBusy] = useState<"preview" | "redact" | null>(null);
  const [res, setRes] = useState<RedactTextOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<ExtraTerm[] | null>(null);
  const [removing, setRemoving] = useState<number | null>(null);
  // undo of the last run: every file it changed, in one go
  const [undo, setUndo] = useState<{ state: "done" | "undone" | "busy"; snaps: CaseSnapshots } | null>(null);

  const parsed = useMemo(() => parseTerms(text, { regex, case_sensitive: caseSensitive, whole_word: wholeWord, entity }), [
    text,
    regex,
    caseSensitive,
    wholeWord,
    entity,
  ]);

  const loadSaved = () =>
    api.getCaseRedactText(caseData.id).then(
      (r) => setSaved(r.terms),
      () => setSaved([]),
    );
  useEffect(() => {
    void loadSaved();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseData.id]);

  const run = async (preview: boolean) => {
    if (parsed.problems.length) {
      setError(parsed.problems[0]);
      return;
    }
    setBusy(preview ? "preview" : "redact");
    setError(null);
    try {
      const r = await api.caseRedactText(caseData.id, { terms: parsed.terms, preview, remember, entity, exemption, file_ids: null });
      setRes(r);
      setUndo(!preview && changeCount(changesOf(r)) > 0 ? { state: "done", snaps: new Map() } : null);
      if (!preview) {
        toast.success(`${r.total_added} redaction${r.total_added === 1 ? "" : "s"} added across the case`);
        onChanged();
        if (r.remembered) void loadSaved();
      }
    } catch (e) {
      setError(e instanceof api.ApiError ? e.detail : e instanceof Error ? e.message : "the request failed");
    } finally {
      setBusy(null);
    }
  };

  const undoRun = async () => {
    if (!res || !undo) return;
    const changes = changesOf(res);
    const was = undo.state;
    setUndo({ ...undo, state: "busy" });
    try {
      if (was === "done") {
        const snaps = await undoCaseRedaction(changes);
        setUndo({ state: "undone", snaps });
        toast.success(`Reverted ${changeCount(changes)} redaction(s) in ${changes.length} file(s)`);
      } else {
        await redoCaseRedaction(changes, undo.snaps);
        setUndo({ state: "done", snaps: undo.snaps });
        toast.success("Redactions applied again");
      }
      onChanged();
    } catch (e) {
      setUndo({ ...undo, state: was });
      toast.error(e, was === "done" ? "Could not undo" : "Could not redo");
    }
  };

  const removeSaved = async (i: number) => {
    if (!saved) return;
    setRemoving(i);
    try {
      const rest = saved.filter((_, k) => k !== i);
      const r = await api.putCaseRedactText(caseData.id, rest);
      setSaved(r.terms);
      toast.success("Removed from the list");
    } catch (e) {
      toast.error(e, "Could not update the list");
    } finally {
      setRemoving(null);
    }
  };

  return (
    <div className="grid-2 redact-text">
      <section className="card stack">
        <div>
          <h3>Redact additional text</h3>
          <p className="small muted">
            Redacts these entries in every file of the case — PDFs, scans (OCR text), Office files, emails and transcripts. Each
            change is recorded in the audit log (without the text itself).
          </p>
        </div>
        <div className="field">
          <label htmlFor="rt-terms">Words, names, numbers or phrases to redact — one per line</label>
          <textarea
            id="rt-terms"
            rows={8}
            className="mono"
            value={text}
            spellCheck={false}
            placeholder={regex ? "e.g. \\bCLM-\\d{4}-\\d+\\b" : "e.g.\nJordan Alvarez\n555-0143\nLot 14, Pinecrest Road"}
            onChange={(e) => {
              setText(e.target.value);
              setError(null);
              setRes(null);
            }}
          />
          <div className="field-hint">
            {parsed.terms.length} entr{parsed.terms.length === 1 ? "y" : "ies"} · up to 500, each under 500 characters
          </div>
        </div>
        <div className="check-grid">
          <label className="check">
            <input type="checkbox" checked={wholeWord} onChange={(e) => setWholeWord(e.target.checked)} /> <span>Whole words only</span>
          </label>
          <label className="check">
            <input type="checkbox" checked={caseSensitive} onChange={(e) => setCaseSensitive(e.target.checked)} /> <span>Match case</span>
          </label>
          <label className="check">
            <input type="checkbox" checked={regex} onChange={(e) => setRegex(e.target.checked)} /> <span>Pattern (regular expression)</span>
          </label>
        </div>
        <div className="form-grid">
          <div className="field">
            <label htmlFor="rt-type">Mark as</label>
            <EntitySelect id="rt-type" value={entity} onChange={setEntity} />
          </div>
          <div className="field">
            <label htmlFor="rt-ex">Exemption code</label>
            <ExemptionSelect id="rt-ex" m={m} value={exemption} onChange={setExemption} emptyLabel="Default for the type" />
          </div>
        </div>
        <Switch checked={remember} onChange={setRemember} label={<strong>Also redact these in files added later</strong>} hint="Kept in this case's list below." />
        {error && (
          <div className="notice notice-error" role="alert">
            {error}
          </div>
        )}
        <div className="row gap-sm">
          <button className="btn" onClick={() => run(true)} disabled={busy !== null || !parsed.terms.length}>
            {busy === "preview" ? <Spinner size={14} /> : <Eye size={15} aria-hidden />} Preview matches
          </button>
          <button className="btn btn-primary" onClick={() => run(false)} disabled={busy !== null || !parsed.terms.length}>
            {busy === "redact" ? <Spinner size={14} /> : <Replace size={15} aria-hidden />} Redact in all files
          </button>
        </div>
        {res && (
          <RedactTextResults
            res={res}
            action={
              undo && (
                <button className="btn btn-xs" onClick={undoRun} disabled={undo.state === "busy"} data-tip="Revert this run in every file (new redactions are removed, earlier suggestions are un-selected again)">
                  {undo.state === "busy" ? <Spinner size={11} /> : undo.state === "done" ? <Undo2 size={12} aria-hidden /> : <Redo2 size={12} aria-hidden />}
                  {undo.state === "undone" ? "Redo" : "Undo"}
                </button>
              )
            }
          />
        )}
      </section>
      <section className="card stack-sm">
        <h3>Redacted in every file of this case</h3>
        <p className="small muted">New and re-analysed files are searched for these automatically. Removing an entry doesn't undo redactions already added.</p>
        {saved === null && <Spinner size={16} label="Loading the list" />}
        {saved && saved.length === 0 && (
          <EmptyState compact title="No remembered entries">
            Entries you redact with “Also redact these in files added later” appear here.
          </EmptyState>
        )}
        {saved && saved.length > 0 && (
          <ul className="saved-terms">
            {saved.map((t, i) => (
              <li key={`${t.text}-${i}`}>
                <span className="mono small grow truncate" title={t.text}>
                  {t.text}
                </span>
                {termFlags(t).map((f) => (
                  <span key={f} className="badge badge-neutral tiny">
                    {f}
                  </span>
                ))}
                {t.entity && t.entity !== "CUSTOM" && <span className="badge badge-info tiny">{m.entityLabel(t.entity)}</span>}
                <button
                  className="icon-btn sm danger"
                  aria-label={`Remove entry ${i + 1} from the list`}
                  data-tip="Remove from the list (redactions already added stay)"
                  onClick={() => removeSaved(i)}
                  disabled={removing !== null}
                >
                  {removing === i ? <Spinner size={12} /> : <Trash2 size={13} />}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
