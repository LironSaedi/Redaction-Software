import { useEffect, useMemo, useState } from "react";
import { Save, ScanSearch } from "lucide-react";
import * as api from "../api";
import { hasRole, useUser } from "../auth";
import { useJobs } from "../jobs";
import { CATEGORY_ORDER, useMeta } from "../meta";
import { useToast } from "./Toast";
import { Field, Modal, ProgressBar, Spinner } from "./ui";
import { statusLabel } from "../lib/format";
import type { AnalyzeParams, FileRecord, Preset, Template, TermList } from "../types";

export const DEFAULT_VISUAL = ["face", "head", "license_plate"];

export function defaultAnalyzeParams(profile = "standard"): AnalyzeParams {
  return {
    profile,
    entities: null,
    use_ml: true,
    ocr: "auto",
    visual_classes: [...DEFAULT_VISUAL],
    video_mode: "balanced",
    audio: true,
    terms: [],
    allow_list: [],
    list_ids: [],
    template_ids: [],
    threshold: 0.5,
    sensitive_sentence_mode: false,
    use_case_dictionary: true,
    image_text: true,
    language: "auto",
    classify_images: true,
    visual_on_pages: true,
    speakers: true,
    second_opinion: true,
  };
}

/** Merge saved preset / last-analysis settings over defaults, ignoring unknown keys. */
export function mergeParams(base: AnalyzeParams, extra: Partial<AnalyzeParams> | undefined | null): AnalyzeParams {
  if (!extra) return base;
  const out: AnalyzeParams = { ...base };
  (Object.keys(base) as (keyof AnalyzeParams)[]).forEach((k) => {
    const v = extra[k];
    if (v !== undefined) (out as unknown as Record<string, unknown>)[k] = v;
  });
  return out;
}

interface SettingsFormProps {
  value: AnalyzeParams;
  onChange: (v: AnalyzeParams) => void;
  kinds: Set<string>;
  caseId?: number;
  idPrefix?: string;
}

