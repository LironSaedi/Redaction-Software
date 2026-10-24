import { useMemo, useState } from "react";
import { CaseSensitive, Check, Regex, Replace, Search, WholeWord } from "lucide-react";
import * as api from "../../api";
import { useMeta } from "../../meta";
import { useToast } from "../../components/Toast";
import { EmptyState, Spinner } from "../../components/ui";
import { truncate } from "../../lib/format";
import type { Detection, ManualDetectionIn, RedactTextOut, SearchIn } from "../../types";
import { RedactTextResults } from "../case/RedactTextTab";
import type { DetectionOps } from "./useDetections";
import { detectionLocation } from "./detectionUtils";
import { EntitySelect, ExemptionSelect } from "./PropertiesPanel";

/** POST /detections body that redacts one search match (time range, text range or its boxes). */
export function matchToManual(match: Detection, entity: string, exemption: string): ManualDetectionIn | null {
  const base: ManualDetectionIn = { entity };
  if (exemption) base.exemption = exemption;
  const t0 = match.meta?.t0;
  const t1 = match.meta?.t1;
  if (typeof t0 === "number" && typeof t1 === "number" && t1 > t0) return { ...base, t0, t1, note: "found by search" };
  if (match.start >= 0 && match.end > match.start) return { ...base, page: match.page, start: match.start, end: match.end };
  if (match.boxes.length) return { ...base, page: match.boxes[0].page, boxes: match.boxes };
  return null;
}

const keyOf = (d: Pick<Detection, "page" | "start" | "end" | "meta">) =>
  d.start >= 0 ? `${d.page}:${d.start}:${d.end}` : `t:${d.meta?.t0 ?? ""}:${d.meta?.t1 ?? ""}`;

interface Props {
  fileId: number;
  dets: Detection[];
  ops: DetectionOps;
  /** highlight these matches in the viewer */
  onPreview: (matches: Detection[]) => void;
  /** show one match in the viewer */
  onJump: (match: Detection) => void;
  disabledReason?: string | null;
  /** enables "Apply to every file in this case" */
  caseId?: number;
}