/** The analysis settings (shared by the Analyze dialog and the Presets editor). */
export function AnalyzeSettingsForm({ value, onChange, kinds, caseId, idPrefix = "an" }: SettingsFormProps) {
  const m = useMeta();
  const meta = m.meta;
  const [lists, setLists] = useState<TermList[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [customEntities, setCustomEntities] = useState(value.entities != null);
  const [termsText, setTermsText] = useState(value.terms.map((t) => t.text).join("\n"));
  const [allowText, setAllowText] = useState(value.allow_list.join("\n"));

  useEffect(() => {
    api.listTermLists(caseId).then(setLists, () => setLists([]));
    api.listTemplates().then(setTemplates, () => setTemplates([]));
  }, [caseId]);

  const set = <K extends keyof AnalyzeParams>(k: K, v: AnalyzeParams[K]) => onChange({ ...value, [k]: v });

  const all = kinds.size === 0;
  const hasVisual = all || kinds.has("image") || kinds.has("video") || kinds.has("pdf") || kinds.has("email");
  const hasOcr = all || kinds.has("pdf") || kinds.has("image") || kinds.has("email");
  const hasVideo = all || kinds.has("video");
  const hasPdf = all || kinds.has("pdf") || kinds.has("email");
  const hasSpeech = all || kinds.has("video") || kinds.has("audio");
  const hasPictures = all || ["pdf", "email", "image", "docx", "pptx", "xlsx"].some((k) => kinds.has(k));
  const languages = useMemo(() => Object.entries(meta?.languages?.codes ?? {}).sort((a, b) => a[1].localeCompare(b[1])), [meta]);
  const englishOnly = meta?.languages?.transcription === "en";
  const so = meta?.second_opinion;

  const profile = meta?.profiles.find((p) => p.key === value.profile);
  const grouped = useMemo(() => {
    const g = new Map<string, { key: string; label: string; description: string }[]>();
    for (const e of meta?.entities ?? []) {
      if (!g.has(e.category)) g.set(e.category, []);
      g.get(e.category)!.push({ key: e.key, label: e.label, description: e.description });
    }
    return Array.from(g.entries()).sort((a, b) => CATEGORY_ORDER.indexOf(a[0]) - CATEGORY_ORDER.indexOf(b[0]));
  }, [meta]);

  const selectedEntities = new Set(value.entities ?? profile?.entities ?? []);
  const toggleEntity = (key: string, on: boolean) => {
    const next = new Set(selectedEntities);
    if (on) next.add(key);
    else next.delete(key);
    set("entities", Array.from(next));
  };

  const toggleIn = (arr: number[], id: number, on: boolean) => (on ? [...new Set([...arr, id])] : arr.filter((x) => x !== id));

  return (
    <div className="analyze-form">
      <div className="form-grid">
        <Field label="Detection profile" htmlFor={`${idPrefix}-profile`}>
          <select
            id={`${idPrefix}-profile`}
            value={value.profile ?? "standard"}
            onChange={(e) => onChange({ ...value, profile: e.target.value, entities: customEntities ? value.entities : null })}
          >
            {(meta?.profiles ?? []).map((p) => (
              <option key={p.key} value={p.key}>
                {p.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Confidence threshold" htmlFor={`${idPrefix}-thr`} hint="Lower finds more, with more false positives.">
          <div className="row gap-sm">
            <input
              id={`${idPrefix}-thr`}
              type="range"
              min={0.2}
              max={0.9}
              step={0.05}
              value={value.threshold}
              onChange={(e) => set("threshold", Number(e.target.value))}
            />
            <span className="mono small">{value.threshold.toFixed(2)}</span>
          </div>
        </Field>
      </div>

      <fieldset className="fieldset">
        <legend>Detectors</legend>
        <div className="check-grid">
          <label className="check">
            <input type="checkbox" checked={value.use_ml} onChange={(e) => set("use_ml", e.target.checked)} />
            <span>
              AI language models (names, addresses, organisations)
              <span className="field-hint block">Slower on first run while the local models load.</span>
            </span>
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={value.sensitive_sentence_mode}
              onChange={(e) => set("sensitive_sentence_mode", e.target.checked)}
            />
            <span>Redact the whole sentence for sensitive health / legal content</span>
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={value.use_case_dictionary}
              onChange={(e) => set("use_case_dictionary", e.target.checked)}
            />
            <span>Use values confirmed elsewhere in this case</span>
          </label>
          {(all || kinds.has("image")) && (
            <label className="check">
              <input type="checkbox" checked={value.image_text} onChange={(e) => set("image_text", e.target.checked)} />
              <span>Read text inside images (OCR)</span>
            </label>
          )}
          <label className={`check ${so && !so.available ? "is-disabled" : ""}`}>
            <input
              type="checkbox"
              checked={!!value.second_opinion && so?.available !== false}
              disabled={so?.available === false}
              onChange={(e) => set("second_opinion", e.target.checked)}
            />
            <span>
              Second opinion with Microsoft Presidio
              <span className="field-hint block">
                {so?.available === false
                  ? `Not available on this server${so.reason ? ` (${so.reason})` : ""}.`
                  : "An independent detector (running locally) re-reads the text; anything extra it finds is added as suggestions for you to review."}
              </span>
            </span>
          </label>
          {hasPictures && (
            <label className="check">
              <input type="checkbox" checked={value.classify_images} onChange={(e) => set("classify_images", e.target.checked)} />
              <span>
                Classify pictures (photos, exhibits, charts, ID cards, signatures)
                <span className="field-hint block">Lists every picture so it can be redacted whole; ID cards and signatures are pre-selected.</span>
              </span>
            </label>
          )}
        </div>
        {hasOcr && (
          <Field label="OCR for scanned pages" htmlFor={`${idPrefix}-ocr`}>
            <select id={`${idPrefix}-ocr`} value={value.ocr} onChange={(e) => set("ocr", e.target.value as AnalyzeParams["ocr"])}>
              <option value="auto">Automatic (pages without a text layer)</option>
              <option value="always">Always (re-read every page)</option>
              <option value="never">Never</option>
            </select>
          </Field>
        )}
      </fieldset>

      <fieldset className="fieldset">
        <legend>
          Entity types{" "}
          <label className="check inline">
            <input
              type="checkbox"
              checked={customEntities}
              onChange={(e) => {
                setCustomEntities(e.target.checked);
                set("entities", e.target.checked ? Array.from(new Set(profile?.entities ?? [])) : null);
              }}
            />
            <span>Choose individually</span>
          </label>
        </legend>
        {!customEntities ? (
          <p className="muted small">
            Using the {profile?.label ?? "selected"} profile ({profile?.entities.length ?? 0} types).
          </p>
        ) : (
          <div className="entity-groups">
            {grouped.map(([cat, ents]) => (
              <div key={cat} className="entity-group">
                <div className="entity-group-head">
                  <span className="cat-dot" style={{ background: m.color(ents[0]?.key ?? cat) }} aria-hidden />
                  <strong>{m.categoryLabel(cat)}</strong>
                  <button
                    type="button"
                    className="link-btn small"
                    onClick={() => {
                      const next = new Set(selectedEntities);
                      ents.forEach((e) => next.add(e.key));
                      set("entities", Array.from(next));
                    }}
                  >
                    all
                  </button>
                  <button
                    type="button"
                    className="link-btn small"
                    onClick={() => {
                      const next = new Set(selectedEntities);
                      ents.forEach((e) => next.delete(e.key));
                      set("entities", Array.from(next));
                    }}
                  >
                    none
                  </button>
                </div>
                {ents.map((e) => (
                  <label key={e.key} className="check small" title={e.description}>
                    <input type="checkbox" checked={selectedEntities.has(e.key)} onChange={(ev) => toggleEntity(e.key, ev.target.checked)} />
                    <span>{e.label}</span>
                  </label>
                ))}
              </div>
            ))}
          </div>
        )}
      </fieldset>

      {hasVisual && (
        <fieldset className="fieldset">
          <legend>Visual detection {hasPdf ? "(images, video and photos inside PDFs)" : ""}</legend>
          {hasPdf && (
            <label className="check fieldset-lead">
              <input type="checkbox" checked={value.visual_on_pages} onChange={(e) => set("visual_on_pages", e.target.checked)} />
              <span>Look for faces and plates in pictures inside PDFs</span>
            </label>
          )}
          <div className="check-grid">
            {Object.entries(meta?.visual_classes ?? {}).map(([k, label]) => (
              <label key={k} className="check">
                <input
                  type="checkbox"
                  checked={(value.visual_classes ?? []).includes(k)}
                  onChange={(e) => {
                    const cur = new Set(value.visual_classes ?? []);
                    if (e.target.checked) cur.add(k);
                    else cur.delete(k);
                    set("visual_classes", Array.from(cur));
                  }}
                />
                <span>{label}</span>
              </label>
            ))}
          </div>
        </fieldset>
      )}

      {hasSpeech && (
        <fieldset className="fieldset">
          <legend>Speech</legend>
          <div className="form-grid">
            <Field
              label="Speech language"
              htmlFor={`${idPrefix}-lang`}
              hint={englishOnly ? "Only the English speech model is installed on this server." : "Auto-detect works for mixed recordings; pick the language if it is known."}
            >
              <select id={`${idPrefix}-lang`} value={value.language || "auto"} onChange={(e) => set("language", e.target.value)}>
                <option value="auto">Auto-detect</option>
                {languages.map(([code, name]) => (
                  <option key={code} value={code}>
                    {name}
                  </option>
                ))}
              </select>
            </Field>
            <label className="check align-center">
              <input type="checkbox" checked={value.speakers} onChange={(e) => set("speakers", e.target.checked)} />
              <span>
                Identify speakers
                <span className="field-hint block">Labels turns as Speaker 1, Speaker 2… (anonymous; no names are guessed).</span>
              </span>
            </label>
          </div>
        </fieldset>
      )}

      {hasVideo && (
        <fieldset className="fieldset">
          <legend>Video</legend>
          <div className="form-grid">
            <Field label="Tracking mode" htmlFor={`${idPrefix}-vm`}>
              <select id={`${idPrefix}-vm`} value={value.video_mode} onChange={(e) => set("video_mode", e.target.value)}>
                {(meta?.video_modes ?? ["balanced", "max_accuracy", "fast"]).map((v) => (
                  <option key={v} value={v}>
                    {v === "max_accuracy" ? "Maximum accuracy (every frame)" : v === "fast" ? "Fast" : "Balanced"}
                  </option>
                ))}
              </select>
            </Field>
            <label className="check">
              <input type="checkbox" checked={value.audio} onChange={(e) => set("audio", e.target.checked)} />
              <span>Transcribe and redact spoken PII in the audio track</span>
            </label>
          </div>
        </fieldset>
      )}

      <fieldset className="fieldset">
        <legend>Lists, templates and extra terms</legend>
        <div className="form-grid">
          <div>
            <div className="label">Term lists</div>
            {lists.length === 0 && <div className="muted small">No lists yet (Library → Term lists).</div>}
            {lists.map((l) => (
              <label key={l.id} className="check small">
                <input
                  type="checkbox"
                  checked={value.list_ids.includes(l.id)}
                  onChange={(e) => set("list_ids", toggleIn(value.list_ids, l.id, e.target.checked))}
                />
                <span>
                  {l.name} <span className="muted">({l.kind === "allow" ? "allow list" : "redact"}, {l.count})</span>
                </span>
              </label>
            ))}
          </div>
          {hasPdf && (
            <div>
              <div className="label">Zone templates (PDF)</div>
              {templates.length === 0 && <div className="muted small">No templates yet.</div>}
              {templates.map((t) => (
                <label key={t.id} className="check small">
                  <input
                    type="checkbox"
                    checked={value.template_ids.includes(t.id)}
                    onChange={(e) => set("template_ids", toggleIn(value.template_ids, t.id, e.target.checked))}
                  />
                  <span>
                    {t.name} <span className="muted">({t.zones.length} zones)</span>
                  </span>
                </label>
              ))}
            </div>
          )}
          <Field label="Extra search terms" htmlFor={`${idPrefix}-terms`} hint="One per line; always redacted.">
            <textarea
              id={`${idPrefix}-terms`}
              rows={3}
              value={termsText}
              onChange={(e) => {
                setTermsText(e.target.value);
                set(
                  "terms",
                  e.target.value
                    .split("\n")
                    .map((t) => t.trim())
                    .filter(Boolean)
                    .map((text) => ({ text })),
                );
              }}
            />
          </Field>
          <Field label="Never redact" htmlFor={`${idPrefix}-allow`} hint="One per line, e.g. agency or officer names.">
            <textarea
              id={`${idPrefix}-allow`}
              rows={3}
              value={allowText}
              onChange={(e) => {
                setAllowText(e.target.value);
                set(
                  "allow_list",
                  e.target.value
                    .split("\n")
                    .map((t) => t.trim())
                    .filter(Boolean),
                );
              }}
            />
          </Field>
        </div>
      </fieldset>
    </div>
  );
}

interface AnalyzeDialogProps {
  caseId: number;
  files: FileRecord[];
  defaultProfile?: string;
  onClose: () => void;
  /** called when every started job has finished */
  onDone?: () => void;
}

export function AnalyzeDialog({ caseId, files, defaultProfile, onClose, onDone }: AnalyzeDialogProps) {
  const user = useUser();
  const toast = useToast();
  const jobs = useJobs();
  const last = files.length === 1 ? files[0].info?.last_analysis : undefined;
  const [params, setParams] = useState<AnalyzeParams>(() =>
    mergeParams(defaultAnalyzeParams(defaultProfile ?? "standard"), last ? { ...last, terms: [] } : undefined),
  );
  const [presets, setPresets] = useState<Preset[]>([]);
  const [presetName, setPresetName] = useState("");
  const [formKey, setFormKey] = useState(0);
  const [busy, setBusy] = useState(false);
  const [jobIds, setJobIds] = useState<number[]>([]);
  const [doneIds, setDoneIds] = useState<Set<number>>(new Set());

  useEffect(() => {
    api.listPresets().then(setPresets, () => setPresets([]));
  }, []);

  const kinds = useMemo(() => new Set(files.map((f) => f.kind)), [files]);

  const start = async () => {
    setBusy(true);
    try {
      let ids: number[];
      if (files.length === 1) ids = [(await api.analyzeFile(files[0].id, params)).job_id];
      else ids = (await api.bulkAnalyze(caseId, files.map((f) => f.id), params)).jobs;
      setJobIds(ids);
      const finished = new Set<number>();
      ids.forEach((id, i) =>
        jobs.track(id, {
          label: files.length === 1 ? `Analysis of ${files[0].name}` : "Analysis",
          fileId: files[i]?.id,
          kind: "analyze",
          notify: files.length === 1,
          onDone: () => {
            finished.add(id);
            setDoneIds(new Set(finished));
            if (finished.size === ids.length) {
              if (ids.length > 1) toast.success(`Analysis finished for ${ids.length} files`);
              onDone?.();
            }
          },
        }),
      );
    } catch (e) {
      toast.error(e, "Could not start analysis");
      setBusy(false);
    }
  };

  const savePreset = async () => {
    if (!presetName.trim()) return;
    try {
      const p = await api.createPreset(presetName.trim(), { ...params, terms: [] });
      setPresets((ps) => [...ps, p]);
      setPresetName("");
      toast.success("Preset saved");
    } catch (e) {
      toast.error(e, "Could not save preset");
    }
  };

  const running = jobIds.length > 0;
  const allDone = running && doneIds.size === jobIds.length;

  return (
    <Modal
      title={files.length === 1 ? `Analyze “${files[0].name}”` : `Analyze ${files.length} files`}
      onClose={onClose}
      size="lg"
      busy={busy && !running}
      footer={
        running ? (
          <button className="btn btn-primary" onClick={onClose}>
            {allDone ? "Close" : "Run in background"}
          </button>
        ) : (
          <>
            <button className="btn" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button className="btn btn-primary" onClick={start} disabled={busy}>
              {busy ? <Spinner size={14} /> : <ScanSearch size={15} aria-hidden />} Start analysis
            </button>
          </>
        )
      }
    >
      {running ? (
        <div className="job-progress-list">
          {jobIds.map((id, i) => {
            const j = jobs.job(id);
            const f = files[i];
            return (
              <div key={id} className="job-progress">
                <div className="row space">
                  <span className="strong">{f?.name ?? `Job ${id}`}</span>
                  <span className="muted small">{j ? statusLabel(j.status) : "Queued"}</span>
                </div>
                <ProgressBar value={j?.status === "done" ? 1 : (j?.progress ?? 0)} indeterminate={!j || j.status === "queued"} />
                {j?.message && <div className={`small ${j.status === "error" ? "text-bad" : "muted"}`}>{j.message}</div>}
              </div>
            );
          })}
          <p className="muted small">You can close this dialog; progress also shows in the top bar.</p>
        </div>
      ) : (
        <>
          {presets.length > 0 && (
            <div className="row gap preset-row">
              <label htmlFor="an-preset" className="label">
                Load preset
              </label>
              <select
                id="an-preset"
                defaultValue=""
                onChange={(e) => {
                  const p = presets.find((x) => String(x.id) === e.target.value);
                  if (p) {
                    setParams(mergeParams(defaultAnalyzeParams(params.profile ?? "standard"), p.settings));
                    setFormKey((k) => k + 1);
                  }
                }}
              >
                <option value="">—</option>
                {presets.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          <AnalyzeSettingsForm key={formKey} value={params} onChange={setParams} kinds={kinds} caseId={caseId} />
          {hasRole(user, "supervisor") && (
            <div className="row gap save-preset">
              <input
                aria-label="Preset name"
                placeholder="Save these settings as a preset…"
                value={presetName}
                onChange={(e) => setPresetName(e.target.value)}
              />
              <button className="btn btn-sm" onClick={savePreset} disabled={!presetName.trim()}>
                <Save size={14} aria-hidden /> Save preset
              </button>
            </div>
          )}
        </>
      )}
    </Modal>
  );
}