export function FindRedactPanel({ fileId, dets, ops, onPreview, onJump, disabledReason, caseId }: Props) {
  const m = useMeta();
  const toast = useToast();
  const [text, setText] = useState("");
  const [wholeWord, setWholeWord] = useState(true);
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [regex, setRegex] = useState(false);
  const [entity, setEntity] = useState("CUSTOM");
  const [exemption, setExemption] = useState("");
  const [matches, setMatches] = useState<Detection[] | null>(null);
  const [busy, setBusy] = useState<"find" | "all" | null>(null);
  const [limit, setLimit] = useState(200);
  const [caseWide, setCaseWide] = useState(false);
  const [remember, setRemember] = useState(true);
  const [caseRes, setCaseRes] = useState<RedactTextOut | null>(null);
  const caseBody = (preview: boolean) => ({
    terms: [{ text, regex, case_sensitive: caseSensitive, whole_word: wholeWord, entity }],
    preview,
    remember,
    entity,
    exemption,
    file_ids: null,
  });

  const regexProblem = useMemo(() => {
    if (!regex || !text) return null;
    try {
      new RegExp(text);
      return null;
    } catch {
      return "This pattern may not be valid (the server uses Python regular expressions).";
    }
  }, [regex, text]);

  const body = (add: boolean): SearchIn => ({
    terms: [{ text, whole_word: wholeWord, case_sensitive: caseSensitive, regex }],
    add,
    entity,
    exemption,
  });

  // existing redactions at the same place, to mark matches that are already redacted
  const existing = useMemo(() => {
    const map = new Map<string, Detection>();
    for (const d of dets) if (d.start >= 0 || d.meta?.t0 != null) map.set(keyOf(d), d);
    return map;
  }, [dets]);

  const reset = () => {
    setMatches(null);
    setCaseRes(null);
    onPreview([]);
  };

  const find = async () => {
    if (!text.trim()) return;
    setBusy("find");
    try {
      const [r, cr] = await Promise.all([
        api.searchFile(fileId, body(false)),
        caseWide && caseId != null ? api.caseRedactText(caseId, caseBody(true)) : Promise.resolve(null),
      ]);
      setMatches(r.matches);
      setCaseRes(cr);
      setLimit(200);
      onPreview(r.matches);
      if (r.matches.length) onJump(r.matches[0]);
    } catch (e) {
      toast.error(e, "Search failed");
    } finally {
      setBusy(null);
    }
  };

  const redactCase = async () => {
    if (caseId == null) return;
    setBusy("all");
    const r = await ops.caseRedact(caseId, caseBody(false));
    setBusy(null);
    if (r) {
      setCaseRes(r);
      setMatches(null);
      onPreview([]);
      toast.success(`${r.total_added} redaction${r.total_added === 1 ? "" : "s"} added in ${r.files.filter((f) => f.added > 0).length} file(s) — Undo reverts every file`);
    }
  };

  const redactAll = async () => {
    if (caseWide) return redactCase();
    setBusy("all");
    const r = await ops.searchAdd(body(true));
    setBusy(null);
    if (r) {
      // counts only — never echo the matched values in notifications
      toast.success(
        r.added
          ? `${r.added} new redaction${r.added === 1 ? "" : "s"} added (${r.result.count} match${r.result.count === 1 ? "" : "es"})`
          : `All ${r.result.count} matches were already redacted`,
      );
      reset();
    }
  };

  const redactOne = async (match: Detection) => {
    const have = existing.get(keyOf(match));
    if (have) {
      if (!have.selected) ops.toggle(have.id, true);
      return;
    }
    const b = matchToManual(match, entity, exemption);
    if (!b) {
      toast.error("This match has no position to redact.");
      return;
    }
    await ops.add(b, "Redact match");
  };

  const pending = matches?.filter((x) => !existing.get(keyOf(x))?.selected).length ?? 0;

  if (disabledReason) {
    return (
      <div className="find-panel">
        <EmptyState compact icon={<Search size={26} />} title="Find & Redact is not available yet">
          {disabledReason}
        </EmptyState>
      </div>
    );
  }

  return (
    <div className="find-panel">
      <form
        className="find-form"
        onSubmit={(e) => {
          e.preventDefault();
          find();
        }}
      >
        <div className="search-input big">
          <Search size={15} aria-hidden />
          <input
            aria-label={regex ? "Regular expression" : "Text to find"}
            placeholder={regex ? "Regular expression, e.g. \\b\\d{3}-\\d{4}\\b" : "Find text to redact"}
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              if (matches) reset();
            }}
            spellCheck={false}
            autoComplete="off"
          />
          <span className="find-toggles" role="group" aria-label="Search options">
            <button
              type="button"
              className={`icon-btn xs ${caseSensitive ? "active" : ""}`}
              aria-pressed={caseSensitive}
              aria-label="Match case"
              data-tip="Match case"
              onClick={() => setCaseSensitive((v) => !v)}
            >
              <CaseSensitive size={15} />
            </button>
            <button
              type="button"
              className={`icon-btn xs ${wholeWord ? "active" : ""}`}
              aria-pressed={wholeWord}
              aria-label="Whole word"
              data-tip="Whole word"
              onClick={() => setWholeWord((v) => !v)}
            >
              <WholeWord size={15} />
            </button>
            <button
              type="button"
              className={`icon-btn xs ${regex ? "active" : ""}`}
              aria-pressed={regex}
              aria-label="Regular expression"
              data-tip="Regular expression"
              onClick={() => setRegex((v) => !v)}
            >
              <Regex size={15} />
            </button>
          </span>
        </div>
        {regexProblem && <div className="field-hint warn-text">{regexProblem}</div>}
        <div className="find-grid">
          <div className="field">
            <label htmlFor="fr-type">Mark matches as</label>
            <EntitySelect id="fr-type" value={entity} onChange={setEntity} />
          </div>
          <div className="field">
            <label htmlFor="fr-ex">Exemption</label>
            <ExemptionSelect id="fr-ex" m={m} value={exemption} onChange={setExemption} emptyLabel="Default for the type" />
          </div>
        </div>
        {caseId != null && (
          <div className="case-wide">
            <label className="check inline small">
              <input
                type="checkbox"
                checked={caseWide}
                onChange={(e) => {
                  setCaseWide(e.target.checked);
                  setCaseRes(null);
                }}
              />
              Apply to every file in this case
            </label>
            {caseWide && (
              <>
                <label className="check inline small">
                  <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> Also in files added later
                </label>
                <div className="tiny muted">One Undo step reverts the redactions in every file.</div>
              </>
            )}
          </div>
        )}
        <div className="row gap-sm">
          <button className="btn btn-sm" type="submit" disabled={!!busy || !text.trim()}>
            {busy === "find" ? <Spinner size={13} /> : <Search size={14} aria-hidden />} Find
          </button>
          {matches && (matches.length > 0 || (caseWide && (caseRes?.total_matches ?? 0) > 0)) && (
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={redactAll}
              disabled={!!busy || (!caseWide && pending === 0)}
            >
              {busy === "all" ? <Spinner size={13} /> : <Replace size={14} aria-hidden />}{" "}
              {caseWide ? `Redact in all files${caseRes ? ` (${caseRes.total_matches})` : ""}` : `Redact all ${pending || ""}`}
            </button>
          )}
          {matches && (
            <button type="button" className="btn btn-sm btn-ghost" onClick={reset}>
              Clear
            </button>
          )}
        </div>
      </form>
      {caseRes && (
        <div className="find-case-results">
          <RedactTextResults res={caseRes} />
        </div>
      )}
      {matches && (
        <div className="find-results">
          <div className="find-results-head small" role="status">
            {matches.length === 0 ? "No matches." : `${matches.length} match${matches.length === 1 ? "" : "es"} · ${matches.length - pending} already redacted`}
          </div>
          <ul className="match-list">
            {matches.slice(0, limit).map((x, i) => {
              const have = existing.get(keyOf(x));
              const done = !!have?.selected;
              return (
                <li key={`${keyOf(x)}:${i}`} className={`match-item ${done ? "done" : ""}`}>
                  <button className="match-main" onClick={() => onJump(x)} data-tip="Show in the document">
                    <span className="match-loc mono">{detectionLocation(x) || "—"}</span>
                    <span className="match-text">{truncate(x.text || "(match)", 60)}</span>
                  </button>
                  {done ? (
                    <span className="badge badge-dark tiny">
                      <Check size={11} aria-hidden /> redacted
                    </span>
                  ) : (
                    <button className="btn btn-xs" onClick={() => redactOne(x)}>
                      Redact this
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
          {matches.length > limit && (
            <button className="link-btn small pad" onClick={() => setLimit((l) => l + 300)}>
              Show more ({matches.length - limit} left)
            </button>
          )}
        </div>
      )}
      {!matches && (
        <p className="muted small find-help">
          Searches the extracted text (and OCR text of scans). Use <strong>Find</strong> to preview the matches, then redact them one by
          one or all at once. Every change can be undone.
        </p>
      )}
    </div>
  );
}
